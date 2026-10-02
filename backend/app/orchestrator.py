"""The orchestrator: Architect -> Planner -> engineers (sequential in P2) -> verification.

It owns the workflow and the shared project memory; every agent step emits events.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .agent.actions import Action
from .agent.loop import AgentResult, run_agent
from .agent.planning import AgentFailed, run_amendment, run_architect, run_planner, run_replanner
from .config import AgentConfig, load_agents
from .events import EventBus
from .llm import LLMClient
from .memory import MessageBus, ProjectMemory, architecture_md, contract_brief, contract_dict, schema_md
from .ports import PortError, PortManager
from .presets import DEFAULT_PRESET, list_presets, load_preset
from .project import create_project, git
from .registry import ModelConfig, ModelRegistry
from .contract_tests import api_test_source, ui_test_source
from .scaffold import db_stub, endpoints_for_task, route_stub
from .schemas import ArchitectOutput, TaskSpec, topo_order
from .tools import ToolBox

ENGINEERS = ("database", "backend", "frontend")
# P2: engineers write their own tests, one prefix each. In P3 the QA agent takes over `tests/**`.
TEST_GLOBS = {"database": "tests/test_db*.py"}  # backend and frontend are tested by generated contract tests
LOCKED = ["backend/main.py", "backend/__init__.py", "backend/api/__init__.py", "database/__init__.py", "database/connection.py"]
ENGINEER_ITERATIONS = 12
MAX_REPLANS = 1


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
    ):
        self.goal, self.registry, self.llm = goal, registry, llm
        self.bus = bus or EventBus()
        self.mode, self.approver, self.forced_preset, self.base = mode, approver, preset, base
        self.overrides, self.local_only = overrides or {}, local_only
        self.ports, self.start_app, self.consultant = ports, start_app, consultant
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
        s = self.stats.setdefault(agent_id, {"model": model.name, "iterations": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0})
        s["iterations"] += iterations
        s["prompt_tokens"] += pt
        s["completion_tokens"] += ct
        s["seconds"] = round(s["seconds"] + seconds, 1)

    def _toolbox(self, agent: AgentConfig, test_cmd: str = "python -m pytest -q", extra_allowed: list[str] | None = None) -> ToolBox:
        assert self.root and self.messages
        return ToolBox(self.root, agent, mode=self.mode, approver=self.approver, emit=self.emit, test_cmd=test_cmd,
                       extra_allowed=extra_allowed, message_sink=lambda f, t, text: self.messages.send(f, t, text))  # type: ignore[union-attr]

    def _engineer(self, owner: str) -> AgentConfig:
        a = self.agents[owner]
        return a.model_copy(update={
            "owned_paths": [*a.owned_paths, *([TEST_GLOBS[owner]] if owner in TEST_GLOBS else [])],
            "forbidden_paths": [".q/**", *LOCKED],
            "max_iterations": max(a.max_iterations, ENGINEER_ITERATIONS),
        })

    def _write(self, agent: AgentConfig, path: str, content: str) -> None:
        """Planning agents write their documents through the same sandboxed tool layer as everyone else."""
        tr = self._toolbox(agent).execute(Action(thought=f"write {path}", action="write_file", path=path, content=content))
        if not tr.ok:
            raise AgentFailed(agent.id, f"could not write {path}: {tr.output}")

    def _commit(self, message: str) -> None:
        assert self.root
        git(self.root, "add", "-A")
        if git(self.root, "status", "--porcelain").strip():
            git(self.root, "commit", "-m", message)

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
        self.memory = ProjectMemory(self.root)
        self.messages = MessageBus(self.memory, self.emit)
        self.emit("project_created", slug=self.root.name, goal=self.goal, preset=design.preset, path=str(self.root))
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

    def _scaffold(self, t: dict, agent: AgentConfig) -> tuple[str, str] | None:
        """Write a contract-derived stub for the task's main file (if it does not exist yet). Returns (path, content)."""
        assert self.root and self.memory
        design = self.design or self.memory.design()
        if design is None or not t["files"]:
            return None
        self._generated_tests(t, design)
        path = t["files"][0]
        if (self.root / path).exists():
            return None
        if t["owner"] == "database" and path.endswith(".py"):
            content = db_stub(design)
        elif t["owner"] == "backend" and path.startswith("backend/api/"):
            db_files = sorted(f for f in (self.root / "database").glob("*.py") if f.stem not in ("__init__", "connection"))
            db_module = db_files[0].stem if db_files else None
            content = route_stub(design, endpoints_for_task(design, t, sum(1 for x in self.tasks if x["owner"] == "backend")), db_module)
        else:
            return None
        self._write(agent, path, content)
        return path, content

    def _generated_tests(self, t: dict, design: ArchitectOutput) -> None:
        """Contract tests are written by the system (not by a model) the moment the area they test is about to be built."""
        assert self.root
        if t["owner"] == "backend":
            name, source = "tests/test_contract_api.py", api_test_source(design)
        elif t["owner"] == "frontend" and "static/app.js" in t["files"]:
            name, source = "tests/test_contract_ui.py", ui_test_source(design)
        else:
            return
        target = self.root / name
        if not target.exists():
            target.write_text(source, encoding="utf-8", newline="\n")
            self.emit("file_changed", agent="orchestrator", path=name, diff=source, created=True)

    def _task_text(self, t: dict, previous_failure: str = "", stub: tuple[str, str] | None = None) -> str:
        crit = "\n".join(f"- {c}" for c in t["acceptance"])
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
        done = [f"- {t['id']} {t['title']} (files: {', '.join(t['files'])}) - {t['summary']}" for t in self.tasks if t["status"] == "done"]
        if done:
            parts.append("Already built by colleagues:\n" + "\n".join(done))
        inbox = self.messages.inbox(owner)
        if inbox:
            parts.append("Messages for you:\n" + "\n".join(f"- from {m['sender']}: {m['text']}" for m in inbox))
        return "\n\n".join(p for p in parts if p)

    def _execute_tasks(self) -> None:
        preset = load_preset(self.design.preset)
        replans = 0
        while True:
            t = next((x for x in self.tasks if x["status"] == "pending" and all(self._status(d) == "done" for d in x["depends_on"])), None)
            if t is None:
                break
            res = self._run_task(t, preset)
            if res.status == "finished":
                self._complete(t, res)
            else:
                # Escalation ladder: local retry / re-plan, then (opt-in) one visible cloud "senior consultant" attempt.
                t["local_failures"] = t.get("local_failures", 0) + 1
                reason = res.reason or res.status
                if replans < MAX_REPLANS and t["attempts"] < 2 and self._replan(t, res):
                    replans += 1
                elif t["local_failures"] < 2:
                    t["status"], t["failure"] = "pending", reason
                elif self.consultant and not t.get("consulted") and self._consult(t, reason, preset):
                    pass
                else:
                    t["status"] = "failed"
                    self.problems.append(f"task {t['id']} ({t['title']}) failed: {reason}")
                    self._block_dependents(t["id"])
            self._save_tasks()
            self._progress()

    def _complete(self, t: dict, res: AgentResult) -> None:
        t.update(status="done", summary=res.summary)
        self._commit(f"[{t['owner']}] {t['title']}"[:72])
        self._after_task(t)

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
        res = self._run_task(t, preset, model=cm, stat_key=f"{agent.id}+consultant")
        ok = res.status == "finished"
        self.emit("consultant_result", task=t["id"], agent=agent.id, model=cm.name, ok=ok, iterations=res.iterations)
        if ok:
            self._complete(t, res)
        else:
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

    def _run_task(self, t: dict, preset, model: ModelConfig | None = None, stat_key: str | None = None) -> AgentResult:
        agent = self._engineer(t["owner"])
        model = model or self._model(agent)
        t["status"], t["attempts"] = "running", t["attempts"] + 1
        self.emit("task_assigned", task=t["id"], title=t["title"], agent=agent.id, model=model.name)
        self._progress()
        tools = self._toolbox(agent, preset.test_cmd, [preset.run_cmd])
        stub = self._scaffold(t, agent)
        res = run_agent(agent, self._task_text(t, t.get("failure", ""), stub), tools, self.llm, model.id, num_ctx=model.num_ctx,
                        context=self._context(agent.id), emit=self.emit)
        self._stat(stat_key or agent.id, model, res.iterations, res.prompt_tokens, res.completion_tokens)
        return res

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
        ok = bool(self.root) and not self.problems and self.tests_passed and all(t["status"] == "done" for t in self.tasks) and bool(self.tasks)
        if self.memory:
            self.memory.write("agents.json", json.dumps(self.stats, indent=2))
            self.memory.write(f"history/build-{int(time.time())}.json", json.dumps(
                {"goal": self.goal, "ok": ok, "seconds": round(seconds), "problems": self.problems, "tasks": self.tasks, "stats": self.stats}, indent=2))
            self.memory.write(f"history/events-{int(time.time())}.jsonl", "\n".join(json.dumps(e, default=str) for e in self.bus.history))
            try:
                self._commit("[q] build record")
            except RuntimeError:
                pass
        self.emit("project_done", ok=ok, seconds=round(seconds), problems=self.problems, app_url=self.app_url)
        return BuildResult(ok, self.root, self.root.name if self.root else "", self.tasks, self.tests_passed, self.test_summary,
                           self.app_url, self.problems, self.stats)
