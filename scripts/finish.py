"""Finish my project from the command line: import a folder (or a GitHub URL), find the gaps, fix them, and (for the sample fixtures) run the hidden acceptance tests.

    backend\\.venv\\Scripts\\python.exe scripts\\finish.py samples\\half-built\\fest-app [--accept] [--keep] [--pick g1,g2] [--finish-model MODEL_ID]
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from solo import cli_approver  # noqa: E402

from app.config import load_env  # noqa: E402
from app.events import EventBus  # noqa: E402
from app.finish.build import FinishBuild  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.registry import ModelRegistry  # noqa: E402
from app.scheduler import ModelScheduler  # noqa: E402
from build import printer as build_printer  # noqa: E402


def printer(e: dict) -> None:
    t = e["type"]
    if t == "gap_report":
        print(f"== gap report: {len(e['gaps'])} gaps")
        for g in e["gaps"]:
            print(f"   {g['id']} [{g['kind']}] {g['title']}  ({g['file']})")
    elif t == "gap_status":
        print(f"== gaps fixed: {len(e['fixed'])}, still open: {len(e['open'])} ({', '.join(e['open']) or '-'})")
    elif t == "finish_summary":
        print(f"== changed {len(e['files'])} files, +{e['insertions']} -{e['deletions']}: " + ", ".join(f['path'] for f in e['files']))
    elif t in ("gaps_selected", "selection_needed"):
        print(f"== {t}: {e.get('ids') or e.get('count')}")
    else:
        build_printer(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--accept", action="store_true", help="run samples/half-built/_acceptance/<name>/ against the finished copy")
    ap.add_argument("--base", help="where the copy goes (default: a temp folder)")
    ap.add_argument("--no-app", action="store_true")
    ap.add_argument("--only", help="comma-separated gap ids (default: all)")
    ap.add_argument("--finish-model", metavar="MODEL_ID", help="the finishing engineers (backend, frontend, database) use this model; the analyst and everyone else keep the default")
    ap.add_argument("--raw", action="store_true", help="print every raw model reply")
    args = ap.parse_args()

    load_env()
    registry = ModelRegistry.load(env={})
    bus = EventBus()
    bus.subscribe(printer)
    base = Path(args.base) if args.base else Path(tempfile.mkdtemp(prefix="q-finish-"))
    started = time.time()
    orch = FinishBuild(args.source, registry, LLMClient(registry, scheduler=ModelScheduler(registry, emit=bus.emit)), bus, auto_fix=True, only=args.only.split(",") if args.only else None, mode="autonomous",
                       overrides={a: args.finish_model for a in ("backend", "frontend", "database")} if args.finish_model else None,
                       approver=cli_approver, base=base, start_app=not args.no_app, fast_live=True)
    if args.raw:
        orch.llm.observer = lambda o: print("RAW>", o["text"][:1200].replace(chr(10), " | "))
    res = orch.run()
    print(f"\n== {'FINISH OK' if res.ok else 'FINISH FAILED'} in {time.time() - started:.0f}s | tests: {res.test_summary}")
    for p in res.problems:
        print(f"   problem: {p}")
    ok = res.ok
    if args.accept and res.root:
        name = Path(args.source.rstrip("/\\")).name
        hidden = ROOT / "samples" / "half-built" / "_acceptance" / name / "test_accept_hidden.py"
        if hidden.is_file():
            dest = res.root / "tests" / "q_hidden"
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy(hidden, dest / "test_accept_hidden.py")
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/q_hidden", "-p", "no:cacheprovider"], cwd=res.root, capture_output=True, text=True)
            print("== hidden acceptance: " + (r.stdout.strip().splitlines() or ["no output"])[-1])
            if r.returncode != 0:
                print(r.stdout[-1800:])
            ok = ok and r.returncode == 0
            shutil.rmtree(dest, ignore_errors=True)
    if res.root:
        print(f"== project: {res.root}")
    orch.ports and orch.ports.stop_all()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
