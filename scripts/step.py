"""Test ONE agent step in isolation (for prompt tuning) instead of re-running a whole build.

    step.py architect "Build a calculator with history" -n 5
    step.py planner   "Build a calculator with history" -n 5          # runs the Architect once, then the Planner N times
    step.py task <project dir> t2 -n 3                                  # re-runs one engineer task on a copy of a finished/failed project

Each run prints PASS/FAIL and the reasons, then a pass rate.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.agent.planning import AgentFailed, run_architect, run_planner  # noqa: E402
from app.config import load_agents, load_env  # noqa: E402
from app.events import EventBus  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.memory import MessageBus, ProjectMemory, contract_brief, contract_dict, schema_md  # noqa: E402
from app.orchestrator import TEST_GLOBS, Orchestrator  # noqa: E402
from app.presets import list_presets, load_preset  # noqa: E402
from app.registry import ModelRegistry  # noqa: E402
from app.sandbox.paths import glob_to_regex  # noqa: E402


def quiet(e: dict) -> None:
    if e["type"] in ("agent_thought", "error") and e.get("agent"):
        print(f"      {e['agent']}: {(e.get('text') or e.get('message'))[:200]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["architect", "planner", "task"])
    ap.add_argument("target", help="goal text (architect/planner) or project directory (task)")
    ap.add_argument("task_id", nargs="?")
    ap.add_argument("-n", type=int, default=3, help="number of runs")
    args = ap.parse_args()

    load_env()
    registry = ModelRegistry.load(env={})  # local only
    llm, agents = LLMClient(registry), load_agents()
    bus = EventBus()
    bus.subscribe(quiet)
    model = registry.get(registry.single_model) if registry.single_model else None
    passed = 0

    if args.step in ("architect", "planner"):
        presets = {n: load_preset(n).description for n in list_presets()}
        mid = model.id if model else registry.default_for("reasoning").id
        design = None
        for i in range(1 if args.step == "planner" else args.n):
            try:
                design, _ = run_architect(agents["architect"], llm, mid, args.target, presets, bus.emit)
                if args.step == "architect":
                    passed += 1
                    print(f"run {i + 1}: PASS  {[f'{e.method} {e.path}' for e in design.endpoints]} funcs={[f.name for f in design.db_functions]}")
            except AgentFailed as e:
                print(f"run {i + 1}: FAIL  {e.reason[:300]}")
        if args.step == "planner":
            if not design:
                return 1
            contract = contract_dict(design)
            for i in range(args.n):
                try:
                    plan, _ = run_planner(agents["planner"], llm, mid, args.target, contract_brief(contract), schema_md(design),
                                          bool(design.tables), design.endpoints, bus.emit)
                    passed += 1
                    print(f"run {i + 1}: PASS  {[(t.id, t.owner, t.depends_on, t.files) for t in plan.tasks]}")
                except AgentFailed as e:
                    print(f"run {i + 1}: FAIL  {e.reason[:300]}")
    else:
        src = Path(args.target).resolve()
        tasks = json.loads((src / ".q" / "tasks.json").read_text(encoding="utf-8"))["tasks"]
        task = next(t for t in tasks if t["id"] == args.task_id)
        mid = model.id if model else registry.default_for(agents[task["owner"]].model_capability).id
        for i in range(args.n):
            tmp = Path(tempfile.mkdtemp(prefix="q-step-"))
            work = tmp / "p"
            shutil.copytree(src, work, ignore=shutil.ignore_patterns(".worktrees", "__pycache__", ".pytest_cache"))
            # Remove what this task produced (its files and its tests); keep everything its dependencies built.
            owner_tests = glob_to_regex(TEST_GLOBS.get(task["owner"], "tests/__none__"))
            for rel in task["files"] + [str(p.relative_to(work)).replace("\\", "/") for p in (work / "tests").glob("*.py") if owner_tests.match("tests/" + p.name)]:
                (work / rel).unlink(missing_ok=True)
            subprocess.run(["git", "add", "-A"], cwd=work, capture_output=True)
            subprocess.run(["git", "commit", "-m", "step baseline"], cwd=work, capture_output=True)
            orch = Orchestrator("step", registry, llm, bus, mode="autonomous", overrides={task["owner"]: mid}, start_app=False)
            orch.root, orch.memory = work, ProjectMemory(work)
            orch.messages = MessageBus(orch.memory, bus.emit)
            orch.tasks = [{**t, "status": "done" if t["id"] != task["id"] and t["id"] in task["depends_on"] else "pending",
                           "summary": t.get("summary", ""), "attempts": 0} for t in tasks]
            target = next(t for t in orch.tasks if t["id"] == task["id"])
            res = orch._run_task(target, load_preset("fastapi-vanilla"))
            check = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=work, capture_output=True, text=True)
            ok = res.status == "finished" and check.returncode == 0
            passed += ok
            last = (check.stdout.strip().splitlines() or [""])[-1]
            print(f"run {i + 1}: {'PASS' if ok else 'FAIL'}  {res.status} {res.reason} in {res.iterations} iterations | pytest: {last}")
            if not ok:
                for line in [l for l in check.stdout.splitlines() if l.startswith(("E ", "FAILED"))][:14]:
                    print("      " + line[:200])
                print(f"      (kept at {work})")
            else:
                shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{passed}/{args.n} passed (model: {model.name if model else 'per-role'})")
    return 0 if passed == args.n else 1


if __name__ == "__main__":
    raise SystemExit(main())
