"""Compare build configurations on the same goals (alternating, so drift hits every configuration alike).

    backend\.venv\Scripts\python.exe scripts\compare.py --goals 1,2 --reps 2 --configs before,after

Default comparison (P8 block): before = the previous commit checked out at --before-root (git worktree), building the original SHORT goal;
after = this tree, building the detailed example-chip goal. Both use the product defaults. The older configs below (fast-only, reviewer-4b) still work.
Summary lines go to workspace/compare-<tag>.txt.
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from goals import CHIPS, SHORT  # noqa: E402

PAIRS = [(SHORT[1], CHIPS[1][1]), (SHORT[2], CHIPS[2][1]), (SHORT[0], CHIPS[0][1])]  # todo, expense, calculator: (short goal, detailed chip goal)
GOALS = [p[0] for p in PAIRS]
CONFIGS = {
    "before": [],
    "after": [],
    "fast-only": ["--single-model", "qwen25-coder-7b"],
    "reviewer-4b": ["--override", "reviewer=qwen3-4b"],
}

ap = argparse.ArgumentParser()
ap.add_argument("--goals", default="1,2,3")
ap.add_argument("--reps", type=int, default=1)
ap.add_argument("--configs", default="before,after")
ap.add_argument("--tag", default="p7")
ap.add_argument("--before-root", default=str(ROOT.parent / "q_before"), help="checkout of the previous commit used by the 'before' config")
args = ap.parse_args()
out = ROOT / "workspace" / f"compare-{args.tag}.txt"
rows = []
for rep in range(1, args.reps + 1):
    for g in [int(x) for x in args.goals.split(",")]:
        for cfg in args.configs.split(","):
            t0 = time.time()
            tree = Path(args.before_root) if cfg == "before" else ROOT
            goal = PAIRS[g - 1][1] if cfg == "after" else PAIRS[g - 1][0]
            p = subprocess.run([sys.executable, str(tree / "scripts" / "build.py"), goal, *CONFIGS[cfg]], cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace")
            text = p.stdout
            (ROOT / "workspace" / "_logs").mkdir(parents=True, exist_ok=True)
            (ROOT / "workspace" / "_logs" / f"compare-{args.tag}-{cfg}-g{g}-r{rep}.txt").write_text(text + "\n--- stderr ---\n" + p.stderr[-1500:], encoding="utf-8")
            secs = time.time() - t0
            reviews = len(re.findall(r"^\s+review t\d+ round", text, re.M))
            polish = (re.findall(r"== polish([^\n]*)", text) or ["-"])[-1].strip(" :")[:70]
            models = (re.findall(r"== models: ([^|]*)\|", text) or ["?"])[0].strip()
            swaps = (re.findall(r"model swaps: (\d+)", text) or ["?"])[0]
            line = (f"{cfg:11} rep{rep} {goal[:34]:34} {'PASS' if 'BUILD OK' in text else 'FAIL'} {secs:5.0f}s reviews={reviews} swaps={swaps} models=[{models}] polish={polish}"
                    + ("" if "BUILD OK" in text else " | " + ((re.findall(r"problem: ([^\n]*)", text) or ["?"])[-1][:140])))
            rows.append(line)
            print(line, flush=True)
            out.write_text("\n".join(rows) + "\n", encoding="utf-8")
