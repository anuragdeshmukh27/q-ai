"""The multi-page shell, the skill-pack rules and the status actions, end to end without a model:
the generated bodies (the contract repair) pass every generated test of the cab, fest and clinic goals, the sample data loads, and every page draws in a fake browser."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.contract_tests import ui_page_test_source, ui_script_test_source
from app.goalspec import goal_spec
from app.look import choose_look
from app.platforms import PLATFORMS
from app.relations import synthesize_design
from app.schemas import SpecOutput, check_architecture, normalize_spec
from app.seeddata import seed_for, seed_test_source
from app.skills import match_skill
from app.uistub import page_stub, script_stub

from test_repair import filled_project

CAB = ("Build a cab booking app: drivers have name, phone, car model, plate number, car type Mini/Sedan/SUV and rating 1-5. Each driver has many rides. "
       "A ride has passenger name, passenger phone, pickup location, drop location, pickup time, fare in rupees and status Requested/Accepted/On trip/Completed/Cancelled. "
       "Actions on a ride: mark completed and cancel. Show total fare earned, filter rides by status, sort by newest, edit and delete.")
FEST = ("Build a college tech fest manager: events have name, category Coding/Robotics/Gaming/Quiz/Workshop, venue, date, start time, capacity and entry fee in rupees. "
        "Each event has many registrations: student name, college, email, phone, team name and status Registered/Checked in/Cancelled; actions: check in and cancel. "
        "Each event has many volunteers: name, phone, role Coordinator/Helper/Tech support and shift Morning/Afternoon/Evening. "
        "Each event has many sponsors: company name, contact person, amount in rupees and status Pledged/Paid; action: mark paid. "
        "Show total registrations, total sponsorship received, registrations per event, filter registrations by status and events by category, search events by name, edit and delete everything.")
CLINIC = ("Build a clinic app: doctors have name, speciality General/Cardiology/Dermatology/Pediatrics/Orthopedics, phone, email, consultation fee in rupees and rating 1-5. "
          "Each doctor has many appointments: patient name, patient phone, date, time, reason and status Scheduled/Completed/Cancelled; actions: complete and cancel. "
          "Each doctor has many prescriptions: patient name, medicine and dosage. Each doctor has many reviews: author, rating 1-5 and comment.")
GOALS = {"cab": CAB, "fest": FEST, "clinic": CLINIC}
SKELETON = Path(__file__).resolve().parents[1] / "app" / "presets" / "fastapi_vanilla" / "skeleton"


def designed(goal: str):
    spec = normalize_spec(goal_spec(goal), goal)
    spec.skill = match_skill(goal, spec.title, [r.name for r in spec.resources])
    design = synthesize_design(spec)
    design.look = choose_look(goal, spec, design)
    return spec, design


def project(tmp_path, design, spec_title):
    root = filled_project(tmp_path, design)
    (root / "tests" / "ui").mkdir(parents=True, exist_ok=True)
    (root / "static" / "index.html").write_text(page_stub(design, spec_title), encoding="utf-8")
    (root / "static" / "app.js").write_text(script_stub(design, spec_title), encoding="utf-8")
    (root / "tests" / "ui" / "test_page.py").write_text(ui_page_test_source(design), encoding="utf-8")
    (root / "tests" / "ui" / "test_script.py").write_text(ui_script_test_source(design), encoding="utf-8")
    rows = seed_for(design, design.look.skill)
    (root / "seed.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    (root / "tests" / "qa" / "test_seed.py").write_text(seed_test_source(), encoding="utf-8")
    return root


@pytest.mark.parametrize("name", list(GOALS))
def test_a_structured_goal_builds_the_whole_app_by_rules_and_every_generated_test_passes(name, tmp_path):
    spec, design = designed(GOALS[name])
    assert check_architecture(design, ["fastapi-vanilla"], spec) == []
    assert design.look.layout == "shell" and spec.skill
    root = project(tmp_path, design, spec.title)
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "--tb=short"], cwd=root, capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stdout[-3500:]


def test_the_fest_has_four_tables_nested_endpoints_actions_and_rules_in_the_schema():
    spec, design = designed(FEST)
    assert [r.name for r in design.resources] == ["events", "registrations", "volunteers", "sponsors"]
    paths = {(e.method, e.path) for e in design.endpoints}
    for child in ("registrations", "volunteers", "sponsors"):
        assert ("GET", f"/api/events/{{event_id}}/{child}") in paths and ("POST", f"/api/events/{{event_id}}/{child}") in paths
        assert ("PUT", f"/api/{child}/{{id}}") in paths and ("DELETE", f"/api/{child}/{{id}}") in paths
    assert ("POST", "/api/registrations/{id}/check_in") in paths and ("POST", "/api/registrations/{id}/cancel") in paths and ("POST", "/api/sponsors/{id}/mark_paid") in paths
    ddl = " ".join(" ".join([c.name for c in t.columns] + t.constraints + t.triggers) for t in design.tables)
    assert "UNIQUE (event_id, email)" in ddl and "registrations_capacity" in ddl and "registrations_status_flow" in ddl and "sponsors_status_flow" in ddl
    assert len([c for t in design.tables if t.name == "registrations" for c in t.columns if c.name == "status"]) == 1
    regs = next(r for r in spec.resources if r.name == "registrations")
    assert [f.name for f in regs.fields] == ["student_name", "college", "email", "phone", "team_name", "status"]  # every field of the goal


def test_the_cab_keeps_pickup_time_and_gets_complete_and_cancel_actions_and_a_status_flow():
    spec, design = designed(CAB)
    rides = next(r for r in design.resources if r.name == "rides")
    assert "pickup_time" in [f.name for f in rides.fields]
    assert [(a.name, a.kind, a.value) for a in rides.actions] == [("complete", "set", "Completed"), ("cancel", "set", "Cancelled")]
    assert rides.rules.transitions["Completed"] == [] and rides.rules.status_field == "status"
    assert rides.rules.positive == ["fare"] and rides.rules.phone == ["passenger_phone"]
    drivers = next(r for r in design.resources if r.name == "drivers")
    assert drivers.rules.unique == ["plate_number"] and drivers.rules.bounds == {"rating": [1.0, 5.0]}


def test_the_app_description_has_everything_the_shell_draws():
    from app.shell import app_config

    spec, design = designed(CAB)
    cfg = app_config(design, spec.title)
    assert cfg["skin"] == "transit" and cfg["currency"] == "INR" and cfg["locale"] == "en-IN"
    rides = next(r for r in cfg["resources"] if r["name"] == "rides")
    assert rides["list"] == "/api/drivers/{parent}/rides" and rides["item"] == "/api/rides/{id}" and "status" in rides["filters"]
    assert [a["url"] for a in rides["actions"]] == ["/api/rides/{id}/complete", "/api/rides/{id}/cancel"]
    assert rides["flow"]["status"]["Completed"] == [] and any(f["name"] == "pickup_time" and f["kind"] == "text" for f in rides["fields"]) is False
    assert any(f["name"] == "pickup_time" for f in rides["fields"])
    assert [k["label"] for k in cfg["dashboard"]["kpis"]][:2] == ["Drivers", "Rides"] and cfg["dashboard"]["charts"]
    assert any(k.get("where") == {"status": "Completed"} for k in cfg["dashboard"]["kpis"])


def test_two_apps_clearly_differ_in_skin_navigation_and_dashboard():
    cab, fest = designed(CAB)[1], designed(FEST)[1]
    from app.shell import app_config

    a, b = app_config(cab, "Cab"), app_config(fest, "Fest")
    assert a["skin"] != b["skin"] and a["icon"] != b["icon"]
    assert [r["label"] for r in a["resources"]] != [r["label"] for r in b["resources"]]
    assert [k["label"] for k in a["dashboard"]["kpis"]] != [k["label"] for k in b["dashboard"]["kpis"]]


def run_smoke(tmp_path, design, title):
    root = tmp_path / "app"
    shutil.copytree(SKELETON, root, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "static" / "index.html").write_text(page_stub(design, title), encoding="utf-8")
    (root / "static" / "app.js").write_text(script_stub(design, title), encoding="utf-8")
    return subprocess.run(["node", str(root / "tests" / "ui" / "shell_smoke.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=60)


@pytest.mark.parametrize("key,words,spec", PLATFORMS)
def test_every_famous_app_draws_every_page_in_a_fake_browser(key, words, spec, tmp_path):
    s = normalize_spec(SpecOutput.model_validate(spec), "Build " + key)
    s.skill = match_skill("Build " + key, s.title, [r.name for r in s.resources])
    design = synthesize_design(s)
    design.look = choose_look("Build " + key, s, design)
    assert design.look.layout == "shell"
    r = run_smoke(tmp_path, design, s.title)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]


@pytest.mark.parametrize("name", list(GOALS))
def test_the_goals_draw_every_page_in_a_fake_browser(name, tmp_path):
    spec, design = designed(GOALS[name])
    r = run_smoke(tmp_path, design, spec.title)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    assert "shell smoke ok" in r.stdout


def test_seed_rows_follow_the_rules_of_the_pack():
    spec, design = designed(FEST)
    rows = seed_for(design, spec.skill)
    assert len(rows["events"]) >= 5 and len(rows["registrations"]) >= 10
    emails = [(r["_idx"], r["email"]) for r in rows["registrations"]]
    assert len(set(emails)) == len(emails)
    assert all(len(r["phone"]) == 10 and r["phone"][0] in "6789" for r in rows["registrations"] + rows["volunteers"])
    assert all(r["amount"] > 0 for r in rows["sponsors"])
    per_event = {}
    for r in rows["registrations"]:
        per_event[r["_idx"]] = per_event.get(r["_idx"], 0) + 1
    assert all(n <= rows["events"][i]["capacity"] for i, n in per_event.items())
    assert rows == seed_for(design, spec.skill)  # deterministic


def test_a_single_resource_app_written_by_the_model_gets_the_shell_too(tmp_path):
    """The todo app: no rules contract, one resource read from its endpoints, a done box that saves at once, a filter and a search box."""
    from test_enrich import SPEC, design

    spec = SPEC.model_copy(deep=True)
    spec.features = ["Form to add a task", "Search box that filters the list as you type", "Filter the list by status"]
    d = design()
    d.ui_features = ["Search box that filters the list by text as you type", "Filter the list by priority"]
    spec.skill = match_skill("Build a todo app: title, priority Low/Medium/High", spec.title, ["todos"])
    d.look = choose_look("Build a todo app: title, priority Low/Medium/High", spec, d)
    assert d.look.layout == "shell" and d.look.skill == "tasks"
    from app.shell import app_config

    cfg = app_config(d, "Todo app")
    todo = cfg["resources"][0]
    assert todo["name"] == "todos" and todo["list"] == "/api/todos" and todo["item"] == "/api/todos/{id}" and todo["toggle"] == "done"
    assert "priority" in todo["filters"] and "title" in todo["search"]
    r = run_smoke(tmp_path, d, "Todo app")
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]


def test_a_calculator_keeps_its_panel():
    from test_orchestrator import DESIGN
    from app.schemas import ArchitectOutput

    d = ArchitectOutput.model_validate(DESIGN)
    assert choose_look("Build a calculator with history", None, d).layout == "calculator"


def test_the_numbers_of_a_build_are_read_from_the_project(tmp_path):
    from app.buildstats import project_stats, stats_line

    q = tmp_path / ".q"
    q.mkdir()
    spec, design = designed(FEST)
    (q / "design.json").write_text(design.model_dump_json(), encoding="utf-8")
    (q / "authorship.json").write_text(json.dumps({"app": {"functions": 62, "lines": 1240, "agent_share_functions": 0.71, "agent_share_lines": 0.2}}), encoding="utf-8")
    stats = project_stats(tmp_path)
    assert stats["modules"] == 4 and stats["tables"] == 4 and stats["pages"] == 10 and stats["endpoints"] == len(design.endpoints) and stats["functions"] == 62
    assert stats_line(stats).startswith("4 modules, 4 tables,") and "62 functions (71% written by agents), 1,240 lines" in stats_line(stats)
    assert project_stats(tmp_path / "nowhere") == {}
