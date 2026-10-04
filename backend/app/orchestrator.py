"""The orchestrator: Architect -> Planner -> engineers (parallel, one git worktree each) -> Reviewer -> Integrator -> QA -> verification.

It owns the workflow and the shared project memory; every agent step emits events. Engineers run in worker threads;
all task bookkeeping (status, re-plans, merges into main) happens on the orchestrator's own thread.
"""
from __future__ import annotations

import ast
import json
import re
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
from .agent.planning import AgentFailed, run_amendment, run_architect, run_planner, run_replanner, run_spec
from . import authorship
from .agent.qa import Failure, bug_markdown, parse_failures, triage_or_fallback
from .agent.review import ReviewOutput, missing_tests, review_markdown, run_review, static_findings
from .approvals import request_approval
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
from .relations import plan_for_relations, resource_for_file, synthesize_design
from .look import choose_look
from .platforms import brand_name, generic_spec, mark_small_version, match_platform
from .scope import classify_goal
from .relation_tests import db_test_source
from .uistub import is_placeholder, page_stub, script_stub
from .schemas import ArchitectOutput, SpecOutput, TaskSpec, add_spec_features, check_architecture, check_plan, is_relational, normalize_plan, normalize_spec, spec_text, topo_order
from .tools import ToolBox

ENGINEERS = ("database", "backend", "frontend")
# The Database engineer tests its own functions; QA owns every other test (generated contract tests and tests/test_qa_*.py).
TEST_GLOBS = {"database": "tests/test_db*.py"}  # backend and frontend are tested by generated contract tests
LOCKED = ["backend/main.py", "backend/__init__.py", "backend/api/__init__.py", "database/__init__.py", "database/connection.py",
          "backend/validation.py", "static/ui-kit.css", "static/ui-kit.js"]
ENGINEER_ITERATIONS = 12
MAX_REPLANS = 1
MAX_REVIEW_ROUNDS = 3  # the first review plus two revisions
MAX_QA_ROUNDS = 3
MAX_BUGS_PER_ROUND = 4
POLISH_FILES = ["static/index.html", "static/app.js", "static/style.css"]


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
        polish: bool = False,
        fast_live: bool = False,
        router=None,
    ):
        self.goal, self.registry, self.llm = goal, registry, llm
        self.bus = bus or EventBus()
        self.mode, self.approver, self.forced_preset, self.base = mode, approver, preset, base
        self.overrides, self.local_only = overrides if overrides is not None else {}, local_only  # the UI keeps a handle on this dict
        self.ports, self.start_app, self.consultant = ports, start_app, consultant
        self.max_parallel, self.review, self.qa, self.fault_injection = max(1, max_parallel), review, qa, inject_fault
        self.polish = polish
        self.fast_live = fast_live  # live-demo speed: no polish when the page already uses the UI kit, one LLM review round per task
        self.router = router  # picks a model per employee from the benchmark scores (None: the registry's capability default)
        self.finished = False
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
        self.spec: SpecOutput | None = None
        self.tests_passed, self.test_summary, self.app_url = False, "", ""
        self.generated: dict[str, str] = {}  # app files the rules wrote (stubs, the generated page): the reference for "who wrote the code"
        self.repaired: set[str] = set()  # files the contract repair rewrote
        self.authorship: dict = {}
        self.known_platform = False  # the spec came from the platform table (platforms.py), not from the model
        self.brand: str | None = None  # a product name that is not in the table

    # -- helpers --------------------------------------------------------------------
    def _model(self, agent: AgentConfig) -> ModelConfig:
        mid = self.overrides.get(agent.id)
        if mid:
            m = self.registry.get(mid)
        elif self.router is not None:
            m = self.router.choose(agent.id, agent.model_capability, local_only=self.local_only).model
        else:
            m = self.registry.default_for(agent.model_capability)
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
        return ToolBox(root or self.root, agent, mode=lambda: self.mode, approver=self.approver, emit=self.emit, test_cmd=test_cmd,
                       extra_allowed=extra_allowed, message_sink=lambda f, t, text: self.messages.send(f, t, text))  # type: ignore[union-attr]

    def _engineer(self, owner: str) -> AgentConfig:
        a = self.agents[owner]
        return a.model_copy(update={
            "owned_paths": [*a.owned_paths, *([TEST_GLOBS[owner]] if owner in TEST_GLOBS else [])],
            "forbidden_paths": [".q/**", *LOCKED],
            "max_iterations": max(a.max_iterations, ENGINEER_ITERATIONS + (6 if self.design is not None and self.design.resources else 0)),
        })

    def _write(self, agent: AgentConfig, path: str, content: str, root: Path | None = None) -> None:
        """Agents write their documents through the same sandboxed tool layer as everyone else."""
        tr = self._toolbox(agent, root=root).execute(Action(thought=f"write {path}", action="write_file", path=path, content=content))
        if not tr.ok and not tr.data.get("unchanged"):  # rewriting identical content (a retried review, say) is not an error
            raise AgentFailed(agent.id, f"could not write {path}: {tr.output}")

    def _commit(self, message: str) -> None:
        """Commit orchestrator and planning documents on main (serialised with merges)."""
        assert self.repo
        with self.repo.lock:
            self.repo.commit(self.root, message)  # type: ignore[arg-type]

    def _progress(self) -> None:
        total = len(self.tasks)
        done = sum(1 for t in self.tasks if t["status"] in ("done", "skipped"))  # a skipped optional task (polish) is finished work
        self.emit("project_progress", done=done, total=total, percent=round(100 * done / total) if total else 0,
                  tasks={t["id"]: t["status"] for t in self.tasks})

    def _save_tasks(self) -> None:
        assert self.memory
        self.memory.write("tasks.json", json.dumps({"tasks": self.tasks}, indent=2))

    # -- the build ------------------------------------------------------------------
    def run(self) -> BuildResult:
        started = time.time()
        try:
            scope = classify_goal(self.goal)
            if scope.level == "impossible":  # before any model work: say what Q cannot build, and what it can
                raise AgentFailed("architect", scope.message)
            self._pipeline()
        except AgentFailed as e:
            self.problems.append(str(e))
            self.emit("error", agent=e.agent, message=e.reason)
        except Exception as e:  # the demo path must never crash: report and stop cleanly
            self.problems.append(f"internal error: {type(e).__name__}: {e}"[:300])
            self.emit("error", agent="orchestrator", message="the build stopped unexpectedly; see the log")
        return self._finish(time.time() - started)

    def _pipeline(self) -> None:
        """The team's workflow (the single-agent baseline in baseline.py replaces it)."""
        self._design()
        self._plan()
        self._execute_tasks()
        self._qa_phase()
        self._polish()
        self._verify()

    def _design(self) -> None:
        arch_agent = self.agents["architect"]
        model = self._model(arch_agent)
        self.emit("agent_state", agent="architect", state="thinking")
        presets = {n: load_preset(n).description for n in list_presets()}
        known = match_platform(self.goal)  # a famous app by name: its small version is written down, so it is the same on every run
        self.known_platform = known is not None
        brand = None if known is not None else brand_name(self.goal)  # a product name that is not in the table: see platforms.py
        self.brand = brand
        try:  # goal enrichment is a bonus: if the model cannot produce a valid spec, the Architect designs from the goal alone
            if known is not None:
                self.spec = normalize_spec(known, self.goal)
                self.emit("agent_thought", agent="architect", text=f"{self.spec.title} is a known app: its small version comes from the platform templates", model="rules", tokens=0, seconds=0.0)
            else:
                self.spec, sst = run_spec(arch_agent, self.llm, model.id, self.goal, self.emit)
                normalize_spec(self.spec, self.goal)
                self._stat("architect", model, sst["iterations"], sst["prompt_tokens"], sst["completion_tokens"], sst["seconds"])
                if brand:
                    mark_small_version(self.spec, brand)
            self.emit("spec_ready", title=self.spec.title, summary=self.spec.summary, features=self.spec.features, text=spec_text(self.spec),
                      not_included=self.spec.not_included)
        except AgentFailed:
            self.spec = None
        if self.spec is None and brand:  # the model could not write a spec for a name it does not know: a plain list app, and the page says so
            self.spec = normalize_spec(generic_spec(brand), self.goal)
            self.emit("agent_thought", agent="architect", text=f"I could not make a spec from the name {brand}: building a plain list app and saying so on the page", model="rules", tokens=0, seconds=0.0)
            self.emit("spec_ready", title=self.spec.title, summary=self.spec.summary, features=self.spec.features, text=spec_text(self.spec), not_included=self.spec.not_included)
        self.emit("agent_state", agent="architect", state="thinking")
        if self.spec is not None and (is_relational(self.spec) or known is not None or brand):  # a famous app's (or a named product's) contract is always generated by rules
            try:
                design = self._relational_design(presets)
            except AgentFailed as e:
                if not brand or known is not None:
                    raise
                # the model's guess at an unknown name made a contract that fails the checks (a `type` field without options, say): a plain list app, and the page says so
                self.emit("agent_thought", agent="architect", text=f"The small version I guessed from the name {brand} did not pass the design checks ({e.reason[:120]}): building a plain list app and saying so on the page",
                          model="rules", tokens=0, seconds=0.0)
                self.spec = normalize_spec(generic_spec(brand), self.goal)
                self.emit("spec_ready", title=self.spec.title, summary=self.spec.summary, features=self.spec.features, text=spec_text(self.spec), not_included=self.spec.not_included)
                design = self._relational_design(presets)
        else:
            design, st = run_architect(arch_agent, self.llm, model.id, self.goal, presets, self.emit, self.forced_preset, self.spec)
            self._stat("architect", model, st["iterations"], st["prompt_tokens"], st["completion_tokens"], st["seconds"])
            add_spec_features(design, self.spec)
        self._init_project(design, model)

    def _relational_design(self, presets: dict[str, str]) -> ArchitectOutput:
        """Related resources and actions: the contract follows from the spec by rules (a 7B cannot keep foreign keys, vote counters, nesting and sort consistent)."""
        assert self.spec is not None
        design = synthesize_design(self.spec)
        problems = check_architecture(design, list(presets), self.spec)
        if problems:  # a bug in the templates, never in the model: stop with a clear message instead of building on a broken contract
            raise AgentFailed("architect", "the generated contract is inconsistent: " + "; ".join(problems)[:300])
        names = " and ".join(r.name for r in design.resources)
        self.emit("agent_thought", agent="architect", text=f"Contract for {names} built from the spec: nested lists, vote actions, sort", model="rules", tokens=0, seconds=0.0)
        self.emit("agent_state", agent="architect", state="idle")
        return design

    def _init_project(self, design: ArchitectOutput, model: ModelConfig) -> None:
        """Everything that follows a finished design: the project repo, `.q/` memory, the contract documents (the benchmarks start here too)."""
        arch_agent = self.agents["architect"]
        design.look = choose_look(self.goal, self.spec, design)  # theme, layout, icon and header text by rules: the model never writes a layout
        self.design = design
        self.root = create_project(self.goal, design.preset, self.base)
        self.repo = Repo(self.root)
        self.memory = ProjectMemory(self.root)
        self.messages = MessageBus(self.memory, self.emit)
        self.emit("project_created", slug=self.root.name, goal=self.goal, preset=design.preset, path=str(self.root))
        ia = self.agents["integrator"]
        self.integrator = Integrator(ia, self.repo, self.llm, self._model(ia).id, self.emit, lambda: self.mode, self.approver)
        self.memory.append_decision(f"Architect ({model.name}) chose preset {design.preset}")

        contract = contract_dict(design)
        self._write(arch_agent, ".q/architecture.md", architecture_md(design, self.goal, self.spec))
        if self.spec is not None:
            self._write(arch_agent, ".q/spec.md", spec_text(self.spec))
        self._write(arch_agent, ".q/api_contract.json", json.dumps(contract, indent=2))
        self._write(arch_agent, ".q/database_schema.md", schema_md(design))
        self.memory.write("design.json", design.model_dump_json(indent=2))
        self.emit("architecture_ready", preset=design.preset, endpoints=len(design.endpoints), tables=len(design.tables))
        self.emit("look_chosen", theme=design.look.theme, layout=design.look.layout, icon=design.look.icon)
        self.emit("agent_thought", agent="architect", text=f"Look chosen by rules: {design.look.theme} theme, {design.look.layout} layout, {design.look.icon}", model="rules", tokens=0, seconds=0.0)
        self.emit("contract_updated", version=contract["version"], endpoints=[f"{e.method} {e.path}" for e in design.endpoints])
        self._commit("[architect] design and API contract")

    def _plan(self) -> None:
        assert self.memory
        agent = self.agents["planner"]
        model = self._model(agent)
        contract_text = contract_brief(self.memory.contract() or {"version": 1, "endpoints": []})
        schema_text = self.memory.read("database_schema.md")
        if self.design.resources:  # one task per table and per router follows from the contract
            plan = normalize_plan(plan_for_relations(self.design))
            problems = check_plan(plan, True, self.design.endpoints, len(self.design.tables))
            if problems:
                raise AgentFailed("planner", "the generated plan is inconsistent: " + "; ".join(problems)[:300])
            self.emit("agent_thought", agent="planner", text=f"Plan: {len(plan.tasks)} tasks, one per table and per router", model="rules", tokens=0, seconds=0.0)
            self._adopt_plan(plan.tasks)
            return
        plan, st = run_planner(agent, self.llm, model.id, self.goal, contract_text, schema_text, bool(self.design.tables),
                               self.design.endpoints, self.emit, len(self.design.tables))
        self._stat("planner", model, st["iterations"], st["prompt_tokens"], st["completion_tokens"], st["seconds"])
        self._adopt_plan(plan.tasks)

    def _adopt_plan(self, specs: list[TaskSpec]) -> None:
        agent = self.agents["planner"]
        self.tasks = [{**t.model_dump(), "status": "pending", "summary": "", "attempts": 0} for t in topo_order(specs)]
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
        if t["owner"] == "frontend":
            return self._page_stub(t, agent, wt, design)
        path = t["files"][0]
        if (wt / path).exists():
            return None
        ri = resource_for_file(design, path)  # None for a plain single-resource design
        if t["owner"] == "database" and path.endswith(".py"):
            content = db_stub(design, ri.name if ri else None)
        elif t["owner"] == "backend" and path.startswith("backend/api/"):
            db_files = sorted(f for f in (wt / "database").glob("*.py") if f.stem not in ("__init__", "connection"))
            db_module = ri.name if ri else (db_files[0].stem if db_files else None)
            content = route_stub(design, endpoints_for_task(design, t, sum(1 for x in self.tasks if x["owner"] == "backend")), db_module,
                                 (ri.parent,) if ri and ri.parent else ())
        else:
            return None
        self._write(agent, path, content, root=wt)
        self.generated.setdefault(path, content)
        return path, content

    def _page_stub(self, t: dict, agent: AgentConfig, wt: Path, design: ArchitectOutput) -> tuple[str, str] | None:
        """The starting page for a frontend task, generated from the contract (only over the preset's placeholder, never over somebody's work)."""
        title = self.spec.title if self.spec else ""
        made = {"static/index.html": page_stub(design, title), "static/app.js": script_stub(design, title)}
        written = []
        for path, content in made.items():  # always the pair: a task that lists only index.html would otherwise leave app.js a placeholder it then writes itself
            target = wt / path
            if content is None or (target.exists() and not is_placeholder(target.read_text(encoding="utf-8", errors="replace"))):
                continue
            self._write(agent, path, content, root=wt)
            self.generated.setdefault(path, content)
            written.append((path, content))
        if not written:  # an earlier task (or attempt) already made the page: show its files, so the engineer edits them instead of writing a new script from scratch
            for p in t["files"]:
                if p in made and (wt / p).is_file():
                    text = (wt / p).read_text(encoding="utf-8", errors="replace")
                    if not is_placeholder(text):
                        written.append((p, text))
        if not written:
            return None
        return ", ".join(p for p, _ in written),"\n".join(f"--- {p} ---\n{c}" for p, c in written)

    def _generated_tests(self, t: dict, design: ArchitectOutput, wt: Path) -> None:
        """Contract tests are written by the system on QA's behalf (not by a model) the moment the area they test is about to be built."""
        files: dict[str, str] = {}
        if t["owner"] == "database" and design.resources:  # the data access functions of one table are tested by tests written from the resource model
            ri = resource_for_file(design, t["files"][0]) if t["files"] else None
            if ri is not None:
                files[f"tests/db/test_{ri.name}.py"] = db_test_source(design, ri)
        if t["owner"] == "backend":
            ri = resource_for_file(design, t["files"][0]) if t["files"] else None
            if design.resources and ri:  # one test file per router: a router task sees only its own resource's tests
                files[f"tests/api/test_contract_{ri.name}.py"] = api_test_source(design, ri.name)
            else:
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

    @staticmethod
    def _request_files(owner: str, wt: Path) -> list[Path]:
        """The files a direct request will most likely change, shown in the task text."""
        if owner == "frontend":
            found = [wt / "static" / "index.html", wt / "static" / "app.js"]
        else:
            folder = wt / ("backend/api" if owner == "backend" else "database")
            found = sorted(f for f in folder.glob("*.py") if f.stem not in ("__init__", "connection")) if folder.is_dir() else []
        return [f for f in found if f.is_file()]

    def _db_scope(self, t: dict) -> tuple[str | None, set[str] | None]:
        """For a relational design: the router's own db module (imported as `db`) and the modules it may call (its parent's, imported as `<parent>_db`)."""
        ri = resource_for_file(self.design, t["files"][0]) if self.design and self.design.resources and t.get("files") else None
        return (ri.name, {ri.name, ri.parent}) if ri else (None, None)

    @staticmethod
    def _db_api(wt: Path, own: str | None = None, modules: set[str] | None = None) -> str:
        """The database functions as they exist right now (exact names and parameters), so a backend engineer calls them correctly."""
        lines: list[str] = []
        for f in sorted((wt / "database").glob("*.py")):
            if f.stem in ("__init__", "connection") or (modules is not None and f.stem not in modules):
                continue
            alias = "db" if own is None or f.stem == own else f"{f.stem}_db"
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except (SyntaxError, OSError):
                continue
            for n in tree.body:
                if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"):
                    ret = f" -> {ast.unparse(n.returns)}" if n.returns else ""
                    doc = (ast.get_docstring(n) or "").splitlines()
                    lines.append(f"- {alias}.{n.name}({ast.unparse(n.args)}){ret}" + (f"  # {doc[0]}" if doc else ""))
        return "\n".join(lines)

    def _task_text(self, t: dict, previous_failure: str = "", stub: tuple[str, str] | None = None, db_api: str = "") -> str:
        crit = "\n".join(f"- {c}" for c in t["acceptance"])
        if t.get("kind") == "request":
            text = (f"Task {t['id']}: {t['title']}\nA human on the team asked you directly: {t['request']}\n"
                    f"The request is NOT done yet, even if the app already has something similar and the tests pass: make the change the human described, so it is "
                    f"visible in the app (for example a card or section where they said), with the smallest edit. "
                    + ("Make the change with `replace` (a small edit of an existing file), never by writing the whole file again: one `replace` per edit, and `pattern` is a short text that occurs "
                       "exactly once in the file (copy it from the current content below). The page has two hooks made for requests: the HTML comment `<!-- request-hook:top -->` (the top of the page, "
                       "before the first card) in static/index.html, and the JavaScript comment `// request-hook:loaded` in static/app.js (inside load(), after the list is read; there `data.items` is the whole list). Each hook is one short line, so copy it whole as the pattern. "
                       "To use a hook, replace it with itself followed by your lines (pattern = the hook line, content = the hook line, a new line, then your lines), so the hook stays for the next request. "
                       "A new card, section, bar or label is markup: put it at `<!-- request-hook:top -->` when the human says \"at the top\", and fill it from the items at `// request-hook:loaded`. "
                       "A progress bar is ONE kit call, `UI.progress(document.getElementById('progress'), done, total)` (the label \"N of M done\" is computed; never type the numbers), with done for example `data.items.filter((i) => i.done).length` and total `data.items.length`: "
                       "the kit draws the bar inside an empty `<div id=\"progress\"></div>` that you put in static/index.html. "
                       "If a hook is missing from the file, use `</header>` (index.html) or the line `const data = await res.json();` (app.js, the first one in load()) as the pattern instead. "
                       "If you move something (the total, a counter) to a new place, delete the old one: an id may appear only once on the page. " if t["owner"] == "frontend" else "")
                    + f"Then run_tests. Do not rewrite files. A counter, total or badge you add always has a "
                    f"text label (for example '2 pending', never just '2'); anything you add to a list shows every important field of an item.\nAcceptance criteria:\n{crit}")
        elif t.get("kind") == "bugfix":
            text = (f"Task {t['id']}: {t['title']}\nQA found bugs in your area. Read each report, open the failing test and the code it exercises, "
                    f"and make the smallest change that fixes the code (the tests are right). Do not rewrite files. If you use `implement`, it replaces the "
                    f"WHOLE function body: send the complete body with only the faulty line changed.\nAcceptance criteria:\n{crit}\n\n{t['bug']}")
        elif t.get("kind") == "polish":
            text = (f"Task {t['id']}: {t['title']}\nThe app already works and every test passes. Make it look finished WITHOUT changing behaviour. "
                    "Their current content is below, so do not read them again. Most of the work is in static/app.js: write the complete new app.js with ONE write_file, "
                    "then run_tests, then finish. static/index.html usually already uses the kit: rewrite it only if something from the list is missing (an identical rewrite is refused).\n"
                    "1. Use the UI kit classes from your prompt: each section in a `card`, inputs in `field` / `form-row`, results as `list` / `list-item` or `table`, "
                    "`badge` for status, priority or category, `alert alert-error` for the error box.\n"
                    "2. If the page shows an operation word (add, subtract, multiply, divide), display its symbol with `UI.symbol(word)`; keep the values sent to the API unchanged.\n"
                    "3. Format every number shown on the page with `UI.num(n)` (money amounts with `UI.money(n)`).\n"
                    "4. Show `UI.loading(box)` while data is being fetched and `UI.empty(box, text)` when a list is empty.\n"
                    "5. Call `UI.toast(text, 'success')` after a successful action.\n"
                    "Hard rules: keep every element id, every fetch URL and every request/response key exactly as they are; keep using textContent (never innerHTML); "
                    f"run_tests must still pass.\nAcceptance criteria:\n{crit}")
        else:
            text = f"Task {t['id']}: {t['title']}\nFiles to create: {', '.join(t['files'])}\nAcceptance criteria:\n{crit}"
        if previous_failure:
            text += (f"\n\nA previous attempt at this area failed ({previous_failure}). Some files may already exist and be partly "
                     "correct: read them first and make the smallest fix instead of starting over.")
        if db_api:
            text += ("\n\nThe database functions you can call (EXACT names and parameters; call them as shown, with keyword arguments). Do not invent other "
                     "functions, parameters or exceptions: you cannot change the database module. A function that finds no row returns False or None, so raise the "
                     f"contract's error yourself.\n{db_api}")
        if stub and t["owner"] == "frontend":
            text += (f"\n\nStarting point: {stub[0]} already exist and are a working page generated from the contract: the form, the list with a button for every "
                     "item endpoint, labelled selects and badges, the done checkbox and the filter" + (", vote buttons and a panel that opens an item's child list" if self.design and self.design.resources else "") + ". Do NOT start from scratch. First run_tests. If they pass and the "
                     "acceptance criteria hold, finish. Otherwise change only the lines the failure points to (read the file first, then write the complete corrected file "
                     f"with ONE write_file). Current content:\n```\n{stub[1]}\n```")
        elif stub:
            text += (f"\n\nStarting point: `{stub[0]}` already exists. It was generated from the contract and schema, so its names, paths, "
                     f"models, status codes and SQL are correct. Do NOT rewrite the file. Fill each stub function with the `implement` action "
                     f"(path, function name, and only the lines inside the function), one call per function, replacing its `raise NotImplementedError`. "
                     + (self._relational_steps(t, stub[1]) if self.design and self.design.resources else "Then write the tests. Current content:")
                     + f"\n```\n{stub[1]}```")
        return text

    @staticmethod
    def _relational_steps(t: dict, stub_text: str) -> str:
        """The last lines of a database or router task: which functions, how many times, and what to do after the last one (a 7B otherwise re-implements them in a loop)."""
        names = re.findall(r"^def (\w+)\(", stub_text, re.M)
        what = "the data access functions" if t["owner"] == "database" else "the route functions"
        return (f"There are {len(names)} functions to implement, each ONCE: {', '.join(names)}. The tests for {what} are already written; "
                "after the last function call run_tests, fix only what fails, and when run_tests passes call finish. Current content:")

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
        # Escalation ladder: the contract repair (a generated contract only), local retry / re-plan, then (opt-in) one visible cloud "senior consultant" attempt.
        t["local_failures"] = t.get("local_failures", 0) + 1
        reason = res.reason or res.status
        feature = t.get("kind", "feature") == "feature"
        if feature and self._contract_repair(t, res):
            return
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

    def _contract_repair(self, t: dict, res: AgentResult) -> bool:
        """A database or router task of a generated contract that the engineer could not finish: the functions the contract implies (plain SQL, the route hints)
        are written, and the task counts as done only if every test passes and the Integrator merges it. It is logged as a decision and an event, never silent.
        The 7B misses one function in a few builds (an unknown variable, ORDER BY created_at, SELECT of some columns); a famous app must not die on that."""
        d = self.design
        if not (d and d.resources and self.repo and self.memory and t["owner"] in ("database", "backend") and t["files"] and self.mode != "assisted"):
            return False
        path = t["files"][0]
        ri = resource_for_file(d, path)
        if ri is None or not path.endswith(".py"):
            return False
        agent = self._engineer(t["owner"])
        wt = self.repo.worktree(agent.id)
        if t["owner"] == "database":
            source = db_stub(d, ri.name, fill=True)
        else:
            source = route_stub(d, endpoints_for_task(d, t, sum(1 for x in self.tasks if x["owner"] == "backend")), ri.name, (ri.parent,) if ri.parent else (), fill=True)
        reason = res.reason or res.status
        self.emit("agent_thought", agent=agent.id, text=f"I could not finish {path} ({reason}). Applying the functions the contract implies, then the tests decide.",
                  model="rules", tokens=0, seconds=0.0)
        try:
            self._write(agent, path, source, root=wt)
        except AgentFailed:
            return False
        passed, summary, _ = run_suite(wt)
        if not passed:  # the engineer's own half-written tests can be what fails: only the generated tests count
            for own in wt.glob("tests/test_*.py"):
                own.unlink()
            passed, summary, _ = run_suite(wt)
        if not passed:
            self.emit("contract_repair", task=t["id"], path=path, ok=False, reason=summary)
            return False
        self.generated[path] = source
        self.repaired.add(path)
        self.repo.commit(wt, f"[{agent.id}] {t['title']} (from the contract)"[:72])
        self.memory.append_decision(f"Contract repair: {agent.name} could not finish {path} ({reason}); the functions the contract implies were applied and every test passes")
        self.emit("contract_repair", task=t["id"], path=path, ok=True, reason=reason)
        return self._complete(t, AgentResult("finished", summary=f"{path} from the contract after the engineer escalated ({reason}); {summary}"))

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
        own, modules = self._db_scope(t)
        task_text = self._task_text(t, t.get("failure", ""), stub, self._db_api(wt, own, modules) if t["owner"] == "backend" else "")
        if t.get("kind") == "polish":
            for rel in ("static/index.html", "static/app.js"):
                p = wt / rel
                if p.is_file():
                    task_text += f"\n\nCurrent {rel}:\n```\n{p.read_text(encoding='utf-8')[:5000]}\n```"
        elif t.get("kind") == "request":  # the engineer edits what exists instead of finishing because the tests already pass
            for p in self._request_files(t["owner"], wt):
                task_text += f"\n\nCurrent {p.relative_to(wt).as_posix()}:\n```\n{p.read_text(encoding='utf-8', errors='replace')[:5000]}\n```"
        res = self._generated_page_is_enough(t, stub, wt, agent)
        generated = res is not None  # nobody wrote anything: the page is the one generated from the contract, so there is nothing for an LLM review to judge
        if res is None:
            res = run_agent(agent, task_text, tools, self.llm, model.id, num_ctx=model.num_ctx, context=context, emit=self.emit)
            self._stat(stat_key or agent.id, model, res.iterations, res.prompt_tokens, res.completion_tokens)
        if res.status != "finished":
            return res
        self.repo.commit(wt, f"[{agent.id}] {t['title']}"[:72])
        if t.get("kind") == "polish":
            # The Reviewer's static checks still apply (innerHTML, eval, ...); the LLM review is skipped: it judges polish against generic criteria.
            found = static_findings({rel: (wt / rel).read_text(encoding="utf-8", errors="replace") for rel in self.repo.changed_files(agent.id) if (wt / rel).is_file()})
            if found:
                return AgentResult("escalated", "review_unresolved", summary="; ".join(f"{i.file}: {i.problem}" for i in found)[:300], iterations=res.iterations)
        elif self.review and t["owner"] in ENGINEERS and not generated:  # a 7B reviewer's request to "improve" the generated page made the engineer rewrite it and lose its layout
            res = self._review_loop(t, agent, res, wt, model, preset, task_text, context)
        return res

    def _generated_page_is_enough(self, t: dict, stub, wt: Path, agent: AgentConfig) -> AgentResult | None:
        """A page generated from the contract that already passes every UI test needs no engineer: asked to "finish", a 7B rewrites the page and breaks it
        (two of the first eight related builds), and it would lose the theme and layout that were chosen by rules. The engineer is called only when a test fails."""
        if not (self.design and t["owner"] == "frontend" and stub and t.get("kind", "feature") == "feature"):
            return None
        self.emit("agent_state", agent=agent.id, state="testing")
        passed, summary, _ = run_suite(wt)
        if not passed:
            return None
        text = f"The page generated from the contract already passes every test ({summary}); nothing to change."
        self.emit("agent_thought", agent=agent.id, text=text, model="rules", tokens=0, seconds=0.0)
        self.emit("agent_state", agent=agent.id, state="idle")
        return AgentResult("finished", summary=text)

    # -- review ---------------------------------------------------------------------
    def _review_loop(self, t: dict, agent: AgentConfig, res: AgentResult, wt: Path, model: ModelConfig, preset, task_text: str, context: str) -> AgentResult:
        """The Reviewer checks the branch diff; REQUEST_CHANGES goes back to the engineer, up to MAX_REVIEW_ROUNDS reviews.

        Fast live mode allows ONE LLM review: if it asks for changes, the engineer makes them once and only the automatic (static) checks look at the
        result, so a clean fix is accepted without a second model review while injection/size/test findings still block."""
        assert self.repo and self.memory and self.messages
        reviewer = self.agents["reviewer"]
        rmodel = self._model(reviewer)
        rounds = 1 if self.fast_live else MAX_REVIEW_ROUNDS
        review = None
        for rnd in range(1, rounds + 1):
            self.emit("agent_state", agent=reviewer.id, state="reading")
            review, st = run_review(reviewer, self.llm, rmodel.id, t, self.repo.diff_vs_main(agent.id, skip_generated_tests=True),
                                    self._automatic_findings(agent, wt, t["owner"]), self.emit)
            self._stat("reviewer", rmodel, st["iterations"], st["prompt_tokens"], st["completion_tokens"], st["seconds"])
            self._write(reviewer, f".q/reviews/{t['id']}-r{rnd}.md", review_markdown(t, review, rnd))
            self.emit("review_result", agent=reviewer.id, task=t["id"], round=rnd, verdict=review.verdict, summary=review.summary,
                      items=[i.model_dump() for i in review.items])
            if review.verdict == "PASS":
                self.emit("agent_state", agent=reviewer.id, state="idle")
                return res
            if rnd == rounds and not self.fast_live:
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
            if rnd == rounds:  # fast live mode: no second model review, the automatic checks decide
                left = self._automatic_findings(agent, wt, t["owner"])
                if not left:
                    note = ReviewOutput(verdict="PASS", summary="fast live mode: changes made, automatic checks are clean")
                    self._write(reviewer, f".q/reviews/{t['id']}-r{rnd + 1}.md", review_markdown(t, note, rnd + 1))
                    self.emit("review_result", agent=reviewer.id, task=t["id"], round=rnd + 1, verdict="PASS", summary=note.summary, items=[])
                    self.emit("agent_state", agent=reviewer.id, state="idle")
                    return res
                review = ReviewOutput(verdict="REQUEST_CHANGES", summary="automatic checks still find problems", items=left)
        # Still not clean after the last round: a human decides (autonomous mode accepts the work and records it).
        asked = "; ".join(f"{i.file}: {i.problem}" for i in review.items)[:300]  # type: ignore[union-attr]
        self.emit("escalation", agent=reviewer.id, task=t["id"], reason="review_unresolved", detail=asked, iterations=rounds, recent=[])
        approved = self.mode == "autonomous" or request_approval(self.emit, self.approver, reviewer.id, "review_unresolved",
                                                                 f"merge {t['id']} with open review items", {"items": asked})
        self.memory.append_decision(f"{t['id']} merged with open review items ({asked})" if approved else f"{t['id']} blocked by unresolved review items ({asked})")
        if approved:
            return res
        return AgentResult("escalated", "review_unresolved", summary=asked, iterations=res.iterations)

    def _automatic_findings(self, agent: AgentConfig, wt: Path, owner: str):
        """The Reviewer's deterministic checks on the files this branch changed."""
        assert self.repo
        files = {}
        for rel in self.repo.changed_files(agent.id):
            p = wt / rel
            if p.is_file():
                files[rel] = p.read_text(encoding="utf-8", errors="replace")
        return static_findings(files) + missing_tests(files, owner)

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

    # -- polish ---------------------------------------------------------------------
    def _polish(self) -> None:
        """After QA passed: one extra Frontend task that applies the UI kit (symbols, number formats, empty and loading states).

        It never puts the build at risk: the branch is merged only if the full suite (every contract and QA test) and `node --check` pass in the
        engineer's worktree first. Any failure skips the polish and leaves main exactly as QA left it."""
        if not (self.polish and self.root and self.repo and self.integrator) or self.problems:
            return
        if any(t["status"] in ("failed", "blocked") for t in self.tasks):
            return
        if not (self.root / "static" / "ui-kit.css").is_file() or not (self.root / "static" / "app.js").is_file():
            return
        if self.fast_live and self._uses_ui_kit():
            if self.memory:
                self.memory.append_decision("Polish skipped (fast live mode): the page already uses the UI kit")
            self.emit("polish_result", ok=True, changed=False, reason="", skipped="fast live mode: the page already uses the UI kit")
            return
        preset = load_preset(self.design.preset)
        t = {"id": "p1", "title": "Polish the UI with the UI kit", "owner": "frontend", "depends_on": [], "files": list(POLISH_FILES), "kind": "polish",
             "acceptance": ["the page uses the UI kit components", "numbers are formatted and operation words show symbols",
                            "lists have loading and empty states", "run_tests passes"],
             "status": "pending", "summary": "", "attempts": 0}
        self.tasks.append(t)
        self.emit("plan_created", tasks=[{k: x[k] for k in ("id", "title", "owner", "depends_on", "files")} for x in self.tasks], replan=True, reason="polish")
        summary, changed = "", False
        try:
            model = self._model(self._engineer("frontend"))
            self._begin(t, model)
            res = self._work(t, preset, model, "frontend", self._context("frontend"))
            summary = res.summary
            reason = ((res.reason or res.status) + (f" ({res.summary[:120]})" if res.summary else "")) if res.status != "finished" else ""
            changed = bool(self.repo.changed_files("frontend")) if res.status == "finished" else False
            if res.status != "finished" and res.reason in ("repeated_action", "no_improvement") and not self.repo.changed_files("frontend"):
                reason = ""  # the engineer kept re-sending the file it already had: the page is as polished as it will get
            if not reason and changed:
                reason = self._polish_check(self.repo.worktree("frontend"))
            if not reason and changed:
                merged = self.integrator.merge("frontend", t["title"])
                reason = "" if merged.ok else f"merge failed: {merged.reason}"
        except AgentFailed as e:
            reason = e.reason
        except Exception as e:  # polish is optional: whatever goes wrong, the finished build stays as it is
            reason = f"unexpected error ({type(e).__name__})"
        if reason or not changed:
            self.repo.discard_unmerged("frontend")  # no half-polished edits are left in the worktree for later requests
        if reason:
            t.update(status="skipped", summary=f"polish skipped: {reason}"[:200])
            if self.memory:
                self.memory.append_decision(f"Polish skipped, main unchanged ({reason})")
            self.emit("polish_result", ok=False, reason=reason[:200])
        else:
            t.update(status="done", summary=summary if changed else "the page already uses the UI kit; nothing to change")
            self.emit("polish_result", ok=True, changed=changed, reason="")
        self._save_tasks()
        self._progress()

    def _uses_ui_kit(self) -> bool:
        """The page links the kit and its script already calls at least two kit helpers (loading, empty, num, money, symbol, toast)."""
        assert self.root
        html, js = self.root / "static" / "index.html", self.root / "static" / "app.js"
        try:
            page, script = html.read_text(encoding="utf-8"), js.read_text(encoding="utf-8")
        except OSError:
            return False
        helpers = {h for h in ("loading", "empty", "num", "money", "symbol", "toast", "renderList", "listItem", "renderTable", "renderCards", "renderChecklist", "renderFeed", "statStrip") if f"UI.{h}(" in script}
        return "ui-kit.css" in page and len(helpers) >= 2

    def _polish_check(self, wt: Path) -> str:
        """Empty string when the polished branch is safe to merge, else why not."""
        passed, summary, _ = run_suite(wt)
        if not passed:
            return f"tests failed on the polished branch ({summary})"
        js = wt / "static" / "app.js"
        if shutil.which("node") and js.is_file():
            syntax = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
            if syntax.returncode != 0:
                return "static/app.js has a JavaScript syntax error"
        source = js.read_text(encoding="utf-8") if js.is_file() else ""
        if not any(f"UI.{h}(" in source for h in ("loading", "empty", "num", "money", "symbol", "toast", "renderList", "listItem", "renderTable", "renderCards", "renderChecklist", "renderFeed", "statStrip")):
            return "the polished script does not use any UI kit helper"
        return ""

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

    # -- direct requests from the human (Ask employee) -------------------------------
    def add_request(self, owner: str, text: str) -> dict:
        """Queue a task that only `owner` receives. Picked up by the running scheduler, or by `finish_requests` after the build."""
        if owner not in ENGINEERS:
            raise ValueError("only the engineers can be given build tasks")
        n = 1 + sum(1 for x in self.tasks if x.get("kind") == "request")
        t = {"id": f"r{n}", "title": f"Request: {text[:50]}", "owner": owner, "depends_on": [], "files": [], "kind": "request", "request": text,
             "acceptance": ["the request is done", "run_tests passes"], "status": "pending", "summary": "", "attempts": 0}
        self.tasks.append(t)
        if self.finished:  # the project was complete: it is in progress again until this request is done
            self.finished = False
            self.emit("project_resumed", agent=owner, task=t["id"], message=f"{self.agents[owner].name} is working on a request; the project is in progress again")
        self.emit("plan_created", tasks=[{k: x[k] for k in ("id", "title", "owner", "depends_on", "files")} for x in self.tasks], replan=True, reason="request")
        self._save_tasks()
        self._progress()
        return t

    def finish_requests(self) -> None:
        """Run queued requests on a finished build, then re-verify the whole project and restart the app."""
        started = time.time()
        involved = sorted({t["owner"] for t in self.tasks if t.get("kind") == "request"})
        try:
            self._execute_tasks()
            self.problems = [p for p in self.problems if not p.startswith("final test run failed")]  # re-verified below
            self._verify()
        except AgentFailed as e:
            self.problems.append(str(e))
            self.emit("error", agent=e.agent, message=e.reason)
        except Exception:
            self.problems.append("internal error while handling a request")
            self.emit("error", agent="orchestrator", message="the request stopped unexpectedly; see the log")
        self._save_tasks()
        ok = self.tests_passed and not self.problems and all(t["status"] in ("done", "skipped") for t in self.tasks)
        self.finished = True
        # `involved` lets the office celebrate only the people who did the work; everyone else stays idle.
        self.emit("project_done", ok=ok, seconds=round(time.time() - started), problems=self.problems, app_url=self.app_url, request=True, involved=involved)

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
        if self.mode != "autonomous" and not request_approval(self.emit, self.approver, "architect", "contract_change",
                                                              f"change the API contract: {request[:80]}", {"reason": decision.reason}):
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

    def _provenance(self) -> dict:
        """Which parts of the design came from the model and which from rules (the other half of "who wrote the code")."""
        rules = bool(self.design and self.design.resources)
        return {"spec_by": "platform table" if self.known_platform else ("model" if self.spec else "none"), "contract_by": "rules" if (rules or self.brand) else "model",
                "plan_by": "rules" if rules else "model", "contract_repairs": len(self.repaired)}

    def _measure_authorship(self) -> None:
        if not (self.root and self.design):
            return
        try:
            self.authorship = authorship.measure(self.root, self.generated, self.repaired, self.design.preset, self._provenance())
            authorship.save(self.root, self.authorship)
        except Exception:  # a report problem must never fail a build
            self.authorship = {}

    def _finish(self, seconds: float) -> BuildResult:
        self._measure_authorship()
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
        self.finished = True
        self.emit("project_done", ok=ok, seconds=round(seconds), problems=self.problems, app_url=self.app_url)
        return BuildResult(ok, self.root, self.root.name if self.root else "", self.tasks, self.tests_passed, self.test_summary,
                           self.app_url, self.problems, self.stats)
