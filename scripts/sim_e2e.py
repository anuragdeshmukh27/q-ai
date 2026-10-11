"""End-to-end check of Simulation mode (human tasks + the in-app IDE), driven through the HTTP API, with the scripted fake team (no Ollama, no GPU).

    backend\.venv\Scripts\python.exe scripts\sim_e2e.py            run the check on port 8200 and stop the server (exit 0 = all steps passed)
    backend\.venv\Scripts\python.exe scripts\sim_e2e.py --serve    only start the fake-team backend on 8200 for the UI, no scripted flow (start the frontend with Q_BACKEND=http://127.0.0.1:8200)

The flow: start a simulation build where you play the database engineer, wait for your task, write a WRONG file in the IDE, run the tests (red), submit (rejected), write the
RIGHT file, run the tests (green) and submit until it is accepted, then wait for the build to finish ok. Ports 8000 and 5173 are never used.
"""
import argparse
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

from api_helpers import make_manager  # noqa: E402
from app.main import create_app  # noqa: E402
from test_orchestrator import DB_ADD, DB_LIST, DB_TESTS  # noqa: E402

GOAL = "Build a calculator with history"
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


def fill(stub: str, add: str, lst: str) -> str:
    """The generated database stub with its two `raise NotImplementedError` bodies replaced."""
    parts = stub.split("    raise NotImplementedError")
    assert len(parts) == 3, "the stub has changed shape"
    indent = lambda code: "\n".join("    " + line for line in code.splitlines())  # noqa: E731
    return parts[0] + indent(add) + parts[1] + indent(lst) + parts[2]


def run(port: int, serve: bool) -> int:
    assert port not in FORBIDDEN_PORTS, "this check never uses ports 8000 or 5173"
    tmp = Path(tempfile.mkdtemp(prefix="q-sim-e2e-"))
    settings, mgr = make_manager(tmp)
    server = uvicorn.Server(uvicorn.Config(create_app(settings, mgr), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    wait(lambda: server.started, 20, "the server")
    base = f"http://127.0.0.1:{port}"
    c = httpx.Client(base_url=base, timeout=60)
    check = Check()
    print(f"fake-team backend on {base} (workspace {tmp})")
    if serve:
        print("serving until you press Ctrl+C: create a Simulation build in the UI (Demo mode off)")
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
        r = c.post("/api/projects", json={"goal": GOAL, "mode": "simulation", "human_roles": ["database"]})
        check(r.status_code == 201 and r.json()["mode"] == "simulation", "simulation build started", r.text)
        pid = r.json()["id"]
        events = lambda: c.get(f"/api/projects/{pid}/events").json()  # noqa: E731
        of = lambda t: [e for e in events() if e["type"] == t]  # noqa: E731
        task = wait(lambda: next(iter(of("human_task_assigned")), None), 120, "your task")
        tid = task["task"]
        check(task["agent"] == "database", f"waiting for your task {tid}: {task['title']}")
        doc = c.get(f"/api/projects/{pid}/tasks/{tid}/doc")
        check(doc.status_code == 200 and f"# {tid}" in doc.text, "task document served")
        ide = f"/api/projects/{pid}/ide/database"
        tree = c.get(f"{ide}/tree").json()
        files = {f["path"]: f for f in tree["files"]}
        check(tree["ready"] and tree["task"] == tid and files["database/calculations.py"]["writable"] and not files["database/connection.py"]["writable"], "IDE tree: your files writable, the rest read-only")
        denied = c.put(f"{ide}/file", json={"path": "backend/main.py", "content": "x = 1\n"})
        check(denied.status_code == 403, "a write outside your role is refused", str(denied.status_code))
        stub = c.get(f"{ide}/file", params={"path": "database/calculations.py"}).json()["content"]
        save = lambda path, text: c.put(f"{ide}/file", json={"path": path, "content": text})  # noqa: E731
        test_run = lambda: (n := len(of("human_test_result")), c.post(f"{ide}/tests"), wait(lambda: len(of("human_test_result")) > n and of("human_test_result")[n], 120, "the test result"))[2]  # noqa: E731

        print("-- a wrong solution")
        check(save("database/calculations.py", fill(stub, "return {'id': 0}", "return []")).status_code == 200, "wrong file saved")
        check(save("tests/test_db_calculations.py", DB_TESTS).status_code == 200, "tests saved")
        red = test_run()
        check(red["ok"] is False and red["failed"] >= 1, "run tests: red", red["summary"])
        check(any("test_add_and_list" in e["line"] for e in of("human_test_output")), "the test output was streamed")
        rejected = c.post(f"/api/projects/{pid}/tasks/{tid}/submit").json()
        check(rejected["ok"] is False and rejected["stage"] == "tests", f"submit rejected at stage '{rejected['stage']}'", rejected["summary"])

        print("-- a file outside your role (the IDE refuses it above; a change made outside the IDE is caught at submit)")
        wt = Path(task["worktree"])
        sneaky = wt / "static" / "sneaky.js"
        sneaky.write_text("// not mine\n", encoding="utf-8")
        scoped = c.post(f"/api/projects/{pid}/tasks/{tid}/submit").json()
        check(scoped["stage"] == "scope" and "static/sneaky.js" in scoped.get("files", []), "submit rejected at stage 'scope', listing the file", str(scoped))
        sneaky.unlink()

        print("-- the right solution")
        check(save("database/calculations.py", fill(stub, DB_ADD, DB_LIST)).status_code == 200, "right file saved")
        green = test_run()
        check(green["ok"] is True and green["failed"] == 0 and green["passed"] >= 1, "run tests: green", green["summary"])
        answer: dict = {}
        for attempt in range(1, 5):  # the Reviewer may send green work back (at most twice)
            answer = c.post(f"/api/projects/{pid}/tasks/{tid}/submit").json()
            print(f"  submit {attempt}: {answer['stage']}{' (' + str(len(answer['items'])) + ' review items)' if answer['items'] else ''}")
            if answer["ok"]:
                break
        check(answer["ok"] is True and answer["stage"] == "accepted", "submit accepted")
        state = wait(lambda: (s := c.get(f"/api/projects/{pid}").json())["state"] in ("done", "failed") and s, 180, "the build to finish")
        check(state["state"] == "done", f"the build finished ok (state {state['state']})", str(state.get("problems")))
        done = of("project_done")
        check(bool(done) and done[-1]["ok"] is True, "project_done ok")
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8200)
    ap.add_argument("--serve", action="store_true", help="only serve the fake-team backend (Ctrl+C stops it), no scripted flow")
    a = ap.parse_args()
    sys.exit(run(a.port, a.serve))
