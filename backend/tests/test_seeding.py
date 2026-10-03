"""Generated contract tests for `/{id}` endpoints: success cases create the row first (through the contract's own POST) instead of assuming id 1 exists."""
import subprocess
import sys

from app.contract_tests import api_test_source
from app.pybody import replace_function_body
from app.schemas import ArchitectOutput

DESIGN = {
    "preset": "fastapi-vanilla", "architecture": "todos", "ui_features": ["list"],
    "endpoints": [
        {"method": "POST", "path": "/api/todos", "summary": "Add", "response_status": 201,
         "request_fields": [{"name": "title", "type": "string"}],
         "response_fields": [{"name": "id", "type": "integer"}, {"name": "title", "type": "string"}],
         "errors": [], "examples": [{"description": "adds", "request": {"title": "Buy milk"}, "status": 201, "response": {"title": "Buy milk"}}]},
        {"method": "PUT", "path": "/api/todos/{id}", "summary": "Rename",
         "request_fields": [{"name": "title", "type": "string"}], "response_fields": [{"name": "updated", "type": "boolean"}],
         "errors": [{"status": 404, "detail": "Todo not found"}],
         "examples": [{"description": "renames", "request": {"id": 1, "title": "New"}, "status": 200, "response": {"updated": True}},
                      {"description": "unknown id", "request": {"id": 99999, "title": "New"}, "status": 404, "response": {"detail": "Todo not found"}}]},
        {"method": "DELETE", "path": "/api/todos/{id}", "summary": "Delete", "response_fields": [{"name": "deleted", "type": "boolean"}],
         "errors": [{"status": 404, "detail": "Todo not found"}],
         "examples": [{"description": "deletes", "request": {"id": 1}, "status": 200, "response": {"deleted": True}},
                      {"description": "unknown id", "request": {"id": 99999}, "status": 404, "response": {"detail": "Todo not found"}}]},
    ],
    "tables": [], "db_functions": [],
}

APP = '''from fastapi import FastAPI, HTTPException
app = FastAPI()
rows = {}

@app.post("/api/todos", status_code=201)
def add(body: dict):
    rid = len(rows) + 100  # deliberately not 1: the tests must use the id the POST returned
    rows[rid] = body["title"]
    return {"id": rid, "title": body["title"]}

@app.put("/api/todos/{rid}")
def put(rid: int, body: dict):
    if rid not in rows:
        raise HTTPException(404, "Todo not found")
    rows[rid] = body["title"]
    return {"updated": True}

@app.delete("/api/todos/{rid}")
def delete(rid: int):
    if rid not in rows:
        raise HTTPException(404, "Todo not found")
    del rows[rid]
    return {"deleted": True}
'''


def test_success_cases_on_id_paths_seed_a_row_and_unknown_id_cases_do_not():
    src = api_test_source(ArchitectOutput.model_validate(DESIGN))
    compile(src, "generated", "exec")
    put_ok = src.split("def test_put_api_todos_id_1_renames")[1].split("def test_")[0]
    assert "client.post('/api/todos'" in put_ok and "seed['id']" in put_ok
    put_missing = src.split("def test_put_api_todos_id_2_unknown_id")[1].split("def test_")[0]
    assert "seed" not in put_missing and "99999" in put_missing


def test_generated_tests_pass_against_an_app_whose_ids_are_not_1(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "__init__.py").write_text("")
    (tmp_path / "backend" / "main.py").write_text(APP)
    (tmp_path / "test_contract.py").write_text(api_test_source(ArchitectOutput.model_validate(DESIGN)))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1500:]


def test_implement_explains_when_two_function_names_are_sent_together():
    src = "def a():\n    pass\n\n\ndef b():\n    pass\n"
    _, problem = replace_function_body(src, "a b", "return 1")
    assert "ONE function name per call" in problem and "a, b" in problem
    _, problem = replace_function_body(src, "zzz", "return 1")
    assert "no function named" in problem


def test_generated_ids_and_list_valued_fields_are_not_mistaken_for_computed_values():
    from app.schemas import Endpoint, ExampleSpec, FieldSpec, check_examples

    ep = Endpoint(method="POST", path="/api/notes", summary="Add a note", response_status=201,
                  request_fields=[FieldSpec(name="title", type="string"), FieldSpec(name="tags", type="array")],
                  response_fields=[FieldSpec(name="id", type="integer"), FieldSpec(name="title", type="string")],
                  errors=[], examples=[ExampleSpec(description="adds", request={"title": "x", "tags": ["a", "b"]}, status=201, response={"id": 1, "title": "x"})])
    assert not any("compute" in p for p in check_examples(ep))  # id is server-generated; list values must not crash the check
    ep.response_fields.append(FieldSpec(name="score", type="number"))
    ep.examples[0].response = {"score": 7}
    assert any("no numbers to compute" in p for p in check_examples(ep))  # a real computed value without inputs is still caught
    ep.method, ep.path, ep.examples[0].request = "GET", "/api/notes", {}
    assert not any("compute" in p for p in check_examples(ep))  # nothing to compute from, and nothing expected to be computed from it


def test_backend_task_lists_the_database_functions_with_exact_signatures(tmp_path):
    from app.orchestrator import Orchestrator

    (tmp_path / "database").mkdir()
    (tmp_path / "database" / "expenses.py").write_text(
        'from database.connection import connect\n\n\ndef add_expense(title: str, amount: float) -> dict:\n    """Insert and return the new row"""\n    return {}\n\n\n'
        'def delete_expense(expense_id: int) -> bool:\n    """True if a row was deleted"""\n    return True\n\n\ndef _private():\n    pass\n', encoding="utf-8")
    (tmp_path / "database" / "connection.py").write_text("def connect(s):\n    pass\n", encoding="utf-8")
    api = Orchestrator._db_api(tmp_path)
    assert "- db.add_expense(title: str, amount: float) -> dict  # Insert and return the new row" in api
    assert "- db.delete_expense(expense_id: int) -> bool  # True if a row was deleted" in api
    assert "_private" not in api and "connect" not in api


def test_a_search_term_field_is_allowed_but_expression_like_fields_are_still_refused():
    from app.schemas import ArchitectOutput, check_architecture

    d = ArchitectOutput.model_validate({**DESIGN, "endpoints": [
        {"method": "GET", "path": "/api/notes/search", "summary": "Search notes",
         "request_fields": [{"name": "query", "type": "string", "description": "text to look for"}],
         "response_fields": [{"name": "items", "type": "array"}],
         "examples": [{"description": "finds", "request": {"query": "milk"}, "status": 200, "response": {}}]}]})
    assert not any("free text" in p for p in check_architecture(d, ["fastapi-vanilla"]))
    d.endpoints[0].request_fields[0].name = "expression"
    assert any("free text" in p for p in check_architecture(d, ["fastapi-vanilla"]))


def test_populated_list_examples_seed_through_the_post_and_check_shape_not_invented_rows(tmp_path):
    design = {**DESIGN, "endpoints": [DESIGN["endpoints"][0],
                                      {"method": "GET", "path": "/api/todos", "summary": "List", "response_fields": [{"name": "items", "type": "array"}],
                                       "examples": [{"description": "lists", "request": {}, "status": 200, "response": {"items": [{"id": 1, "title": "Invented by the architect"}]}},
                                                    {"description": "empty", "request": {}, "status": 200, "response": {"items": []}}]}]}
    src = api_test_source(ArchitectOutput.model_validate(design))
    listed = src.split("def test_get_api_todos_1_lists")[1].split("def test_")[0]
    assert "client.post('/api/todos'" in listed and "len(data['items']) >= 1" in listed and "Invented" not in listed
    empty = src.split("def test_get_api_todos_2_empty")[1]
    assert "seed" not in empty and "data['items'] == []" in empty
    app = APP + '\n@app.get("/api/todos")\ndef lst():\n    return {"items": [{"id": k, "title": v} for k, v in rows.items()]}\n'
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "__init__.py").write_text("")
    (tmp_path / "backend" / "main.py").write_text(app)
    (tmp_path / "test_contract.py").write_text(src)
    fresh = "import pytest\nfrom backend import main\n\n\n@pytest.fixture(autouse=True)\ndef fresh():\n    main.rows.clear()\n"  # like the preset's per-test database
    (tmp_path / "conftest.py").write_text(fresh)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1500:]


def test_array_fields_are_plain_lists_in_generated_models_so_tags_can_be_strings():
    from app.scaffold import route_stub

    d = ArchitectOutput.model_validate({**DESIGN, "endpoints": [
        {"method": "POST", "path": "/api/bookmarks", "summary": "Add", "response_status": 201,
         "request_fields": [{"name": "title", "type": "string"}, {"name": "tags", "type": "array"}],
         "response_fields": [{"name": "id", "type": "integer"}, {"name": "tags", "type": "array"}], "errors": [],
         "examples": [{"description": "adds", "request": {"title": "x", "tags": ["a"]}, "status": 201, "response": {}}]}]})
    stub = route_stub(d, d.endpoints, None)
    assert "tags: list\n" in stub and "list[dict]" not in stub


def test_get_endpoints_with_request_fields_get_query_parameters_in_the_route_stub():
    from app.scaffold import route_stub

    d = ArchitectOutput.model_validate({**DESIGN, "endpoints": [
        {"method": "GET", "path": "/api/notes/search", "summary": "Search", "request_fields": [{"name": "query", "type": "string"}, {"name": "limit", "type": "integer"}],
         "response_fields": [{"name": "items", "type": "array"}],
         "examples": [{"description": "finds", "request": {"query": "milk", "limit": 5}, "status": 200, "response": {}}]}]})
    stub = route_stub(d, d.endpoints, None)
    assert "def handle_get_notes_search(query: str, limit: int):" in stub
    compile(stub, "stub", "exec")


def test_implement_refuses_a_body_that_would_leave_the_file_unparseable(tmp_path):
    from app.agent.actions import Action
    from app.config import load_agents
    from app.tools import ToolBox

    (tmp_path / "database").mkdir()
    f = tmp_path / "database" / "x.py"
    original = "def list_x():\n    raise NotImplementedError\n"
    f.write_text(original, encoding="utf-8")
    tb = ToolBox(tmp_path, load_agents()["database"], mode="autonomous", emit=lambda *a, **k: None)
    r = tb.execute(Action(thought="t", action="implement", path="database/x.py", function="list_x", content="SELECT id, name FROM x ORDER BY id DESC"))
    assert not r.ok and "invalid Python" in r.output and "conn.execute" in r.output
    assert f.read_text(encoding="utf-8") == original  # untouched, so the next implement call still works
    ok = tb.execute(Action(thought="t", action="implement", path="database/x.py", function="list_x", content="return []"))
    assert ok.ok and "return []" in f.read_text(encoding="utf-8")


def test_a_plan_with_two_database_tasks_is_refused_and_stubs_import_re_and_json():
    from app.schemas import PlannerOutput, check_plan
    from app.scaffold import db_stub, route_stub

    plan = PlannerOutput.model_validate({"tasks": [
        {"id": "t1", "title": "Bookmarks DB", "owner": "database", "depends_on": [], "files": ["database/bookmarks.py"], "acceptance": ["add and list work"]},
        {"id": "t2", "title": "Tags DB", "owner": "database", "depends_on": [], "files": ["database/tags.py"], "acceptance": ["add and list work"]}]})
    assert any("exactly ONE database task" in p for p in check_plan(plan, True, []))
    d = ArchitectOutput.model_validate(DESIGN)
    assert "import re" in route_stub(d, d.endpoints, None) and "import json" in route_stub(d, d.endpoints, None)
    assert "import json" in db_stub(d)
    compile(db_stub(d), "db", "exec")


def test_timestamps_in_examples_are_checked_for_presence_not_for_their_invented_value():
    d = ArchitectOutput.model_validate({**DESIGN, "endpoints": [
        {"method": "POST", "path": "/api/expenses", "summary": "Add", "response_status": 201,
         "request_fields": [{"name": "category", "type": "string"}],
         "response_fields": [{"name": "id", "type": "integer"}, {"name": "category", "type": "string"}, {"name": "created_at", "type": "string"}],
         "errors": [], "examples": [{"description": "adds", "request": {"category": "food"}, "status": 201,
                                     "response": {"category": "food", "created_at": "2023-04-10T12:34:56.789Z"}}]}]})
    src = api_test_source(d)
    assert "assert 'created_at' in data" in src and "2023-04-10" not in src and "data['category'] == 'food'" in src


def test_list_valued_columns_get_a_json_row_helper_in_the_database_stub(tmp_path):
    from app.scaffold import db_stub

    d = ArchitectOutput.model_validate({**DESIGN, "endpoints": [
        {"method": "POST", "path": "/api/bookmarks", "summary": "Add", "response_status": 201,
         "request_fields": [{"name": "title", "type": "string"}, {"name": "tags", "type": "array"}],
         "response_fields": [{"name": "id", "type": "integer"}, {"name": "tags", "type": "array"}], "errors": [],
         "examples": [{"description": "adds", "request": {"title": "x", "tags": ["a"]}, "status": 201, "response": {}}]}],
        "tables": [{"name": "bookmarks", "columns": [{"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY AUTOINCREMENT"},
                                                     {"name": "title", "type": "TEXT"}, {"name": "tags", "type": "TEXT"}]}],
        "db_functions": [{"name": "add_bookmark", "signature": "add_bookmark(title: str, tags: list) -> dict", "description": "Insert"}]})
    src = db_stub(d)
    assert "JSON_COLUMNS = ('tags',)" in src and "def _row(r)" in src and "return _row(row) / [_row(r) for r in rows]" in src
    ns: dict = {}
    exec(compile(src.replace("from database.connection import connect", "connect = None"), "stub", "exec"), ns)
    assert ns["_row"]({"id": 1, "tags": '["a", "b"]'}) == {"id": 1, "tags": ["a", "b"]}
    assert "_row" not in db_stub(ArchitectOutput.model_validate(DESIGN))  # no list columns, no helper


def test_request_fields_must_reach_the_database_layer():
    from app.schemas import check_architecture

    d = ArchitectOutput.model_validate({**DESIGN, "endpoints": [
        {"method": "POST", "path": "/api/bookmarks", "summary": "Add", "response_status": 201,
         "request_fields": [{"name": "title", "type": "string"}, {"name": "tags", "type": "array"}],
         "response_fields": [{"name": "id", "type": "integer"}], "errors": [],
         "examples": [{"description": "adds", "request": {"title": "x", "tags": ["a"]}, "status": 201, "response": {"id": 1}}]}],
        "tables": [{"name": "bookmarks", "columns": [{"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY AUTOINCREMENT"}, {"name": "title", "type": "TEXT"}]}],
        "db_functions": [{"name": "add_bookmark", "signature": "add_bookmark(title: str) -> dict", "description": "Insert"}]})
    problems = check_architecture(d, ["fastapi-vanilla"])
    assert any("'tags' is not a parameter of any db_function" in p for p in problems) and any("'tags' is not a column" in p for p in problems)
    assert not any("'title'" in p for p in problems)
    d.db_functions[0].signature = "add_bookmark(title: str, tags: list) -> dict"
    d.tables[0].columns.append(type(d.tables[0].columns[0])(name="tags", type="TEXT", constraints=""))
    assert not any("db_function" in p or "column" in p for p in check_architecture(d, ["fastapi-vanilla"]))


def test_an_architect_schema_that_sqlite_rejects_is_sent_back():
    from app.schemas import check_architecture

    d = ArchitectOutput.model_validate({**DESIGN, "tables": [{"name": "items", "columns": [
        {"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY AUTOINCREMENT"}, {"name": "name", "type": "TEXT"}]}]})
    assert not any("valid SQLite" in p for p in check_architecture(d, ["fastapi-vanilla"]))
    bad = d.tables[0].columns[1].model_copy(update={"name": "owner_id", "type": "INTEGER FOREIGN KEY REFERENCES users(id)"})
    d.tables[0].columns.append(bad)
    problems = check_architecture(d, ["fastapi-vanilla"])
    assert any("not valid SQLite" in p and "no FOREIGN KEY" in p for p in problems)
