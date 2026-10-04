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
    """Regression (cab goal): the 7B could not cut 'rides has 7 fields' in 3 tries, the spec failed and the model Architect built drivers only."""
    rides = _res("rides", [_f("passenger_name"), _f("passenger_phone"), _f("pickup_location"), _f("drop_location"), _f("pickup_time"), _f("fare", "number"),
                           _f("status", o=["Requested", "Completed"])], parent="drivers")
    spec = SpecOutput(title="Cabs", summary="x", features=["a"], resources=[_res("drivers", [_f("name")]), rides])
    normalize_spec(spec, CAB)
    names = [f.name for f in spec.resources[1].fields]
    assert len(names) == 6 and "pickup_time" not in names and {"fare", "status"} <= set(names)
    assert "ride pickup time" in spec.not_included
    assert check_spec(spec, CAB) == []


def test_one_click_actions_on_a_labelled_status_are_left_out_not_built_as_two_flips_of_one_column():
    """Regression (cab goal): 'mark completed' and 'cancel' both flipped `status`, so the contract had the column twice and the labels became a yes/no box."""
    from app.schemas import SpecAction, check_architecture
    from app.relations import synthesize_design

    rides = _res("rides", [_f("passenger_name"), _f("fare", "number"), _f("status", o=["Requested", "Completed", "Cancelled"])], parent="drivers")
    rides.actions = [SpecAction(name="mark_completed", field="status", kind="toggle"), SpecAction(name="cancel", field="status", kind="toggle")]
    spec = SpecOutput(title="Cabs", summary="x", features=["Add a ride", "Mark a ride as completed", "Cancel a ride"], resources=[_res("drivers", [_f("name")]), rides])
    normalize_spec(spec, CAB)
    ride = spec.resources[1]
    assert ride.actions == [] and [(f.name, f.options) for f in ride.fields][-1] == ("status", ["Requested", "Completed", "Cancelled"])
    assert any("one-click mark completed" in x for x in spec.not_included)
    assert spec.features == ["Add a ride"]
    assert check_architecture(synthesize_design(spec), ["fastapi-vanilla"], spec) == []


def test_any_game_goal_is_refused_but_game_data_apps_are_not():
    """Regression: 'Build a 3D cab racing game' was built as a list app called 'players' because only '3d game' (adjacent words) matched."""
    from app.scope import classify_goal

    for goal in ("Build a 3D cab racing game", "Make a fun trivia game", "Create a space shooter game for two players"):
        assert classify_goal(goal).level == "impossible", goal
    for goal in ("Build a game score tracker", "Build a game library with ratings", "Build a video game review site", "Build a board game collection tracker"):
        assert classify_goal(goal).level != "impossible", goal
