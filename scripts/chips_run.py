"""Build every example chip once with the local model and screenshot each built app (the regression check for a change to themes, layouts or the engine).

    backend\.venv\Scripts\python.exe scripts\chips_run.py [--tag p9b] [--only 1,2,3] [--famous]

One line per goal goes to workspace/chips-<tag>.txt: PASS or FAIL, seconds, the theme and layout that were chosen, the screenshot. --famous builds the
"Try a famous app" goals instead of the detailed chips.
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from goals import CHIPS, FAMOUS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="p9b")
    ap.add_argument("--only", default="")
    ap.add_argument("--famous", action="store_true")
    args = ap.parse_args()
    goals = FAMOUS if args.famous else CHIPS
    pick = [int(x) for x in args.only.split(",")] if args.only else list(range(1, len(goals) + 1))
    out = ROOT / "workspace" / f"chips-{args.tag}.txt"
    rows: list[str] = []
    (ROOT / "workspace" / "_logs").mkdir(parents=True, exist_ok=True)
    for n in pick:
        label, goal = goals[n - 1]
        t0 = time.time()
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py"), goal], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        secs = time.time() - t0
        text = p.stdout
        (ROOT / "workspace" / "_logs" / f"chips-{args.tag}-{n}.txt").write_text(text + "\n--- stderr ---\n" + p.stderr[-1500:], encoding="utf-8")
        ok = "BUILD OK" in text
        m = re.search(r"== project: (.*)", text)
        shot = ""
        if ok and m:
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "shots.py"), m.group(1).strip(), "--out", str(ROOT / "workspace" / "_shots" / args.tag)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            shot = (r.stdout.strip().splitlines() or ["no screenshot"])[-1]
        problem = "" if ok else " | " + (re.findall(r"problem: ([^\n]*)", text) or ["?"])[-1][:140]
        rows.append(f"{label:20} | {'PASS' if ok else 'FAIL'} | {secs:4.0f}s | {shot}{problem}")
        print(rows[-1], flush=True)
        out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"{sum(1 for r in rows if '| PASS |' in r)}/{len(rows)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
