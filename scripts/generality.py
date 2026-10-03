"""Generality check: build several different apps (local models only, one fresh project each) and report pass/fail per goal.

    backend\.venv\Scripts\python.exe scripts\generality.py [--only 1,3] [--no-polish]

Logs go to workspace/generality-<n>.log; the summary is also written to workspace/generality-summary.txt.
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GOALS = [
    "Build a todo app with priorities",
    "Build an expense tracker with categories and totals",
    "Build a notes app with search",
    "Build a habit tracker",
    "Build a quiz app",
    "Build a bookmark manager with tags",
    "Build a contact book",
    "Build an inventory list",
]

ap = argparse.ArgumentParser()
ap.add_argument("--only", help="comma-separated 1-based goal numbers")
ap.add_argument("--no-polish", action="store_true")
args = ap.parse_args()
picked = [int(x) for x in args.only.split(",")] if args.only else list(range(1, len(GOALS) + 1))

lines = []
for n in picked:
    goal = GOALS[n - 1]
    t0 = time.time()
    cmd = [sys.executable, str(ROOT / "scripts" / "build.py"), goal, *(["--no-polish"] if args.no_polish else [])]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = p.stdout
    ok = "BUILD OK" in out
    problems = [l.strip() for l in out.splitlines() if l.strip().startswith(("problem:", "!! escalation"))]
    polish = [p.strip(" :") for p in re.findall(r"== polish([^\n]*)", out)]
    slug = (re.findall(r"== project (\S+)", out) or ["?"])[0]
    (ROOT / "workspace" / f"generality-{n}.log").write_text(out + "\n--- stderr ---\n" + p.stderr[-2000:], encoding="utf-8")
    line = (f"{n}. {goal}: {'PASS' if ok else 'FAIL'} in {time.time() - t0:.0f}s [{slug}] polish={polish[-1][:90] if polish else 'n/a'}"
            + ("" if ok else f" | {problems[-1][:200] if problems else '?'}"))
    lines.append(line)
    print(line, flush=True)
summary = "\n".join(lines)
(ROOT / "workspace" / "generality-summary.txt").write_text(summary + "\n", encoding="utf-8")
print(f"\npassed {sum('PASS in' in l for l in lines)}/{len(lines)}")
