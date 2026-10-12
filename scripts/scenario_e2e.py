"""End-to-end check of the scenario "Production incident: Bookings are down", driven through the HTTP API with the LLM stubbed (no Ollama, no GPU).

    backend\\.venv\\Scripts\\python.exe scripts\\scenario_e2e.py            run the check on port 8200 and stop the server (exit 0 = all steps passed)
    backend\\.venv\\Scripts\\python.exe scripts\\scenario_e2e.py --serve    only start the stubbed backend on 8200 for the UI, no scripted flow (start the frontend with Q_BACKEND=http://127.0.0.1:8200)

The flow: start the scenario, wait for the task and Ananya's report, run the tests (red), open the files, ask Karan something in the channel, apply the reference fix through
the IDE endpoints (the same calls the editor makes), run the tests (green), submit, and check the fix is accepted, the session log holds every step and the guide is complete.
Then the debrief: the team meets, five judges post their criterion, and the report (scores, rows that quote the session log, fairness checks, files, attempt history) is checked.
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
from scenario_helpers import FIX_FILES, REGRESSION_PATH, REGRESSION_TEST, ScenarioLLM, apply_reference_fix  # noqa: E402

SCENARIO = "opd-bookings-down"
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


def run(port: int, serve: bool) -> int:
    assert port not in FORBIDDEN_PORTS, "this check never uses ports 8000 or 5173"
    tmp = Path(tempfile.mkdtemp(prefix="q-scenario-e2e-"))
    settings = make_settings(tmp)
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
        cards = c.get("/api/scenarios").json()
        check([x["id"] for x in cards] == [SCENARIO], "the scenario list has the incident", str(cards))
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
        check(info["summary"]["hints"] == 1 and info["summary"]["saves"] == 3, "one hint and three saves were counted", str(info["summary"]))
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
        check(len(rep["rows"]) == 20 and all(r["verified"] and r["event"] in log_ids for r in rep["rows"]), "every point quotes an entry that is in the session log")
        fair = rep["fairness"]
        check(fair["points"] == fair["quoted"] == fair["matched"] == 20 and fair["dropped"] == [] and fair["rubric"] == "v1", "fairness: 20 points quoted, 20 quotes matched, none dropped, rubric v1", str(fair))
        check(fair["tests_rerun"]["ok"] is True and fair["tests_rerun"]["passed"] == fair["tests_rerun"]["total"], "the suite was re-run on the merged project", str(fair["tests_rerun"]))
        check(fair["wording"]["source"] == "template", "the stubbed model wrote nothing, so the template wording was used", str(fair["wording"]))
        md = c.get(f"/api/projects/{pid}/report", params={"format": "md"})
        check(md.status_code == 200 and md.text.startswith("# Debrief: Production incident") and "**Attempt 1: 100/100**" in md.text, "the markdown report is served")
        folder = next((tmp / "ws").glob("opd-bookings-down*")) / ".q" / "reports"
        check((folder / "attempt-1.md").read_text(encoding="utf-8") == md.text and json.loads((folder / "attempt-1.json").read_text(encoding="utf-8")) == rep, ".q/reports/attempt-1.md and .json are in the project and match the endpoint")
        history = json.loads((tmp / "ws" / ".q-attempts" / f"{SCENARIO}.json").read_text(encoding="utf-8"))
        check([(a["attempt"], a["total"]) for a in history] == [(1, 100)], "the attempt history has attempt 1 with its score", str(history))
        check(info["events"][-1]["kind"] == "session_finished", "the debrief added nothing to the session log")
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
    ap.add_argument("--serve", action="store_true", help="only serve the stubbed backend for the UI")
    args = ap.parse_args()
    sys.exit(run(args.port, args.serve))
