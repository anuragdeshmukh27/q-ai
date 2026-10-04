"""Finish my project: import a half-built project and finish its broken ends, on a branch, with the same team.

import -> analyse (rules first, a model for a free-text README) -> gap report and a test for every gap -> the human picks the gaps -> a task per file with gaps ->
the engineers fill only those files (their owned paths) -> the Integrator merges into `q/finish` -> the whole suite runs, a summary diff, "Open app".
The user's own folder is never touched (see importer.py); `q/base` keeps exactly what was imported.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import threading
import time
from pathlib import Path

from pydantic import BaseModel, Field

from ..agent.planning import AgentFailed, structured_step
from ..agent.qa import parse_failures
from ..config import PROMPTS_DIR, WORKSPACE
from ..integrator import Integrator, run_suite
from ..memory import MessageBus, ProjectMemory
from ..orchestrator import Orchestrator
from ..ports import PortError, PortManager
from ..repo import Repo
from ..schemas import ArchitectOutput, TaskSpec
from .analyze import Analysis, Gap, ImportDeclined, analyse, extract_routes, find_app, home_file, matches, project_files, reconstruct_contract, run_command
from .gaptests import gap_tests
from .importer import check, fetch, import_project, scratch_dir
from .stubs import insert, router_of, stub_source

OWNED = {"backend": ["**/*.py"], "frontend": ["**/*.js", "**/*.html", "**/*.css", "**/*.jinja", "**/*.j2", "static/**", "templates/**"], "database": ["**/*.py"]}
FORBIDDEN = [".q/**", "tests/**", "test_*.py", "**/test_*.py", "conftest.py", "**/conftest.py"]
MAX_DIFF = 40_000
MAX_GAP_TASKS = 12


class PlannedFeature(BaseModel):
    title: str
    method: str = "POST"
    path: str
    fields: list[str] = Field(default_factory=list)
    detail: str = ""


class ReadmeFeatures(BaseModel):
    features: list[PlannedFeature] = Field(default_factory=list)


class FinishBuild(Orchestrator):
    STAGES = ("import", "analyse", "pick", "plan", "tasks", "verify")
    LOCAL_ATTEMPTS = 4  # a task is one small gap and a failed attempt costs about 20 s: more fresh starts beat a longer first try with a 7B

    def __init__(self, source: str, registry, llm, bus=None, auto_fix: bool = False, only: list[str] | None = None, **kw):
        kw.update(review=False, qa=False, polish=False)  # the project's own tests and the generated gap tests are the judge; there is no generated design to review against
        name = Path(source.rstrip("/\\")).name.removesuffix(".git") or "project"
        super().__init__(f"Finish the project {name}", registry, llm, bus, **kw)
        self.source, self.auto_fix, self.only = source, auto_fix, only
        self.analysis: Analysis | None = None
        self.gaps: list[Gap] = []
        self.selected: list[str] | None = None
        self._picked = threading.Event()
        self._owned: dict[str, list[str]] = {}
        self._current: dict[str, dict] = {}
        self._trees: dict[str, Path] = {}  # task id -> the worktree it runs in (the task text shows that file, with the placeholders rules added)
        self.design = ArchitectOutput(preset="fastapi-vanilla", architecture="An imported project", endpoints=[])  # only its preset (test command) is used

    # -- the people ---------------------------------------------------------------------
    def _engineer(self, owner: str):
        """The engineer of the current task may change that task's file and the database module, and nothing else: a 7B that is free to roam edits other tasks' files."""
        a = self.agents[owner]
        owned = self._owned.get(owner) or OWNED.get(owner, OWNED["backend"])
        return a.model_copy(update={"owned_paths": owned, "forbidden_paths": FORBIDDEN, "system_prompt_file": "finish.md",
                                    "tools": [t for t in dict.fromkeys([*a.tools, "replace", "implement"]) if not (t == "replace" and owner != "frontend")],  # a 7B loops on `replace` in Python: `implement` is the one edit it does reliably
                                    "max_iterations": max(a.max_iterations, 16)})

    def _begin(self, t: dict, model) -> None:
        files = [*t.get("files", []), *(self.analysis.db_files if self.analysis and t["owner"] == "backend" else [])]
        self._owned[t["owner"]] = list(dict.fromkeys(files))
        self._current[t["owner"]] = t
        super()._begin(t, model)

    def _toolbox(self, agent, test_cmd: str = "python -m pytest -q", extra_allowed=None, root=None):
        """run_tests for an engineer covers the project's own tests and the gap tests of ITS task: the tests of the gaps other tasks will close are left out, or run_tests could never pass."""
        tb = super()._toolbox(agent, self._scoped_tests(agent.id) or test_cmd, extra_allowed, root)
        tb.allow_new_functions = True
        tb.name_hints = self._name_hints(agent.id)
        return tb

    def _name_hints(self, owner: str) -> dict[str, str]:
        """For the names a 7B keeps inventing: what this project does instead (read from the file of the current task)."""
        a, t = self.analysis, self._current.get(owner)
        if not (a and t and t.get("files") and self.root):
            return {}
        path = (self._trees.get(t["id"]) or self.root) / t["files"][0]
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            return {}
        defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        imported = {(x.asname or x.name).split(".")[0] for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) for x in n.names}
        hints: dict[str, str] = {}
        if a.framework == "flask":
            hints["HTTPException"] = 'This is a Flask app: a missing row is `return jsonify(error="... not found"), 404`, with no exception and no import.'
            for name, mod in (("request", "flask"), ("jsonify", "flask"), ("abort", "flask")):
                if name not in imported:
                    hints[name] = f"Make `from {mod} import {name}` the first line of your function body."
        elif a.framework == "fastapi" and "HTTPException" not in imported:
            hints["HTTPException"] = "Make `from fastapi import HTTPException` the first line of your function body."
        helper = next((d for d in sorted(defined) if re.search(r"db|conn|session|engine", d, re.I)), "")
        if helper:
            for name in ("db", "conn", "cursor", "session"):
                if name not in imported and name not in defined:
                    hints[name] = f"This file reaches the database with `{helper}()` (see the example routes above): call that, there is no `{name}`."
        return hints

    def _scoped_tests(self, owner: str) -> str:
        t = self._current.get(owner)
        if not t or not t.get("gaps"):
            return ""
        mine = set(t["gaps"])
        skip = [g for g in self.gaps if g.id not in mine]
        keys = [f"test_{g.id}_" for g in skip if g.kind != "failing_test"]
        cmd = "python -m pytest -q"
        for g in skip:
            if g.kind == "failing_test" and g.test:
                cmd += f" --deselect {g.test}"
        if keys:
            cmd += ' -k "' + " and ".join(f"not {k}" for k in keys) + '"'
        return cmd

    # -- the run ------------------------------------------------------------------------
    def run(self):
        started = time.time()
        try:
            self._pipeline()
        except ImportDeclined as e:
            self.problems.append(str(e))
            self.failed_stage = self.stage
            self.emit("error", agent="architect", message=str(e))
        except AgentFailed as e:
            self.problems.append(str(e))
            self.failed_stage = self.stage
            self.emit("error", agent=e.agent, message=e.reason)
        except Exception as e:  # the demo path must never crash
            self.problems.append(f"internal error: {type(e).__name__}: {e}"[:300])
            self.failed_stage = self.stage
            self.emit("error", agent="orchestrator", message="the build stopped unexpectedly; see the log")
        return self._finish(time.time() - started)

    def _pipeline(self, start: str = "import") -> None:
        steps = {"import": self._import, "analyse": self._analyse, "pick": self._pick, "plan": self._plan_finish, "tasks": self._execute_tasks, "verify": self._verify}
        for name in self.STAGES[self.STAGES.index(start):]:
            if self.stopped.is_set():
                break
            self.stage = name
            steps[name]()

    def _replan(self, t, res) -> bool:  # a gap file is already as narrow as a task gets
        return False

    def _scaffold(self, t, agent, wt):
        """The routes the project is missing (the page calls them, the README promises them) are put into the task's file as placeholder functions by rules, so the engineer
        only fills bodies. Nothing else is generated: the project's own files are the starting point."""
        self._trees[t["id"]] = wt
        if t.get("failure"):  # a retry starts from the integrated version of the files, not from the half-edits of the failed attempt
            owned = [f for f in self._owned.get(t["owner"], []) if (wt / f).exists()]
            if owned:
                subprocess.run(["git", "checkout", self.repo.main, "--", *owned], cwd=wt, capture_output=True)
        a = self.analysis
        if not a or t["owner"] != "backend" or not t.get("files"):
            return None
        file = t["files"][0]
        want = [g for g in self.gaps if g.id in t.get("gaps", []) and g.kind in ("missing_endpoint", "readme_feature") and g.method and g.path]
        path = wt / file
        if not want or not path.is_file():
            return None
        routes = extract_routes(wt, project_files(wt), a.framework)
        todo = [g for g in want if not matches(routes, g.method, g.path)]
        if not todo:
            return None
        source = path.read_text(encoding="utf-8")
        var, prefix = router_of(a.routes, file)
        taken = set(re.findall(r"^\s*(?:async )?def (\w+)\(", source, re.M))
        made = [stub_source(a, g, var, prefix, taken) for g in todo]
        for g, (_, fname) in zip(todo, made):
            g.function = fname  # the placeholder now exists under this name
        new = insert(source, [src for src, _ in made])
        self._write(agent, file, new, root=wt)
        self.emit("agent_thought", agent=agent.id, text=f"I added a placeholder for {', '.join(f'{g.method} {g.path}' for g in todo)} to {file}; now I fill its body.", model="rules", tokens=0, seconds=0.0)
        return None

    def _generated_page_is_enough(self, t, stub, wt, agent):
        return None

    def _strip_strays(self, wt, t) -> None:  # an engineer may add files here (a new module): nothing is "a stray"
        return None

    # -- import -------------------------------------------------------------------------
    def _import(self) -> None:
        self.emit("agent_state", agent="architect", state="reading")
        src = fetch(self.source, scratch_dir())
        framework, files = check(src)
        module, var, _ = find_app(src, files, framework)
        self.root = import_project(src, self.base or WORKSPACE)
        self.repo = Repo(self.root, main="q/finish")
        self.memory = ProjectMemory(self.root)
        self.messages = MessageBus(self.memory, self.emit)
        self.memory.write("goal.md", f"# Goal\n\n{self.goal}\n\nImported from {self.source}. The original is on the branch q/base; the work is on q/finish.\n")
        self.memory.write("decisions.md", "# Decisions\n\n- Imported project: the user's folder is never touched; q/base is the original, q/finish is where the work happens\n")
        ia = self.agents["integrator"]
        self.integrator = Integrator(ia, self.repo, self.llm, self._model(ia).id, self.emit, lambda: self.mode, self.approver)
        self.emit("project_created", slug=self.root.name, goal=self.goal, preset="imported", path=str(self.root), run_cmd=run_command(framework, module, var), health_path="/")
        self.emit("agent_thought", agent="architect", text=f"I copied the project ({len(files)} files, {framework}) to a branch of my own: your folder stays as it is.", model="rules", tokens=0, seconds=0.0)

    # -- analyse ------------------------------------------------------------------------
    def _analyse(self) -> None:
        assert self.root and self.memory
        self.emit("agent_state", agent="architect", state="thinking")
        a = analyse(self.root, run_suite, parse_failures)
        a.run_cmd = a.run_cmd or ""
        self.analysis = a
        if a.readme and not any(g.kind == "readme_feature" for g in a.gaps) and any(w in a.readme.lower() for w in ("planned", "roadmap", "todo", "not yet", "coming soon", "not done", "missing")):
            self._readme_with_the_model(a)
        self.gaps = a.gaps
        contract = reconstruct_contract(a)
        self.memory.write("api_contract.json", json.dumps(contract, indent=2))
        self.memory.write("gap_report.md", self._report_md(a))
        self.memory.append_decision(f"Gap report: {len(a.gaps)} gaps in {len({g.file for g in a.gaps})} files; the contract was reconstructed from the code ({len(contract['endpoints'])} endpoints)")
        tests = gap_tests(a, a.gaps)
        qa = self.agents["qa"]
        self._write(qa, "tests/q_finish/test_gaps.py", tests, root=self.root)
        self.emit("file_changed", agent=qa.id, path="tests/q_finish/test_gaps.py", diff=tests, created=True)
        self._commit("[analyst] gap report, reconstructed contract and a test for every gap")
        self.emit("architecture_ready", preset="imported", endpoints=len(contract["endpoints"]), tables=len(a.tables))
        self.emit("contract_updated", version=1, endpoints=[f"{e['method']} {e['path']}" for e in contract["endpoints"]])
        self.emit("gap_report", **a.public())
        self.emit("agent_thought", agent="architect",
                  text=f"{a.framework.title()} app {a.module}:{a.var}, {len(a.routes)} routes, {len(a.tables)} tables. {len(a.gaps)} gaps found: " +
                  ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in sorted({k: sum(1 for g in a.gaps if g.kind == k) for k in {g.kind for g in a.gaps}}.items())) + ".",
                  model="rules", tokens=0, seconds=0.0)
        self.emit("agent_state", agent="architect", state="idle")

    def _readme_with_the_model(self, a: Analysis) -> None:
        """A README that is prose, not a checklist: the model lists what it says is not done (validated, and only endpoints that do not exist)."""
        agent = self.agents["architect"]
        try:
            model = self._model(agent)
            system = (PROMPTS_DIR / "analyst.md").read_text(encoding="utf-8").replace("{name}", agent.name).replace("{role}", "Analyst")
            routes = "\n".join(f"- {r.method} {r.path}" for r in a.routes)
            found, st = structured_step(agent, self.llm, model.id, system, f"README:\n{a.readme}\n\nRoutes that exist:\n{routes}", ReadmeFeatures, lambda f: [], self.emit)
        except AgentFailed:
            return
        self._stat("architect", model, st["iterations"], st["prompt_tokens"], st["completion_tokens"], st["seconds"])
        for f in found.features[:6]:
            method = f.method.upper()
            if method not in ("GET", "POST", "PUT", "PATCH", "DELETE") or not f.path.startswith("/") or matches(a.routes, method, f.path):
                continue
            a.gaps.append(Gap(f"g{len(a.gaps) + 1}", "readme_feature", f"README: {f.title} ({method} {f.path})", home_file(a.routes, a.entry_file, f.path), "backend",
                              detail=f.detail[:600], method=method, path=f.path, body_keys=f.fields))

    @staticmethod
    def _report_md(a: Analysis) -> str:
        lines = [f"# Gap report", "", f"Framework: {a.framework} ({a.module}:{a.var}); {len(a.files)} files; {len(a.routes)} routes; tables: {', '.join(a.tables) or 'none'}.",
                 f"Tests before: {a.tests.get('summary', 'not run')}", "", "## Gaps"]
        lines += [f"- {g.id} [{g.kind}] {g.title} - {g.file}" + (f"\n    {g.detail}" if g.detail else "") for g in a.gaps]
        return "\n".join(lines) + "\n"

    # -- the human picks ----------------------------------------------------------------
    def pick(self, ids: list[str]) -> None:
        """The gaps the human chose to fix (an unknown id is ignored)."""
        self.selected = [g.id for g in self.gaps if g.id in set(ids)]
        self._picked.set()

    def _pick(self) -> None:
        if not self.gaps:
            self.selected = []
            return
        if self.auto_fix:
            self.selected = [g.id for g in self.gaps if not self.only or g.id in self.only]
            self.emit("gaps_selected", ids=self.selected, auto=True)
            return
        self.emit("selection_needed", count=len(self.gaps))
        self.emit("agent_state", agent="architect", state="waiting_human")
        while not self._picked.wait(1.0):
            if self.stopped.is_set():
                return
        self.emit("agent_state", agent="architect", state="idle")
        self.emit("gaps_selected", ids=self.selected, auto=False)

    # -- plan ---------------------------------------------------------------------------
    def _plan_finish(self) -> None:
        chosen = [g for g in self.gaps if g.id in (self.selected or [])]
        chosen, attached = self._attach_failing_tests(chosen)
        groups: list[tuple[str, list[Gap]]] = []  # (file, its gaps): one task per gap (a 7B closes one gap per attempt reliably), one per file when there are many
        if len(chosen) <= MAX_GAP_TASKS:
            groups = [(g.file, [g, *attached.get(g.id, [])]) for g in sorted(chosen, key=lambda g: (g.owner != "backend", g.file, g.line))]
        else:
            by_file: dict[str, list[Gap]] = {}
            for g in chosen:
                by_file.setdefault(g.file, []).append(g)
            groups = sorted(((f, [x for g in gs for x in (g, *attached.get(g.id, []))]) for f, gs in by_file.items()), key=lambda kv: (kv[1][0].owner != "backend", kv[0]))
        specs = []
        backend_ids = [f"t{i}" for i, (_, gs) in enumerate(groups, 1) if gs[0].owner == "backend"]
        for i, (file, gs) in enumerate(groups, 1):
            owner = gs[0].owner
            short = gs[0].title.split(" is a placeholder")[0][:70] if len(gs) == 1 else f"{len(gs)} gaps"
            specs.append(TaskSpec(id=f"t{i}", title=f"Finish {file}: {short}", owner=owner, depends_on=backend_ids if owner == "frontend" else [], files=[file],
                                  acceptance=[g.title for g in gs][:8] + ["run_tests passes for these gaps (tests/q_finish and the project's own tests)"]))
        if not specs:
            self.memory.write("tasks.json", json.dumps({"tasks": []}))
            self.emit("agent_thought", agent="planner", text="Nothing to fix: no gap was chosen.", model="rules", tokens=0, seconds=0.0)
            self.tasks = [{"id": "t1", "title": "Read the project: nothing was chosen to fix", "owner": "architect", "depends_on": [], "files": [], "acceptance": [], "status": "done", "summary": "", "attempts": 0}]
            self.emit("plan_created", tasks=[{k: t[k] for k in ("id", "title", "owner", "depends_on", "files")} for t in self.tasks])
            self.tests_passed = True
            return
        self.tasks = [{**t.model_dump(), "status": "pending", "summary": "", "attempts": 0, "gaps": [g.id for g in groups[k][1]]} for k, t in enumerate(specs)]
        if len(chosen) != len(self.gaps):  # the tests of the gaps nobody chose to fix would stay red for ever
            qa = self.agents["qa"]
            self._write(qa, "tests/q_finish/test_gaps.py", gap_tests(self.analysis, chosen), root=self.root)
        self.memory.write("tasks.json", json.dumps({"tasks": self.tasks}, indent=2))
        self.emit("agent_thought", agent="planner", text=f"{len(chosen)} gap{'s' if len(chosen) != 1 else ''} in {len(specs)} task{'s' if len(specs) != 1 else ''}: one small task each, backend first.", model="rules", tokens=0, seconds=0.0)
        self.emit("plan_created", tasks=[{k: t[k] for k in ("id", "title", "owner", "depends_on", "files")} for t in self.tasks])
        self._commit("[planner] task plan")
        self._progress()

    STOP = {"test", "tests", "the", "and", "with", "from", "that", "this", "note", "notes", "answers", "returns", "comes", "first", "works", "does", "not", "for", "its"}

    def _attach_failing_tests(self, chosen: list[Gap]) -> tuple[list[Gap], dict[str, list[Gap]]]:
        """A failing test of the project is the oracle of the gap it is about (test_delete_... and the FIXME in delete()), not a task of its own: it is attached to the gap whose
        function, path or comment shares the most words with the test's name, so one problem is one task and its test is the check. An unmatched test stays a task."""
        others = [g for g in chosen if g.kind != "failing_test"]
        if not others:
            return chosen, {}
        stem = lambda w: w[:4]  # noqa: E731
        kept: list[Gap] = []
        attached: dict[str, list[Gap]] = {}
        for g in chosen:
            if g.kind != "failing_test":
                kept.append(g)
                continue
            words = {stem(w) for w in re.findall(r"[a-z]{3,}", g.test.split("::")[-1].lower()) if w not in self.STOP}

            def score(o: Gap) -> int:
                text = {stem(w) for w in re.findall(r"[a-z]{3,}", " ".join([o.function, o.path, o.detail, o.title, o.text]).lower())}
                return sum(1 for w in words if any(w.startswith(x) or x.startswith(w) for x in text))

            best = max(others, key=score)
            if score(best) > 0:
                attached.setdefault(best.id, []).append(g)
            else:
                kept.append(g)
        return kept, attached

    def _task_text(self, t: dict, previous_failure: str = "", stub=None, db_api: str = "") -> str:
        gaps = [g for g in self.gaps if g.id in t.get("gaps", [])]
        file = t["files"][0] if t.get("files") else ""
        path = (self._trees.get(t["id"]) or self.root) / file if self.root and file else None
        current = path.read_text(encoding="utf-8", errors="replace")[:7000] if path and path.is_file() else ""
        lines = []
        for g in gaps:
            lines.append(f"- {g.id} ({g.kind.replace('_', ' ')}): {g.title}" + (f"\n    {g.detail}" if g.detail else "") + (f"\n    request body keys the page sends: {', '.join(g.body_keys)}" if g.body_keys else "")
                         + (f"\n    failing test output:\n{g.text}" if g.kind == "failing_test" and g.text else ""))
        text = (f"Task {t['id']}: {t['title']}\nThe file to change is `{file}`. Close these gaps in it:\n" + "\n".join(lines) +
                "\n\nThe project's own tests and the generated gap tests in tests/q_finish are the specification; never edit a test. Keep the style of the file. Make the smallest change that closes each gap, "
                f"run_tests after each change, and finish when run_tests passes.\n\nCurrent content of {file}:\n```\n{current}\n```")
        if t["owner"] == "backend" and self.analysis:
            others = [f for f in self.analysis.fetches if any(g.path == f["path"] for g in gaps)]
            for f in others[:3]:
                js = (self.root / f["file"]).read_text(encoding="utf-8", errors="replace")
                lo = max(0, f["line"] - 6)
                text += f"\n\nThe page calls {f['method']} {f['path']} like this ({f['file']}):\n```\n" + "\n".join(js.splitlines()[lo:f["line"] + 14]) + "\n```"
                if f.get("reads"):
                    text += f"\nThe page reads exactly these keys of the JSON answer: {', '.join(f['reads'])}. Return an object with those keys, in the shape the page uses them (a count is a number, a list is an array)."
        fill = [g for g in gaps if g.function and t["owner"] == "backend"]
        if fill:  # a 7B mixes up `implement` and `replace` (it sends `pattern` and no `content`): the exact call, with the blank to fill
            text += "\n\nTo fill each placeholder, send exactly this action with the real body as `content` (only the lines inside the function):\n" + "\n".join(
                json.dumps({"thought": "fill the placeholder", "action": "implement", "path": file, "function": g.function, "content": f"<the lines inside {g.function}>"}) for g in fill)
        if t["owner"] == "backend":
            ctx = self._project_context(t, gaps)
            if ctx:
                text += "\n\n" + ctx
        helpers = self._db_helpers(file) if t["owner"] == "backend" else ""
        if helpers:
            text += "\n\n" + helpers
        if previous_failure:
            text += f"\n\nA previous attempt failed ({previous_failure}). Some of your edits may already be in the file: read it first and continue from there."
        return text

    def _project_context(self, t: dict, gaps: list[Gap]) -> str:
        """What a stranger to the project needs and a 7B guesses wrong: the real table definitions (column names), and routes of THIS project that already work, as style examples."""
        a = self.analysis
        if not (a and self.root):
            return ""
        parts = []
        tables = []
        for f in a.db_files:
            src = (self.root / f).read_text(encoding="utf-8", errors="replace")
            tables += re.findall(r"CREATE TABLE[^;]*?" + chr(92) + ");", src, re.S | re.I)
        if tables:
            parts.append("The tables (use exactly these column names):" + chr(10) + chr(10).join(x.strip() for x in tables)[:1800])
        want = {g.method for g in gaps if g.method}
        file = t["files"][0] if t.get("files") else ""
        done = [r for r in a.routes if not r.stub and r.file.endswith(".py")]
        done.sort(key=lambda r: (r.file != file, r.method not in want, r.line))
        shown = 0
        for r in done:
            src = (self.root / r.file).read_text(encoding="utf-8", errors="replace").splitlines()
            try:
                tree = ast.parse(chr(10).join(src))
            except SyntaxError:
                continue
            fn = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == r.function and n.lineno == r.line or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == r.function)), None)
            if fn is None or len(fn.body) < 2:
                continue
            seg = chr(10).join(src[max(0, fn.decorator_list[0].lineno - 1 if fn.decorator_list else fn.lineno - 1):getattr(fn, "end_lineno", fn.lineno)])
            parts.append(f"A route of this project that already works ({r.file}), for its style:" + chr(10) + "```" + chr(10) + seg[:900] + chr(10) + "```")
            shown += 1
            if shown == 2:
                break
        names = self._file_names(t)
        if names:
            parts.append("Names this file already imports or defines (use only these; a name that is not in this list is NOT available inside your function, so import it inside the body, for example `from flask import request`):" + chr(10) + names)
        if a.framework == "flask":
            parts.append("Flask idioms: the query string is `q = request.args.get(\"q\", \"\")`; a JSON body is `data = request.get_json() or {}`; a missing row is `return jsonify(error=\"Note not found\"), 404` (never HTTPException; `abort` only if it is in the list of names above); "
                         "reach the database exactly like the example routes above do; a route returns `jsonify(...)` or a `(jsonify(...), status)` tuple.")
        elif a.framework == "fastapi":
            parts.append("FastAPI idioms: a missing row is `raise HTTPException(404, \"... not found\")` (if `HTTPException` is not in the list of names above, make `from fastapi import HTTPException` the first line of your function body); the query string and the path are parameters of the function; a route returns a dict.")
        return (chr(10) + chr(10)).join(parts)

    def _file_names(self, t: dict) -> str:
        """The names a function in the task's file can use without importing: what the file imports and defines at the top level."""
        file = t["files"][0] if t.get("files") else ""
        path = (self._trees.get(t["id"]) or self.root) / file if self.root and file else None
        if not (path and path.is_file()):
            return ""
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            return ""
        out: list[str] = []
        for n in tree.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                out += [(x.asname or x.name).split(".")[0] for x in n.names]
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append(n.name)
            elif isinstance(n, ast.Assign):
                out += [x.id for x in n.targets if isinstance(x, ast.Name)]
        return ", ".join(f"`{x}`" for x in dict.fromkeys(out))[:900]

    def _clean_comments(self, closed: list[Gap]) -> None:
        """The TODO comment that described a placeholder is removed once the function is filled (the code is the answer now); every other comment stays."""
        assert self.root
        for g in closed:
            path = self.root / g.file
            if not path.is_file():
                continue
            lines = path.read_text(encoding="utf-8").split(chr(10))
            gone = {("# " + x.strip()).rstrip() for x in g.detail.split(chr(10)) if x.strip()}
            kept = [l for l in lines if l.strip() not in gone]
            if len(kept) != len(lines):
                path.write_text(chr(10).join(kept), encoding="utf-8", newline=chr(10))

    def _db_helpers(self, file: str) -> str:
        """The project's database functions with their exact names, and how the task's file reaches them (a call to a name it does not import is refused by the sandbox)."""
        a = self.analysis
        if not (a and self.root and a.db_files):
            return ""
        source = (self.root / file).read_text(encoding="utf-8", errors="replace") if (self.root / file).is_file() else ""
        out = []
        for f in a.db_files:
            stem = Path(f).stem
            try:
                tree = ast.parse((self.root / f).read_text(encoding="utf-8"))
            except (SyntaxError, OSError):
                continue
            sigs = []
            for n in tree.body:
                if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"):
                    deco = " (a context manager: `with %s.%s() as conn:` gives a connection)" % (stem, n.name) if any("contextmanager" in ast.unparse(d) for d in n.decorator_list) else ""
                    sigs.append(f"- {stem}.{n.name}({ast.unparse(n.args)}){deco}")
            imported = re.search(rf"^\s*(from\s+[\w.]+\s+import\s+[^\n]*\b{stem}\b|import\s+[\w.]*\b{stem}\b)", source, re.M)
            package = ".".join(Path(f).with_suffix("").parts[:-1])
            how = f"the file already imports it: call `{stem}.name(...)`" if imported else f"import it first: `from {package} import {stem}`" if package else f"import it first: `import {stem}`"
            out.append(f"The database module `{f}` ({how}); its functions, with exact names and parameters (call only these; use `with {stem}.connect() as conn:` for new SQL when a connection helper exists):\n" + "\n".join(sigs))
        return "\n\n".join(out)

    # -- verify -------------------------------------------------------------------------
    def _verify(self) -> None:
        assert self.root and self.repo and self.analysis
        before = self.analysis
        after = analyse(self.root, run_suite, parse_failures)  # one suite run: it gives the verdict and the gaps that are still open
        failed = list(after.tests.get("failed", []))
        unselected = {g.test for g in before.gaps if g.kind == "failing_test" and g.id not in (self.selected or [])}  # the owner's own failures the human chose to leave
        summary = after.tests.get("summary", "")
        passed = bool(after.tests.get("passed")) or (bool(failed) and all(f in unselected for f in failed))
        self.tests_passed, self.test_summary = passed, summary
        self.emit("test_result", agent="orchestrator", passed=passed, failed=failed, summary=summary, signature="")

        implemented = [r for r in after.routes if not r.stub]

        def still_open(g: Gap) -> bool:
            if g.kind in ("missing_endpoint", "readme_feature"):  # a placeholder that was added by rules and never filled is still a gap
                return not matches(implemented, g.method, g.path)
            if g.kind == "failing_test":
                return g.test in failed
            if g.kind == "todo_body":
                return any(x.kind == "todo_body" and x.file == g.file and x.function == g.function for x in after.gaps)
            return any(x.kind == g.kind and x.file == g.file and x.text == g.text for x in after.gaps)

        fixed = [g.id for g in before.gaps if g.id in (self.selected or []) and not still_open(g)]
        self._clean_comments([g for g in before.gaps if g.id in fixed and g.kind == "todo_body" and g.detail and not re.match(r"^[\w/.\-]+:\d+$", g.detail)])
        self.emit("gap_status", fixed=fixed, open=[g.id for g in before.gaps if g.id not in fixed], selected=self.selected or [])
        if not passed:
            self.problems.append(f"final test run failed: {summary}")
        self._commit("[q] finished")
        base, head = "q/base", "q/finish"
        stat = subprocess.run(["git", "diff", "--numstat", base, head, "--", ".", ":(exclude).q", ":(exclude)tests/q_finish", ":(exclude).gitignore"], cwd=self.root, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        files = []
        for row in stat.splitlines():
            add, dele, path = (row.split("\t") + ["", "", ""])[:3]
            files.append({"path": path, "added": int(add) if add.isdigit() else 0, "deleted": int(dele) if dele.isdigit() else 0})
        diff = subprocess.run(["git", "diff", base, head, "--", ".", ":(exclude).q", ":(exclude)tests/q_finish", ":(exclude).gitignore"], cwd=self.root, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        self.emit("finish_summary", files=files, insertions=sum(f["added"] for f in files), deletions=sum(f["deleted"] for f in files), diff=diff[:MAX_DIFF], truncated=len(diff) > MAX_DIFF,
                  branch=head, base=base, fixed=len(fixed), selected=len(self.selected or []))
        if self.start_app and passed:
            ports = self.ports or PortManager()
            self.ports = ports
            try:
                app = ports.start(self.root.name, self.root, self.analysis.run_cmd, self.analysis.health_path, ok_below=500)
                self.app_url = app.url
                self.emit("app_running", url=app.url, port=app.port, project=self.root.name)
            except PortError as e:
                self.problems.append(f"the app did not start: {e}")
