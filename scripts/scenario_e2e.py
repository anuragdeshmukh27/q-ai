"""End-to-end check of a scenario ("Production incident: Bookings are down" by default, "Double bookings" with --scenario opd-double-bookings, or "The form says it saved"
with --scenario opd-form-says-saved), driven through the HTTP API with the LLM stubbed (no Ollama, no GPU).

    backend\\.venv\\Scripts\\python.exe scripts\\scenario_e2e.py            run the check on port 8200 and stop the server (exit 0 = all steps passed)
    backend\\.venv\\Scripts\\python.exe scripts\\scenario_e2e.py --serve    only start the stubbed backend on 8200 for the UI, no scripted flow (start the frontend with Q_BACKEND=http://127.0.0.1:8200)

The flow: start the scenario, wait for the task and Ananya's report, run the tests (red), open the files, ask Karan something in the channel, apply the reference fix through
the IDE endpoints (the same calls the editor makes), run the tests (green), submit, and check the fix is accepted, the session log holds every step and the guide is complete.
Then the debrief: the team meets, five judges post their criterion, and the report (scores, rows that quote the session log, fairness checks, files, attempt history) is checked.
Last, "Watch a run": a scripted strong run at 2x speed plays the scenario through the same calls (about 90 seconds), scores 100 as a demo, and the learner's attempt history is untouched.
Ports 8000 and 5173 are never used.
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app.main import create_app  # noqa: E402
from app.registry import ModelRegistry  # noqa: E402
from app.session import SessionManager  # noqa: E402
from api_helpers import make_settings  # noqa: E402
from app.scenarios.autoplay import reference_fix, regression_test  # noqa: E402
from scenario_helpers import FIX_FILES, REGRESSION_PATH, REGRESSION_TEST, ScenarioLLM, apply_reference_fix  # noqa: E402

SCENARIO = "opd-bookings-down"
TWO = "opd-double-bookings"
THREE = "opd-form-says-saved"
SCENARIO_IDS = [SCENARIO, TWO, THREE]
REGRESSION_THREE = "tests/regression/test_regression_refusals.py"
SHELL = "static/shell.js"
CAUSE_THREE = ("Update: the server is right, it answers 409 with a message. The page is wrong: call() in static/shell.js only throws when the answer has no body, "
               "so a 409 with a detail is treated as a success and every form and button says it saved. I will fix call().")
REGRESSION_TWO = "tests/regression/test_regression_double_booking.py"
MIGRATION_TWO = "database/migrations/0008_one_booking_per_slot.sql"
FORBIDDEN_PORTS = {8000, 5173}


class Check:
    def __init__(self):
        self.failed: list[str] = []

    def __call__(self, ok: bool, what: str, detail: str = "") -> None:
        print(f"  [{'ok' if ok else 'FAIL'}] {what}{(': ' + detail) if detail and not ok else ''}")
        if not ok:
            self.failed.append(what)


def wait(fn, timeout: float, what: str):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for {what}")


def bookings_down(c: httpx.Client, check: Check, tmp: Path) -> None:
    """The first scenario ("Bookings are down", the backend engineer), through the same HTTP calls the browser makes."""
    cards = c.get("/api/scenarios").json()
    check([x["id"] for x in cards] == SCENARIO_IDS, "the scenario list has all three incidents", str(cards))
    r = c.post(f"/api/scenarios/{SCENARIO}/start")
    check(r.status_code == 201 and r.json()["mode"] == "simulation" and r.json()["scenario"]["id"] == SCENARIO, "scenario started", r.text)
    pid = r.json()["id"]
    events = lambda: c.get(f"/api/projects/{pid}/events").json()  # noqa: E731
    of = lambda t: [e for e in events() if e["type"] == t]  # noqa: E731
    task = wait(lambda: next(iter(of("human_task_assigned")), None), 120, "your task")
    tid = task["task"]
    check(task["agent"] == "backend" and len(task["tests"]) == 3, f"your task {tid} was handed over: {task['title']}")
    check(not of("architecture_ready") and not of("spec_ready"), "no design or planning step ran")
    report = wait(lambda: next((e for e in of("channel_message") if e["from"] == "qa"), None), 30, "Ananya's report")
    check("TypeError: add_appointment() got an unexpected keyword argument 'slot_time'" in report["text"], "Ananya reported the real error in #incident-opd")
    doc = c.get(f"/api/projects/{pid}/tasks/{tid}/doc").text
    check("morning clinic opens at 09:00" in doc and "test_booking_an_appointment_returns_201" in doc, "the task document carries the brief and the acceptance tests")
    check(c.get(f"/api/projects/{pid}/tasks/{tid}/guide").text.startswith("# Priya's guide"), "Priya's guide is a file in the project")

    ide = f"/api/projects/{pid}/ide/backend"
    test_run = lambda: (n := len(of("human_test_result")), c.post(f"{ide}/tests"), wait(lambda: len(of("human_test_result")) > n and of("human_test_result")[n], 120, "the test result"))[2]  # noqa: E731
    print("-- the bug")
    red = test_run()
    check(red["ok"] is False and red["failed"] >= 3, "run tests: red before the fix", red["summary"])
    current = {p: c.get(f"{ide}/file", params={"path": p}).json()["content"] for p in FIX_FILES}
    check(all("slot_time" in text for text in current.values()), "both route files still say slot_time")
    c.get(f"{ide}/file", params={"path": "database/migrations/0007_rename_slot_time_to_slot_at.sql"})
    check(c.put(f"{ide}/file", json={"path": "database/migrations/0007_rename_slot_time_to_slot_at.sql", "content": "-- x\n"}).status_code == 403, "the migration is read-only for you")
    asked = c.post(f"/api/projects/{pid}/channel", json={"text": "Karan, did anything change in the appointments table?", "to": "database"})
    check(asked.status_code == 200 and asked.json()["to"] == ["database"], "asked Karan in the channel")
    wait(lambda: any(e["from"] == "database" and e.get("reply_to") for e in of("channel_message")), 30, "Karan's reply")
    check(True, "Karan replied")
    found = c.get(f"{ide}/search", params={"q": "slot_time"}).json()
    check(found["matches"] >= 6 and any(f["path"].startswith("database/migrations") for f in found["results"]) and any(f["path"] == "backend/api/doctors.py" for f in found["results"]),
          "a project-wide search finds the old name, in the read-only migration too", str(found["files"]))
    posted = c.post(f"/api/projects/{pid}/channel", json={"text": "Update: the routes still say slot_time but migration 0007 renamed it to slot_at. Fixing now."})
    check(posted.status_code == 200, "posted an update that names the cause")
    saved = c.put(f"{ide}/file", json={"path": REGRESSION_PATH, "content": REGRESSION_TEST})
    check(saved.status_code == 200, "saved a regression test in tests/regression/")
    red_regression = test_run()
    check(red_regression["ok"] is False and any(REGRESSION_PATH in t["id"] and t["outcome"] == "failed" for t in red_regression["tests"]), "the regression test is red before the fix")

    print("-- the reference fix, saved the way the editor saves")
    for path, text in apply_reference_fix(current).items():
        check(c.put(f"{ide}/file", json={"path": path, "content": text}).status_code == 200, f"saved {path}")
    green = test_run()
    check(green["ok"] is True and green["failed"] == 0, "run tests: green after the fix", green["summary"])
    c.post(f"/api/projects/{pid}/channel", json={"text": "Fix is ready: both routes use slot_at and a regression test covers it. Submitting."})
    answer: dict = {}
    for attempt in range(1, 5):  # the Reviewer may send green work back (at most twice)
        answer = c.post(f"/api/projects/{pid}/tasks/{tid}/submit").json()
        print(f"  submit {attempt}: {answer['stage']}")
        if answer["ok"]:
            break
    check(answer["ok"] is True and answer["stage"] == "accepted", "submit accepted")
    state = wait(lambda: (s := c.get(f"/api/projects/{pid}").json())["state"] in ("done", "failed") and s, 180, "the session to finish")
    check(state["state"] == "done" and state["finished"]["ok"] is True, f"the build finished ok (state {state['state']})", str(state.get("problems")))

    print("-- the session log")
    info = c.get(f"/api/projects/{pid}/session").json()
    kinds = [e["kind"] for e in info["events"]]
    check([e["id"] for e in info["events"]] == [f"E{i:03d}" for i in range(1, len(kinds) + 1)], "events have stable ids E001, E002, ...")
    check(all(k in kinds for k in ("file_opened", "file_saved", "test_run", "test_result", "message_posted", "hint_given", "submit", "submit_result", "session_finished")), "every kind of step is in the log", str(sorted(set(kinds))))
    check(info["summary"]["hints"] == 1 and info["summary"]["saves"] == 3 and info["summary"]["searches"] == 1, "one hint (the question to Karan; the two status updates were only acknowledged), three saves and one search were counted", str(info["summary"]))
    check(info["guide"]["current"] is None and info["guide"]["done"] == 8, "Priya's guide is complete", str(info["guide"]["done"]))
    check(any(m.get("ref") == "react-accepted-lead" for m in info["messages"]), "Aarav thanked you for the fix")

    print("-- the debrief")
    ended = wait(lambda: next(iter(of("debrief_ended")), None), 240, "the debrief to end")
    check(ended["ok"] is True and not of("debrief_failed"), "the team met and the debrief ended")
    started = of("debrief_started")[0]
    check(started["attempt"] == 1 and len(started["judges"]) == 5, "the team went to the meeting room (attempt 1, five judges)")
    judges = [m for m in of("channel_message") if m.get("criterion")]
    check([(m["from"], m["criterion"]) for m in judges] == [("architect", "communication"), ("database", "diagnosis"), ("reviewer", "fix_quality"), ("qa", "testing"), ("architect", "ownership")],
          "each judge posted their criterion in #incident-opd", str([(m["from"], m["criterion"]) for m in judges]))
    check(all(re.search(r"^[A-Za-z ]+ \d/4\. At \d\d:\d\d: “.+” .+ Tip: .+", m["text"]) for m in judges), "every post has a score, a quoted moment with its timestamp and a tip")
    rep = c.get(f"/api/projects/{pid}/report").json()
    check(rep["total"] == 100 and [x["score"] for x in rep["criteria"]] == [4, 4, 4, 4, 4], "the report scores the run 100/100", f"{rep['total']} {[x['score'] for x in rep['criteria']]}")
    log_ids = {e["id"]: e for e in info["events"]}
    check(len(rep["rows"]) == 20 and all(r["verified"] and (r["event"] in log_ids or rep["events"][r["event"]]["kind"] == "debrief_check") for r in rep["rows"]), "every point quotes an entry that is in the session log or one of the debrief's own measurements")
    fair = rep["fairness"]
    check(fair["points"] == fair["quoted"] == fair["matched"] == 20 and fair["dropped"] == [] and fair["rubric"] == "v1", "fairness: 20 points quoted, 20 quotes matched, none dropped, rubric v1", str(fair))
    check(fair["tests_rerun"]["ok"] is True and fair["tests_rerun"]["passed"] == fair["tests_rerun"]["total"], "the suite was re-run on the merged project", str(fair["tests_rerun"]))
    check(fair["dropped"] == [] and fair["ai_rejected"] == [], "a clean run shows 0 unbacked claims and no AI line rejected")
    check(fair["voices"] == {"judges": "template", "coach": "template", "reason": "error"} and {r["worded_by"] for r in rep["rows"]} == {"rule"},
          "every point is its rule's; the stubbed model wrote no line and no paragraph, so the template ones were used", str(fair["voices"]))
    by = {**log_ids, **rep["events"]}
    check(all(by[r["event"]]["t"] == r["t"] for r in rep["rows"]), "every point carries the time of the entry it quotes")
    check(all(re.findall(r"\d\d:\d\d", r["note"]) in ([], [f"{int(r['t']) // 60:02d}:{int(r['t']) % 60:02d}"]) for r in rep["rows"]), "the time in every note is the time of the entry it quotes")
    checks = [e for e in rep["events"].values() if e["kind"] == "debrief_check"]
    check(len(checks) == 5 and any(e["text"].startswith("Debrief re-run on main: ") and "passed" in e["text"] for e in checks) and any(e["text"].startswith("Regression test ") for e in checks),
          "the debrief's own measurements are entries a point quotes", str([e["text"] for e in checks]))
    scoring = c.get(f"/api/projects/{pid}/session").json()["scoring"]
    check(sum(len(x["rules"]) for x in scoring) == 20 and len(scoring) == 5, "the 20 rules in plain words come with the session (How you are scored)")
    md = c.get(f"/api/projects/{pid}/report", params={"format": "md"})
    check(md.status_code == 200 and md.text.startswith("# Debrief: Production incident") and "**Attempt 1: 100/100**" in md.text, "the markdown report is served")
    folder = next((tmp / "ws").glob("opd-bookings-down*")) / ".q" / "reports"
    check((folder / "attempt-1.md").read_text(encoding="utf-8") == md.text and json.loads((folder / "attempt-1.json").read_text(encoding="utf-8")) == rep, ".q/reports/attempt-1.md and .json are in the project and match the endpoint")
    history = json.loads((tmp / "ws" / ".q-attempts" / f"{SCENARIO}.json").read_text(encoding="utf-8"))
    check([(a["attempt"], a["total"]) for a in history] == [(1, 100)], "the attempt history has attempt 1 with its score", str(history))
    check(info["events"][-1]["kind"] == "session_finished", "the debrief added nothing to the session log")
    print("-- autoplay (a scripted strong run at 2x)")
    r = c.post(f"/api/scenarios/{SCENARIO}/autoplay", json={"variant": "strong", "speed": 2})
    check(r.status_code == 201 and r.json()["scenario"]["kind"] == "demo" and r.json()["scenario"]["attempt"] == 1, "autoplay started as demo attempt 1", r.text[:200])
    apid = r.json()["id"]
    aevents = lambda: c.get(f"/api/projects/{apid}/events").json()  # noqa: E731
    ended_run = wait(lambda: next((e for e in aevents() if e["type"] == "autoplay_ended"), None), 400, "the autoplay run to end")
    check(ended_run["reason"] == "done", "the scripted run reached the end of the debrief", str(ended_run))
    kinds_seen = {e["type"] for e in aevents()}
    check({"autoplay_started", "autoplay_step", "autoplay_open_file", "autoplay_search", "autoplay_edit", "human_test_output", "debrief_report"} <= kinds_seen, "the screen has every event it follows: opens, search, edits, test output, report")
    demo = c.get(f"/api/projects/{apid}/report").json()
    check(demo["total"] == 100 and demo["kind"] == "demo" and demo["variant"] == "strong" and demo["attempt"] == 1, "the demo scored 100 and is marked demo", f"{demo['total']} {demo['kind']}")
    history = json.loads((tmp / "ws" / ".q-attempts" / f"{SCENARIO}.json").read_text(encoding="utf-8"))
    check([(a["attempt"], a["total"]) for a in history] == [(1, 100)], "the learner's attempt history did not take the demo", str(history))
    mine = json.loads((tmp / "ws" / ".q-attempts" / f"{SCENARIO}-demo.json").read_text(encoding="utf-8"))
    check([(a["attempt"], a["total"], a["variant"]) for a in mine] == [(1, 100, "strong")], "the demo has a history of its own", str(mine))


def ref_regression() -> str:
    return regression_test(TWO)


def ref_migration() -> str:
    return reference_fix({}, TWO, create=(MIGRATION_TWO,))[MIGRATION_TWO]


def double_bookings(c: httpx.Client, check: Check, tmp: Path) -> None:
    """The second scenario ("Double bookings", the database engineer), through the same HTTP calls the browser makes."""
    cards = c.get("/api/scenarios").json()
    check([x["id"] for x in cards] == SCENARIO_IDS, "the scenario list has all three incidents", str(cards))
    check(next(x for x in cards if x["id"] == TWO)["role"] == "database", "the second card is played as the database engineer")
    r = c.post(f"/api/scenarios/{TWO}/start")
    check(r.status_code == 201 and r.json()["mode"] == "simulation" and r.json()["scenario"]["id"] == TWO, "scenario started", r.text)
    pid = r.json()["id"]
    events = lambda: c.get(f"/api/projects/{pid}/events").json()  # noqa: E731
    of = lambda t: [e for e in events() if e["type"] == t]  # noqa: E731
    task = wait(lambda: next(iter(of("human_task_assigned")), None), 120, "your task")
    tid = task["task"]
    check(task["agent"] == "database" and len(task["tests"]) == 5, f"your task {tid} was handed over to the database desk: {task['title']}")
    check(not of("architecture_ready") and not of("spec_ready"), "no design or planning step ran")
    report = wait(lambda: next((e for e in of("channel_message") if e["from"] == "qa"), None), 30, "Ananya's report")
    check("Rahul Deshmukh (appointment 7) and Meera Joshi (appointment 19)" in report["text"], "Ananya reported the real rows in #incident-duplicates")
    doc = c.get(f"/api/projects/{pid}/tasks/{tid}/doc").text
    check("two patients were booked with the same doctor" in doc and "database/**" in doc and "tests/regression/**" in doc and "tests/test_db" not in doc, "the task document carries the brief and the files you may edit: database/ and tests/regression/ only")

    ide = f"/api/projects/{pid}/ide/database"
    test_run = lambda: (n := len(of("human_test_result")), c.post(f"{ide}/tests"), wait(lambda: len(of("human_test_result")) > n and of("human_test_result")[n], 120, "the test result"))[2]  # noqa: E731
    print("-- the problem")
    red = test_run()
    check(red["ok"] is False and red["failed"] == 5, "run tests: the five acceptance tests are red", red["summary"])
    check(c.get(f"{ide}/file", params={"path": "fixtures/prod_snapshot.sql"}).status_code == 200 and c.put(f"{ide}/file", json={"path": "fixtures/prod_snapshot.sql", "content": "-- x\n"}).status_code == 403, "the production snapshot is readable and read-only")
    check(c.put(f"{ide}/file", json={"path": "backend/api/appointments.py", "content": "# x\n"}).status_code == 403, "backend/ is Rohan's: read-only for you")
    c.get(f"{ide}/file", params={"path": "database/migrations/0006_index_appointments_by_doctor_and_slot.sql"})
    asked = c.post(f"/api/projects/{pid}/channel", json={"text": "Rohan, does the booking route check for a taken slot?", "to": "backend"})
    check(asked.status_code == 200 and asked.json()["to"] == ["backend"], "asked Rohan in the channel")
    wait(lambda: any(e["from"] == "backend" and e.get("reply_to") for e in of("channel_message")), 30, "Rohan's reply")
    check(True, "Rohan replied")
    found = c.get(f"{ide}/search", params={"q": "UNIQUE"}).json()
    check(found["matches"] >= 2 and any(f["path"].startswith("database/migrations") for f in found["results"]), "a project-wide search finds UNIQUE in the migrations", str(found["files"]))
    posted = c.post(f"/api/projects/{pid}/channel", json={"text": "Update: nothing in the database stops a second Booked row for a slot, and three slots already hold duplicates. Writing migration 0008."})
    check(posted.status_code == 200, "posted an update that names the cause")
    regression = ref_regression()
    check(c.put(f"{ide}/file", json={"path": REGRESSION_TWO, "content": regression}).status_code == 200, "saved a regression test in tests/regression/")
    red_regression = test_run()
    check(red_regression["ok"] is False and any(REGRESSION_TWO in t["id"] and t["outcome"] == "failed" for t in red_regression["tests"]), "the regression test (books a slot twice) is red before the fix")

    print("-- migration 0008, saved the way the editor saves")
    check(c.put(f"{ide}/file", json={"path": MIGRATION_TWO, "content": ref_migration()}).status_code == 200, f"saved {MIGRATION_TWO}")
    green = test_run()
    check(green["ok"] is True and green["failed"] == 0, "run tests: green after the migration", green["summary"])
    c.post(f"/api/projects/{pid}/channel", json={"text": "Fix is ready: migration 0008 cancels the later duplicates and adds the partial unique index. Submitting."})
    answer: dict = {}
    for attempt in range(1, 5):
        answer = c.post(f"/api/projects/{pid}/tasks/{tid}/submit").json()
        print(f"  submit {attempt}: {answer['stage']}")
        if answer["ok"]:
            break
    check(answer["ok"] is True and answer["stage"] == "accepted", "submit accepted")
    state = wait(lambda: (s := c.get(f"/api/projects/{pid}").json())["state"] in ("done", "failed") and s, 180, "the session to finish")
    check(state["state"] == "done" and state["finished"]["ok"] is True, f"the build finished ok (state {state['state']})", str(state.get("problems")))

    print("-- the session log")
    info = c.get(f"/api/projects/{pid}/session").json()
    kinds = [e["kind"] for e in info["events"]]
    check(all(k in kinds for k in ("file_opened", "file_saved", "test_run", "test_result", "message_posted", "hint_given", "submit", "submit_result", "session_finished")), "every kind of step is in the log", str(sorted(set(kinds))))
    check(info["summary"]["hints"] == 1 and info["summary"]["saves"] == 2 and info["summary"]["searches"] == 1, "one hint (the question to Rohan), two saves and one search were counted", str(info["summary"]))
    check(info["guide"]["current"] is None and info["guide"]["done"] == 8, "Priya's guide is complete", str(info["guide"]["done"]))
    check(any(m.get("ref") == "react-accepted-lead" for m in info["messages"]), "Aarav thanked you for the fix")

    print("-- the debrief")
    ended = wait(lambda: next(iter(of("debrief_ended")), None), 240, "the debrief to end")
    check(ended["ok"] is True and not of("debrief_failed"), "the team met and the debrief ended")
    judges = [m for m in of("channel_message") if m.get("criterion")]
    check([(m["from"], m["criterion"]) for m in judges] == [("architect", "communication"), ("backend", "diagnosis"), ("reviewer", "fix_quality"), ("qa", "testing"), ("architect", "ownership")],
          "each judge posted their criterion in #incident-duplicates (Rohan judges the diagnosis)", str([(m["from"], m["criterion"]) for m in judges]))
    rep = c.get(f"/api/projects/{pid}/report").json()
    check(rep["scenario"] == TWO and rep["total"] == 100 and [x["score"] for x in rep["criteria"]] == [4, 4, 4, 4, 4], "the report scores the run 100/100", f"{rep['total']} {[x['score'] for x in rep['criteria']]}")
    fair = rep["fairness"]
    check(fair["points"] == fair["quoted"] == fair["matched"] == 20 and fair["dropped"] == [], "fairness: 20 points quoted, 20 quotes matched, none dropped", str(fair))
    check(fair["tests_rerun"]["ok"] is True, "the suite was re-run on the merged project", str(fair["tests_rerun"]))
    checks = [e for e in rep["events"].values() if e["kind"] == "debrief_check"]
    check(len(checks) >= 5 and any(e["text"].startswith("Debrief upgrade of the production snapshot: 30 of 30") for e in checks) and any(e["text"].startswith("Debrief check of the index: unique") for e in checks),
          "the debrief tried the migration on the production snapshot and the results are entries a point quotes", str([e["text"] for e in checks]))
    check(all("#incident-duplicates" in r["source"] for r in rep["rows"] if r["source"].startswith("#")), "every channel source names #incident-duplicates")
    history = json.loads((tmp / "ws" / ".q-attempts" / f"{TWO}.json").read_text(encoding="utf-8"))
    check([(a["attempt"], a["total"]) for a in history] == [(1, 100)], "the attempt history of this scenario has attempt 1", str(history))
    check(not (tmp / "ws" / ".q-attempts" / f"{SCENARIO}.json").exists(), "the other scenario has no history from this run")

    print("-- autoplay (a scripted strong run at 2x)")
    r = c.post(f"/api/scenarios/{TWO}/autoplay", json={"variant": "strong", "speed": 2})
    check(r.status_code == 201 and r.json()["scenario"]["kind"] == "demo" and r.json()["scenario"]["attempt"] == 1, "autoplay started as demo attempt 1", r.text[:200])
    apid = r.json()["id"]
    aevents = lambda: c.get(f"/api/projects/{apid}/events").json()  # noqa: E731
    ended_run = wait(lambda: next((e for e in aevents() if e["type"] == "autoplay_ended"), None), 400, "the autoplay run to end")
    check(ended_run["reason"] == "done", "the scripted run reached the end of the debrief", str(ended_run))
    demo = c.get(f"/api/projects/{apid}/report").json()
    check(demo["total"] == 100 and demo["kind"] == "demo" and demo["variant"] == "strong" and demo["scenario"] == TWO, "the demo scored 100 and is marked demo", f"{demo['total']} {demo['kind']}")
    history = json.loads((tmp / "ws" / ".q-attempts" / f"{TWO}.json").read_text(encoding="utf-8"))
    check([(a["attempt"], a["total"]) for a in history] == [(1, 100)], "the learner's attempt history did not take the demo", str(history))
    mine = json.loads((tmp / "ws" / ".q-attempts" / f"{TWO}-demo.json").read_text(encoding="utf-8"))
    check([(a["attempt"], a["total"], a["variant"]) for a in mine] == [(1, 100, "strong")], "the demo has a history of its own", str(mine))


def form_says_saved(c: httpx.Client, check: Check, tmp: Path) -> None:
    """The third scenario ("The form says it saved", the frontend engineer), through the same HTTP calls the browser makes."""
    cards = c.get("/api/scenarios").json()
    check([x["id"] for x in cards] == SCENARIO_IDS, "the scenario list has all three incidents", str(cards))
    check(next(x for x in cards if x["id"] == THREE)["role"] == "frontend", "the third card is played as the frontend engineer")
    r = c.post(f"/api/scenarios/{THREE}/start")
    check(r.status_code == 201 and r.json()["mode"] == "simulation" and r.json()["scenario"]["id"] == THREE, "scenario started", r.text)
    pid = r.json()["id"]
    events = lambda: c.get(f"/api/projects/{pid}/events").json()  # noqa: E731
    of = lambda t: [e for e in events() if e["type"] == t]  # noqa: E731
    task = wait(lambda: next(iter(of("human_task_assigned")), None), 120, "your task")
    tid = task["task"]
    check(task["agent"] == "frontend" and len(task["tests"]) == 6, f"your task {tid} was handed over to the frontend desk: {task['title']}")
    check(not of("architecture_ready") and not of("spec_ready"), "no design or planning step ran")
    report = wait(lambda: next((e for e in of("channel_message") if e["from"] == "qa"), None), 30, "Ananya's report")
    check("'Appointment added'" in report["text"] and '"Slot already booked"' in report["text"], "Ananya reported the steps and the real 409 in #incident-frontdesk")
    doc = c.get(f"/api/projects/{pid}/tasks/{tid}/doc").text
    check("form still closes with a green 'Appointment added'" in doc and "static/**" in doc and "tests/regression/**" in doc and "In this incident you also own `static/shell.js`" in doc,
          "the task document carries the brief and the files you may edit: static/ (the shell included) and tests/regression/")

    ide = f"/api/projects/{pid}/ide/frontend"
    test_run = lambda: (n := len(of("human_test_result")), c.post(f"{ide}/tests"), wait(lambda: len(of("human_test_result")) > n and of("human_test_result")[n], 120, "the test result"))[2]  # noqa: E731
    print("-- the problem")
    red = test_run()
    check(red["ok"] is False and red["failed"] == 6, "run tests: the six acceptance tests are red (the rest of the suite, backend included, is green)", red["summary"])
    check(c.put(f"{ide}/file", json={"path": "backend/main.py", "content": "# x\n"}).status_code == 403 and c.put(f"{ide}/file", json={"path": "database/connection.py", "content": "# x\n"}).status_code == 403,
          "backend/ and database/ are read-only: the API answers correctly and is not yours")
    check(c.get(f"{ide}/file", params={"path": "tests/api/test_double_booking_api.py"}).status_code == 200 and c.get(f"{ide}/file", params={"path": "backend/main.py"}).status_code == 200,
          "what the server answers can be read")
    current = c.get(f"{ide}/file", params={"path": SHELL}).json()["content"]
    asked = c.post(f"/api/projects/{pid}/channel", json={"text": "Rohan, what does the API answer when a slot is taken?", "to": "backend"})
    check(asked.status_code == 200 and asked.json()["to"] == ["backend"], "asked Rohan in the channel")
    wait(lambda: any(e["from"] == "backend" and e.get("reply_to") for e in of("channel_message")), 30, "Rohan's reply")
    check(True, "Rohan replied")
    found = c.get(f"{ide}/search", params={"q": "409"}).json()
    check(found["matches"] >= 2 and any(f["path"].startswith("tests/api") or f["path"].startswith("backend") for f in found["results"]), "a project-wide search finds 409 in the backend and its tests", str(found["files"]))
    posted = c.post(f"/api/projects/{pid}/channel", json={"text": CAUSE_THREE})
    check(posted.status_code == 200, "posted an update that names the cause")
    check(c.put(f"{ide}/file", json={"path": REGRESSION_THREE, "content": regression_test(THREE)}).status_code == 200, "saved a regression test in tests/regression/")
    red_regression = test_run()
    check(red_regression["ok"] is False and any(REGRESSION_THREE in t["id"] and t["outcome"] == "failed" for t in red_regression["tests"]), "the regression test (a refused request is an error) is red before the fix")

    print("-- the fix in static/shell.js, saved the way the editor saves")
    fixed = reference_fix({SHELL: current}, THREE)[SHELL]
    check(c.put(f"{ide}/file", json={"path": SHELL, "content": fixed}).status_code == 200, f"saved {SHELL}")
    green = test_run()
    check(green["ok"] is True and green["failed"] == 0, "run tests: green after the fix", green["summary"])
    c.post(f"/api/projects/{pid}/channel", json={"text": "Fix is ready: call() now throws for any refused answer, so every form shows the server's message. Submitting."})
    answer: dict = {}
    for attempt in range(1, 5):
        answer = c.post(f"/api/projects/{pid}/tasks/{tid}/submit").json()
        print(f"  submit {attempt}: {answer['stage']}")
        if answer["ok"]:
            break
    check(answer["ok"] is True and answer["stage"] == "accepted", "submit accepted")
    state = wait(lambda: (s := c.get(f"/api/projects/{pid}").json())["state"] in ("done", "failed") and s, 180, "the session to finish")
    check(state["state"] == "done" and state["finished"]["ok"] is True, f"the build finished ok (state {state['state']})", str(state.get("problems")))

    print("-- the session log")
    info = c.get(f"/api/projects/{pid}/session").json()
    kinds = [e["kind"] for e in info["events"]]
    check(all(k in kinds for k in ("file_opened", "file_saved", "test_run", "test_result", "message_posted", "hint_given", "submit", "submit_result", "session_finished")), "every kind of step is in the log", str(sorted(set(kinds))))
    check(info["summary"]["hints"] == 1 and info["summary"]["saves"] == 2 and info["summary"]["searches"] == 1, "one hint (the question to Rohan), two saves and one search were counted", str(info["summary"]))
    check(info["guide"]["current"] is None and info["guide"]["done"] == 8, "Priya's guide is complete", str(info["guide"]["done"]))
    check(any(m.get("ref") == "react-accepted-lead" for m in info["messages"]), "Aarav thanked you for the fix")

    print("-- the debrief")
    ended = wait(lambda: next(iter(of("debrief_ended")), None), 240, "the debrief to end")
    check(ended["ok"] is True and not of("debrief_failed"), "the team met and the debrief ended")
    judges = [m for m in of("channel_message") if m.get("criterion")]
    check([(m["from"], m["criterion"]) for m in judges] == [("architect", "communication"), ("backend", "diagnosis"), ("reviewer", "fix_quality"), ("qa", "testing"), ("architect", "ownership")],
          "each judge posted their criterion in #incident-frontdesk (Rohan judges the diagnosis)", str([(m["from"], m["criterion"]) for m in judges]))
    rep = c.get(f"/api/projects/{pid}/report").json()
    check(rep["scenario"] == THREE and rep["total"] == 100 and [x["score"] for x in rep["criteria"]] == [4, 4, 4, 4, 4], "the report scores the run 100/100", f"{rep['total']} {[x['score'] for x in rep['criteria']]}")
    fair = rep["fairness"]
    check(fair["points"] == fair["quoted"] == fair["matched"] == 20 and fair["dropped"] == [], "fairness: 20 points quoted, 20 quotes matched, none dropped", str(fair))
    check(fair["tests_rerun"]["ok"] is True, "the suite was re-run on the merged project", str(fair["tests_rerun"]))
    checks = [e for e in rep["events"].values() if e["kind"] == "debrief_check"]
    check(len(checks) >= 5 and any(e["text"].startswith("Debrief check of the pages: all 8 refused requests") for e in checks) and any(e["text"].startswith("Debrief check of the messages: in all 8 cases") for e in checks),
          "the debrief ran the pages on the real answers of the API and the results are entries a point quotes", str([e["text"] for e in checks]))
    check(all("#incident-frontdesk" in r["source"] for r in rep["rows"] if r["source"].startswith("#")), "every channel source names #incident-frontdesk")
    history = json.loads((tmp / "ws" / ".q-attempts" / f"{THREE}.json").read_text(encoding="utf-8"))
    check([(a["attempt"], a["total"]) for a in history] == [(1, 100)], "the attempt history of this scenario has attempt 1", str(history))
    check(not (tmp / "ws" / ".q-attempts" / f"{SCENARIO}.json").exists() and not (tmp / "ws" / ".q-attempts" / f"{TWO}.json").exists(), "the other scenarios have no history from this run")

    print("-- autoplay (a scripted strong run at 2x)")
    r = c.post(f"/api/scenarios/{THREE}/autoplay", json={"variant": "strong", "speed": 2})
    check(r.status_code == 201 and r.json()["scenario"]["kind"] == "demo" and r.json()["scenario"]["attempt"] == 1, "autoplay started as demo attempt 1", r.text[:200])
    apid = r.json()["id"]
    aevents = lambda: c.get(f"/api/projects/{apid}/events").json()  # noqa: E731
    ended_run = wait(lambda: next((e for e in aevents() if e["type"] == "autoplay_ended"), None), 400, "the autoplay run to end")
    check(ended_run["reason"] == "done", "the scripted run reached the end of the debrief", str(ended_run))
    demo = c.get(f"/api/projects/{apid}/report").json()
    check(demo["total"] == 100 and demo["kind"] == "demo" and demo["variant"] == "strong" and demo["scenario"] == THREE, "the demo scored 100 and is marked demo", f"{demo['total']} {demo['kind']}")
    history = json.loads((tmp / "ws" / ".q-attempts" / f"{THREE}.json").read_text(encoding="utf-8"))
    check([(a["attempt"], a["total"]) for a in history] == [(1, 100)], "the learner's attempt history did not take the demo", str(history))
    mine = json.loads((tmp / "ws" / ".q-attempts" / f"{THREE}-demo.json").read_text(encoding="utf-8"))
    check([(a["attempt"], a["total"], a["variant"]) for a in mine] == [(1, 100, "strong")], "the demo has a history of its own", str(mine))


def run(port: int, serve: bool, scenario: str) -> int:
    assert port not in FORBIDDEN_PORTS, "this check never uses ports 8000 or 5173"
    tmp = Path(tempfile.mkdtemp(prefix="q-scenario-e2e-"))
    settings = make_settings(tmp)
    if serve:
        settings.debrief_pace = 3.5  # a person watches the meeting: the judges speak a few seconds apart (the scripted check does not wait)
    llm = ScenarioLLM("That was my migration 0007: slot_time is slot_at now. I did not touch backend/.")
    mgr = SessionManager(settings, ModelRegistry.load(env={}), llm_factory=lambda registry, observer: llm)
    server = uvicorn.Server(uvicorn.Config(create_app(settings, mgr), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    wait(lambda: server.started, 20, "the server")
    base = f"http://127.0.0.1:{port}"
    c = httpx.Client(base_url=base, timeout=60)
    check = Check()
    print(f"stubbed backend on {base} (workspace {tmp})")
    if serve:
        print("serving until you press Ctrl+C: choose Simulation (Demo mode off) and start the scenario in the UI; the teammates answer from a stub")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            mgr.shutdown()
            server.should_exit = True
            th.join(15)
            shutil.rmtree(tmp, ignore_errors=True)
        return 0
    try:
        {SCENARIO: bookings_down, TWO: double_bookings, THREE: form_says_saved}[scenario](c, check, tmp)
    except (TimeoutError, KeyboardInterrupt) as e:
        print(f"  [FAIL] {e}")
        check.failed.append(str(e))
    finally:
        mgr.shutdown()
        server.should_exit = True
        th.join(15)
        shutil.rmtree(tmp, ignore_errors=True)
    print("RESULT:", "all steps passed" if not check.failed else f"{len(check.failed)} step(s) failed: {check.failed}")
    return 1 if check.failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8200)
    ap.add_argument("--scenario", default=SCENARIO, choices=SCENARIO_IDS, help="which incident to run end to end (default: Bookings are down)")
    ap.add_argument("--serve", action="store_true", help="only serve the stubbed backend for the UI")
    args = ap.parse_args()
    sys.exit(run(args.port, args.serve, args.scenario))
