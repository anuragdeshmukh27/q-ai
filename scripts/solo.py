"""P1 check: one Backend agent builds a small FastAPI feature with passing tests.

    backend\.venv\Scripts\python.exe scripts\solo.py "<goal>" [--model ID] [--mode supervised]
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.agent.loop import run_agent  # noqa: E402
from app.config import load_agents, load_env  # noqa: E402
from app.events import EventBus  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.ports import PortError, PortManager  # noqa: E402
from app.presets import DEFAULT_PRESET, load_preset  # noqa: E402
from app.project import create_project  # noqa: E402
from app.registry import ModelRegistry  # noqa: E402
from app.tools import ToolBox  # noqa: E402


def cli_approver(agent: str, kind: str, summary: str, details: dict) -> bool:
    if not sys.stdin.isatty():
        print(f"    approval needed ({summary}) - denied, no terminal attached")
        return False
    return input(f"    {agent} wants to {summary}. Approve? [y/N] ").strip().lower() == "y"


def printer(e: dict) -> None:
    t = e["type"]
    if t == "iteration":
        print(f"\n[{e['n']}/{e['max']}]", end=" ")
    elif t == "agent_thought":
        print(f"{e['text']}  ({e['model']}, {e['tokens']} tok, {e['seconds']:.1f}s)")
    elif t == "tool_call":
        arg = next(iter(e["args"].values()), "")
        arg = (arg if isinstance(arg, str) else str(arg)).replace("\n", " ")[:70]
        print(f"    {e['tool']} {arg} -> {'ok' if e['ok'] else 'FAILED'} ({e['decision']}, {e['duration']}s)")
        if not e["ok"]:
            print(f"      {e['output'][:160]!r}")
    elif t == "test_result":
        print(f"    tests: {'PASS' if e['passed'] else 'FAIL'} {e['summary']}")
    elif t in ("escalation", "error"):
        print(f"    !! {t}: {e.get('detail') or e.get('message')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("goal")
    ap.add_argument("--model", help="model id from config/models.yaml (default: best local coding model)")
    ap.add_argument("--mode", default="supervised", choices=["assisted", "supervised", "autonomous"])
    ap.add_argument("--preset", default=DEFAULT_PRESET)
    ap.add_argument("--max-iterations", type=int, default=12)
    args = ap.parse_args()

    load_env()
    registry = ModelRegistry.load()
    model = registry.get(args.model) if args.model else registry.default_for("coding")
    preset = load_preset(args.preset)
    root = create_project(args.goal, args.preset)
    print(f"project: {root}\nmodel:   {model.name} (num_ctx {model.num_ctx})\nmode:    {args.mode}")

    # Solo mode: the Backend agent also writes its own tests (QA does that in the full team).
    agent = load_agents()["backend"].model_copy(
        update={"owned_paths": ["backend/**", "tests/**"], "forbidden_paths": [".q/**"], "max_iterations": args.max_iterations}
    )
    bus = EventBus()
    bus.subscribe(printer)
    tools = ToolBox(root, agent, mode=args.mode, approver=cli_approver, emit=bus.emit, test_cmd=preset.test_cmd,
                    extra_allowed=[preset.run_cmd])
    task = (
        f"Goal: {args.goal}\n\nBuild this as a small FastAPI feature. Put pure logic and endpoints in small modules under backend/ "
        "(include your router in backend/main.py) and write pytest tests in tests/ that cover the happy path and invalid input."
    )
    res = run_agent(agent, task, tools, LLMClient(registry), model.id, num_ctx=model.num_ctx, emit=bus.emit)

    print(f"\n== agent: {res.status} {res.reason} | {res.iterations} iterations | {res.completion_tokens} tokens generated")
    print(f"== files: {', '.join(res.files_touched)}")
    if res.summary:
        print(f"== summary: {res.summary}")

    # Independent verification, outside the agent's own claims.
    check = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=root, capture_output=True, text=True)
    last = check.stdout.strip().splitlines()[-1] if check.stdout.strip() else check.stderr[-200:]
    print(f"== verify pytest: {'PASS' if check.returncode == 0 else 'FAIL'} - {last}")
    if check.returncode == 0:
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"[backend] {args.goal[:60]}"], cwd=root, capture_output=True)
        pm = PortManager()
        try:
            app = pm.start(root.name, root, preset.run_cmd, preset.health_path)
            print(f"== app healthy at {app.url}")
        except PortError as e:
            print(f"== app did not start: {e}")
        finally:
            pm.stop_all()
    return 0 if res.status == "finished" and check.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
