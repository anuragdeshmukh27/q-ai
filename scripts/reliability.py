"""Run the calculator build N times (local models only) and report the pass rate.

    backend\.venv\Scripts\python.exe scripts\reliability.py [-n 5] [--goal "..."]
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ap = argparse.ArgumentParser()
ap.add_argument("-n", type=int, default=5)
ap.add_argument("--consultant", action="store_true", help="enable the cloud senior-consultant ladder")
ap.add_argument("--goal", default="Build a calculator with history")
args = ap.parse_args()

results = []
for i in range(1, args.n + 1):
    t0 = time.time()
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py"), args.goal, *(["--consultant"] if args.consultant else [])], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = p.stdout
    ok = "BUILD OK" in out
    tail = [l.strip() for l in out.splitlines() if l.strip().startswith(("problem:", "!! escalation"))]
    escal = len(re.findall(r"!! escalation", out))
    consulted = len(re.findall(r"SENIOR CONSULTANT", out))
    results.append(ok)
    (ROOT / "workspace" / f"reliability-run{i}.log").write_text(out, encoding="utf-8")
    print(f"run {i}: {'PASS' if ok else 'FAIL'} in {time.time() - t0:.0f}s, {escal} escalation(s), {consulted} consultant call(s)" + ("" if ok else f" | {tail[-1][:160] if tail else '?'}"), flush=True)
print(f"\npass rate: {sum(results)}/{len(results)}")
