"""Orchestrator end to end with a scripted fake LLM: design -> plan -> engineers -> verification, plus the escalation ladder."""
import json

import pytest

from app import orchestrator as orch_mod
from app.agent.actions import Action
from app.agent.planning import AmendOutput
from app.agent.qa import BugTriage
from app.agent.review import ReviewItem, ReviewOutput
from app.events import EventBus
from app.integrator import Resolution
from app.llm import StructuredResult
from app.orchestrator import Orchestrator
from app.registry import ModelRegistry
from app.schemas import ArchitectOutput, PlannerOutput, SpecOutput

DESIGN = {
    "preset": "fastapi-vanilla", "architecture": "Store calculations in SQLite and expose two endpoints.", "ui_features": ["form", "history list"],
    "endpoints": [
        {"method": "POST", "path": "/api/calculate", "summary": "Compute and store", "response_status": 201,
         "request_fields": [{"name": "a", "type": "number"}, {"name": "b", "type": "number"}, {"name": "operation", "type": "string"}],
         "response_fields": [{"name": "id", "type": "integer"}, {"name": "result", "type": "number"}],
         "errors": [{"status": 400, "detail": "Cannot divide by zero"}],
         "examples": [
             {"description": "adds", "request": {"a": 2, "b": 3, "operation": "add"}, "status": 201, "response": {"result": 5}},
             {"description": "zero", "request": {"a": 1, "b": 0, "operation": "divide"}, "status": 400, "response": {"detail": "Cannot divide by zero"}}]},
        {"method": "GET", "path": "/api/history", "summary": "List calculations", "response_fields": [{"name": "items", "type": "array"}],
         "examples": [{"description": "lists", "request": {}, "status": 200, "response": {}}]},
    ],
    "tables": [{"name": "calculations", "columns": [
        {"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY AUTOINCREMENT"}, {"name": "a", "type": "REAL"},
        {"name": "b", "type": "REAL"}, {"name": "operation", "type": "TEXT"}, {"name": "result", "type": "REAL"}]}],
    "db_functions": [
        {"name": "add_calculation", "signature": "add_calculation(a: float, b: float, operation: str, result: float) -> dict", "description": "Stores a row"},
        {"name": "list_history", "signature": "list_history() -> list[dict]", "description": "All rows, newest first"}],
}
PLAN = {"tasks": [
    {"id": "t1", "title": "DB functions", "owner": "database", "depends_on": [], "files": ["database/calculations.py"], "acceptance": ["add and list work"]},
    {"id": "t2", "title": "API router", "owner": "backend", "depends_on": ["t1"], "files": ["backend/api/calculator.py"], "acceptance": ["POST /api/calculate returns 201"]},
    {"id": "t3", "title": "Page", "owner": "frontend", "depends_on": ["t2"], "files": ["static/index.html", "static/style.css"], "acceptance": ["has a form"]},
    {"id": "t4", "title": "Script", "owner": "frontend", "depends_on": ["t3"], "files": ["static/app.js"], "acceptance": ["calls the API"]},
]}

DB_ADD = "with connect(SCHEMA) as conn:\n    cur = conn.execute('INSERT INTO calculations (a, b, operation, result) VALUES (?, ?, ?, ?)', (a, b, operation, result))\n    return dict(conn.execute('SELECT * FROM calculations WHERE id = ?', (cur.lastrowid,)).fetchone())"
DB_LIST = "with connect(SCHEMA) as conn:\n    return [dict(r) for r in conn.execute('SELECT * FROM calculations ORDER BY id DESC')]"
API_POST = ("ops = {'add': lambda x, y: x + y, 'divide': lambda x, y: x / y}\nif req.operation == 'divide' and req.b == 0:\n"
            "    raise HTTPException(status_code=400, detail='Cannot divide by zero')\n"
            "return db.add_calculation(req.a, req.b, req.operation, ops[req.operation](req.a, req.b))")
API_GET = "return {'items': db.list_history()}"
HTML = "<!doctype html><html><head><link rel='stylesheet' href='/static/style.css'></head><body><form id='f'></form><script src='/static/app.js'></script></body></html>"
JS = ("async function go() { await fetch('/api/calculate'); const d = await (await fetch('/api/history')).json();\n"
      "  for (const item of d.items) { console.log(item.operation); } }\ngo();\n")


DB_TESTS = """from database.calculations import add_calculation, list_history


def test_add_and_list():
    row = add_calculation(2, 3, 'add', 5)
    assert row['result'] == 5
    assert [r['id'] for r in list_history()] == [row['id']]
"""

def act(action, **kw):
    return {"thought": "t", "action": action, **kw}


GOOD = {
    "Karan": [act("implement", path="database/calculations.py", function="add_calculation", content=DB_ADD),
              act("implement", path="database/calculations.py", function="list_history", content=DB_LIST),
              act("write_file", path="tests/test_db_calculations.py", content=DB_TESTS),
              act("run_tests"), act("finish", summary="db done")],
    "Rohan": [act("implement", path="backend/api/calculator.py", function="handle_post_calculate", content=API_POST),
              act("implement", path="backend/api/calculator.py", function="handle_get_history", content=API_GET),
              act("run_tests"), act("finish", summary="api done")],
    "Meera": [act("write_file", path="static/index.html", content=HTML), act("write_file", path="static/style.css", content="body { margin: 0; }\n"),
              act("run_tests"), act("finish", summary="page done"),
              act("write_file", path="static/app.js", content=JS), act("run_tests"), act("finish", summary="script done")],
}


class FakeLLM:
    """Dispatches on the requested schema; engineers follow per-name scripts. `broken` makes one agent loop on list_dir (a local failure)."""

    def __init__(self, broken_local=None):
        self.scripts = {k: list(v) for k, v in GOOD.items()}
        self.broken_local, self.models_used = broken_local, []
        self.reviews: list[ReviewOutput] = []  # popped per review call; empty -> PASS
        self.triaged: list[str] = []

    def call(self, model_id, messages, schema_model, temperature=0.2):
        self.models_used.append((model_id, schema_model.__name__))
        system = messages[0]["content"]
        if schema_model is ArchitectOutput:
            parsed = ArchitectOutput.model_validate(DESIGN)
        elif schema_model is SpecOutput:
            parsed = SpecOutput.model_validate({"title": "Calculator", "summary": "Calculate with two numbers and keep a history.", "features": ["Calculate form", "History list"],
                                                "resources": [{"name": "calculations", "fields": [{"name": "a", "type": "number"}, {"name": "b", "type": "number"}], "operations": ["list", "create"]}]})
        elif schema_model is PlannerOutput:
            parsed = PlannerOutput.model_validate(PLAN)
        elif schema_model is AmendOutput:
            parsed = AmendOutput(approve=False, reason="not needed")
        elif schema_model is ReviewOutput:
            parsed = self.reviews.pop(0) if self.reviews else ReviewOutput(verdict="PASS", summary="looks fine")
        elif schema_model is BugTriage:
            self.triaged.append(messages[1]["content"])
            parsed = BugTriage(verdict="app_bug", owner="backend", title="Wrong calculation", expected="a + b", actual="wrong value", suggestion="check the operator")
        elif schema_model is Resolution:
            parsed = Resolution(content="x = 1\n", summary="kept both")
        else:
            name = next(n for n in ("Karan", "Rohan", "Meera") if f"You are {n}" in system)
            if self.broken_local == name and not model_id.startswith("gemini"):
                parsed = Action.model_validate(act("list_dir"))
            else:
                parsed = Action.model_validate(self.scripts[name].pop(0))
        return StructuredResult(parsed, model_id, 1, 10, 5, 0.01, "{}")


def make(tmp_path, llm, **kw):
    env = kw.pop("env", {})
    registry = ModelRegistry.load(env=env)
    bus = EventBus()
    return Orchestrator("Build a calculator with history", registry, llm, bus, mode="autonomous", base=tmp_path, start_app=False, **kw), bus


def types(bus):
    return [e["type"] for e in bus.history]


def test_full_build_with_scripted_team(tmp_path):
    llm = FakeLLM()
    o, bus = make(tmp_path, llm)
    res = o.run()
    assert res.ok, res.problems
    assert res.tests_passed and [t["status"] for t in res.tasks] == ["done"] * 5
    root = res.root
    for f in (".q/architecture.md", ".q/api_contract.json", ".q/database_schema.md", ".q/tasks.json", ".q/design.json",
              "tests/api/test_contract_api.py", "tests/ui/test_page.py", "tests/ui/test_script.py", "tests/qa/test_edge_cases.py", "database/calculations.py", "backend/api/calculator.py"):
        assert (root / f).is_file(), f
    assert json.loads((root / ".q/api_contract.json").read_text())["version"] == 1
    t = types(bus)
    assert t.index("architecture_ready") < t.index("plan_created") < t.index("task_assigned") and t[-1] == "project_done"
    assert bus.history[-1]["ok"] is True and bus.history[-1]["type"] == "project_done"
    assert [e["agent"] for e in bus.history if e["type"] == "task_assigned"] == ["database", "backend", "frontend", "frontend", "qa"]
    log = o.memory.read("decisions.md")
    assert "Architect" in log
    assert (root / ".q/agents.json").is_file() and list((root / ".q/history").glob("events-*.jsonl"))


def test_engineers_cannot_touch_locked_files_or_generated_tests(tmp_path):
    o, _ = make(tmp_path, FakeLLM())
    o.run()
    from app.orchestrator import LOCKED
    backend = o._engineer("backend")
    assert set(LOCKED) <= set(backend.forbidden_paths)
    from app.sandbox.paths import PathPolicy, SandboxError
    pp = PathPolicy(o.root, backend.owned_paths, backend.forbidden_paths)
    for bad in ("backend/main.py", "tests/api/test_contract_api.py", ".q/api_contract.json", "static/app.js"):
        with pytest.raises(SandboxError):
            pp.resolve_write(bad)


def test_without_a_router_each_role_uses_the_registry_default_and_stays_local(tmp_path):
    llm = FakeLLM()
    o, _ = make(tmp_path, llm)
    o.run()
    reg = ModelRegistry.load(env={})
    assert {m for m, _ in llm.models_used} <= {reg.default_for(c).id for c in ("coding", "frontend", "sql", "reasoning", "review")}
    assert all(reg.get(m).local for m, _ in llm.models_used)


def test_cloud_model_is_refused_when_local_only(tmp_path):
    o, bus = make(tmp_path, FakeLLM(), overrides={"architect": "gemini-flash"}, env={"GEMINI_API_KEY": "x"})
    res = o.run()
    assert not res.ok and any("local-only" in p for p in res.problems)


def test_local_failure_is_replanned_once_then_retried_locally_without_consultant(tmp_path, monkeypatch):
    """Two local escalations and no consultant (default): the task fails, dependents are blocked, nothing runs on a cloud model."""
    monkeypatch.setattr(orch_mod, "MAX_REPLANS", 0)
    llm = FakeLLM(broken_local="Rohan")
    o, bus = make(tmp_path, llm, env={"GEMINI_API_KEY": "x"})
    res = o.run()
    assert not res.ok
    statuses = {t["id"]: t["status"] for t in res.tasks}
    assert statuses == {"t1": "done", "t2": "failed", "t3": "blocked", "t4": "blocked"}
    assert "consultant_called" not in types(bus) and not any(m.startswith("gemini") for m, _ in llm.models_used)
    assert len([e for e in bus.history if e["type"] == "escalation" and e["agent"] == "backend"]) == 2


def test_consultant_is_called_after_two_local_escalations_and_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(orch_mod, "MAX_REPLANS", 0)
    llm = FakeLLM(broken_local="Rohan")
    o, bus = make(tmp_path, llm, consultant=True, env={"GEMINI_API_KEY": "x"})
    res = o.run()
    assert res.ok, res.problems
    called = [e for e in bus.history if e["type"] == "consultant_called"]
    assert len(called) == 1 and called[0]["task"] == "t2" and called[0]["model"] == "gemini-3.8-flash"
    assert [e["ok"] for e in bus.history if e["type"] == "consultant_result"] == [True]
    assert len([e for e in bus.history if e["type"] == "escalation" and e["agent"] == "backend"]) == 2  # exactly two local escalations first
    assert "Senior consultant" in o.memory.read("decisions.md")
    assert "backend+consultant" in res.agent_stats and res.agent_stats["backend+consultant"]["model"] == "gemini-3.8-flash"
    # only the backend task used the cloud model
    assert {m for m, s in llm.models_used if m.startswith("gemini")} == {"gemini-flash"}


def test_consultant_needs_an_available_cloud_model(tmp_path, monkeypatch):
    monkeypatch.setattr(orch_mod, "MAX_REPLANS", 0)
    o, bus = make(tmp_path, FakeLLM(broken_local="Rohan"), consultant=True, env={})
    res = o.run()
    assert not res.ok and "consultant_called" not in types(bus)


def test_contract_amendment_denied_by_architect_leaves_contract_unchanged(tmp_path):
    o, bus = make(tmp_path, FakeLLM())
    o.run()
    o.messages.send("backend", "architect", "please add a DELETE endpoint")
    o._after_task({})
    assert json.loads((o.root / ".q/api_contract.json").read_text())["version"] == 1
    assert any("denied" in m["text"] for m in o.messages.all() if m["recipient"] == "backend")
