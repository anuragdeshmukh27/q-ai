"""Record a full build as a replay: starts the real Q server, creates the project over HTTP, auto-approves, saves recordings/<name>/.

    backend\\.venv\\Scripts\\python.exe scripts\\record.py "Build a calculator with history" --name calculator-fault --inject-fault

Uses the live local models (Ollama must be running). Replay it later with no model and no network: POST /api/projects {"demo": true}.
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("goal", nargs="?", default="")
    ap.add_argument("--import", dest="import_from", default="", help="Finish my project: record the finishing of this half-built folder or GitHub URL (the human's choice is simulated: every gap)")
    ap.add_argument("--name", required=True, help="recording name (lowercase, digits, dashes)")
    ap.add_argument("--mode", default="supervised", choices=["assisted", "supervised", "autonomous"])
    ap.add_argument("--inject-fault", action="store_true", help="deliberately break the app so QA finds and the owner fixes a bug")
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--title", default="", help="card title in the Demo picker")
    ap.add_argument("--app", default="", help="app type shown on the card, e.g. 'Todo app'")
    ap.add_argument("--feature", default="", help="what the run shows, e.g. 'QA bug fix', 'Approvals', 'Ask employee'")
    ap.add_argument("--ask", action="append", default=[], metavar="AGENT=TEXT", help="Ask-employee task sent after the build, recorded too (repeatable)")
    ap.add_argument("--timeout", type=int, default=1500, help="give up after this many seconds")
    ap.add_argument("--override", action="append", default=[], metavar="EMPLOYEE=MODEL", help="a model for one employee from the first call on, e.g. architect=qwen25-coder-14b (repeatable)")
    args = ap.parse_args()

    port = free_port()
    env = {**os.environ, "Q_MODE": "record", "PYTHONIOENCODING": "utf-8"}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory", "--port", str(port), "--log-level", "warning"],
                              cwd=ROOT / "backend", env=env, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    http = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15)
    try:
        for _ in range(60):
            try:
                if http.get("/api/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        r = http.post("/api/projects", json={"goal": args.goal, "mode": args.mode, "record_as": args.name, "inject_fault": args.inject_fault, "parallel": args.parallel, "overrides": dict(o.split("=", 1) for o in args.override) or None, **({"import_from": args.import_from, "auto_fix": False} if args.import_from else {}),
                                              "record_info": {k: v for k, v in (("title", args.title), ("app", args.app), ("feature", args.feature)) if v},
                                              "then_ask": [{"agent": a.split("=", 1)[0], "text": a.split("=", 1)[1]} for a in args.ask]})
        if r.status_code != 201:
            print("could not start:", r.json().get("detail", r.text))
            return 1
        pid = r.json()["id"]
        print(f"recording '{args.name}' (project {pid}, {args.mode} mode{', fault injected' if args.inject_fault else ''})")
        seen, started, last, picked = set(), time.time(), "", False
        while time.time() - started < args.timeout:
            s = http.get(f"/api/projects/{pid}").json()
            for a in s["pending_approvals"]:
                if a["id"] not in seen:
                    seen.add(a["id"])
                    http.post(f"/api/projects/{pid}/approvals/{a['id']}", json={"approve": True})
                    print(f"   approved: {a['agent']} - {a['summary']}")
            line = f"{s['state']} {s['progress']['percent']}% " + ",".join(f"{x['id']}:{x['state']}" for x in s["agents"] if x["state"] not in ("idle",))
            if line != last:
                print(f"   [{time.time() - started:4.0f}s] {line}")
                last = line
            if args.import_from and not picked:  # the human opens the Gap report and keeps every gap ticked
                ev = http.get(f"/api/projects/{pid}/events").json()
                report = next((e for e in ev if e["type"] == "gap_report"), None)
                if report and any(e["type"] == "selection_needed" for e in ev):
                    time.sleep(1)
                    http.post(f"/api/projects/{pid}/finish", json={"gaps": [g["id"] for g in report["gaps"]]})
                    picked = True
                    print(f"   picked all {len(report['gaps'])} gaps")
            if s["state"] in ("done", "failed"):
                break
            time.sleep(0.4 if args.mode == "assisted" else 2)
        else:
            print("timed out")
            return 1
        time.sleep(1)  # the recorder finalizes right after the build
        rec = next((m for m in http.get("/api/recordings").json() if m["name"] == args.name), None)
        if not rec:
            print("the recording was not saved (see the server output above)")
            return 1
        print(f"\n== {'BUILD OK' if rec['ok'] else 'BUILD FAILED'}: {rec['events']} events, {rec['llm_calls']} model responses, "
              f"{rec['seconds']}s, snapshot={rec['snapshot']}\n== saved to recordings/{args.name}/")
        for p in rec["problems"]:
            print("   problem:", p)
        return 0 if rec["ok"] else 1
    finally:
        try:
            server.send_signal(signal.CTRL_BREAK_EVENT)
            server.wait(20)
        except Exception:
            subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
