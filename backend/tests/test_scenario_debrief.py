"""Step 5 through the API: the debrief after an accepted fix (the meeting, the judges' posts, the report and its files), attempt numbering and history. The scripted fake team plays
the AI employees and a scripted model words the points; nothing needs Ollama."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.registry import ModelRegistry
from app.scenarios.reports import History
from app.scenarios.wording import PointWording
from app.session import SessionManager

from api_helpers import make_client, make_settings, wait_for
from scenario_helpers import FIX_FILES, REGRESSION_PATH, REGRESSION_TEST, ScenarioLLM, apply_reference_fix

ID = "opd-bookings-down"


def manager(tmp_path, llm):
    settings = make_settings(tmp_path)
    mgr = SessionManager(settings, ModelRegistry.load(env={}), llm_factory=lambda registry, observer: llm)
    return TestClient(create_app(settings, mgr)), mgr, settings


def events(s, type_):
    return [e for e in s.bus.history if e["type"] == type_]


def start(client, mgr):
    r = client.post(f"/api/scenarios/{ID}/start")
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    s = mgr.get(pid)
    wait_for(lambda: next(iter(events(s, "human_task_assigned")), None), 90, "the task to be handed over")
    return pid, s


def run_tests(client, s, pid):
    n = len(events(s, "human_test_result"))
    client.post(f"/api/projects/{pid}/ide/backend/tests")
    return wait_for(lambda: len(events(s, "human_test_result")) > n and events(s, "human_test_result")[n], 120, "the test result")


def submit(client, pid):
    answer = {}
    for _ in range(4):  # the Reviewer may send green work back (the scripted one does not)
        answer = client.post(f"/api/projects/{pid}/tasks/h1/submit").json()
        if answer["ok"]:
            break
    return answer


def fix_it(client, pid):
    ide = f"/api/projects/{pid}/ide/backend"
    current = {p: client.get(f"{ide}/file", params={"path": p}).json()["content"] for p in FIX_FILES}
    for path, text in apply_reference_fix(current).items():
        assert client.put(f"{ide}/file", json={"path": path, "content": text}).status_code == 200


def add_regression_test(client, pid):
    assert client.put(f"/api/projects/{pid}/ide/backend/file", json={"path": REGRESSION_PATH, "content": REGRESSION_TEST}).status_code == 200


def strong_attempt(client, s, pid):
    """Reproduce, read the route and the migration, tell the channel, add a regression test, run it red, fix, run green, tell the channel, submit."""
    ide = f"/api/projects/{pid}/ide/backend"
    assert run_tests(client, s, pid)["ok"] is False
    client.get(f"{ide}/file", params={"path": "backend/api/appointments.py"})
    client.get(f"{ide}/file", params={"path": "database/migrations/0007_rename_slot_time_to_slot_at.sql"})
    client.post(f"/api/projects/{pid}/channel", json={"text": "Update: the routes still say slot_time, migration 0007 renamed it to slot_at. Fixing now."})
    add_regression_test(client, pid)
    assert run_tests(client, s, pid)["ok"] is False
    fix_it(client, pid)
    assert run_tests(client, s, pid)["ok"] is True
    client.post(f"/api/projects/{pid}/channel", json={"text": "Fix is ready: both routes use slot_at and a regression test covers it. Submitting."})
    answer = submit(client, pid)
    assert answer["ok"] and answer["stage"] == "accepted"


def finish(s, timeout=240):
    return wait_for(lambda: next(iter(events(s, "debrief_ended")), None), timeout, "the debrief to end")


@pytest.fixture
def scenario(tmp_path):
    llm = ScenarioLLM()
    client, mgr, settings = manager(tmp_path, llm)
    pid, s = start(client, mgr)
    yield client, s, pid, llm, mgr, settings
    s.orch.stop()
    mgr.shutdown()


# -- a strong attempt -----------------------------------------------------------------------------------------------------

def test_a_strong_attempt_ends_in_the_meeting_room_with_five_judges_and_a_full_report(scenario):
    client, s, pid, llm, mgr, settings = scenario
    assert client.get(f"/api/projects/{pid}/report").status_code == 404  # nothing before the fix is accepted
    strong_attempt(client, s, pid)
    ended = finish(s)
    assert ended["ok"] is True and not events(s, "debrief_failed")
    at = lambda pred: next(i for i, e in enumerate(s.bus.history) if pred(e))  # noqa: E731
    done, began, report_at, over = at(lambda e: e["type"] == "project_done"), at(lambda e: e["type"] == "debrief_started"), at(lambda e: e["type"] == "debrief_report"), at(lambda e: e["type"] == "debrief_ended")
    first_post = at(lambda e: e["type"] == "channel_message" and e.get("source") == "debrief")
    assert done < began < first_post < report_at < over  # the team walks to the meeting room, the judges speak, the report is published, everyone walks back
    started = events(s, "debrief_started")[0]
    assert started["attempt"] == 1 and [j["name"] for j in started["judges"]] == ["Aarav", "Karan", "Vikram", "Ananya", "Aarav"] and started["rubric"]["id"] == "opd-bookings-down-v1"

    posts = [e for e in events(s, "channel_message") if e.get("source") == "debrief"]
    judges = [p for p in posts if p.get("criterion")]
    assert [(p["from"], p["criterion"], p["score"]) for p in judges] == [("architect", "communication", 4), ("database", "diagnosis", 4), ("reviewer", "fix_quality", 4), ("qa", "testing", 4), ("architect", "ownership", 4)]
    for p in judges:
        assert re.search(r"^[A-Za-z ]+ 4/4\. At \d\d:\d\d: “.+” .+ Tip: .+", p["text"]) and len(p["bubble"]) <= 78 and p["bubble"].startswith(p["text"].split(".")[0] + ".")
        assert p["debrief"] is True and p["id"].startswith("C")
    assert posts[0]["from"] == "planner" and posts[-1]["from"] == "planner" and "Report is ready: 100/100" in posts[-1]["text"]

    report = client.get(f"/api/projects/{pid}/report").json()
    assert report["total"] == 100 and report["attempt"] == 1 and [c["score"] for c in report["criteria"]] == [4, 4, 4, 4, 4]
    fair = report["fairness"]
    assert fair["points"] == fair["quoted"] == fair["matched"] == 20 and fair["dropped"] == [] and fair["rubric"] == "v1"
    assert fair["tests_rerun"]["ok"] is True and fair["tests_rerun"]["passed"] == fair["tests_rerun"]["total"] and fair["tests_rerun"]["total"] >= 100
    assert fair["wording"]["source"] == "template" and fair["wording"]["reason"] == "error"  # the scripted model was not set up to word anything: the template wording was used
    assert events(s, "debrief_report")[0]["report"] == report
    log = {e["id"]: e for e in client.get(f"/api/projects/{pid}/session").json()["events"]}
    assert all(r["event"] in log and r["verified"] and set(r["events"]) <= set(log) for r in report["rows"])  # every point quotes an entry of the session log
    assert report["events"] and all(k in log and report["events"][k] == log[k] for k in report["events"])
    assert client.get(f"/api/projects/{pid}/session").json()["events"][-1]["kind"] == "session_finished"  # the debrief adds nothing to the evidence


def test_the_report_is_saved_in_the_project_as_markdown_and_json_and_served_by_the_endpoint(scenario):
    client, s, pid, llm, mgr, settings = scenario
    strong_attempt(client, s, pid)
    finish(s)
    folder = Path(s.root) / ".q" / "reports"
    saved = json.loads((folder / "attempt-1.json").read_text(encoding="utf-8"))
    assert saved == client.get(f"/api/projects/{pid}/report").json() and saved["files"] == {"md": ".q/reports/attempt-1.md", "json": ".q/reports/attempt-1.json"}
    md = (folder / "attempt-1.md").read_text(encoding="utf-8")
    assert md.startswith("# Debrief: Production incident: Bookings are down") and "**Attempt 1: 100/100**" in md and "## Testing 4/4" in md and "Quotes matched to the session log: 20/20" in md
    r = client.get(f"/api/projects/{pid}/report", params={"format": "md"})
    assert r.status_code == 200 and r.text == md and r.headers["content-type"].startswith("text/plain")
    assert client.get(f"/api/projects/{pid}/report", params={"format": "xml"}).status_code == 400
    history = json.loads((Path(settings.workspace) / ".q-attempts" / f"{ID}.json").read_text(encoding="utf-8"))
    assert [(a["attempt"], a["total"], a["project"]) for a in history] == [(1, 100, Path(s.root).name)]
    assert history[0]["scores"] == {"communication": 4, "diagnosis": 4, "fix_quality": 4, "testing": 4, "ownership": 4}


# -- a weak attempt ------------------------------------------------------------------------------------------------------------

def weak_attempt(client, s, pid):
    """Fix first, submit red once (one route still wrong), no test of its own, asks Karan twice, never posts."""
    ide = f"/api/projects/{pid}/ide/backend"
    current = {p: client.get(f"{ide}/file", params={"path": p}).json()["content"] for p in FIX_FILES}
    fixed = apply_reference_fix(current)
    appt = "backend/api/appointments.py"
    assert client.put(f"{ide}/file", json={"path": appt, "content": fixed[appt]}).status_code == 200  # only one of the two files
    first = client.post(f"/api/projects/{pid}/tasks/h1/submit").json()
    assert first["ok"] is False and first["stage"] == "tests"
    client.post(f"/api/projects/{pid}/channel", json={"text": "Karan, what changed?", "to": "database"})
    client.post(f"/api/projects/{pid}/channel", json={"text": "Karan, is anything else renamed?", "to": "database"})
    s.orch.director.join()
    other = "backend/api/doctors.py"
    assert client.put(f"{ide}/file", json={"path": other, "content": fixed[other]}).status_code == 200
    answer = submit(client, pid)
    assert answer["ok"] and answer["stage"] == "accepted"


def test_a_weak_attempt_gets_gaps_with_advice_and_every_point_is_still_quoted(tmp_path):
    def word(prompt: str):
        evidence = dict(re.findall(r"^(F\d\d) \[.*\n   evidence: (E\d+) at", prompt, re.M))
        text = dict(re.findall(r"^(F\d\d) \[.*\n   evidence: E\d+ at [\d:]+: \"(.*?)\"$", prompt, re.M))
        f1 = "F01"
        return [PointWording(finding=f1, event=evidence[f1], quote=text[f1][:30], note="You never posted, so the lead had nobody to ask.", advice="Post a first update in the channel within two minutes."),
                PointWording(finding="F02", event="E999", quote="you answered at once", note="You answered at once.", advice=""),                    # an event that does not exist
                PointWording(finding="F05", event=evidence["F05"], quote="I ran the tests first", note="You ran the tests first.", advice="")]  # a quote that is not in the entry

    llm = ScenarioLLM(wording=word)
    client, mgr, settings = manager(tmp_path, llm)
    pid, s = start(client, mgr)
    try:
        weak_attempt(client, s, pid)
        finish(s)
        report = client.get(f"/api/projects/{pid}/report").json()
        rule = lambda name: next(r for r in report["rows"] if r["rule"] == name)  # noqa: E731
        assert report["total"] < 100 and len(report["rows"]) == 20 and report["fairness"]["matched"] == 20
        crit = {c["id"]: c["score"] for c in report["criteria"]}
        assert crit["testing"] == 0 and crit["communication"] == 4  # a red submit, no green run of its own, no new test; but the questions to Karan were early and named the rename
        assert rule("no_red_submit")["kind"] == "gap" and rule("regression_test_added")["kind"] == "gap" and rule("regression_test_proves_fix")["kind"] == "gap"
        assert rule("reproduced_first")["kind"] == "gap" and rule("reproduced_first")["event"].startswith("E")  # the weak attempt fixed first and ran the tests later
        assert rule("few_hints")["kind"] == "gap" and rule("few_hints")["event"].startswith("E")
        assert all(r["advice"] for r in report["rows"] if r["kind"] == "gap") and all(not r["advice"] for r in report["rows"] if r["kind"] == "strength")
        # the model's wording: one point held, two were dropped and recorded; the score did not move
        first = rule("first_update")
        assert first["worded_by"] == "model" and first["note"] == "You never posted, so the lead had nobody to ask."
        dropped = report["fairness"]["dropped"]
        assert [(d["finding"], d["reason"]) for d in dropped][:1] == [("F02", "event E999 is not in the session log")] and any(d["finding"] == "F05" and "the quote is not in" in d["reason"] for d in dropped)
        assert report["fairness"]["wording"]["source"] == "mixed" and report["fairness"]["wording"]["model_points"] == 1
        assert len(report["focus"]) == 3 and all(f for f in report["focus"])
        md = client.get(f"/api/projects/{pid}/report", params={"format": "md"}).text
        assert "**GAP**" in md and "Claims dropped: 2" in md
    finally:
        s.orch.stop()
        mgr.shutdown()


# -- attempts --------------------------------------------------------------------------------------------------------------

def test_the_second_attempt_is_numbered_two_and_the_report_carries_the_first(tmp_path):
    llm = ScenarioLLM()
    client, mgr, settings = manager(tmp_path, llm)
    History(settings.workspace, ID).add({"attempt": 1, "total": 60, "scores": {"communication": 3, "diagnosis": 3, "fix_quality": 3, "testing": 2, "ownership": 1}, "project": "opd-bookings-down",
                                         "finished_at": "2026-10-12T09:00:00", "elapsed": 600.0})
    pid, s = start(client, mgr)
    try:
        info = client.get(f"/api/projects/{pid}").json()
        assert info["scenario"]["attempt"] == 2 and events(s, "scenario_started")[0]["attempt"] == 2 and client.get(f"/api/projects/{pid}/session").json()["attempt"] == 2
        strong_attempt(client, s, pid)
        finish(s)
        report = client.get(f"/api/projects/{pid}/report").json()
        assert report["attempt"] == 2 and [(a["attempt"], a["total"]) for a in report["attempts"]] == [(1, 60), (2, 100)]
        assert report["files"]["md"] == ".q/reports/attempt-2.md" and (Path(s.root) / ".q" / "reports" / "attempt-2.md").is_file()
        assert "Report is ready: 100/100 (attempt 1: 60)" in [e for e in events(s, "channel_message") if e.get("source") == "debrief"][-1]["text"]
        assert History(settings.workspace, ID).next_number() == 3
    finally:
        s.orch.stop()
        mgr.shutdown()


def test_a_session_that_is_stopped_before_the_fix_is_accepted_has_no_debrief_and_no_history(scenario):
    client, s, pid, llm, mgr, settings = scenario
    run_tests(client, s, pid)
    s.orch.stop()
    wait_for(lambda: client.get(f"/api/projects/{pid}").json()["state"] in ("done", "failed"), 60, "the session to end")
    assert not events(s, "debrief_started") and client.get(f"/api/projects/{pid}/report").status_code == 404
    assert History(settings.workspace, ID).attempts() == []


def test_the_report_belongs_to_scenario_sessions_only(tmp_path):
    client, settings, mgr = make_client(tmp_path)
    pid = client.post("/api/projects", json={"goal": "Build a calculator with history", "mode": "simulation", "human_roles": ["database"]}).json()["id"]
    assert client.get(f"/api/projects/{pid}/report").status_code == 409
    mgr.get(pid).orch.stop()
    mgr.shutdown()
