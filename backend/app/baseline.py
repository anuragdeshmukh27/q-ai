"""The single-agent baseline: what one model loop does with everything the team gets except the team.

Same goal, same model, same Architect step (spec, contract, look: shared code), same contract-generated stubs, page and tests (the complete suite, edge tests
included, is in the project from the start), same tools and sandbox, same termination rules, same final verification. What is missing is the organisation:
no Planner (a rules plan only places the same stubs), no per-task context (ONE loop and one context for the whole app), no parallel engineers, no git branch
per agent, no Reviewer, no QA and bug routing, no Integrator, no contract repair, no re-plan and no second attempt. The loop gets more iterations than any one
team task (SOLO_ITERATIONS), about what the team's tasks get together.
"""
from __future__ import annotations

import ast
import time

from .agent.loop import run_agent
from .agent.planning import AgentFailed
from .config import AgentConfig
from .contract_tests import edge_test_source
from .orchestrator import LOCKED, Orchestrator
from .presets import load_preset
from .relations import plan_for_relations
from .schemas import TaskSpec, topo_order

SOLO_ITERATIONS = 60


def rules_plan(design) -> list[TaskSpec]:
    """Where the stubs go: the same files the team's plan names (relational designs: the plan the team gets by rules; a single resource: one file per layer)."""
    if design.resources:
        return plan_for_relations(design).tasks
    table = design.tables[0].name if design.tables else "items"
    tasks: list[TaskSpec] = []
    if design.tables:
        tasks.append(TaskSpec(id="t1", title="Data access functions", owner="database", files=[f"database/{table}.py"], acceptance=["run_tests passes"]))
    tasks.append(TaskSpec(id=f"t{len(tasks) + 1}", title="API routes", owner="backend", depends_on=[t.id for t in tasks], files=[f"backend/api/{table}.py"], acceptance=["run_tests passes"]))
    tasks.append(TaskSpec(id=f"t{len(tasks) + 1}", title="Page", owner="frontend", files=["static/index.html", "static/style.css"], acceptance=["run_tests passes"]))
    tasks.append(TaskSpec(id=f"t{len(tasks) + 1}", title="Page script", owner="frontend", files=["static/app.js"], acceptance=["run_tests passes"]))
    return tasks


def unimplemented(path_text: str) -> list[str]:
    """Names of the functions in a stub whose body is still `raise NotImplementedError`."""
    try:
        tree = ast.parse(path_text)
    except SyntaxError:
        return []
    return [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and any(isinstance(x, ast.Raise) and "NotImplementedError" in ast.dump(x) for x in n.body)]


class SoloBuild(Orchestrator):
    """One agent builds the whole app in one loop. `run()` is the team's, with the team's own phases replaced by `_pipeline` below."""

    def _solo_agent(self) -> AgentConfig:
        b = self.agents["backend"]
        return b.model_copy(update={
            "id": "solo", "name": "Solo", "role": "Full-stack engineer (the whole team in one)", "system_prompt_file": "solo.md",
            "owned_paths": ["backend/**", "database/**", "static/**", "frontend/**", "tests/test_db*.py"],
            "forbidden_paths": [".q/**", *LOCKED], "max_iterations": SOLO_ITERATIONS,
        })

    def _pipeline(self) -> None:
        self._design()
        agent = self._solo_agent()
        assert self.root and self.design and self.memory
        # Place the same stubs, page and tests the team starts from (all of them, before the loop starts).
        parts = [{**t.model_dump(), "status": "pending", "summary": "", "attempts": 0} for t in topo_order(rules_plan(self.design))]
        self.tasks = parts
        for t in parts:
            self._scaffold(t, agent, self.root)
        edge = edge_test_source(self.design)
        target = self.root / "tests" / "qa" / "test_edge_cases.py"
        if "def test_" in edge and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edge, encoding="utf-8", newline="\n")
        task = {"id": "s1", "title": "Build the whole app", "owner": "solo", "depends_on": [], "files": [f for p in parts for f in p["files"]], "acceptance": ["run_tests passes"],
                "status": "pending", "summary": "", "attempts": 0}
        self.routers = [p for p in parts if p["owner"] == "backend"]  # kept for the task text: which db module each router calls
        self.tasks = [task]
        self.emit("plan_created", tasks=[{k: task[k] for k in ("id", "title", "owner", "depends_on", "files")}])
        self._commit("[solo] contract scaffolding and tests")
        preset = load_preset(self.design.preset)
        model = self._model(agent)
        self._begin(task, model)
        started = time.time()
        res = run_agent(agent, self._solo_task(task), self._toolbox(agent, preset.test_cmd, [preset.run_cmd], root=self.root), self.llm, model.id, num_ctx=model.num_ctx,
                        context=self._solo_context(), emit=self.emit)
        self._stat("solo", model, res.iterations, res.prompt_tokens, res.completion_tokens, time.time() - started)
        if res.status == "finished":
            self._commit("[solo] build the whole app")
            task.update(status="done", summary=res.summary)
        else:
            task["status"] = "failed"
            self.problems.append(f"the single agent stopped: {res.reason or res.status}")
        self._save_tasks()
        self._progress()
        self._verify()

    def _solo_context(self) -> str:
        assert self.memory
        return "\n\n".join(p for p in (self.memory.context_for("backend"), self.memory.context_for("frontend")) if p)

    def _solo_task(self, t: dict) -> str:
        assert self.root
        lines = []
        for rel in t["files"]:
            p = self.root / rel
            if p.suffix == ".py" and p.is_file():
                names = unimplemented(p.read_text(encoding="utf-8"))
                if names:
                    lines.append(f"- {rel}: implement {len(names)} functions, each ONCE: {', '.join(names)}")
        page = [r for r in t["files"] if r.startswith("static/")]
        return (f"Task {t['id']}: {t['title']}\nThe whole app is yours. These files are stubs generated from the contract:\n" + "\n".join(lines)
                + (f"\n- {', '.join(page)}: a working page generated from the contract; change it only where a failing test points" if page else "")
                + "\nThe complete test suite is already written. Read the stubs with read_file (the database stubs first: the routes call them), fill every function with `implement`, "
                  "then run_tests, fix only what fails, and when run_tests passes call finish.\n\nThe database functions the routes call (exact names and parameters):\n"
                + "\n".join((f"For {r['files'][0]}:\n" if len(self.routers) > 1 else "") + self._db_api(self.root, *self._db_scope(r)) for r in self.routers))
