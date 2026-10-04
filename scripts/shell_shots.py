r"""Real screenshots of the multi-page shell: a filled project (the bodies the contract repair writes, so no model is needed) is served with its sample data,
and headless Chrome shoots the dashboard, a list page and a detail page of each app.

    backend\.venv\Scripts\python.exe scripts\shell_shots.py cab fest clinic "Build Instagram" "Build an expense tracker" --out workspace\_shots\p10a [--dark]

An app is a goal, or one of the keys cab / fest / clinic (the goals of the tests), or a platform name.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.contract_tests import ui_page_test_source, ui_script_test_source  # noqa: E402,F401
from app.goalspec import goal_spec  # noqa: E402
from app.look import choose_look  # noqa: E402
from app.platforms import match_platform  # noqa: E402
from app.relations import synthesize_design  # noqa: E402
from app.schemas import normalize_spec  # noqa: E402
from app.seeddata import seed_for  # noqa: E402
from app.skills import match_skill  # noqa: E402
from app.uistub import page_stub, script_stub  # noqa: E402
from cdp_shot import CHROME  # noqa: E402,F401
from test_repair import filled_project  # noqa: E402
from test_shell import CAB, CLINIC, FEST  # noqa: E402

GOALS = {"cab": CAB, "fest": FEST, "clinic": CLINIC}


def build(goal: str, tmp: Path):
    spec = match_platform(goal) or goal_spec(goal)
    if spec is None:
        raise SystemExit(f"{goal!r}: needs the model (not a platform, not a structured goal)")
    normalize_spec(spec, goal)
    spec.skill = match_skill(goal, spec.title, [r.name for r in spec.resources])
    design = synthesize_design(spec)
    design.look = choose_look(goal, spec, design)
    root = filled_project(tmp, design)
    (root / "static" / "index.html").write_text(page_stub(design, spec.title), encoding="utf-8")
    (root / "static" / "app.js").write_text(script_stub(design, spec.title), encoding="utf-8")
    (root / "seed.json").write_text(json.dumps(seed_for(design, spec.skill), ensure_ascii=False), encoding="utf-8")
    return root, design, spec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("apps", nargs="*")
    ap.add_argument("--project", action="append", default=[], help="a finished project folder (workspace/<slug>): its own app is started and shot as it is")
    ap.add_argument("--out", default=str(ROOT / "workspace" / "_shots" / "p10a"))
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--dark", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for folder in args.project:
        root = Path(folder).resolve()
        design = json.loads((root / ".q" / "design.json").read_text(encoding="utf-8"))
        tmp = Path(tempfile.mkdtemp(prefix="q-shots-"))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = {**os.environ, "Q_SEED": "1", "APP_DB": str(tmp / "app.db")}
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port)], cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                    break
                except OSError:
                    time.sleep(0.5)
            res = [r["name"] for r in design.get("resources", [])]
            first = res[0] if res else next((t["name"] for t in design["tables"]), "items")
            name = root.name.rsplit("-", 1)[0] if root.name.rsplit("-", 1)[-1].isdigit() else root.name
            pages = {"dashboard": "/", "list": f"/#/{res[-1] if len(res) > 1 else first}", "detail": f"/#/{first}/1"}
            for page, path in pages.items():
                file = out / f"{name}-{page}{'-dark' if args.dark else ''}.png"
                cmd = [sys.executable, str(Path(__file__).resolve().parent / "cdp_shot.py"), f"http://127.0.0.1:{port}/?mode={'dark' if args.dark else 'light'}{path.lstrip('/')}", "--size", args.size, "--out", str(file)]
                subprocess.run(cmd, check=False, capture_output=True, timeout=120)
                print(f"{root.name}: {file.name} (skin {(design.get('look') or {}).get('skin')})")
        finally:
            server.terminate()
    for app in args.apps:
        goal = GOALS.get(app, app)
        tmp = Path(tempfile.mkdtemp(prefix="q-shots-"))
        root, design, spec = build(goal, tmp)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = {**os.environ, "Q_SEED": "1", "APP_DB": str(tmp / "app.db")}
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port)], cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                    break
                except OSError:
                    time.sleep(0.5)
            first = design.resources[0].name if design.resources else "items"
            name = app.replace(" ", "-").lower()
            pages = {"dashboard": "/", "list": f"/#/{design.resources[-1].name}" if len(design.resources) > 1 else f"/#/{first}", "detail": f"/#/{first}/1"}
            for page, path in pages.items():
                file = out / f"{name}-{page}{'-dark' if args.dark else ''}.png"
                cmd = [sys.executable, str(Path(__file__).resolve().parent / "cdp_shot.py"), f"http://127.0.0.1:{port}/?mode={'dark' if args.dark else 'light'}{path.lstrip('/')}", "--size", args.size, "--out", str(file)]
                subprocess.run(cmd, check=False, capture_output=True, timeout=120)
                print(f"{app}: {file.name} (skin {design.look.skin}, skill {spec.skill})")
        finally:
            server.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
