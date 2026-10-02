"""The orchestrator: Architect -> Planner -> engineers (parallel, one git worktree each) -> Reviewer -> Integrator -> QA -> verification.

It owns the workflow and the shared project memory; every agent step emits events. Engineers run in worker threads;
all task bookkeeping (status, re-plans, merges into main) happens on the orchestrator's own thread.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

from .agent.actions import Action
from .agent.loop import AgentResult, run_agent
from .agent.planning import AgentFailed, run_amendment, run_architect, run_planner, run_replanner
from .agent.qa import Failure, bug_markdown, parse_failures, triage_or_fallback
from .agent.review import missing_tests, review_markdown, run_review, static_findings
from .faults import inject_fault
from .repo import GitError, Repo
from .integrator import Integrator, run_suite
from .config import AgentConfig, load_agents
from .events import EventBus
from .llm import LLMClient
from .memory import MessageBus, ProjectMemory, architecture_md, contract_brief, contract_dict, schema_md
from .ports import PortError, PortManager
from .presets import DEFAULT_PRESET, list_presets, load_preset
from .project import create_project
from .registry import ModelConfig, ModelRegistry
from .contract_tests import api_test_source, edge_test_source, ui_page_test_source, ui_script_test_source
from .scaffold import db_stub, endpoints_for_task, route_stub
from .schemas import ArchitectOutput, TaskSpec, topo_order
from .tools import ToolBox

ENGINEERS = ("database", "backend", "frontend")
# The Database engineer tests its own functions; QA owns every other test (generated contract tests and tests/test_qa_*.py).
TEST_GLOBS = {"database": "tests/test_db*.py"}  # backend and frontend are tested by generated contract tests
LOCKED = ["backend/main.py", "backend/__init__.py", "backend/api/__init__.py", "database/__init__.py", "database/connection.py"]
ENGINEER_ITERATIONS = 12
MAX_REPLANS = 1
MAX_REVIEW_ROUNDS = 3  # the first review plus two revisions
MAX_QA_ROUNDS = 3
MAX_BUGS_PER_ROUND = 4


@dataclass
class BuildResult:
    ok: bool
    root: Path | None = None
    slug: str = ""
    tasks: list[dict] = field(default_factory=list)
    tests_passed: bool = False
    test_summary: str = ""
    app_url: str = ""
    problems: list[str] = field(default_factory=list)
    agent_stats: dict = field(default_factory=dict)


class Orchestrator:
    def __init__(
        self,
        goal: str,
        registry: ModelRegistry,
        llm: LLMClient,
        bus: EventBus | None = None,
        mode: str = "supervised",
        approver=None,
        preset: str | None = None,
        base: Path | None = None,
        overrides: dict[str, str] | None = None,
        local_only: bool = True,
        ports: PortManager | None = None,
        agents: dict[str, AgentConfig] | None = None,
        start_app: bool = True,
        consultant: bool = False,
        max_parallel: int = 2,
        review: bool = True,
        qa: bool = True,
        inject_fault: bool = False,
    ):
        self.goal, self.registry, self.llm = goal, registry, llm
        self.bus = bus or EventBus()
        self.mode, self.approver, self.forced_preset, self.base = mode, approver, preset, base
        self.overrides, self.local_only = overrides or {}, local_only
        self.ports, self.start_app, self.consultant = ports, start_app, consultant
        self.max_parallel, self.review, self.qa, self.fault_injection = max(1, max_parallel), review, qa, inject_fault
        self.repo: Repo | None = None
        self.integrator: Integrator | None = None
        self.fault = None
        self.bugs: list[dict] = []
        self._replans = 0
        self._stat_lock = threading.Lock()
        self.agents = agents or load_agents()
        self.emit = self.bus.emit
        self.root: Path | None = None
        self.memory: ProjectMemory | None = None
        self.messages: MessageBus | None = None
        self.stats: dict[str, dict] = {}
        self.problems: list[str] = []
        self.tasks: list[dict] = []
        self.design: ArchitectOutput | None = None
        self.tests_passed, self.test_summary, self.app_url = False, "", ""

    # -- helpers --------------------------------------------------------------------
    def _model(self, agent: AgentConfig) -> ModelConfig:
        mid = self.overrides.get(agent.id) or self.registry.single_model
        m = self.registry.get(mid) if mid else self.registry.default_for(agent.model_capability)
        if self.local_only and not m.local:
            raise AgentFailed(agent.id, f"model {m.id} is a cloud model but this build is local-only")
        if not self.registry.is_available(m.id):
            raise AgentFailed(agent.id, f"model {m.id} is not available")
        return m

    def _stat(self, agent_id: str, model: ModelConfig, iterations: int, pt: int, ct: int, seconds: float = 0.0) -> None:
        with self._stat_lock:
            s = self.stats.setdefault(agent_id, {"model": model.name, "iterations": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0})
            s["iterations"] += iterations
            s["prompt_tokens"] += pt
            s["completion_tokens"] += ct
            s["seconds"] = round(s["seconds"] + seconds, 1)

    def _toolbox(self, agent: AgentConfig, test_cmd: str = "python -m pytest -q", extra_allowed: list[str] | None = None, root: Path | None = None) -> ToolBox:
        """A sandboxed toolbox rooted in `root` (an agent's own worktree) or, by default, the main checkout."""
        assert self.root and self.messages
        return ToolBox(root or self.root, agent, mode=self.mode, approver=self.approver, emit=self.emit, test_cmd=test_cmd,
                       extra_allowed=extra_allowed, message_sink=lambda f, t, text: self.messages.send(f, t, text))  # type: ignore[union-attr]

    def _engineer(self, owner: str) -> AgentConfig:
        a = self.agents[owner]
        return a.model_copy(update={
            "owned_paths": [*a.owned_paths, *([TEST_GLOBS[owner]] if owner in TEST_GLOBS else [])],
            "forbidden_paths": [".q/**", *LOCKED],
            "max_iterations": max(a.max_iterations, ENGINEER_ITERATIONS),
        })

    def _write(self, agent: AgentConfig, path: str, content: str, root: Path | None = None) -> None:
        """Agents write their documents through the same sandboxed tool layer as everyone else."""
        tr = self._toolbox(agent, root=root).execute(Action(thought=f"write {path}", action="write_file", path=path, content=content))
        if not tr.ok:
            raise AgentFailed(agent.id, f"could not write {path}: {tr.output}")

    def _commit(self, message: str) -> None:
        """Commit orchestrator and planning documents on main (serialised with merges)."""
        assert self.repo
        with self.repo.lock:
            self.repo.commit(self.root, message)  # type: ignore[arg-type]

    def _progress(self) -> None:
        total = len(self.tasks)
        done = sum(1 for t in self.tasks if t["status"] == "done")
        self.emit("project_progress", done=done, total=total, percent=round(100 * done / total) if total else 0,
                  tasks={t["id"]: t["status"] for t in self.tasks})

    def _save_tasks(self) -> None:
        assert self.memory
        self.memory.write("tasks.json", json.dumps({"tasks": self.tasks}, indent=2))

    # -- the build ------------------------------------------------------------------
    def run(self) -> BuildResult:
        started = time.time()
        try:
            self._design()
            self._plan()
            self._execute_tasks()
            self._qa_phase()
            self._verify()
        except AgentFailed as e:
            self.problems.append(str(e))
            self.emit("error", agent=e.agent, message=e.reason)
        except Exception as e:  # the demo path must never crash: report and stop cleanly
            self.problems.append(f"internal error: {type(e).__name__}: {e}"[:300])
            self.emit("error", agent="orchestrator", message="the build stopped unexpectedly; see the log")
        return self._finish(time.time() - started)

    def _design(self) -> None:
        arch_agent = self.agents["architect"]
        model = self._model(arch_agent)
        self.emit("agent_state", agent="architect", state="thinking")
        presets = {n: load_preset(n).description for n in list_presets()}
        design, st = run_architect(arch_agent, self.llm, model.id, self.goal, presets, self.emit, self.forced_preset)
        self._stat("architect", model, st["iterations"], st["prompt_tokens"], st["completion_tokens"], st["seconds"])
        self.design = design

        self.root = create_project(self.goal, design.preset, self.base)
        self.repo = Repo(self.root)
        self.memory = ProjectMemory(self.root)
        self.messages = MessageBus(self.memory, self.emit)
        self.emit("project_created", slug=self.root.name, goal=self.goal, preset=design.preset, path=str(self.root))
        ia = self.agents["integrator"]
        self.integrator = Integrator(ia, self.repo, self.llm, self._model(ia).id, self.emit, self.mode, self.approver)
        self.memory.append_decision(f"Architect ({model.name}) chose preset {design.preset}")

        contract = contract_dict(design)
        self._write(arch_agent, ".q/architecture.md", architecture_md(design, self.goal))
        self._write(arch_agent, ".q/api_contract.json", json.dumps(contract, indent=2))
        self._write(arch_agent, ".q/database_schema.md", schema_md(design))
        self.memory.write("design.json", design.model_dump_json(indent=2))
        self.emit("architecture_ready", preset=design.preset, endpoints=len(design.endpoints), tables=len(design.tables))
        self.emit("contract_updated", version=contract["version"], endpoints=[f"{e.method} {e.path}" for e in design.endpoints])
        self._commit("[architect] design and API contract")

    def _plan(self) -> None:
        assert self.memory
        agent = self.agents["planner"]
        model = self._model(agent)
        contract_text = contract_brief(self.memory.contract() or {"version": 1, "endpoints": []})
        schema_text = self.memory.read("database_schema.md")
        plan, st = run_planner(agent, self.llm, model.id, self.goal, contract_text, schema_text, bool(self.design.tables),
                               self.design.endpoints, self.emit)
        self._stat("planner", model, st["iterations"], st["prompt_tokens"], st["completion_tokens"], st["seconds"])
        self.tasks = [{**t.model_dump(), "status": "pending", "summary": "", "attempts": 0} for t in topo_order(plan.tasks)]
        self._write(agent, ".q/tasks.json", json.dumps({"tasks": self.tasks}, indent=2))
        self.emit("plan_created", tasks=[{k: t[k] for k in ("id", "title", "owner", "depends_on", "files")} for t in self.tasks])
        self._commit("[planner] task plan")
        self._progress()

    def _scaffold(self, t: dict, agent: AgentConfig, wt: Path) -> tuple[str, str] | None:
        """Write a contract-derived stub for the task's main file (if it does not exist yet). Returns (path, content)."""
        assert self.memory
        design = self.design or self.memory.design()
        if design is None or not t["files"] or t["owner"] not in ENGINEERS:
            return None
        self._generated_tests(t, design, wt)
        path = t["files"][0]
        if (wt / path).exists():
            return None
        if t["owner"] == "database" and path.endswith(".py"):
            content = db_stub(design)
        elif t["owner"] == "backend" and path.startswith("backend/api/"):
            db_files = sorted(f for f in (wt / "database").glob("*.py") if f.stem not in ("__init__", "connection"))
            db_module = db_files[0].stem if db_files else None
            content = route_stub(design, endpoints_for_task(design, t, sum(1 for x in self.tasks if x["owner"] == "backend")), db_module)
        else:
            return None
        self._write(agent, path, content, root=wt)
        return path, content

    def _generated_tests(self, t: dict, design: ArchitectOutput, wt: Path) -> None:
        """Contract tests are written by the system on QA's behalf (not by a model) the moment the area they test is about to be built."""
        files: dict[str, str] = {}
        if t["owner"] == "backend":
            files["tests/api/test_contract_api.py"] = api_test_source(design)
        elif t["owner"] == "frontend":
            if "static/index.html" in t["files"]:
                files["tests/ui/test_page.py"] = ui_page_test_source(design)
            if "static/app.js" in t["files"]:
                files["tests/ui/test_script.py"] = ui_script_test_source(design)
        for name, source in files.items():
            target = wt / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8", newline="\n")
                self.emit("file_changed", agent="qa", path=name, diff=source, created=True)

    def _task_text(self, t: dict, previous_failure: str = "", stub: tuple[str, str] | None = None) -> str:
        crit = "\n".join(f"- {c}" for c in t["acceptance"])
        if t.get("kind") == "bugfix":
            text = (f"Task {t['id']}: {t['title']}\nQA found bugs in your area. Read each report, open the failing test and the code it exercises, "
                    f"and make the smallest change that fixes the code (the tests are right). Do not rewrite files.\nAcceptance criteria:\n{crit}\n\n{t['bug']}")
        else:
            text = f"Task {t['id']}: {t['title']}\nFiles to create: {', '.join(t['files'])}\nAcceptance criteria:\n{crit}"
        if previous_failure:
            text += (f"\n\nA previous attempt at this area failed ({previous_failure}). Some files may already exist and be partly "
                     "correct: read them first and make the smallest fix instead of starting over.")
        if stub:
            text += (f"\n\nStarting point: `{stub[0]}` already exists. It was generated from the contract and schema, so its names, paths, "
                     f"models, status codes and SQL are correct. Do NOT rewrite the file. Fill each stub function with the `implement` action "
                     f"(path, function name, and only the lines inside the function), one call per function, replacing its `raise NotImplementedError`. "
                     f"Then write the tests. Current content:\n```\n{stub[1]}```")
        return text

    def _context(self, owner: str) -> str:
        assert self.memory and self.messages
        parts = [self.memory.context_for(owner)]
        done = [f"- {t['id']} {t['title']} (files: {', '.join(t['files'])}) - {t['summary']}" for t in self.tasks if t["status"] == "done" and t["files"]]
        if done:
            parts.append("Already built by colleagues:\n" + "\n".join(done))
        inbox = self.messages.inbox(owner)
        if inbox:
            parts.append("Messages for you:\n" + "\n".join(f"- from {m['sender']}: {m['text']}" for m in inbox))
        return "\n\n".join(p for p in parts if p)

    # -- scheduling and execution ---------------------------------------------------
    def _next_ready(self, busy: set[str]) -> dict | None:
        """First pending task whose dependencies are done and whose owner (one worktree each) is free."""
        return next((x for x in self.tasks if x["status"] == "pending" and x["owner"] not in busy
                     and all(self._status(d) == "done" for d in x["depends_on"])), None)

    def _execute_tasks(self) -> None:
        """Run every ready task, up to `max_parallel` at once (never two for the same owner). Results are handled here, on one thread."""
        preset = load_preset(self.design.preset)
        running: dict[Future, dict] = {}
        with ThreadPoolExecutor(max_workers=self.max_parallel, thread_name_prefix="agent") as pool:
            while True:
                busy = {t["owner"] for t in running.values()}
                while len(running) < self.max_parallel:
                    t = self._next_ready(busy)
                    if t is None:
                        break
                    model = self._model(self._engineer(t["owner"]))
                    self._begin(t, model)
                    running[pool.submit(self._work, t, preset, model, None, self._context(t["owner"]))] = t
                    busy.add(t["owner"])
                if not running:
                    break
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for fut in done:
                    t = running.pop(fut)
                    self._handle(t, fut.result(), preset)
                    self._save_tasks()
                    self._progress()

    def _begin(self, t: dict, model: ModelConfig) -> None:
        t["status"], t["attempts"] = "running", t["attempts"] + 1
        self.emit("task_assigned", task=t["id"], title=t["title"], agent=t["owner"], model=model.name, kind=t.get("kind", "feature"))
        self._progress()

    def _handle(self, t: dict, res: AgentResult, preset) -> None:
        if res.status == "finished":
            self._complete(t, res)
            return
        # Escalation ladder: local retry / re-plan, then (opt-in) one visible cloud "senior consultant" attempt.
        t["local_failures"] = t.get("local_failures", 0) + 1
        reason = res.reason or res.status
        feature = t.get("kind", "feature") == "feature"
        if feature and self._replans < MAX_REPLANS and t["attempts"] < 2 and self._replan(t, res):
            self._replans += 1
        elif t["local_failures"] < 2:
            t["status"], t["failure"] = "pending", reason
        elif self.consultant and not t.get("consulted") and self._consult(t, reason, preset):
            pass
        else:
            t["status"] = "failed"
            self.problems.append(f"task {t['id']} ({t['title']}) failed: {reason}")
            self._block_dependents(t["id"])

    def _complete(self, t: dict, res: AgentResult) -> bool:
        """The task's branch is finished and reviewed: the Integrator merges it into main. Returns True when it is merged."""
        assert self.integrator
        merged = self.integrator.merge(t["owner"], t["title"])
        if not merged.ok:
            t["status"] = "failed"
            self.problems.append(f"task {t['id']} ({t['title']}) could not be merged: {merged.reason}")
            self._block_dependents(t["id"])
            return False
        t.update(status="done", summary=res.summary)
        self._after_task(t)
        return True

    def _consultant_model(self, agent: AgentConfig) -> ModelConfig | None:
        cands = [m for m in self.registry.available() if not m.local and agent.model_capability in m.capabilities]
        return cands[0] if cands else None

    def _consult(self, t: dict, reason: str, preset) -> bool:
        """After two local escalations, retry the task once on a cloud model. Always an explicit, logged event.
        Returns True if it handled the task (done or failed), False if no consultant is available."""
        agent = self._engineer(t["owner"])
        cm = self._consultant_model(agent)
        if cm is None:
            return False
        t["consulted"] = True
        self.emit("consultant_called", task=t["id"], title=t["title"], agent=agent.id, model=cm.name, reason=reason,
                  message=f"{agent.name} escalated twice on the local model; asking a senior consultant ({cm.name})")
        self.memory.append_decision(f"Senior consultant ({cm.name}, cloud) called for {t['id']} after two local escalations ({reason})")
        t["failure"] = f"{reason}; two local attempts failed"
        self._begin(t, cm)
        res = self._work(t, preset, cm, f"{agent.id}+consultant", self._context(agent.id))
        ok = res.status == "finished"
        self.emit("consultant_result", task=t["id"], agent=agent.id, model=cm.name, ok=ok, iterations=res.iterations)
        if ok and self._complete(t, res):
            return True
        if t["status"] != "failed":
            t["status"] = "failed"
            self.problems.append(f"task {t['id']} ({t['title']}) failed even with the senior consultant: {res.reason or res.status}")
            self._block_dependents(t["id"])
        return True

    def _status(self, task_id: str) -> str:
        return next((x["status"] for x in self.tasks if x["id"] == task_id), "missing")

    def _block_dependents(self, failed_id: str) -> None:
        changed = True
        while changed:
            changed = False
            for x in self.tasks:
                if x["status"] == "pending" and any(self._status(d) in ("failed", "blocked") for d in x["depends_on"]):
                    x["status"] = "blocked"
                    changed = True

    def _work(self, t: dict, preset, model: ModelConfig, stat_key: str | None, context: str) -> AgentResult:
        """One attempt at a task, in the agent's own worktree (runs in a worker thread): code -> test -> fix, commit, then review."""
        assert self.repo
        agent = self._engineer(t["owner"])
        wt = self.repo.worktree(agent.id)
        self.repo.commit(wt, f"[{agent.id}] work in progress")  # keep a previous attempt's partial work; it is the starting point for this one
        try:
            self.repo.sync(agent.id)
        except GitError as e:
            return AgentResult("error", "sync_failed", summary=str(e))
        tools = self._toolbox(agent, preset.test_cmd, [preset.run_cmd], root=wt)
        stub = self._scaffold(t, agent, wt)
        task_text = self._task_text(t, t.get("failure", ""), stub)
        res = run_agent(agent, task_text, tools, self.llm, model.id, num_ctx=model.num_ctx, context=context, emit=self.emit)
        self._stat(stat_key or agent.id, model, res.iterations, res.prompt_tokens, res.completion_tokens)
        if res.status != "finished":
            return res
        self.repo.commit(wt, f"[{agent.id}] {t['title']}"[:72])
        if self.review and t["owner"] in ENGINEERS:
            res = self._review_loop(t, agent, res, wt, model, preset, task_text, context)
        return res

    # -- review ---------------------------------------------------------------------
    def _review_loop(self, t: dict, agent: AgentConfig, res: AgentResult, wt: Path, model: ModelConfig, preset, task_text: str, context: str) -> AgentResult:
        """The Reviewer checks the branch diff; REQUEST_CHANGES goes back to the engineer, up to MAX_REVIEW_ROUNDS reviews."""
        assert self.repo and self.memory and self.messages
        reviewer = self.agents["reviewer"]
        rmodel = self._model(reviewer)
        for rnd in range(1, MAX_REVIEW_ROUNDS + 1):
            self.emit("agent_state", agent=reviewer.id, state="reading")
            files = {}
            for rel in self.repo.changed_files(agent.id):
                p = wt / rel
                if p.is_file():
                    files[rel] = p.read_text(encoding="utf-8", errors="replace")
            review, st = run_review(reviewer, self.llm, rmodel.id, t, self.repo.diff_vs_main(agent.id),
                                    static_findings(files) + missing_tests(files, t["owner"]), self.emit)
            self._stat("reviewer", rmodel, st["iterations"], st["prompt_tokens"], st["completion_tokens"], st["seconds"])
            self._write(reviewer, f".q/reviews/{t['id']}-r{rnd}.md", review_markdown(t, review, rnd))
            self.emit("review_result", agent=reviewer.id, task=t["id"], round=rnd, verdict=review.verdict, summary=review.summary,
                      items=[i.model_dump() for i in review.items])
            if review.verdict == "PASS":
                self.emit("agent_state", agent=reviewer.id, state="idle")
                return res
            if rnd == MAX_REVIEW_ROUNDS:
                break
            self.messages.send(reviewer.id, agent.id, "Review requested changes: " + "; ".join(f"{i.file}: {i.problem}" for i in review.items))
            asked = "\n".join(f"- {i.file}: {i.problem}" for i in review.items)
            fix = (f"{task_text}\n\nYour work was reviewed and the reviewer requested changes. Address EVERY item with the smallest change, "
                   f"then run_tests again:\n{asked}")
            tools = self._toolbox(agent, preset.test_cmd, [preset.run_cmd], root=wt)
            res = run_agent(agent, fix, tools, self.llm, model.id, num_ctx=model.num_ctx, context=context, emit=self.emit)
            self._stat(agent.id, model, res.iterations, res.prompt_tokens, res.completion_tokens)
            if res.status != "finished":
                return res
            self.repo.commit(wt, f"[{agent.id}] address review ({t['id']})"[:72])
        # Still not clean after the last round: a human decides (autonomous mode accepts the work and records it).
        asked = "; ".join(f"{i.file}: {i.problem}" for i in review.items)[:300]
        self.emit("escalation", agent=reviewer.id, task=t["id"], reason="review_unresolved", detail=asked, iterations=MAX_REVIEW_ROUNDS, recent=[])
        approved = self.mode == "autonomous" or bool(self.approver and self.approver(reviewer.id, "review_unresolved", f"merge {t['id']} with open review items", {"items": asked}))
        self.memory.append_decision(f"{t['id']} merged with open review items ({asked})" if approved else f"{t['id']} blocked by unresolved review items ({asked})")
        if approved:
            return res
        return AgentResult("escalated", "review_unresolved", summary=asked, iterations=res.iterations)

    # -- QA -------------------------------------------------------------------------
    def _qa_phase(self) -> None:
        """QA writes extra tests, the suite runs on main, and every failure becomes a bug routed to its owner, fixed, reviewed, merged, re-tested."""
        if not self.qa or not self.root or any(t["status"] in ("failed", "blocked") for t in self.tasks):
            return
        qa = self.agents["qa"]
        self._qa_tests()
        if self.fault_injection:
            self._inject()
        self.emit("agent_state", agent=qa.id, state="testing")
        for rnd in range(1, MAX_QA_ROUNDS + 1):
            passed, summary, out = run_suite(self.root)
            failures = parse_failures(out)
            self.emit("test_result", agent=qa.id, passed=passed, failed=[f.test_id for f in failures], summary=summary, signature="", round=rnd)
            if passed:
                self._mark_bugs("fixed")
                break
            if rnd == MAX_QA_ROUNDS or not failures:
                self.problems.append(f"QA: tests still failing after {rnd} round(s): {summary}")
                break
            if not self._file_bugs(failures[:MAX_BUGS_PER_ROUND]):
                break
            self._execute_tasks()
        self.emit("agent_state", agent=qa.id, state="idle")

    def _qa_tests(self) -> None:
        """QA adds its edge-case suite (generated from the contract, written through QA's own sandboxed toolbox in QA's worktree) and the Integrator merges it."""
        assert self.repo and self.integrator
        qa = self.agents["qa"]
        source = edge_test_source(self.design)
        if "def test_" not in source:
            return
        task = {"id": "q1", "title": "Edge-case tests from the contract", "owner": "qa", "depends_on": [], "files": ["tests/qa/test_edge_cases.py"],
                "acceptance": [], "status": "running", "summary": "", "attempts": 1, "kind": "qa"}
        self.tasks.append(task)
        self.emit("task_assigned", task="q1", title=task["title"], agent="qa", model="generated", kind="qa")
        self._progress()
        self.emit("agent_state", agent=qa.id, state="typing")
        wt = self.repo.worktree(qa.id)
        self.repo.sync(qa.id)
        self._write(qa, "tests/qa/test_edge_cases.py", source, root=wt)
        self.emit("file_changed", agent=qa.id, path="tests/qa/test_edge_cases.py", diff=source, created=True)
        self.repo.commit(wt, "[qa] edge-case tests from the contract")
        merged = self.integrator.merge(qa.id, task["title"])
        if merged.ok:
            task.update(status="done", summary="edge-case tests merged")
        else:
            task["status"] = "failed"
            self.problems.append(f"QA edge-case tests could not be merged: {merged.reason}")
        self._save_tasks()
        self._progress()

    def _inject(self) -> None:
        assert self.root and self.memory
        self.fault = inject_fault(self.root)
        if self.fault is None:
            self.emit("fault_injected", ok=False, message="no detectable fault could be injected")
            return
        self.memory.append_decision(f"Fault injected for the QA proof: {self.fault.file} - {self.fault.description}")
        self.emit("fault_injected", ok=True, file=self.fault.file, description=self.fault.description, owner=self.fault.owner,
                  message=f"deliberate bug injected into {self.fault.file} ({self.fault.description})")

    def _file_bugs(self, failures: list[Failure]) -> int:
        """Triage each failure, write `.q/bugs/NNN-*.md`, message the owner, and create one fix task per owner. Returns the number of tasks created."""
        assert self.memory and self.messages
        qa = self.agents["qa"]
        model = self._model(qa)
        contract = contract_brief(self.memory.contract() or {"version": 1, "endpoints": []})
        by_owner: dict[str, list[tuple[int, str]]] = {}
        for f in failures:
            triage, st = triage_or_fallback(qa, self.llm, model.id, f, contract, self.emit)
            self._stat("qa", model, st["iterations"], st["prompt_tokens"], st["completion_tokens"], st["seconds"])
            bug_id = len(self.bugs) + 1
            text = bug_markdown(bug_id, f, triage)
            slug = "".join(c if c.isalnum() else "-" for c in triage.title.lower()).strip("-")[:30] or "bug"
            path = f".q/bugs/{bug_id:03d}-{slug}.md"
            self._write(qa, path, text)
            owner = triage.owner
            self.bugs.append({"id": bug_id, "path": path, "owner": owner, "test": f.test_id, "title": triage.title, "failure": f, "triage": triage})
            self.emit("bug_filed", agent=qa.id, bug=bug_id, owner=owner, title=triage.title, test=f.test_id, verdict=triage.verdict, path=path)
            self.messages.send(qa.id, owner, f"Bug {bug_id:03d}: {triage.title}. See {path}. Failing test: {f.test_id}.")
            by_owner.setdefault(owner, []).append((bug_id, text))
        n = 0
        for owner, items in by_owner.items():
            ids = ", ".join(f"{i:03d}" for i, _ in items)
            task = {"title": f"Fix bug {ids}", "files": [], "kind": "bugfix", "acceptance": ["the failing test(s) listed in the report pass", "run_tests passes"]}
            task.update(id=f"b{items[0][0]}", owner=owner, depends_on=[], status="pending", summary="", attempts=0, bug="\n\n".join(t for _, t in items))
            self.tasks.append(task)
            n += 1
        self.emit("plan_created", tasks=[{k: x[k] for k in ("id", "title", "owner", "depends_on", "files")} for x in self.tasks], replan=True, reason="bugs")
        self._save_tasks()
        self._progress()
        return n

    def _mark_bugs(self, status: str) -> None:
        for b in self.bugs:
            if b.get("status") == status:
                continue
            try:
                self._write(self.agents["qa"], b["path"], bug_markdown(b["id"], b["failure"], b["triage"], status))
            except AgentFailed:
                continue
            b["status"] = status
            self.emit("bug_fixed" if status == "fixed" else "bug_updated", agent="qa", bug=b["id"], owner=b["owner"], title=b["title"])
        self._commit("[qa] bug reports")

    def _replan(self, t: dict, res: AgentResult) -> bool:
        """Hand a failed task back to the Planner for a narrower split. Returns True if the plan was changed."""
        assert self.memory
        agent = self.agents["planner"]
        reason = res.reason or res.status
        try:
            model = self._model(agent)
            next_id = max(int(x["id"][1:]) for x in self.tasks) + 1
            plan, st = run_replanner(agent, self.llm, model.id, self.goal, {k: t[k] for k in ("id", "title", "owner", "depends_on", "files", "acceptance")},
                                     reason, [res.last_test["summary"]] if res.last_test else [], contract_brief(self.memory.contract() or {"version": 1, "endpoints": []}),
                                     self.memory.read("database_schema.md"), next_id, bool(self.design.tables), self.emit)
        except AgentFailed:
            return False
        self._stat("planner", model, st["iterations"], st["prompt_tokens"], st["completion_tokens"], st["seconds"])
        new = [{**x.model_dump(), "status": "pending", "summary": "", "attempts": 1, "local_failures": t.get("local_failures", 0), "failure": f"{reason}; the previous attempt did: {res.summary or 'see the files'}"}
               for x in topo_order(plan.tasks)]
        ids = [x["id"] for x in new]
        last = ids[-1]
        idx = self.tasks.index(t)
        self.tasks[idx:idx + 1] = new
        for x in self.tasks:  # whatever waited for the failed task now waits for the last replacement
            x["depends_on"] = [last if d == t["id"] else d for d in x["depends_on"]]
        self.memory.append_decision(f"Planner re-planned {t['id']} after failure ({reason}) into {', '.join(ids)}")
        self.emit("plan_created", tasks=[{k: x[k] for k in ("id", "title", "owner", "depends_on", "files")} for x in self.tasks], replan=True)
        return True

    # -- messages and contract amendments -------------------------------------------
    def _after_task(self, t: dict) -> None:
        assert self.messages and self.memory
        for m in self.messages.inbox("architect"):
            self._amend(m["sender"], m["text"])

    def _amend(self, sender: str, request: str) -> None:
        assert self.memory and self.messages
        agent = self.agents["architect"]
        try:
            model = self._model(agent)
            decision, st = run_amendment(agent, self.llm, model.id, request, sender, contract_brief(self.memory.contract() or {}), self.emit)
        except AgentFailed as e:
            self.problems.append(f"contract change requested by {sender} could not be decided: {e.reason}")
            return
        self._stat("architect", model, st["iterations"], st["prompt_tokens"], st["completion_tokens"], st["seconds"])
        if not decision.approve:
            self.messages.send("architect", sender, f"Contract change denied: {decision.reason}")
            return
        if self.mode != "autonomous" and not (self.approver and self.approver("architect", "contract_change", f"change the API contract: {request[:80]}", {"reason": decision.reason})):
            self.messages.send("architect", sender, "Contract change was not approved by the human; keep the current contract.")
            return
        old = self.memory.contract() or {"version": 1}
        self.design.endpoints = decision.endpoints
        contract = contract_dict(self.design, old["version"] + 1)
        self._write(agent, ".q/api_contract.json", json.dumps(contract, indent=2))
        self._write(agent, ".q/architecture.md", architecture_md(self.design, self.goal))
        self.memory.append_decision(f"Contract v{contract['version']}: {decision.reason}")
        for who in ("backend", "frontend"):
            self.messages.send("architect", who, f"The API contract is now v{contract['version']} ({decision.reason}). Re-read .q/api_contract.json.")
        self.emit("contract_updated", version=contract["version"], endpoints=[f"{e['method']} {e['path']}" for e in contract["endpoints"]])
        self._commit(f"[architect] contract v{contract['version']}")

    # -- verification ---------------------------------------------------------------
    def _verify(self) -> None:
        assert self.root
        preset = load_preset(self.design.preset)
        check = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=self.root, capture_output=True, text=True, encoding="utf-8", errors="replace")
        lines = [l for l in check.stdout.strip().splitlines() if l.strip()]
        self.test_summary = lines[-1] if lines else check.stderr[-200:]
        self.tests_passed = check.returncode == 0
        self.emit("test_result", agent="orchestrator", passed=self.tests_passed, failed=[], summary=self.test_summary, signature="")
        js = self.root / "static" / "app.js"
        if shutil.which("node") and js.is_file():
            syntax = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
            if syntax.returncode != 0:
                self.problems.append("static/app.js has a JavaScript syntax error: " + syntax.stderr.strip().splitlines()[0][:160])
        if not self.tests_passed:
            self.problems.append(f"final test run failed: {self.test_summary}")
            return
        self._commit("Final build")
        if self.start_app:
            ports = self.ports or PortManager()
            self.ports = ports
            try:
                app = ports.start(self.root.name, self.root, preset.run_cmd, preset.health_path)
                self.app_url = app.url
                self.emit("app_running", url=app.url, port=app.port, project=self.root.name)
            except PortError as e:
                self.problems.append(f"the app did not start: {e}")

    def _finish(self, seconds: float) -> BuildResult:
        ok = bool(self.root) and not self.problems and self.tests_passed and all(t["status"] in ("done", "skipped") for t in self.tasks) and bool(self.tasks)
        if self.memory:
            self.memory.write("agents.json", json.dumps(self.stats, indent=2))
            self.memory.write(f"history/build-{int(time.time())}.json", json.dumps(
                {"goal": self.goal, "ok": ok, "seconds": round(seconds), "problems": self.problems, "tasks": self.tasks, "stats": self.stats}, indent=2))
            self.memory.write(f"history/events-{int(time.time())}.jsonl", "\n".join(json.dumps(e, default=str) for e in self.bus.history))
            if self.repo:
                self.memory.write("history/git-graph.json", json.dumps(self.repo.graph(), indent=1))
                self.memory.write("history/bugs.json", json.dumps([{k: b[k] for k in ("id", "path", "owner", "test", "title", "status") if k in b} for b in self.bugs], indent=1))
            try:
                self._commit("[q] build record")
            except RuntimeError:
                pass
        self.emit("project_done", ok=ok, seconds=round(seconds), problems=self.problems, app_url=self.app_url)
        return BuildResult(ok, self.root, self.root.name if self.root else "", self.tasks, self.tests_passed, self.test_summary,
                           self.app_url, self.problems, self.stats)
