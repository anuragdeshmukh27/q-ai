"""Goal enrichment, labelled categories and item actions: schema checks, the UI kit, and the generated UI tests."""
import subprocess
from pathlib import Path

import pytest

from app.contract_tests import edge_test_source, ui_script_test_source
from app.memory import contract_brief, contract_dict
from app.schemas import ArchitectOutput, FieldSpec, SpecField, SpecOutput, check_architecture, check_options, check_spec, spec_text

LABELS = ["Low", "Medium", "High"]


def _fields(*names, cat=True):
    out = [{"name": "title", "type": "string"}]
    if cat:
        out.append({"name": "priority", "type": "string", "options": LABELS})
    out.append({"name": "done", "type": "boolean"})
    return out


def design(**over):
    d = {
        "preset": "fastapi-vanilla", "architecture": "todos", "ui_features": ["list"],
        "endpoints": [
            {"method": "POST", "path": "/api/todos", "summary": "Add", "response_status": 201, "request_fields": _fields(),
             "response_fields": [{"name": "id", "type": "integer"}, *_fields()], "errors": [],
             "examples": [{"description": "adds", "request": {"title": "a", "priority": "High", "done": False}, "status": 201, "response": {"title": "a", "priority": "High"}}]},
            {"method": "GET", "path": "/api/todos", "summary": "List", "response_fields": [{"name": "items", "type": "array", "description": "id, title, priority, done"}],
             "examples": [{"description": "lists", "request": {}, "status": 200, "response": {}}]},
            {"method": "PUT", "path": "/api/todos/{id}", "summary": "Edit", "request_fields": _fields(), "response_fields": [{"name": "id", "type": "integer"}, *_fields()],
             "errors": [{"status": 404, "detail": "Todo not found"}],
             "examples": [{"description": "unknown id", "request": {"id": 99999, "title": "a", "priority": "Low", "done": True}, "status": 404, "response": {"detail": "Todo not found"}}]},
            {"method": "DELETE", "path": "/api/todos/{id}", "summary": "Delete", "response_fields": [{"name": "deleted", "type": "boolean"}],
             "errors": [{"status": 404, "detail": "Todo not found"}],
             "examples": [{"description": "unknown id", "request": {"id": 99999}, "status": 404, "response": {"detail": "Todo not found"}}]},
        ],
        "tables": [{"name": "todos", "columns": [{"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY AUTOINCREMENT"}, {"name": "title", "type": "TEXT"},
                                                  {"name": "priority", "type": "TEXT"}, {"name": "done", "type": "INTEGER"}]}],
        "db_functions": [{"name": "add_todo", "signature": "add_todo(title: str, priority: str, done: bool) -> dict", "description": "Stores the given values and returns the new row"},
                         {"name": "list_todos", "signature": "list_todos() -> list[dict]", "description": "All"},
                         {"name": "update_todo", "signature": "update_todo(todo_id: int, title: str, priority: str, done: bool) -> dict | None", "description": "u"}],
    }
    d.update(over)
    return ArchitectOutput.model_validate(d)


SPEC = SpecOutput.model_validate({
    "title": "Todo app", "summary": "Tasks with priorities.",
    "resources": [{"name": "todos", "fields": [{"name": "title", "type": "string"}, {"name": "priority", "type": "string", "options": LABELS}, {"name": "done", "type": "boolean"}],
                   "operations": ["list", "create", "update", "delete"]}],
    "features": ["Form", "List with badges"]})


# --- schema checks --------------------------------------------------------------------

def test_a_good_design_passes_with_the_spec():
    assert check_architecture(design(), ["fastapi-vanilla"], SPEC) == []


def test_numeric_category_is_rejected():
    assert any("must be a string with human labels" in p for p in check_options("x", "priority", "integer", []))
    assert any("not a number" in p for p in check_options("x", "status", "number", []))
    assert check_options("x", "amount", "number", []) == []


def test_category_without_options_is_rejected():
    assert any("give it `options`" in p for p in check_options("x", "category", "string", []))
    assert check_options("x", "title", "string", []) == []


@pytest.mark.parametrize("bad", [["1", "2", "3"], ["low_priority", "high"], ["Low"], ["Low", "low"], [" Low", "High"]])
def test_labels_must_be_human(bad):
    assert check_options("x", "priority", "string", bad)


def test_example_value_must_be_one_of_the_options():
    d = design()
    d.endpoints[0].examples[0].request["priority"] = "Urgent"
    assert any("not one of its options" in p for p in check_architecture(d, ["fastapi-vanilla"]))


def test_same_field_needs_the_same_options_everywhere():
    d = design()
    d.endpoints[2].request_fields[1].options = ["Low", "High"]
    assert any("same options everywhere" in p for p in check_architecture(d, ["fastapi-vanilla"]))


def test_design_must_follow_the_spec():
    d = design()
    d.endpoints = [e for e in d.endpoints if e.method != "DELETE"]
    assert any("deleted" in p for p in check_architecture(d, ["fastapi-vanilla"], SPEC))
    d = design()
    d.endpoints[0].request_fields[1].options = ["Urgent", "Normal"]
    assert any("must have options" in p for p in check_architecture(d, ["fastapi-vanilla"], SPEC))


def test_caps_on_endpoints_and_fields():
    d = design()
    extra = [d.endpoints[1].model_copy(update={"path": f"/api/todos/x{i}"}) for i in range(3)]
    d.endpoints += extra
    assert any("at most 4" in p for p in check_architecture(d, ["fastapi-vanilla"]))
    d = design()
    d.endpoints[0].request_fields += [FieldSpec(name=f"extra{i}", type="string") for i in range(9)]
    assert any("fields" in p and "keep the 8" in p for p in check_architecture(d, ["fastapi-vanilla"]))


def test_spec_checks_and_text():
    assert check_spec(SPEC) == []
    big = SPEC.model_copy(deep=True)
    big.resources[0].fields += [SpecField(name=f"f{i}", type="string") for i in range(9)]
    assert any("keep the 8" in p for p in check_spec(big))
    bare = SPEC.model_copy(deep=True)
    bare.resources[0].fields[1].options = []
    assert check_spec(bare)
    text = spec_text(SPEC)
    assert "Low / Medium / High" in text and "Features:" in text


def test_contract_brief_shows_the_labels():
    brief = contract_brief(contract_dict(design()))
    assert 'priority: "Low" | "Medium" | "High"' in brief


def test_route_stub_uses_literal_for_options():
    from app.scaffold import route_stub

    d = design()
    src = route_stub(d, d.endpoints, None)
    assert "priority: Literal['Low', 'Medium', 'High']" in src
    compile(src, "stub", "exec")


# --- generated tests ------------------------------------------------------------------

GOOD_JS = '''
const list = document.getElementById("list");
const FIELDS = [{ name: "title", label: "Title" }, { name: "priority", label: "Priority", options: ["Low", "Medium", "High"] }, { name: "done", label: "Done", type: "checkbox" }];
async function save(id, values) {
  await fetch("/api/todos/" + id, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
  await load();
}
async function remove(id) {
  await fetch(`/api/todos/${id}`, { method: "DELETE" });
  await load();
}
async function load() {
  const res = await fetch("/api/todos");
  const data = await res.json();
  UI.renderList(list, data.items, (item) => ({
    title: "title", badges: ["priority"], done: "done",
    onToggle: (checked) => save(item.id, { ...item, done: checked }),
    actions: [
      { label: "Edit", onClick: () => UI.form("Edit task", FIELDS, item, (values) => save(item.id, values)) },
      { label: "Delete", kind: "danger", onClick: () => remove(item.id) },
    ],
  }), "No tasks yet.");
}
document.getElementById("form").addEventListener("submit", async () => {
  await fetch("/api/todos", { method: "POST", body: JSON.stringify({ title: "x", priority: "High", done: false }) });
});
load();
'''
GOOD_HTML = '<select id="priority"><option>Low</option><option>Medium</option><option>High</option></select>'


class FakeClient:
    def __init__(self, js, html):
        self.js, self.html = js, html

    def get(self, path):
        text = self.js if path.endswith("app.js") else self.html

        class R:
            pass

        r = R()
        r.text = text
        return r


def run_generated(js, html=GOOD_HTML, d=None):
    src = ui_script_test_source(d or design())
    src = src.replace("from fastapi.testclient import TestClient", "").replace("from backend.main import app", "").replace("client = TestClient(app)", "")
    ns = {"client": FakeClient(js, html)}
    exec(compile(src, "generated", "exec"), ns)
    failures = []
    for name, fn in ns.items():
        if name.startswith("test_"):
            try:
                fn()
            except AssertionError as e:
                failures.append((name, str(e)))
    return {n for n, _ in failures}, failures


def test_generated_ui_test_accepts_a_page_with_labels_and_actions():
    failed, details = run_generated(GOOD_JS)
    assert failed == set(), details


def test_enum_rendered_as_a_number_fails():
    for js, html in [(GOOD_JS.replace('"High"', "3"), "<select><option value='1'>x</option></select>"),
                     (GOOD_JS + '\nconst p = parseInt(document.getElementById("priority").value);', GOOD_HTML),
                     (GOOD_JS + "\nconst body = { priority: 2 };", GOOD_HTML)]:
        failed, _ = run_generated(js, html)
        assert "test_categories_are_shown_as_labels_not_numbers" in failed


def test_missing_item_buttons_fail():
    no_actions = GOOD_JS.replace("actions:", "other:")
    failed, _ = run_generated(no_actions)
    assert "test_every_item_endpoint_has_a_button_in_the_list" in failed


def test_a_delete_that_no_button_reaches_fails():
    js = GOOD_JS.replace('{ label: "Delete", kind: "danger", onClick: () => remove(item.id) },', "")
    failed, details = run_generated(js)
    assert "test_every_item_endpoint_has_a_button_in_the_list" in failed
    assert any("DELETE /api/todos/{id}" in msg for _, msg in details)


def test_inline_fetch_in_an_action_counts():
    js = GOOD_JS.replace("onClick: () => remove(item.id)", 'onClick: async () => { await fetch("/api/todos/" + item.id, { method: "DELETE" }); load(); }')
    failed, details = run_generated(js)
    assert failed == set(), details


def test_missing_done_toggle_fails():
    js = GOOD_JS.replace("onToggle", "other").replace("checkbox", "radio")
    failed, _ = run_generated(js)
    assert "test_every_item_endpoint_has_a_button_in_the_list" in failed


def test_a_promised_filter_must_exist():
    d = design(ui_features=["List of tasks", "Filter the list by status"])
    failed, _ = run_generated(GOOD_JS, GOOD_HTML, d)
    assert "test_the_list_can_be_filtered" in failed
    failed, _ = run_generated(GOOD_JS + " const shown = data.items.filter((i) => i.done);", GOOD_HTML, d)
    assert failed == set()


def test_no_item_endpoints_no_action_test():
    d = design()
    d.endpoints = [e for e in d.endpoints if "{" not in e.path]
    failed, _ = run_generated("fetch('/api/todos'); priority High Low Medium", GOOD_HTML, d)
    assert "test_every_item_endpoint_has_a_button_in_the_list" not in failed


def test_edge_tests_cover_update_and_delete():
    src = edge_test_source(design())
    assert "updates_the_item" in src and "removes_the_item" in src
    compile(src, "edge", "exec")


# --- the UI kit ------------------------------------------------------------------------

def test_ui_kit_form_toggle_and_tones():
    kit = Path(__file__).parents[1] / "app" / "presets" / "fastapi_vanilla" / "skeleton" / "static" / "ui-kit.js"
    out = subprocess.run(["node", str(Path(__file__).parent / "js" / "kit_enrich.mjs"), str(kit)], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    assert "OK" in out.stdout, out.stdout


# --- failures the engineer can read ----------------------------------------------------

FIXTURE = Path(__file__).parent / "fixtures_500_traceback.txt"  # real pytest output of a route that raised AttributeError inside FastAPI


def test_digest_names_the_exception_and_the_project_line_for_a_500():
    from app.tools import _FINAL_LINE, failure_digest

    out = FIXTURE.read_text(encoding="utf-8", errors="replace")
    digest = failure_digest(out)
    assert "AttributeError: 'float' object has no attribute 'strip'" in digest
    assert "calculations.py:28" in digest and "starlette" not in digest
    assert _FINAL_LINE.findall(out)[-1].endswith("in 1.54s")


def test_the_engineers_observation_starts_with_what_failed():
    from app.agent.actions import Action
    from app.agent.loop import _step
    from app.tools import ToolResult, failure_digest

    out = FIXTURE.read_text(encoding="utf-8", errors="replace")
    tr = ToolResult(False, out, {"passed": False, "digest": failure_digest(out)})
    step = _step(1, Action(thought="t", action="run_tests"), tr, False)
    text = step.observation["content"]
    assert "What failed (read this first)" in text.split("\n", 2)[1] + text[:200] or "What failed" in text[:200]
    assert "AttributeError: 'float' object has no attribute 'strip'" in text[:600]


def test_server_assigned_ids_are_checked_for_presence_not_value():
    """Regression: an Architect example expecting id 2 or 3 for a POST can never pass, because every test starts with an empty database."""
    from app.contract_tests import api_test_source

    d = design()
    d.endpoints[0].examples[0].response["id"] = 2
    src = api_test_source(d)
    assert "assert 'id' in data" in src
    assert "data['id'] ==" not in src


def test_acceptance_may_only_name_errors_the_contract_lists():
    """Regression (calculator): 'POST with an empty a returns 400 {detail: A must not be empty}' was invented, the engineer coded it, and 0 was rejected."""
    from app.schemas import TaskSpec, check_acceptance

    d = design()
    d.endpoints[0].errors = []
    bad = TaskSpec(id="t2", title="x", owner="backend", files=["backend/api/x.py"],
                   acceptance=['POST with an empty a returns 400 {"detail": "A must not be empty"}', "POST returns 201"])
    assert any("not in the API contract" in p for p in check_acceptance(bad, d.endpoints))
    listed = d.endpoints[2]  # PUT lists 404 'Todo not found'
    ok = TaskSpec(id="t2", title="x", owner="backend", files=["backend/api/x.py"],
                  acceptance=['PUT of an unknown id returns 404 {"detail": "Todo not found"}', "missing title is answered with 422"])
    assert check_acceptance(ok, [listed]) == []
    assert check_acceptance(TaskSpec(id="t3", title="x", owner="backend", files=["backend/api/x.py"], acceptance=["returns 409 when full"]), [listed])


# --- the generated starting page -------------------------------------------------------

def _calc_design():
    ops = {"name": "operation", "type": "string", "options": ["add", "subtract", "multiply", "divide"]}
    row = [{"name": "id", "type": "integer"}, {"name": "a", "type": "number"}, {"name": "b", "type": "number"}, ops, {"name": "result", "type": "number"}]
    return ArchitectOutput.model_validate({
        "preset": "fastapi-vanilla", "architecture": "x", "ui_features": ["Calculate form", "History list", "Clear history button"],
        "endpoints": [
            {"method": "POST", "path": "/api/calculations", "summary": "s", "response_status": 201,
             "request_fields": [{"name": "a", "type": "number"}, {"name": "b", "type": "number"}, ops], "response_fields": row, "errors": [{"status": 400, "detail": "Division by zero"}],
             "examples": [{"description": "adds", "request": {"a": 5, "b": 3, "operation": "add"}, "status": 201, "response": {"result": 8}}]},
            {"method": "GET", "path": "/api/calculations", "summary": "s", "response_fields": [{"name": "items", "type": "array"}], "examples": []},
            {"method": "DELETE", "path": "/api/calculations", "summary": "s", "response_fields": [{"name": "cleared", "type": "boolean"}], "examples": []}]})


def _node_check(js, tmp_path):
    import shutil

    if not shutil.which("node"):
        return
    f = tmp_path / "app.js"
    f.write_text(js, encoding="utf-8")
    out = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_generated_page_passes_the_generated_ui_tests_for_a_todo_app(tmp_path):
    from app.uistub import page_stub, script_stub

    d = design(ui_features=["Form", "List of tasks", "Filter the list by status"])
    js, html = script_stub(d), page_stub(d, "Todo app")
    failed, details = run_generated(js, html, d)
    assert failed == set(), details
    _node_check(js, tmp_path)
    assert "<option>Low</option><option>Medium</option><option>High</option>" in html
    assert 'id="filter"' in html and "UI.form(" in js and "onToggle" in js and 'method: "DELETE"' in js and 'method: "PUT"' in js


def test_generated_page_passes_the_generated_ui_tests_for_a_calculator(tmp_path):
    from app.uistub import page_stub, script_stub

    d = _calc_design()
    js, html = script_stub(d), page_stub(d)
    failed, details = run_generated(js, html, d)
    assert failed == set(), details
    _node_check(js, tmp_path)
    assert 'id="result"' in html and 'id="clear"' in html and "UI.symbol" in js and "UI.form" not in js  # no item endpoints -> no edit dialog


def test_a_design_that_is_not_a_list_and_add_app_gets_no_stub():
    from app.uistub import script_stub

    d = design()
    d.endpoints = [e for e in d.endpoints if e.method != "POST"]
    assert script_stub(d) is None


def test_plan_normalization_keeps_the_first_owner_of_a_file_and_drops_emptied_tasks():
    """Regression: the Planner sent 'static/app.js in both t4 and t5' three times in a row."""
    from app.schemas import PlannerOutput, normalize_plan

    task = lambda i, owner, files, deps=(): {"id": i, "title": i, "owner": owner, "files": files, "depends_on": list(deps), "acceptance": ["x"]}  # noqa: E731
    p = PlannerOutput.model_validate({"tasks": [
        task("t1", "database", ["database/x.py"]), task("t2", "backend", ["backend/api/x.py"], ["t1"]),
        task("t3", "frontend", ["static/index.html"]), task("t4", "frontend", ["static/app.js"], ["t3"]),
        task("t5", "frontend", ["static/app.js"], ["t4"]), task("t6", "frontend", ["static/style.css", "static/app.js"], ["t5"])]})
    out = normalize_plan(p)
    assert [t.id for t in out.tasks] == ["t1", "t2", "t3", "t4", "t6"]
    assert out.tasks[-1].files == ["static/style.css"]
    assert out.tasks[-1].depends_on == ["t4"]  # t5 was dropped: t6 now waits for what t5 waited for



def test_sql_keywords_are_not_allowed_as_field_or_column_names():
    """Regression (contact book chip): a field called `group` made the generated CREATE TABLE invalid."""
    assert check_options("x", "group", "string", ["Family", "Friends", "Work"])
    assert any("group_name" in p for p in check_options("x", "group", "string", []))
    assert check_options("x", "group_name", "string", ["Family", "Friends"]) == []
    d = design()
    d.tables[0].columns[1].name = "order"
    assert any("SQL keyword" in p for p in check_architecture(d, ["fastapi-vanilla"]))
    bad = SPEC.model_copy(deep=True)
    bad.resources[0].fields[0].name = "group"
    assert any("SQL keyword" in p for p in check_spec(bad))
