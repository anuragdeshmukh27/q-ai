"""Run Task C on the sample fixtures several times and keep an honest record (pass, seconds, gaps fixed, hidden acceptance result).

    backend\.venv\Scripts\python.exe scripts\task_c_runs.py notes-flask library-readme --runs 3 [--finish-model qwen25-coder-14b] [--label 14b]

Each run is one `scripts/finish.py --accept` process, killed (with its children) after --cap minutes and recorded as a timeout. Pass = the build reports success AND the hidden
acceptance tests of the fixture pass. Appends to backend/benchmarks/task_c_runs.json; one run at a time (one GPU job).
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = ROOT / "backend" / "benchmarks" / "task_c_runs.json"
LOGS = ROOT / "workspace" / "_taskc_logs"


def one(fixture: str, finish_model: str | None, cap_s: int, log: Path) -> dict:
    cmd = [sys.executable, "-u", str(ROOT / "scripts" / "finish.py"), str(ROOT / "samples" / "half-built" / fixture), "--accept", "--no-app"]
    if finish_model:
        cmd += ["--finish-model", finish_model]
    t0 = time.time()
    timed_out = False
    with log.open("w", encoding="utf-8") as f:
        p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=ROOT)
        try:
            p.wait(cap_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            p.wait(30)
    secs = round(time.time() - t0)
    text = log.read_text(encoding="utf-8", errors="replace")
    build = re.search(r"== FINISH (OK|FAILED) in (\d+)s \| tests: (.*)", text)
    gaps = re.findall(r"== gaps fixed: (\d+), still open: (\d+)", text)
    hidden = re.search(r"== hidden acceptance: (.*)", text)
    ok_hidden = bool(hidden and "passed" in hidden.group(1) and "failed" not in hidden.group(1) and "error" not in hidden.group(1))
    return {"fixture": fixture, "finish_model": finish_model or "default (router/registry)", "passed": bool(build and build.group(1) == "OK" and ok_hidden and not timed_out),
            "timeout": timed_out, "seconds": secs, "build": build.group(1) if build else "no result", "tests": build.group(3).strip() if build else "",
            "gaps_fixed": int(gaps[-1][0]) if gaps else 0, "gaps_open": int(gaps[-1][1]) if gaps else 0,
            "hidden_acceptance": hidden.group(1).strip() if hidden else "not run", "log": str(log.relative_to(ROOT))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixtures", nargs="+")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--finish-model")
    ap.add_argument("--cap", type=int, default=30, help="minutes after which a run is killed and recorded as a timeout")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {"runs": []}
    for fx in args.fixtures:
        for i in range(1, args.runs + 1):
            log = LOGS / f"{fx}-{args.label or 'run'}-{int(time.time())}.log"
            r = one(fx, args.finish_model, args.cap * 60, log) | {"label": args.label, "run": i, "ts": time.strftime("%Y-%m-%d %H:%M")}
            data["runs"].append(r)
            OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
            print(f"{fx:15} run {i}: {'PASS' if r['passed'] else 'FAIL'} {r['seconds']}s fixed {r['gaps_fixed']}/{r['gaps_fixed'] + r['gaps_open']} hidden: {r['hidden_acceptance']}" + (" TIMEOUT" if r["timeout"] else ""), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
