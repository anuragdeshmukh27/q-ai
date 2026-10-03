"""The benchmark tasks. Each is small, runs the real component of its role, and ends in an automatic pass/fail that does not trust the model:

| role      | task                                    | pass when                                                                                                 |
|-----------|-----------------------------------------|-----------------------------------------------------------------------------------------------------------|
| architect | design for two goals                    | a valid design (schema + semantic checks within 3 attempts) whose generated stubs and contract tests compile |
| planner   | plan for two fixed designs              | a valid task DAG (the Planner's own checks)                                                               |
| database  | data layer for two fixtures             | the real agent loop finishes, merges, and hidden pytest checks pass                                       |
| backend   | API router for two fixtures             | the real agent loop finishes, merges, generated contract tests + QA edge cases pass                       |
| frontend  | page + script for two fixtures          | the real agent loop finishes, merges, generated UI tests (incl. every list field is shown) + `node --check` pass |
| reviewer  | seven seeded diffs (4 defects, 3 clean) | the verdict is right and a defect is named in the right file (static checks switched off)                 |
| qa        | four failing-test reports               | the model routes the bug to the right owner and calls it an app bug (traceback hint switched off)         |
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.agent.planning import AgentFailed, run_architect, run_planner
from app.agent.qa import Failure, run_triage
from app.agent.review import run_review
from app.config import load_agents
from app.contract_tests import api_test_source, edge_test_source
from app.events import EventBus
from app.integrator import run_suite
from app.llm import LLMClient
from app.memory import contract_brief, contract_dict, schema_md
from app.orchestrator import Orchestrator
from app.presets import list_presets, load_preset
from app.registry import ModelConfig, ModelRegistry
from app.scaffold import db_stub, route_stub
from app.schemas import ArchitectOutput, PlannerOutput, TaskSpec

from .review_cases import CASES

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
HIDDEN = HERE / "hidden"


@dataclass
class Outcome:
    passed: bool
    iterations: int = 0
    tokens: int = 0
    detail: str = ""


@dataclass
class Ctx:
    model: ModelConfig
    registry: ModelRegistry
    llm: LLMClient
    workdir: Path
    agents: dict = field(default_factory=load_agents)

    def quiet(self) -> Callable[..., object]:
        return EventBus().emit


@dataclass
class Task:
    id: str
    role: str
    title: str
    run: Callable[[Ctx], Outcome]
    reps: int = 1  # cheap single-shot roles repeat, so one lucky sample does not decide a cell


def load_design(name: str) -> ArchitectOutput:
    return ArchitectOutput.model_validate_json((FIXTURES / f"{name}.design.json").read_text(encoding="utf-8"))


def load_plan(name: str) -> list[TaskSpec]:
    return PlannerOutput.model_validate_json((FIXTURES / f"{name}.plan.json").read_text(encoding="utf-8")).tasks


# -- architect and planner ----------------------------------------------------------------------------------------

def _architect(goal: str) -> Callable[[Ctx], Outcome]:
    def run(c: Ctx) -> Outcome:
        presets = {n: load_preset(n).description for n in list_presets()}
        try:
            design, st = run_architect(c.agents["architect"], c.llm, c.model.id, goal, presets, c.quiet())
        except AgentFailed as e:
            return Outcome(False, 3, 0, e.reason[:200])
        tokens = st["prompt_tokens"] + st["completion_tokens"]
        try:  # the design must be usable: the system generates stubs and tests from it
            for src in (db_stub(design), route_stub(design, design.endpoints, "db"), api_test_source(design), edge_test_source(design)):
                compile(src, "generated", "exec")
        except SyntaxError as e:
            return Outcome(False, st["iterations"], tokens, f"generated code does not compile: {e.msg}")
        return Outcome(True, st["iterations"], tokens)
    return run


def _planner(fixture: str, goal: str) -> Callable[[Ctx], Outcome]:
    def run(c: Ctx) -> Outcome:
        design = load_design(fixture)
        contract = contract_brief(contract_dict(design))
        try:
            plan, st = run_planner(c.agents["planner"], c.llm, c.model.id, goal, contract, schema_md(design), bool(design.tables), design.endpoints, c.quiet())
        except AgentFailed as e:
            return Outcome(False, 3, 0, e.reason[:200])
        return Outcome(bool(plan.tasks), st["iterations"], st["prompt_tokens"] + st["completion_tokens"])
    return run


# -- engineers: the real agent loop inside the real orchestrator, on a fixed design ---------------------------------

def _node_check(root: Path) -> str:
    js = root / "static" / "app.js"
    if not js.is_file():
        return "static/app.js is missing"
    if shutil.which("node"):
        r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        if r.returncode != 0:
            return "static/app.js has a syntax error"
    return ""


def _pytest(root: Path, *paths: str) -> tuple[bool, str]:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *paths], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
    return r.returncode == 0, (lines[-1] if lines else r.stderr[-200:])


def _engineer(role: str, fixture: str, goal: str) -> Callable[[Ctx], Outcome]:
    def run(c: Ctx) -> Outcome:
        design = load_design(fixture)
        everyone = {a: c.model.id for a in c.agents}  # the model under test plays every part the pipeline needs; only `role`'s work is judged
        orch = Orchestrator(goal, c.registry, c.llm, EventBus(), mode="autonomous", base=c.workdir, overrides=everyone, start_app=False,
                            review=False, qa=False, polish=False, max_parallel=1, fast_live=False)
        orch._init_project(design, c.model)
        assert orch.root is not None
        if role == "backend":  # the data layer a backend engineer would find already merged
            ref = FIXTURES / f"{fixture}.database.py"
            plan_db = next(t for t in load_plan(fixture) if t.owner == "database").files[0]
            (orch.root / plan_db).write_text(ref.read_text(encoding="utf-8"), encoding="utf-8")
            orch._commit("[bench] reference data layer")
        mine = [t for t in load_plan(fixture) if t.owner == role]
        ids = {t.id for t in mine}
        orch._adopt_plan([t.model_copy(update={"depends_on": [d for d in t.depends_on if d in ids]}) for t in mine])
        orch._execute_tasks()
        st = orch.stats.get(role, {})
        tokens = st.get("prompt_tokens", 0) + st.get("completion_tokens", 0)
        iterations = st.get("iterations", 0)
        bad = [t["id"] for t in orch.tasks if t["status"] != "done"]
        if bad:
            return Outcome(False, iterations, tokens, f"task(s) {', '.join(bad)} did not finish: {'; '.join(orch.problems)[:160]}")
        root = orch.root
        if role == "database":
            module = next(t for t in mine).files[0].split("/")[-1][:-3]
            shutil.copy(HIDDEN / f"{fixture}_db_test.py", root / "tests" / "test_hidden_db.py")
            ok, summary = _pytest(root, "tests/test_hidden_db.py")
            return Outcome(ok, iterations, tokens, f"hidden tests: {summary} ({module})")
        if role == "backend":
            (root / "tests" / "qa").mkdir(parents=True, exist_ok=True)
            (root / "tests" / "qa" / "test_edge_cases.py").write_text(edge_test_source(design), encoding="utf-8")
            ok, summary = _pytest(root, "tests/api", "tests/qa")
            return Outcome(ok, iterations, tokens, f"contract + edge tests: {summary}")
        ok, summary = _pytest(root, "tests/ui")
        syntax = _node_check(root)
        return Outcome(ok and not syntax, iterations, tokens, syntax or f"ui tests: {summary}")
    return run


# -- reviewer ----------------------------------------------------------------------------------------------------------------

def _review(case: dict) -> Callable[[Ctx], Outcome]:
    def run(c: Ctx) -> Outcome:
        review, st = run_review(c.agents["reviewer"], c.llm, c.model.id, case["task"], case["diff"], [], c.quiet())
        tokens = st["prompt_tokens"] + st["completion_tokens"]
        want = case["defect_file"]
        if want is None:
            return Outcome(review.verdict == "PASS", st["iterations"], tokens, "clean diff: " + review.verdict)
        named = any(i.file.strip().lstrip("./").endswith(want) or want.endswith(i.file.strip().lstrip("./")) for i in review.items)
        return Outcome(review.verdict == "REQUEST_CHANGES" and named, st["iterations"], tokens, f"defect in {want}: {review.verdict}" + ("" if named else ", file not named"))
    return run


# -- QA triage -----------------------------------------------------------------------------------------------------------------

TRIAGE_CASES = [
    ("backend-status", "backend", Failure(
        "tests/api/test_contract_api.py::test_post_api_todos_2_rejects_an_empty_title", "tests/api/test_contract_api.py",
        "test_post_api_todos_2_rejects_an_empty_title", "assert 201 == 400",
        "def test_post_api_todos_2_rejects_an_empty_title():\n        r = client.post('/api/todos', json={'title': '', 'description': 'x', 'priority': 'low'})\n"
        ">       assert r.status_code == 400, r.text\nE       AssertionError: {\"id\":1,\"title\":\"\",\"description\":\"x\",\"priority\":\"low\"}\nE       assert 201 == 400\n\n"
        "tests/api/test_contract_api.py:31: AssertionError")),
    ("database-order", "database", Failure(
        "tests/api/test_contract_api.py::test_get_api_todos_1_lists_newest_first", "tests/api/test_contract_api.py",
        "test_get_api_todos_1_lists_newest_first", "assert ['first', 'second'] == ['second', 'first']",
        "tests/api/test_contract_api.py:44: in test_get_api_todos_1_lists_newest_first\n    assert titles == ['second', 'first']\nE   assert ['first', 'second'] == ['second', 'first']\n\n"
        "The list was produced by database/todos.py:24 in list_todos: rows = conn.execute(\"SELECT id, title, description, priority FROM todos ORDER BY id ASC\")")),
    ("frontend-list", "frontend", Failure(
        "tests/ui/test_script.py::test_list_view_shows_every_field_of_an_item", "tests/ui/test_script.py",
        "test_list_view_shows_every_field_of_an_item", "AssertionError: the list never uses the item field 'priority'",
        "tests/ui/test_script.py:19: in test_list_view_shows_every_field_of_an_item\n    assert re.search(...)\n"
        "E   AssertionError: the list never uses the item field 'priority'. Show EVERY important field of each item, not just the title")),
    ("backend-edge", "backend", Failure(
        "tests/qa/test_edge_cases.py::test_post_api_todos_rejects_missing_title", "tests/qa/test_edge_cases.py",
        "test_post_api_todos_rejects_missing_title", "assert 500 == 422",
        "tests/qa/test_edge_cases.py:12: in test_post_api_todos_rejects_missing_title\n    assert client.post('/api/todos', json={'description': 'd', 'priority': 'low'}).status_code == 422\n"
        "E   assert 500 == 422\n\nbackend/api/todos.py:21: in handle_post_todos\n    if not req.title.strip():\nE   KeyError: 'title'")),
]


def _triage(case_id: str, owner: str, failure: Failure) -> Callable[[Ctx], Outcome]:
    def run(c: Ctx) -> Outcome:
        contract = contract_brief(contract_dict(load_design("todo")))
        try:
            t, st = run_triage(c.agents["qa"], c.llm, c.model.id, failure, contract, "", c.quiet(), hint=False)
        except AgentFailed as e:
            return Outcome(False, 2, 0, e.reason[:200])
        ok = t.owner == owner and t.verdict == "app_bug"
        return Outcome(ok, st["iterations"], st["prompt_tokens"] + st["completion_tokens"], f"{case_id}: owner {t.owner} ({t.verdict}), expected {owner}")
    return run


def all_tasks() -> list[Task]:
    tasks = [
        Task("design-todo", "architect", "Design a todo app", _architect("Build a todo app with priorities"), reps=2),
        Task("design-calculator", "architect", "Design a calculator with history", _architect("Build a calculator with history"), reps=2),
        Task("plan-todo", "planner", "Plan the todo app", _planner("todo", "Build a todo app with priorities"), reps=2),
        Task("plan-calculator", "planner", "Plan the calculator", _planner("calculator", "Build a calculator with history"), reps=2),
        Task("db-todo", "database", "Data layer: todos", _engineer("database", "todo", "Build a todo app with priorities"), reps=2),
        Task("db-calculator", "database", "Data layer: calculations", _engineer("database", "calculator", "Build a calculator with history"), reps=2),
        Task("api-todo", "backend", "API router: todos", _engineer("backend", "todo", "Build a todo app with priorities"), reps=2),
        Task("api-calculator", "backend", "API router: calculate + history", _engineer("backend", "calculator", "Build a calculator with history"), reps=2),
        Task("ui-todo", "frontend", "Page + script: todos", _engineer("frontend", "todo", "Build a todo app with priorities"), reps=2),
        Task("ui-calculator", "frontend", "Page + script: calculator", _engineer("frontend", "calculator", "Build a calculator with history"), reps=2),
    ]
    tasks += [Task(f"review-{c['id']}", "reviewer", f"Review: {c['id']}", _review(c), reps=2) for c in CASES]
    tasks += [Task(f"triage-{cid}", "qa", f"Triage: {cid}", _triage(cid, owner, f), reps=2) for cid, owner, f in TRIAGE_CASES]
    return tasks
