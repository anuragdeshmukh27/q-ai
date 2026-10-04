"""A test for every gap, generated from the reconstructed contract (no model writes these): tests/q_finish/test_gaps.py in the imported project.

- a placeholder route or a missing endpoint: the route is registered, and a request with a sample body is answered below 500 (a NotImplementedError is a 500);
- a placeholder function: its body is no longer a placeholder (the same rule the analyst used);
- a TODO or FIXME comment: the comment is gone from the file;
- a failing test of the project: it is the project's own test, nothing new is generated.
The tests need the application object (module:variable) and its framework's test client; they use whatever database the project uses (the copy is disposable).
"""
from __future__ import annotations

import re

from .analyze import Analysis, Gap

HELPERS = '''
import ast
import re
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def norm(path):
    return re.sub(r"\\{[^}]*\\}|<[^>]*>", "{}", path)


def is_stub(fn, source=""):
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body:
        return True

    def trivial(st):
        if isinstance(st, ast.Pass) or (isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant)):
            return True
        if isinstance(st, ast.Raise):
            return "NotImplemented" in (ast.unparse(st.exc) if st.exc else "")
        if isinstance(st, ast.Return):
            return st.value is None or (isinstance(st.value, ast.Constant) and st.value.value is None)
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and ast.unparse(st.value.func).endswith("abort") and st.value.args and ast.unparse(st.value.args[0]) == "501":
            return True
        return False

    return all(trivial(st) for st in body)


LAST = {"error": ""}


def describe(e):
    where = next((f"{Path(x.filename).name}:{x.lineno} `{x.line}`" for x in reversed(traceback.extract_tb(e.__traceback__)) if "site-packages" not in x.filename), "")
    return f"{type(e).__name__}: {e} at {where}"


def function_is_a_placeholder(file, name):
    tree = ast.parse((ROOT / file).read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    assert fns, f"{name}() is gone from {file}: keep the function and write its body"
    return all(is_stub(f) for f in fns)
'''

FASTAPI = '''
from fastapi.testclient import TestClient

from {module} import {var} as app

_client = TestClient(app, raise_server_exceptions=True)


def routes():
    paths = app.openapi().get("paths", {{}})  # the schema lists included routers in every FastAPI version
    return {{(m.upper(), norm(p)) for p, ops in paths.items() for m in ops if m.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE")}}


def call(method, path, body=None):
    LAST["error"] = ""
    try:
        r = _client.request(method, path, json=body) if body is not None else _client.request(method, path)
    except Exception as e:  # the server's own exception: the engineer needs to read it, not just "500"
        LAST["error"] = describe(e)
        return 500
    return r.status_code


def call_json(method, path, body=None):
    try:
        r = _client.request(method, path, json=body) if body is not None else _client.request(method, path)
        return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else None)
    except Exception as e:
        LAST["error"] = describe(e)
        return 500, None
'''

FLASK = '''
from {module} import {var} as app


def routes():
    return {{(m, norm(r.rule)) for r in app.url_map.iter_rules() for m in r.methods if m not in ("HEAD", "OPTIONS")}}


def call(method, path, body=None):
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = True
    LAST["error"] = ""
    try:
        with app.test_client() as c:
            r = c.open(path, method=method, json=body) if body is not None else c.open(path, method=method)
            return r.status_code
    except Exception as e:
        LAST["error"] = describe(e)
        return 500


def call_json(method, path, body=None):
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = True
    try:
        with app.test_client() as c:
            r = c.open(path, method=method, json=body) if body is not None else c.open(path, method=method)
            return r.status_code, r.get_json(silent=True)
    except Exception as e:
        LAST["error"] = describe(e)
        return 500, None
'''


def sample_value(key: str, annotation: str = ""):
    k = key.lower()
    if "int" in annotation or re.search(r"(^|_)(id|count|capacity|quantity|qty|age|year|stock|seats)$", k):
        return 1
    if "float" in annotation or re.search(r"amount|price|fare|fee|cost|total|rate|score", k):
        return 10.5
    if "bool" in annotation:
        return True
    if "email" in k:
        return "sample@example.com"
    if "date" in k:
        return "2026-01-15"
    return "sample"


def esc(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")  # the generated message is an f-string: a path like /events/{id} must not be read as a name


def unknown_path(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "999999", path)


def sample_path(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "1", path)


def _body(g: Gap, annotations: dict) -> dict | None:
    if g.method not in ("POST", "PUT", "PATCH"):
        return None
    return {k: sample_value(k, annotations.get(k, "")) for k in g.body_keys} or {}


def gap_tests(a: Analysis, gaps: list[Gap]) -> str:
    ann = {r.path + r.method: r.body for r in a.routes}
    out = ['"""Generated by Q from the gap report: one test per gap. Do not edit; finish the project instead."""', HELPERS, (FASTAPI if a.framework == "fastapi" else FLASK).format(module=a.module, var=a.var), ""]
    for g in gaps:
        n = g.id
        if g.kind in ("todo_body", "missing_endpoint", "readme_feature") and g.method:
            body = _body(g, ann.get(g.path + g.method, {}))
            out += [f"def test_{n}_{g.method.lower()}_route_is_there_and_does_not_crash():",
                    f"    assert ({g.method!r}, norm({g.path!r})) in routes(), 'the route {g.method} {g.path} is not registered'",
                    f"    status = call({g.method!r}, {sample_path(g.path)!r}{', ' + repr(body) if body is not None else ''})",
                    f"    assert status < 500 and status != 405, f'{g.method} {esc(g.path)} answered {{status}}: ' + LAST['error']", "", ""]
            if re.search(r"404|not found|does not exist", g.detail or "", re.I) and "{" in g.path:
                out += [f"def test_{n}_unknown_id_answers_404():",
                        f"    status = call({g.method!r}, {unknown_path(g.path)!r}{', ' + repr(body) if body is not None else ''})",
                        f"    assert status == 404, f'{g.method} {esc(g.path)} for an id that does not exist must answer 404, it answered {{status}}: ' + LAST['error']", "", ""]
        if g.kind in ("missing_endpoint", "todo_body", "readme_feature") and g.reads and g.method == "GET" and "{" not in g.path:
            out += [f"def test_{n}_answers_with_the_keys_the_page_reads():",
                    f"    status, data = call_json('GET', {g.path!r})",
                    f"    assert status == 200 and isinstance(data, dict), 'GET {esc(g.path)} must answer 200 with a JSON object, it answered ' + str(status) + ' ' + LAST['error']",
                    f"    missing = [k for k in {g.reads!r} if k not in data]",
                    f"    assert not missing, 'the page reads these keys of the answer of GET {esc(g.path)} but they are missing: ' + ', '.join(missing)", "", ""]
        if g.kind == "todo_body" and g.function:
            fn = re.sub(r"[^a-zA-Z0-9_]", "_", g.function)
            out += [f"def test_{n}_{fn}_is_implemented():", f"    assert not function_is_a_placeholder({g.file!r}, {g.function!r}), '{g.function}() is still a placeholder'", "", ""]
        elif g.kind == "todo_comment" and g.text:
            out += [f"def test_{n}_the_todo_is_done():", f"    assert {g.text!r} not in (ROOT / {g.file!r}).read_text(encoding='utf-8'), 'the comment is still in {g.file}: do what it says, then remove it'", "", ""]
    return "\n".join(out).rstrip() + "\n"
