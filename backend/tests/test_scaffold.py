"""Contract-derived stubs: deterministic, valid Python, exact names/paths/status codes/SQL."""
import sqlite3

from app.scaffold import db_stub, endpoints_for_task, route_stub, schema_sql
from app.schemas import ArchitectOutput

DESIGN = ArchitectOutput.model_validate({
    "preset": "fastapi-vanilla", "architecture": "x", "ui_features": ["x"],
    "endpoints": [
        {"method": "POST", "path": "/api/calculate", "summary": "Compute and store", "response_status": 201,
         "request_fields": [{"name": "a", "type": "number"}, {"name": "b", "type": "number"}, {"name": "operation", "type": "string"}],
         "response_fields": [{"name": "id", "type": "integer"}, {"name": "result", "type": "number"}],
         "errors": [{"status": 400, "detail": "Cannot divide by zero"}]},
        {"method": "GET", "path": "/api/history", "summary": "List", "response_fields": [{"name": "items", "type": "array"}]},
        {"method": "DELETE", "path": "/api/history/{id}", "summary": "Delete one", "response_fields": [{"name": "deleted", "type": "boolean"}],
         "errors": [{"status": 404, "detail": "Not found"}]},
    ],
    "tables": [{"name": "calculations", "columns": [
        {"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY AUTOINCREMENT"},
        {"name": "result", "type": "REAL", "constraints": "NOT NULL"}]}],
    "db_functions": [{"name": "add_calculation", "signature": "add_calculation(result: float) -> dict", "description": "Stores a row"},
                     {"name": "list_history", "signature": "list_history() -> list[dict]", "description": "All rows"}],
})


def test_schema_sql_is_valid_sqlite():
    sqlite3.connect(":memory:").executescript(schema_sql(DESIGN))


def test_db_stub_compiles_and_keeps_exact_signatures():
    code = db_stub(DESIGN)
    compile(code, "stub.py", "exec")
    assert "def add_calculation(result: float) -> dict:" in code and "def list_history() -> list[dict]:" in code
    assert code.count("raise NotImplementedError") == 2 and "SCHEMA =" in code


def test_route_stub_has_exact_paths_models_and_status_codes():
    code = route_stub(DESIGN, DESIGN.endpoints, "calculations")
    compile(code, "stub.py", "exec")
    assert '@router.post("/api/calculate", status_code=201, response_model=PostCalculateResponse)' in code
    assert "class PostCalculateRequest(BaseModel):" in code and "    operation: str" in code
    assert "def handle_post_calculate(req: PostCalculateRequest):" in code
    assert 'raise HTTPException(status_code=400, detail="Cannot divide by zero")' in code
    assert "def handle_delete_history_by_id(id: int):" in code  # path parameter becomes an argument, names never clash with db functions
    assert "from database import calculations as db" in code and "import operator" in code


def test_endpoints_for_task_picks_named_endpoints_or_all():
    task = {"title": "Implement the calculate endpoint", "acceptance": ["POST /api/calculate returns 201"]}
    assert [e.path for e in endpoints_for_task(DESIGN, task, 2)] == ["/api/calculate"]
    assert len(endpoints_for_task(DESIGN, task, 1)) == 3  # a single backend task owns every endpoint
    assert len(endpoints_for_task(DESIGN, {"title": "Router", "acceptance": ["works"]}, 2)) == 3


def test_contract_tests_are_generated_from_examples_and_run_green_against_a_correct_app(tmp_path, monkeypatch):
    from app.contract_tests import api_test_source, ui_test_source
    from app.schemas import ExampleSpec

    d = DESIGN.model_copy(deep=True)
    d.endpoints[0].examples = [
        ExampleSpec(description="adds", request={"a": 2, "b": 3, "operation": "add"}, status=201, response={"result": 5}),
        ExampleSpec(description="div by zero", request={"a": 1, "b": 0, "operation": "divide"}, status=400, response={"detail": "Cannot divide by zero"}),
    ]
    d.endpoints[2].examples = [ExampleSpec(description="unknown", request={"id": 99999}, status=404, response={"detail": "Not found"})]
    src = api_test_source(d)
    compile(src, "t.py", "exec")
    assert "client.post('/api/calculate', json={'a': 2, 'b': 3, 'operation': 'add'})" in src
    assert "client.delete('/api/history/99999')" in src and "pytest.approx(5)" in src
    assert "'id' in data" in src and "'result' in data" in src
    ui = ui_test_source(d)
    compile(ui, "t.py", "exec")
    assert "'/api/calculate'" in ui and "'/api/history'" in ui


def test_examples_expecting_computed_numbers_need_numeric_inputs():
    from app.schemas import ExampleSpec, check_examples

    ep = DESIGN.endpoints[0].model_copy(deep=True)
    ep.request_fields = [f for f in ep.request_fields if f.name == "operation"]
    ep.examples = [ExampleSpec(description="adds", request={"operation": "add"}, status=201, response={"result": 5}),
                   ExampleSpec(description="zero", request={"operation": "divide"}, status=400, response={"detail": "Cannot divide by zero"})]
    assert any("no numbers to compute" in p for p in check_examples(ep))
    ep.request_fields = DESIGN.endpoints[0].request_fields
    ep.examples[0] = ExampleSpec(description="adds", request={"a": 2, "b": 3, "operation": "add"}, status=201, response={"result": 5})
    assert not any("no numbers" in p for p in check_examples(ep))


def test_errors_about_missing_fields_are_rejected_because_fastapi_answers_422():
    from app.schemas import ErrorSpec, check_architecture

    d = DESIGN.model_copy(deep=True)
    d.endpoints[0].errors.append(ErrorSpec(status=400, detail="One or both numbers are missing"))
    assert any("422" in p for p in check_architecture(d, ["fastapi-vanilla"]))


def test_example_values_must_match_declared_field_types():
    from app.schemas import ExampleSpec, check_examples

    ep = DESIGN.endpoints[0].model_copy(deep=True)
    ep.examples = [ExampleSpec(description="empty number", request={"a": "", "b": 3, "operation": "add"}, status=400, response={"detail": "Cannot divide by zero"})]
    assert any("422" in p and "'a'" in p for p in check_examples(ep))
