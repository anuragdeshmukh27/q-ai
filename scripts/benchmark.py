"""Benchmark runner: small tasks per role, run per model, results into SQLite and (with --export) the committed results file.

    backend\.venv\Scripts\python.exe scripts\benchmark.py --models qwen25-coder-7b,qwen3-4b,llama32-3b [--roles backend,qa] [--only api-todo] [--reps 1] [--export]

Ollama must be running. Runs for a model replace nothing: they are appended to the local database; --export writes the effective results
(local runs win per role x model cell) to backend/benchmarks/results.json, which is committed so the leaderboard is never empty.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import load_env  # noqa: E402
from app.leaderboard import SHIPPED_RESULTS, Leaderboard  # noqa: E402
from benchmarks.runner import run_benchmarks  # noqa: E402


def machine() -> str:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{out} (Windows laptop)"
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="qwen25-coder-7b,qwen3-4b,llama32-3b")
    ap.add_argument("--roles", help="comma-separated roles (default: all)")
    ap.add_argument("--only", help="comma-separated task ids")
    ap.add_argument("--reps", type=int, help="repetitions per task (default: the task's own)")
    ap.add_argument("--db", default=str(ROOT / "data" / "q.db"))
    ap.add_argument("--fresh", action="store_true", help="start from an empty local database")
    ap.add_argument("--export", action="store_true", help="write backend/benchmarks/results.json from the effective results")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()
    load_env()
    db = Path(args.db)
    if args.fresh and db.exists():
        db.unlink()
    board = Leaderboard(db, shipped=None if args.fresh else SHIPPED_RESULTS)
    run_benchmarks(args.models.split(","), args.roles.split(",") if args.roles else None, board, args.reps, only=args.only.split(",") if args.only else None)
    s = board.summary()
    print("\nrole x model (pass rate, runs):")
    for role in s["roles"]:
        print(f"  {role:9}", "  ".join(f"{m}: {round(c['pass_rate'] * 100)}% ({c['runs']})" for m, c in sorted(s["matrix"][role].items())))
    if args.export:
        n = board.export(SHIPPED_RESULTS, machine(), args.notes)
        print(f"exported {n} runs to {SHIPPED_RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
