"""Live-test fixes: plan edges repaired by rules, a stated relation reaches the rules path, over-cap fields trimmed, escalation actions, replay approvals."""
from app.schemas import PlannerOutput, SpecField, SpecOutput, SpecResource, check_plan, check_spec, goal_relations, is_relational, normalize_spec

CAB = ("Build a cab booking app: drivers have name, phone, car model, plate number, car type Mini/Sedan/SUV and rating 1-5. Each driver has many rides. "
       "A ride has passenger name, passenger phone, pickup location, drop location, pickup time, fare in rupees and status Requested/Accepted/On trip/Completed/Cancelled.")


def _task(i, owner, files, deps=()):
    return {"id": i, "title": i, "owner": owner, "files": files, "depends_on": list(deps), "acceptance": ["x"]}


def test_normalize_plan_adds_the_missing_database_edges():
    """Regression (cab goal): the Planner escalated after 3 tries on 't3 (backend) must depend on the database task(s) t2'."""
    from app.schemas import normalize_plan

    p = PlannerOutput.model_validate({"tasks": [
        _task("t1", "database", ["database/drivers.py"]), _task("t2", "database", ["database/rides.py"]),
        _task("t3", "backend", ["backend/api/drivers.py"], ["t2"]), _task("t4", "backend", ["backend/api/rides.py"], ["t3"]),
        _task("t5", "frontend", ["static/index.html"]), _task("t6", "frontend", ["static/app.js"], ["t5"])]})
    out = normalize_plan(p)
    from app.schemas import _ancestors

    assert {"t1", "t2"} <= _ancestors(out.tasks, "t3") and {"t1", "t2"} <= _ancestors(out.tasks, "t4")
    assert {t.id: t.depends_on for t in out.tasks}["t5"] == []  # the frontend codes against the contract: it still does not wait
    assert not any("must depend" in x for x in check_plan(out, True, [], 2))


def test_normalize_plan_does_not_close_a_cycle():
    from app.schemas import normalize_plan

    p = PlannerOutput.model_validate({"tasks": [
        _task("t1", "backend", ["backend/api/a.py"]), _task("t2", "database", ["database/a.py"], ["t1"])]})
    out = normalize_plan(p)
    assert {t.id: t.depends_on for t in out.tasks} == {"t1": [], "t2": ["t1"]}


def test_goal_relations_reads_each_x_has_many_y():
    assert goal_relations(CAB) == [("driver", "rides")]
    assert goal_relations("Each todo has a priority") == []
    assert goal_relations("every post can have several comments") == [("post", "comments")]


def _res(name, fields, parent=""):
    return SpecResource(name=name, fields=fields, operations=["list", "create"], parent=parent)


def _f(n, t="string", o=()):
    return SpecField(name=n, type=t, options=list(o))


def test_a_goal_that_states_a_relation_makes_the_spec_relational_even_if_the_model_forgot_the_parent():
    spec = SpecOutput(title="Cabs", summary="x", features=["a"], resources=[
        _res("drivers", [_f("name"), _f("car_type", o=["Mini", "Sedan"])]), _res("rides", [_f("passenger_name"), _f("fare", "number")])])
    assert not is_relational(spec)
    normalize_spec(spec, CAB)
    assert spec.resources[1].parent == "drivers" and is_relational(spec)


def test_a_spec_that_drops_the_child_resource_the_goal_names_is_rejected():
    spec = SpecOutput(title="Cabs", summary="x", features=["a"], resources=[_res("drivers", [_f("name")])])
    assert any("each driver has many rides" in x for x in check_spec(normalize_spec(spec, CAB), CAB))
    assert check_spec(normalize_spec(spec, "Build a driver list"), "Build a driver list") == []


def test_fields_over_the_cap_are_trimmed_by_rules_and_listed():
    """Regression (cab goal): the 7B could not cut 'rides has 7 fields' in 3 tries, the spec failed and the model Architect built drivers only. The cap is 8 now."""
    names9 = ["passenger_name", "passenger_phone", "pickup_location", "drop_location", "pickup_time", "fare", "notes", "luggage", "tip"]
    rides = _res("rides", [_f(n, "number" if n in ("fare", "tip") else "string") for n in names9] + [_f("status", o=["Requested", "Completed"])], parent="drivers")
    spec = SpecOutput(title="Cabs", summary="x", features=["a"], resources=[_res("drivers", [_f("name")]), rides])
    normalize_spec(spec, CAB)
    names = [f.name for f in spec.resources[1].fields]
    assert len(names) == 8 and "pickup_time" not in names and {"fare", "status"} <= set(names)
    assert "ride pickup time" in spec.not_included
    assert check_spec(spec, CAB) == []


def test_one_click_status_actions_set_a_label_of_the_status_field():
    """The cab goal's 'mark completed' and 'cancel' are endpoints that SET the existing status (POST /api/rides/{id}/complete): no column added, no action dropped."""
    from app.schemas import SpecAction, check_architecture
    from app.relations import synthesize_design

    rides = _res("rides", [_f("passenger_name"), _f("fare", "number"), _f("status", o=["Requested", "Completed", "Cancelled"])], parent="drivers")
    rides.actions = [SpecAction(name="mark_completed", field="status", kind="toggle"), SpecAction(name="cancel", field="status", kind="toggle")]
    spec = SpecOutput(title="Cabs", summary="x", features=["Add a ride"], resources=[_res("drivers", [_f("name")]), rides])
    normalize_spec(spec, CAB)
    ride = spec.resources[1]
    assert [(a.name, a.kind, a.field, a.value) for a in ride.actions] == [("complete", "set", "status", "Completed"), ("cancel", "set", "status", "Cancelled")]
    assert [(f.name, f.options) for f in ride.fields][-1] == ("status", ["Requested", "Completed", "Cancelled"])
    design = synthesize_design(spec)
    assert check_architecture(design, ["fastapi-vanilla"], spec) == []
    paths = {(e.method, e.path) for e in design.endpoints}
    assert ("POST", "/api/rides/{id}/complete") in paths and ("POST", "/api/rides/{id}/cancel") in paths
    assert [c.name for c in next(t for t in design.tables if t.name == "rides").columns].count("status") == 1


def test_goal_actions_read_the_actions_a_goal_lists():
    from app.goalspec import goal_spec

    fest = ("Build a fest: events have name, category Coding/Quiz and capacity. Each event has many registrations: student name, email and status Registered/Checked in/Cancelled; "
            "actions: check in and cancel. Each event has many sponsors: company name, amount in rupees and status Pledged/Paid; action: mark paid.")
    spec = normalize_spec(goal_spec(fest), fest)
    acts = {r.name: [(a.name, a.value) for a in r.actions] for r in spec.resources}
    assert acts["registrations"] == [("check_in", "Checked in"), ("cancel", "Cancelled")] and acts["sponsors"] == [("mark_paid", "Paid")]
    assert [r.parent for r in spec.resources] == ["", "events", "events"]


def test_a_structured_goal_is_read_by_rules_and_keeps_every_field():
    from app.goalspec import goal_spec

    spec = normalize_spec(goal_spec(CAB + " Actions on a ride: mark completed and cancel. Show total fare earned, filter rides by status, sort by newest, edit and delete."), CAB)
    drivers, rides = spec.resources
    assert [f.name for f in drivers.fields] == ["name", "phone", "car_model", "plate_number", "car_type", "rating"]
    assert dict((f.name, f.type) for f in drivers.fields)["plate_number"] == "string" and dict((f.name, f.type) for f in drivers.fields)["rating"] == "integer"
    assert [f.name for f in rides.fields] == ["passenger_name", "passenger_phone", "pickup_location", "drop_location", "pickup_time", "fare", "status"]
    assert rides.parent == "drivers" and [a.name for a in rides.actions] == ["complete", "cancel"]
    assert goal_spec("Build a todo app: title, description, priority Low/Medium/High, due date, mark as done, edit and delete") is None  # one resource: the usual path


def test_every_skill_pack_loads_and_matches_its_domain():
    from app.skills import match_skill, packs

    assert len(packs()) == 11
    assert match_skill("Build a college tech fest manager: events have name") == "events"
    assert match_skill("Build a cab booking app: drivers have name") == "transport"
    assert match_skill("Build a clinic app with doctors and appointments") == "clinic"
    assert match_skill("Build a hackathon management platform: teams have name") == "hackathon"
    assert match_skill("Build an expense tracker with categories and totals") == "finance"
    assert match_skill("Build Instagram", "Instagram", ["posts", "comments"]) == "social"
    assert match_skill("Build a calculator with history") == ""


def test_any_game_goal_is_refused_but_game_data_apps_are_not():
    """Regression: 'Build a 3D cab racing game' was built as a list app called 'players' because only '3d game' (adjacent words) matched."""
    from app.scope import classify_goal

    for goal in ("Build a 3D cab racing game", "Make a fun trivia game", "Create a space shooter game for two players"):
        assert classify_goal(goal).level == "impossible", goal
    for goal in ("Build a game score tracker", "Build a game library with ratings", "Build a video game review site", "Build a board game collection tracker"):
        assert classify_goal(goal).level != "impossible", goal


def test_a_reserved_word_renamed_by_the_spec_is_renamed_in_the_architects_design():
    """Regression (contact book): the spec renamed `group` to `group_value`; the 7B Architect kept writing `group` and the design never passed the checks."""
    from app.schemas import normalize_design
    from test_enrich import SPEC, design

    d = design()
    for e in d.endpoints:
        for f in [*e.request_fields, *e.response_fields]:
            if f.name == "priority":
                f.name = "group"
    d.tables[0].columns[2].name = "group"
    d.db_functions[0].signature = "add_todo(title: str, group: str, done: bool) -> dict"
    spec = SPEC.model_copy(deep=True)
    spec.resources[0].fields[1].name = "group_value"
    normalize_design(d, spec)
    names = {f.name for e in d.endpoints for f in [*e.request_fields, *e.response_fields]}
    assert "group_value" in names and "group" not in names
    assert d.tables[0].columns[2].name == "group_value" and "group_value: str" in d.db_functions[0].signature


def test_a_planner_that_splits_the_one_table_or_calls_it_all_tables_is_repaired_by_rules():
    """Regression (calculator chip, 2 of 3 runs): 'use exactly ONE database task' / 'never all tables' were sent back to the 7B until it gave up."""
    from app.schemas import PlannerOutput, normalize_plan, check_plan

    p = PlannerOutput.model_validate({"tasks": [
        _task("t1", "database", ["database/calculations.py"]), _task("t2", "database", ["database/history.py"], ["t1"]),
        {**_task("t3", "backend", ["backend/api/calculator.py"], ["t2"]), "title": "API"}, _task("t4", "frontend", ["static/index.html"]), _task("t5", "frontend", ["static/app.js"], ["t4"])]})
    p.tasks[0].title = "Implement all tables"
    out = normalize_plan(p, 1)
    assert [t.id for t in out.tasks] == ["t1", "t3", "t4", "t5"] and out.tasks[0].title == "Implement the table"
    assert [t.depends_on for t in out.tasks] == [[], ["t1"], [], ["t4"]]
    assert not any("ONE database task" in x or "all tables" in x for x in check_plan(out, True, [], 1))
