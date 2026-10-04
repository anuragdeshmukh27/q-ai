"""Render the multi-page shell for a goal without any model: the spec by rules, the contract by rules, then the page and its script into a copy of the preset,
and run the fake-browser smoke test (tests/ui/shell_smoke.mjs) on it.

    backend\\.venv\\Scripts\\python.exe scripts\\shell_try.py "Build Instagram" [--keep DIR]
    backend\\.venv\\Scripts\\python.exe scripts\\shell_try.py --file goal.txt
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.goalspec import goal_spec  # noqa: E402
from app.look import choose_look  # noqa: E402
from app.platforms import match_platform  # noqa: E402
from app.relations import synthesize_design  # noqa: E402
from app.schemas import normalize_spec  # noqa: E402
from app.skills import match_skill  # noqa: E402
from app.uistub import page_stub, script_stub  # noqa: E402

SKELETON = ROOT / "backend" / "app" / "presets" / "fastapi_vanilla" / "skeleton"


def build(goal: str, out: Path) -> None:
    spec = match_platform(goal) or goal_spec(goal)
    if spec is None:
        raise SystemExit("this goal needs the model (no platform, not a structured goal)")
    normalize_spec(spec, goal)
    spec.skill = match_skill(goal, spec.title, [r.name for r in spec.resources])
    design = synthesize_design(spec)
    design.look = choose_look(goal, spec, design)
    shutil.copytree(SKELETON, out, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (out / "static" / "index.html").write_text(page_stub(design, spec.title), encoding="utf-8")
    (out / "static" / "app.js").write_text(script_stub(design, spec.title), encoding="utf-8")
    print(f"{spec.title}: skill={spec.skill or '-'} skin={design.look.skin} layout={design.look.layout} resources={[r.name for r in design.resources]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("goal", nargs="?", default="")
    ap.add_argument("--file")
    ap.add_argument("--keep")
    args = ap.parse_args()
    goal = Path(args.file).read_text(encoding="utf-8").strip() if args.file else args.goal
    out = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="q-shell-")) / "app"
    if out.exists():
        shutil.rmtree(out)
    build(goal, out)
    r = subprocess.run(["node", str(out / "tests" / "ui" / "shell_smoke.mjs")], capture_output=True, text=True)
    print((r.stdout + r.stderr).strip()[-1500:])
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
