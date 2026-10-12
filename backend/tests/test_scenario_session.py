"""Scenarios, step 4, through the API: start, the task and the guide, the incident channel, the session log, and the reference fix accepted. The scripted fake team plays the AI
employees (only the Reviewer is ever asked anything) and a scripted model plays the teammates' live replies; nothing needs Ollama."""
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.registry import ModelRegistry
from app.session import SessionManager

from api_helpers import make_client, make_settings, wait_for
from scenario_helpers import FIX_FILES, ScenarioLLM, apply_reference_fix

ID = "opd-bookings-down"


def manager(tmp_path, llm):
    settings = make_settings(tmp_path)
    mgr = SessionManager(settings, ModelRegistry.load(env={}), llm_factory=lambda registry, observer: llm)
    return TestClient(create_app(settings, mgr)), mgr


def events(s, type_):
    return [e for e in s.bus.history if e["type"] == type_]


@pytest.fixture
def scenario(tmp_path):
    """A running scenario session, waiting for the learner at the handed-over task."""
    llm = ScenarioLLM()
    client, mgr = manager(tmp_path, llm)
    r = client.post(f"/api/scenarios/{ID}/start")
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    s = mgr.get(pid)
    task = wait_for(lambda: next(iter(events(s, "human_task_assigned")), None), 90, "the task to be handed over")
    yield client, s, pid, task, llm
    s.orch.stop()
    mgr.shutdown()


# -- the scenario list and the start endpoint --------------------------------------------------------------

def test_the_scenario_list_has_one_card_without_the_script(tmp_path):
    client, mgr = manager(tmp_path, ScenarioLLM())
    cards = client.get("/api/scenarios").json()
    assert [c["id"] for c in cards] == [ID] and cards[0]["title"] == "Production incident: Bookings are down" and cards[0]["role"] == "backend"
    assert "timeline" not in cards[0] and "guide" not in cards[0] and "characters" not in cards[0]


def test_unknown_scenarios_and_a_second_session_are_refused(tmp_path):
    client, mgr = manager(tmp_path, ScenarioLLM())
    assert client.post("/api/scenarios/nope/start").status_code == 404
    assert client.post("/api/scenarios/..%2Fx/start").status_code == 404
    first = client.post(f"/api/scenarios/{ID}/start")
    assert first.status_code == 201
    again = client.post(f"/api/scenarios/{ID}/start")
    assert again.status_code == 409 and "already running" in again.json()["detail"]
    mgr.get(first.json()["id"]).orch.stop()
    mgr.shutdown()


def test_start_makes_a_project_from_the_seed_with_one_human_task_and_no_design_or_planning(scenario):
    client, s, pid, task, llm = scenario
    status = client.get(f"/api/projects/{pid}").json()
    assert status["mode"] == "simulation" and status["scenario"]["id"] == ID and status["scenario"]["role"] == "backend" and status["scenario"]["summary"]["events"] >= 1
    assert events(s, "simulation_started")[0]["human_roles"] == ["backend"] and events(s, "scenario_started")[0]["channel"] == {"id": "incident-opd", "name": "#incident-opd"}
    plan = events(s, "plan_created")
    assert len(plan) == 1 and plan[0]["tasks"] == [{"id": "h1", "title": "Fix: booking an appointment returns 500", "owner": "backend", "depends_on": [],
                                                    "files": ["backend/api/appointments.py", "backend/api/doctors.py"], "assignee": "human"}]
    assert task["agent"] == "backend" and task["task"] == "h1" and len(task["tests"]) == 3
    assert not [e for e in s.bus.history if e["type"] in ("architecture_ready", "spec_ready", "contract_updated", "look_chosen")]
    assert {name for _, name in llm.models_used} <= {"ReviewOutput"} and llm.chat_calls == 0  # nothing asked of a model yet: no architect, no planner
    root = Path(s.root)
    assert (root / "database/migrations/0007_rename_slot_time_to_slot_at.sql").is_file() and (root / "backend/api/doctors.py").is_file()
    log = subprocess.run(["git", "log", "--format=%H %s", "main"], cwd=root, capture_output=True, text=True).stdout.splitlines()
    seed_sha, seed_subject = log[-1].split(" ", 1)
    assert seed_subject == "Seed: Production incident: Bookings are down"
    seeded = subprocess.run(["git", "ls-tree", "-r", "--name-only", seed_sha], cwd=root, capture_output=True, text=True).stdout.splitlines()
    assert "backend/api/appointments.py" in seeded and not [f for f in seeded if f.endswith(".db") or "__pycache__" in f or f.startswith((".q/history", "data/", "node_modules/"))]
    assert (root / ".worktrees" / "backend" / "backend" / "api" / "appointments.py").is_file()


def test_the_task_document_carries_the_brief_and_the_guide_is_a_file_in_the_project(scenario):
    client, s, pid, task, llm = scenario
    doc = client.get(f"/api/projects/{pid}/tasks/h1/doc").text
    assert doc.startswith("# h1: Fix: booking an appointment returns 500") and "Production incident" not in doc.split("\n")[0] and "morning clinic opens at 09:00" in doc
    assert "tests/api/test_booking.py::test_booking_an_appointment_returns_201" in doc and "## Files you may edit" in doc and "backend/**" in doc and "## How to submit" in doc
    guide = client.get(f"/api/projects/{pid}/tasks/h1/guide")
    assert guide.status_code == 200 and guide.text.startswith("# Priya's guide: h1") and "**Reproduce it**" in guide.text
    assert (Path(s.root) / ".q" / "guides" / "h1.md").read_text(encoding="utf-8") == guide.text
    assert client.get(f"/api/projects/{pid}/tasks/nothing/guide").status_code == 404
    first = events(s, "guide_progress")[0]
    assert first["task"] == "h1" and first["current"] == "run-tests" and [x["state"] for x in first["steps"]][:2] == ["current", "todo"]


def test_the_ide_shows_the_app_with_the_migrations_readable_and_only_backend_writable(scenario):
    client, s, pid, task, llm = scenario
    tree = client.get(f"/api/projects/{pid}/ide/backend/tree").json()
    files = {f["path"]: f for f in tree["files"]}
    assert tree["ready"] and tree["task"] == "h1"
    assert files["backend/api/appointments.py"]["writable"] and files["backend/api/doctors.py"]["writable"]
    assert not files["database/migrations/0007_rename_slot_time_to_slot_at.sql"]["writable"] and files["database/migrations/0007_rename_slot_time_to_slot_at.sql"]["owner"] == "database"
    assert not files["tests/api/test_booking.py"]["writable"] and not files["database/appointments.py"]["writable"]
    denied = client.put(f"/api/projects/{pid}/ide/backend/file", json={"path": "database/migrations/0007_rename_slot_time_to_slot_at.sql", "content": "-- nope\n"})
    assert denied.status_code == 403


# -- the channel -------------------------------------------------------------------------------------------

def test_the_channel_endpoint_validates_and_a_teammate_answers(scenario):
    client, s, pid, task, llm = scenario
    post = lambda body: client.post(f"/api/projects/{pid}/channel", json=body)  # noqa: E731
    assert post({"text": "   "}).status_code == 400 and post({"text": "x" * 1001}).status_code == 400
    assert post({"text": "hello", "to": "nobody"}).status_code == 400 and post({"text": "hello", "to": "backend"}).status_code == 400  # you are not a teammate of yourself
    ok = post({"text": "Karan, did something change in the appointments table?"})
    assert ok.status_code == 200 and ok.json()["to"] == ["database"] and ok.json()["message"]["from"] == "human" and ok.json()["message"]["source"] == "learner"
    s.orch.director.join()
    karan = [m for m in s.orch.director.messages if m["from"] == "database"]
    assert len(karan) == 1 and karan[0]["source"] == "live" and karan[0]["text"] == llm.reply
    assert [e["from"] for e in events(s, "channel_message") if e["from"] in ("human", "database")] == ["human", "database"]


def test_when_ollama_is_down_the_channel_still_answers_from_the_script(tmp_path):
    client, mgr = manager(tmp_path, ScenarioLLM(fail=True))
    pid = client.post(f"/api/scenarios/{ID}/start").json()["id"]
    s = mgr.get(pid)
    wait_for(lambda: events(s, "human_task_assigned"), 90, "the task")
    client.post(f"/api/projects/{pid}/channel", json={"text": "Karan, what changed on Monday?", "to": "database"})
    s.orch.director.join()
    karan = [m for m in s.orch.director.messages if m["from"] == "database"][0]
    assert karan["source"] == "fallback" and "migration 0007" in karan["text"]
    assert client.get(f"/api/projects/{pid}/session").json()["summary"]["hints"] == 1
    s.orch.stop()
    mgr.shutdown()


def test_the_channel_belongs_to_scenario_sessions_only(tmp_path):
    client, settings, mgr = make_client(tmp_path)
    pid = client.post("/api/projects", json={"goal": "Build a calculator with history", "mode": "simulation", "human_roles": ["database"]}).json()["id"]
    assert client.post(f"/api/projects/{pid}/channel", json={"text": "hi"}).status_code == 409
    assert client.get(f"/api/projects/{pid}/session").status_code == 409
    assert "scenario" not in client.get(f"/api/projects/{pid}").json()
    mgr.get(pid).orch.stop()
    mgr.shutdown()


# -- the whole incident: fix it through the IDE endpoints ------------------------------------------------------

def test_the_reference_fix_through_the_ide_is_accepted_and_every_step_is_in_the_session_log(scenario):
    client, s, pid, task, llm = scenario
    ide = f"/api/projects/{pid}/ide/backend"
    run_tests = lambda: (n := len(events(s, "human_test_result")), client.post(f"{ide}/tests"), wait_for(lambda: len(events(s, "human_test_result")) > n and events(s, "human_test_result")[n], 120, "the test result"))[2]  # noqa: E731

    red = run_tests()
    assert red["ok"] is False and red["failed"] >= 3
    current = {p: client.get(f"{ide}/file", params={"path": p}).json()["content"] for p in FIX_FILES}
    client.get(f"{ide}/file", params={"path": "database/migrations/0007_rename_slot_time_to_slot_at.sql"})
    client.post(f"/api/projects/{pid}/channel", json={"text": "Found it: the routes still say slot_time, the migration renamed it.", "to": "database"})
    s.orch.director.join()
    for path, text in apply_reference_fix(current).items():
        assert client.put(f"{ide}/file", json={"path": path, "content": text}).status_code == 200
    green = run_tests()
    assert green["ok"] is True and green["failed"] == 0
    answer = {}
    for _ in range(4):  # the Reviewer may send green work back (the scripted one does not)
        answer = client.post(f"/api/projects/{pid}/tasks/h1/submit").json()
        if answer["ok"]:
            break
    assert answer["ok"] and answer["stage"] == "accepted"
    wait_for(lambda: client.get(f"/api/projects/{pid}").json()["state"] in ("done", "failed"), 180, "the session to end")
    status = client.get(f"/api/projects/{pid}").json()
    assert status["state"] == "done" and status["finished"]["ok"] is True

    info = client.get(f"/api/projects/{pid}/session").json()
    log = info["events"]
    kinds = [e["kind"] for e in log]
    assert [e["id"] for e in log] == [f"E{i:03d}" for i in range(1, len(log) + 1)]  # stable, quotable ids
    assert all(a["t"] <= b["t"] for a, b in zip(log, log[1:])) and log[0]["kind"] == "session_started" and log[0]["t"] == 0.0
    for k in ("file_opened", "file_saved", "test_run", "test_result", "message_posted", "hint_given", "submit", "submit_result", "session_finished", "team_message"):
        assert k in kinds, f"{k} is not in the session log: {kinds}"
    saved = {e["path"]: e for e in log if e["kind"] == "file_saved"}
    assert set(saved) == set(FIX_FILES) and saved["backend/api/appointments.py"]["added"] == 4 and saved["backend/api/appointments.py"]["removed"] == 4
    assert saved["backend/api/doctors.py"]["added"] == 1 and saved["backend/api/doctors.py"]["removed"] == 1 and saved["backend/api/doctors.py"]["size"] > 100
    opened = [e["path"] for e in log if e["kind"] == "file_opened"]
    assert "backend/api/appointments.py" in opened and "database/migrations/0007_rename_slot_time_to_slot_at.sql" in opened
    runs = [(e["kind"], e.get("trigger"), e.get("ok")) for e in log if e["kind"] in ("test_run", "test_result")]
    assert runs[:2] == [("test_run", "ide", None), ("test_result", "ide", False)] and ("test_result", "ide", True) in runs and runs[-2:] == [("test_run", "submit", None), ("test_result", "submit", True)]
    assert [e["kind"] for e in log if e["kind"] in ("submit", "submit_result")] == ["submit", "submit_result"] and next(e for e in log if e["kind"] == "submit_result")["stage"] == "accepted"
    assert [e["n"] for e in log if e["kind"] == "hint_given"] == [1] and info["summary"]["hints"] == 1 and info["summary"]["saves"] == 2 and info["summary"]["submits"] == 1
    assert log[-1]["kind"] == "session_finished" and log[-1]["ok"] is True
    # the same entries are on the event stream and in the project's file
    assert [e["id"] for e in events(s, "session_event")] == [e["id"] for e in log]
    assert [json.loads(x) for x in (Path(s.root) / ".q" / "session" / "log.jsonl").read_text(encoding="utf-8").splitlines()] == log
    # the guide is complete and the team reacted to the accepted fix
    assert info["guide"]["current"] is None and info["guide"]["done"] == 7 and events(s, "guide_progress")[-1]["done"] == 7
    said = [(m["from"], m.get("ref")) for m in info["messages"]]
    assert ("qa", "qa-report") in said and ("architect", "react-accepted-lead") in said
    assert (Path(s.root) / "backend" / "api" / "doctors.py").read_text(encoding="utf-8").count("slot_time") == 0 and "[human] Fix: booking an appointment returns 500" in subprocess.run(
        ["git", "log", "--all", "--format=%s"], cwd=s.root, capture_output=True, text=True).stdout


def test_a_red_submit_is_logged_and_ananya_names_the_failing_tests(scenario):
    client, s, pid, task, llm = scenario
    answer = client.post(f"/api/projects/{pid}/tasks/h1/submit").json()
    assert not answer["ok"] and answer["stage"] == "tests" and any("test_booking_an_appointment_returns_201" in f for f in answer["failed"])
    log = client.get(f"/api/projects/{pid}/session").json()
    res = [e for e in log["events"] if e["kind"] == "submit_result"]
    assert len(res) == 1 and res[0]["ok"] is False and res[0]["stage"] == "tests" and res[0]["failed"] == answer["failed"]
    qa = [m for m in log["messages"] if m.get("ref") == "react-tests-failed"]
    assert len(qa) == 1 and "test_booking_an_appointment_returns_201" in qa[0]["text"]
    assert not events(s, "project_done")  # the task is still open
