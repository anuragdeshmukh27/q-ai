r"""Try an Ask-employee request on a copy of a finished project, several times, without rebuilding the app (for tuning the request task and its tools).

    backend\.venv\Scripts\python.exe scripts\ask_step.py workspace\<finished todo project> -n 3 [--text "Add a progress bar at the top showing how many todos are done"]

Each run copies the project, queues the request for the Frontend engineer, runs it exactly like the Ask-employee box does (same task text, same tools, review,
Integrator merge), runs pytest, and checks the page in headless Chrome with scripts/ask_check.py. Prints PASS only when all of that holds.
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

from app.config import load_agents, load_env  # noqa: E402
from app.events import EventBus  # noqa: E402
from app.integrator import Integrator  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.memory import MessageBus, ProjectMemory  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from app.registry import ModelRegistry  # noqa: E402
from app.repo import Repo, run_git  # noqa: E402
from app.schemas import ArchitectOutput  # noqa: E402

VERBOSE = False
DEFAULT_TEXT = "Add a progress bar at the top showing how many todos are done"


def one(src: Path, text: str, model_id: str, registry: ModelRegistry, llm: LLMClient) -> tuple[bool, str, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="q-ask-"))
    work = tmp / "p"
    shutil.copytree(src, work, ignore=shutil.ignore_patterns(".worktrees", "__pycache__", ".pytest_cache", "*.db"))
    shutil.rmtree(work / ".git" / "worktrees", ignore_errors=True)  # these point at the original project's worktrees: the copy gets its own
    for b in run_git(work, "branch", "--list", "agent/*", check=False).stdout.split():
        if b.startswith("agent/"):
            run_git(work, "branch", "-D", b, check=False)
    run_git(work, "checkout", "-f", "main", check=False)
    agents = load_agents()
    bus = EventBus()
    orch = Orchestrator("ask", registry, llm, bus, mode="autonomous", overrides={a: model_id for a in agents}, start_app=False, fast_live=True)
    orch.root, orch.repo = work, Repo(work)
    orch.memory = ProjectMemory(work)
    orch.messages = MessageBus(orch.memory, bus.emit)
    orch.design = ArchitectOutput.model_validate_json((work / ".q" / "design.json").read_text(encoding="utf-8"))
    orch.integrator = Integrator(agents["integrator"], orch.repo, llm, model_id, bus.emit, lambda: "autonomous", None)
    orch.tasks = []
    orch.add_request("frontend", text)
    orch.finished = False
    orch.finish_requests()
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace")
    last = (tests.stdout.strip().splitlines() or [""])[-1]
    check = subprocess.run([sys.executable, str(ROOT / "scripts" / "ask_check.py"), str(work), "--out", str(ROOT / "workspace" / "_shots")], capture_output=True, text=True, encoding="utf-8", errors="replace")
    verdict = check.stdout.strip().splitlines()[-1] if check.stdout.strip() else check.stderr[-200:]
    thoughts = [e.get("text", "")[:120] for e in bus.history if e["type"] == "agent_thought" and e.get("agent") == "frontend"]
    if VERBOSE:
        for e in bus.history:
            if e["type"] == "tool_call" and e["agent"] == "frontend":
                print(f"      {e['tool']} {str(e['args'])[:260]!r} -> {'ok' if e['ok'] else 'FAILED'} {e['output'][:150]!r}")
    ok = tests.returncode == 0 and check.returncode == 0 and not orch.problems
    return ok, f"pytest: {last} | page: {verdict} | problems: {orch.problems[:2]} | last thought: {thoughts[-1] if thoughts else ''}", work


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("-n", type=int, default=3)
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("-v", action="store_true", help="print the Frontend engineer's tool calls")
    args = ap.parse_args()
    global VERBOSE
    VERBOSE = args.v
    load_env()
    registry = ModelRegistry.load(env={})
    llm = LLMClient(registry)
    model_id = registry.router_config.get("safe_default", "qwen25-coder-7b")
    passed = 0
    for i in range(args.n):
        ok, detail, work = one(Path(args.project).resolve(), args.text, model_id, registry, llm)
        passed += ok
        print(f"run {i + 1}: {'PASS' if ok else 'FAIL'}  {detail}", flush=True)
        if ok:
            shutil.rmtree(work.parent, ignore_errors=True)
        else:
            print(f"      (kept at {work})")
    print(f"\n{passed}/{args.n} passed")
    return 0 if passed == args.n else 1


if __name__ == "__main__":
    raise SystemExit(main())
