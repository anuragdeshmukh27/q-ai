"""Judge test: judges type short platform names, so build each one once on the local model and check what came out.

    backend\.venv\Scripts\python.exe scripts\judge.py [--tree <checkout>] [--tag after] [--only 1,3,5] [--reps 1]

A goal behaves correctly when it is either built (tests pass, the resources fit the scope below, and when the spec leaves things out the page itself
says "Not in this version: ...") or refused politely with 3 suggestions. One line per build goes to workspace/judge-<tag>.txt and the raw output of
every build to workspace/_logs/judge-<tag>-<n>.txt.
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

# (goal, expected: words that must appear in the resource names (any of each group), or "refuse")
GOALS = [
    ("Build Instagram", [["post", "photo"], ["comment"]]),
    ("Build Twitter", [["tweet", "post"], ["repl", "comment"]]),
    ("Build Amazon", [["product", "item"], ["review"]]),
    ("Build Zomato", [["restaurant"], ["review"]]),
    ("Build YouTube", [["video"], ["comment"]]),
    ("Build LinkedIn", [["post", "job", "profile"], ["comment", "application", "skill", "experience"]]),
    ("Build WhatsApp", [["chat", "conversation"], ["message"]]),
    ("Build Uber", [["ride", "trip"]]),
    ("Build a hospital management system", [["patient"], ["appointment", "visit", "record"]]),
    ("Build a library management system", [["book"], ["loan", "member", "borrow", "review"]]),
    ("Build a flappy bird game", "refuse"),
]


def check(goal: str, expect, text: str, root: Path | None) -> tuple[bool, str, str]:
    """-> (correct, what was built, note)"""
    ok = "BUILD OK" in text
    if expect == "refuse":
        refused = not root and "cannot build" in text and len(re.findall(r'"Build [^"]+"', text)) >= 3
        return refused, "refused" + (" with 3 suggestions" if refused else " (wrong)" if ok else " without suggestions"), ""
    if not root or not (root / ".q" / "design.json").exists():
        return False, "nothing built", (re.findall(r"problem: ([^\n]*)", text) or ["?"])[-1][:120]
    design = json.loads((root / ".q" / "design.json").read_text(encoding="utf-8"))
    names = [r["name"] for r in design.get("resources", [])] or sorted({t["name"] for t in design.get("tables", [])})
    built = " -> ".join(names) or "?"
    spec = (root / ".q" / "spec.md").read_text(encoding="utf-8") if (root / ".q" / "spec.md").exists() else ""
    left = re.search(r"Not in this version: ([^\n]*)", spec)
    page = "".join((root / "static" / f).read_text(encoding="utf-8", errors="replace") for f in ("index.html", "app.js", "shell.js") if (root / "static" / f).exists())  # the shell keeps the note in its description (app.js) and draws it (shell.js)
    notes = []
    fits = all(any(w in n for n in names for w in group) for group in expect)
    if not fits:
        notes.append("resources do not fit")
    if left and "Not in this version" not in page:
        notes.append("banner missing in the app")
    if not left:
        notes.append("spec has no 'Not in this version'")  # a platform name always asks for more than the MVP holds
    return ok and fits and (not left or "Not in this version" in page), built + (f" | left out: {left.group(1)[:90]}" if left else ""), "; ".join(notes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", default=str(ROOT), help="checkout to build with (default: this one)")
    ap.add_argument("--tag", default="after")
    ap.add_argument("--only", default="")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--goal", action="append", default=[], help="build these goals instead of the built-in list (no expected resources: only 'built, banner shown' or 'refused' is judged)")
    args = ap.parse_args()
    if args.goal:
        GOALS[:] = [(g, []) for g in args.goal]
    tree = Path(args.tree)
    pick = [int(x) for x in args.only.split(",")] if args.only else list(range(1, len(GOALS) + 1))
    rows = []
    out = ROOT / "workspace" / f"judge-{args.tag}.txt"
    (ROOT / "workspace" / "_logs").mkdir(parents=True, exist_ok=True)
    for rep in range(args.reps):
        for n in pick:
            goal, expect = GOALS[n - 1]
            t0 = time.time()
            p = subprocess.run([sys.executable, str(tree / "scripts" / "build.py"), goal], cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace")
            secs = time.time() - t0
            text = p.stdout + "\n" + p.stderr[-1500:]
            (ROOT / "workspace" / "_logs" / f"judge-{args.tag}-{n}-{rep}.txt").write_text(text, encoding="utf-8")
            m = re.search(r"== project: (.*)", text)
            root = Path(m.group(1).strip()) if m else None
            good, built, note = check(goal, expect, text, root)
            rows.append(f"{goal:38} | {built[:150]:60} | {'PASS' if good else 'FAIL'} | {secs:4.0f}s" + (f" | {note}" if note else ""))
            print(rows[-1], flush=True)
            out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"{sum(1 for r in rows if '| PASS |' in r)}/{len(rows)} correct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
