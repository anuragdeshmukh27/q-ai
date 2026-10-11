"""Replay recordings with MAIN's code, headless and offline, and check they work there.

    backend\.venv\Scripts\python.exe scripts\verify_on_main.py <main-checkout> <recording-folder> [<recording-folder> ...]

<main-checkout> is a read-only checkout of main (a temporary `git worktree add --detach`), never the live q folder.
Each recording folder is COPIED into <main-checkout>\recordings\ (the checkout is thrown away afterwards). For each one the checkout's own
tests\offline_server.py is started (network blocked, Ollama blocked, a random free port, never 8000 or 5173), the recording is replayed over
HTTP and WebSocket at 1000x, and these are checked: it reaches project_done with ok, the events match the recording type for type, the
restored app answers /health and /, nothing tried to leave the machine, and the restored project's own tests pass.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from websockets.sync.client import connect

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def free_port() -> int:
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port not in (8000, 5173, 11434):
            return port


def verify(main: Path, rec: Path, python: str) -> list[str]:
    problems: list[str] = []
    name = rec.name
    tmp = Path(tempfile.mkdtemp(prefix="verify-"))
    recs = tmp / "recordings"
    shutil.copytree(rec, recs / name)
    recorded = [json.loads(l) for l in (rec / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    port = free_port()
    log = tmp / "net.log"
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY") and k != "OLLAMA_HOST"}
    env.update(Q_MODE="replay", Q_RECORDINGS_DIR=str(recs), Q_WORKSPACE_DIR=str(tmp / "ws"), Q_DB=str(tmp / "q.db"), Q_NET_LOG=str(log),
               OLLAMA_HOST="http://127.0.0.1:1", PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([python, str(main / "backend" / "tests" / "offline_server.py"), str(port)], cwd=main / "backend", env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            if proc.poll() is not None:
                return [f"server exited: {proc.stdout.read()[-800:]}"]
            try:
                if httpx.get(base + "/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        http = httpx.Client(base_url=base, timeout=15)
        listed = [r["name"] for r in http.get("/api/recordings").json()] if http.get("/api/recordings").status_code == 200 else []
        if name not in listed:
            problems.append(f"the recording is not listed by main's /api/recordings: {listed}")
        r = http.post("/api/projects", json={"goal": "demo", "speed": 1000, "recording": name})
        if r.status_code != 201:
            return problems + [f"could not start the replay: {r.status_code} {r.text[:200]}"]
        pid = r.json()["id"]
        got: list[dict] = []
        with connect(f"ws://127.0.0.1:{port}/ws/{pid}", open_timeout=10) as ws:
            while True:
                e = json.loads(ws.recv(timeout=90))
                got.append(e)
                if e["type"] == "approval_needed" and e.get("replayed"):
                    for _ in range(100):
                        if http.post(f"/api/projects/{pid}/approvals/{e['id']}", json={"approve": True}).status_code != 404:
                            break
                        time.sleep(0.05)
                if e["type"] == "project_done":
                    break
        if not got[-1].get("ok"):
            problems.append("project_done is not ok")
        kinds = lambda evs: [e["type"] for e in evs if e["type"] != "metrics"]  # noqa: E731
        if kinds(got) != kinds(recorded):
            problems.append(f"event types differ from the recording ({len(kinds(got))} vs {len(kinds(recorded))})")
        unknown = sorted({e["type"] for e in recorded} - {e["type"] for e in got})
        if unknown:
            problems.append(f"event types missing in the replay: {unknown}")
        status = http.get(f"/api/projects/{pid}").json()
        if status["state"] != "done":
            problems.append(f"state {status['state']}")
        app = status.get("app") or {}
        if not app.get("running"):
            problems.append("the restored app is not running")
        else:
            for path in ("/health", "/"):
                code = httpx.get(app["url"] + path, timeout=10).status_code
                if code != 200:
                    problems.append(f"restored app {path} -> {code}")
        # the restored project's own tests
        ws_root = tmp / "ws"
        projects = [p for p in ws_root.iterdir() if p.is_dir() and (p / "tests").is_dir()] if ws_root.is_dir() else []
        if not projects:
            problems.append("no restored project folder found")
        else:
            t = subprocess.run([python, "-m", "pytest", "-q", "--tb=line"], cwd=projects[0], capture_output=True, text=True, timeout=300)
            last = (t.stdout.strip().splitlines() or [""])[-1]
            print(f"   restored app tests: {last}")
            if t.returncode != 0:
                problems.append("the restored app's tests fail: " + last)
        if log.exists() and log.read_text().strip():
            problems.append("network attempts: " + log.read_text().strip()[:200])
        print(f"   events replayed: {len(got)} (recording has {len(recorded)})")
    finally:
        if proc.poll() is None:
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
                proc.wait(15)
            except Exception:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        time.sleep(1)
        shutil.rmtree(tmp, ignore_errors=True)
    return problems


def main() -> int:
    main_dir = Path(sys.argv[1]).resolve()
    recs = [Path(a).resolve() for a in sys.argv[2:]]
    bad = 0
    for rec in recs:
        print(f"== {rec.name} on {main_dir}")
        problems = verify(main_dir, rec, sys.executable)
        print("   OK" if not problems else "   FAILED: " + "; ".join(problems))
        bad += bool(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
