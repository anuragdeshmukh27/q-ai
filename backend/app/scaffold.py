"""Contract-derived starting files, so a 7B engineer fills small gaps instead of writing a file from nothing.

Everything here is deterministic: names, paths, status codes, request/response models and SQL come straight from
the Architect's design. The engineer replaces the `raise NotImplementedError` bodies.
"""
from __future__ import annotations

import re

from .schemas import ArchitectOutput, Endpoint, FieldSpec, ResourceInfo, _resource, declares_blank_error, required_text

PY_TYPES = {"string": "str", "number": "float", "integer": "int", "boolean": "bool", "array": "list", "object": "dict"}  # arrays carry no item type in the contract: tags are strings as often as objects


def _words(path: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", re.sub(r"\{[^}]*\}", "", path.lower())) if w and w != "api"]


def _camel(parts: list[str]) -> str:
    return "".join(p.capitalize() for p in parts)


def _model(name: str, fields: list[FieldSpec], request: bool = False) -> str:
    # a categorical field is a Literal of its labels, so FastAPI answers 422 for a value that is not one of them;
    # in a request, a required text field is `Required` (backend/validation.py): empty or only spaces is a 400 with a message, for parents and children alike
    def kind(f: FieldSpec) -> str:
        if request and required_text(f):
            return "Required"
        return f"Literal[{', '.join(repr(o) for o in f.options)}]" if f.options and f.type == "string" else PY_TYPES[f.type]

    body = "\n".join(f"    {f.name}: {kind(f)}" for f in fields)
    return f"class {name}(BaseModel):\n{body}\n"


def schema_sql(design: ArchitectOutput) -> str:
    stmts = []
    for t in design.tables:
        cols = ", ".join(f"{c.name} {c.type} {c.constraints}".strip() for c in t.columns)
        stmts.append(f"CREATE TABLE IF NOT EXISTS {t.name} ({cols});")
    return " ".join(stmts)


def json_columns(design: ArchitectOutput) -> list[str]:
    """Table columns that hold lists: the contract says the field is an array, but SQLite only stores text, so they are kept as JSON text."""
    arrays = {f.name for e in design.endpoints for f in [*e.request_fields, *e.response_fields] if f.type == "array"}
    return [c.name for t in design.tables for c in t.columns if c.name in arrays]


def functions_of(design: ArchitectOutput, ri: ResourceInfo):
    """The db functions that belong to one resource's table (its own module)."""
    s, p = ri.singular, ri.name
    names = {f"add_{s}", f"get_{s}", f"list_{p}", f"update_{s}", f"delete_{s}", *(f"{a.name}_{s}" for a in ri.actions)}
    return [f for f in design.db_functions if f.name in names]


def db_stub(design: ArchitectOutput, table: str | None = None, fill: bool = False) -> str:
    """The data access stub. With `table` (a relational design), only that table's functions; SCHEMA still creates every table so a parent can delete its children.
    With `fill`, the bodies are written too (the contract repair: what the engineer should have written, from the resource model)."""
    cols = json_columns(design)
    ri = next((r for r in design.resources if r.name == table), None)
    funcs = functions_of(design, ri) if ri else design.db_functions
    out = [
        '"""Data access functions (stubs generated from the database schema). Fill in the bodies."""',
        "import json",
        "",
        "from database.connection import connect",
        "",
        f'SCHEMA = "{schema_sql(design)}"',
        "",
    ]
    if cols:
        out += [f"JSON_COLUMNS = {tuple(cols)!r}  # list-valued columns: store them with json.dumps(...)", "", "",
                "def _row(r) -> dict:", '    """A row as a dict; list-valued columns (stored as JSON text) are turned back into lists."""',
                "    d = dict(r)", "    for c in JSON_COLUMNS:", "        if isinstance(d.get(c), str):", "            d[c] = json.loads(d[c])", "    return d", ""]
    shape = "_row(row) / [_row(r) for r in rows]" if cols else "dict(row) / [dict(r) for r in rows]"
    for f in funcs:
        body = db_body(design, ri, f.name) if fill and ri else None
        out += [
            "",
            f"def {f.signature.strip()}:",
            f'    """{f.description}"""',
            *(["    " + line for line in body] if body else [f"    # with connect(SCHEMA) as conn:  ... use ? placeholders, return {shape}", "    raise NotImplementedError"]),
            "",
        ]
    return "\n".join(out).rstrip() + "\n"


def db_body(design: ArchitectOutput, ri: ResourceInfo, name: str) -> list[str] | None:
    """The body of one data access function of a relational resource, in plain sqlite3 with ? placeholders (None for a name it does not know)."""
    p, s = ri.name, ri.singular
    cols = ([ri.fk] if ri.fk else []) + [f.name for f in ri.fields]
    child = next((r for r in design.resources if r.parent == ri.name), None)

    def select(arg: str) -> str:
        return f'conn.execute("SELECT * FROM {p} WHERE id = ?", ({arg},)).fetchone()'

    if name == f"add_{s}":
        marks = ", ".join("?" for _ in cols)
        return ["with connect(SCHEMA) as conn:", f'    cur = conn.execute("INSERT INTO {p} ({", ".join(cols)}) VALUES ({marks})", ({", ".join(cols)},))',
                f"    row = {select('cur.lastrowid')}", "    return dict(row)"]
    if name == f"get_{s}":
        return ["with connect(SCHEMA) as conn:", f"    row = {select(s + '_id')}", "    return dict(row) if row else None"]
    if name == f"list_{p}":
        where = f" WHERE {ri.fk} = ?" if ri.fk else ""
        params = f"({ri.fk},)" if ri.fk else "()"
        order = [f'    order = "{ri.top_by} DESC, id DESC" if sort == "top" else "id DESC"'] if ri.sorts else ['    order = "id DESC"']
        return ["with connect(SCHEMA) as conn:", *order, f'    rows = conn.execute("SELECT * FROM {p}{where} ORDER BY " + order, {params}).fetchall()', "    return [dict(r) for r in rows]"]
    if name == f"update_{s}":
        sets = ", ".join(f"{f.name} = ?" for f in ri.fields)
        vals = ", ".join(f.name for f in ri.fields)
        return ["with connect(SCHEMA) as conn:", f'    conn.execute("UPDATE {p} SET {sets} WHERE id = ?", ({vals}, {s}_id))', f"    row = {select(s + '_id')}",
                "    return dict(row) if row else None"]
    if name == f"delete_{s}":
        cascade = [f'    conn.execute("DELETE FROM {child.name} WHERE {child.fk} = ?", ({s}_id,))'] if child else []
        return ["with connect(SCHEMA) as conn:", *cascade, f'    cur = conn.execute("DELETE FROM {p} WHERE id = ?", ({s}_id,))', "    return cur.rowcount > 0"]
    action = next((a for a in ri.actions if name == f"{a.name}_{s}"), None)
    if action is not None:
        change = f"{action.field} + 1" if action.kind == "increment" else f"1 - {action.field}"
        return ["with connect(SCHEMA) as conn:", f'    conn.execute("UPDATE {p} SET {action.field} = {change} WHERE id = ?", ({s}_id,))', f"    row = {select(s + '_id')}",
                "    return dict(row) if row else None"]
    return None


def _route(e: Endpoint, response_model: str | None, request_model: str | None, func: str, hints: list[str] | None = None, fill: bool = False) -> str:
    params = re.findall(r"\{(\w+)\}", e.path)
    # GET/DELETE have no body: their request fields are query parameters, i.e. plain function arguments (scalar types only).
    query = [f"{f.name}: {PY_TYPES[f.type]}" for f in e.request_fields if e.method in ("GET", "DELETE") and f.name not in params and f.type in ("string", "number", "integer", "boolean") and not f.options]
    # a query field with options (sort) is optional and limited to its labels: FastAPI answers 422 for anything else
    optional = [f"{f.name}: Literal[{', '.join(repr(o) for o in f.options)}] = {f.options[0]!r}" for f in e.request_fields if e.method in ("GET", "DELETE") and f.name not in params and f.options]
    args = [f"{p}: int" for p in params] + query + ([f"req: {request_model}"] if request_model else []) + optional
    deco_extra = (f", status_code={e.response_status}" if e.response_status != 200 else "") + (f", response_model={response_model}" if response_model else "")
    notes = [f"# {e.summary}"] + [f'# error: raise HTTPException(status_code={x.status}, detail="{x.detail}")' for x in e.errors]
    notes += [f"# body: {h}" for h in hints or []]
    body = "\n".join("    " + n for n in notes)
    code = "\n".join("    " + h for h in hints) if fill and hints else "    raise NotImplementedError"  # the hints ARE the body once they are applied
    return f'@router.{e.method.lower()}("{e.path}"{deco_extra})\ndef {func}({", ".join(args)}):\n{body}\n{code}\n'


def route_stub(design: ArchitectOutput, endpoints: list[Endpoint], db_module: str | None, parent_modules: tuple[str, ...] = (), fill: bool = False) -> str:
    """The route stub of one router. With `fill`, every route of a relational design has its body from the hints (the contract repair)."""
    out = ['"""Route stubs generated from the API contract. Fill in the bodies; keep paths, models and status codes."""',
           "import json", "import operator", "import re", "from typing import Literal", "from fastapi import APIRouter, HTTPException", "from pydantic import BaseModel", "from backend.validation import Required"]
    if db_module:
        out.append(f"from database import {db_module} as db")
    out += [f"from database import {m} as {m}_db" for m in parent_modules]
    out += ["", "router = APIRouter()", ""]
    for e in endpoints:
        by = re.findall(r"\{(\w+)\}", e.path)
        base = _camel([e.method.lower()] + _words(e.path) + (["by"] + by if by else []))
        func = "handle_" + "_".join([e.method.lower()] + _words(e.path) + (["by"] + by if by else []))
        req = res = None
        if e.method in ("POST", "PUT", "PATCH") and e.request_fields:
            req = base + "Request"
            out += [_model(req, e.request_fields, request=not declares_blank_error(e))]
        if e.response_fields:
            res = base + "Response"
            out += [_model(res, e.response_fields)]
        out += [_route(e, res, req, func, _hints(design, e), fill)]
    return "\n".join(out).rstrip() + "\n"


def _hints(design: ArchitectOutput, e: Endpoint) -> list[str]:
    """For a relational design, the body of each route in plain words (the engineer writes it with `implement`; a 7B copies a hint more reliably than it invents a rule)."""
    if not design.resources:
        return []
    ri = next((r for r in design.resources if r.name == _resource(e.path, {t.name for t in design.tables})), None)
    if ri is None:
        return []
    s, p = ri.singular, ri.name
    kw = ", ".join(f"{f.name}=req.{f.name}" for f in e.request_fields if f.name != "sort")
    sort = ", sort=sort" if any(f.name == "sort" for f in e.request_fields) else ""
    nf = next((f'raise HTTPException(status_code=404, detail="{x.detail}")' for x in e.errors if x.status == 404), "")
    action = next((a for a in ri.actions if e.method == "POST" and e.path.endswith("/" + a.name)), None)
    parent = next((r for r in design.resources if r.name == ri.parent), None)
    if action is not None:
        return [f"row = db.{action.name}_{s}(id)", f"if row is None: {nf}", "return row"]
    if parent is not None and e.path.startswith(f"/api/{parent.name}/{{"):
        check = f"if {parent.name}_db.get_{parent.singular}({ri.fk}) is None: {nf}"
        if e.method == "GET":
            return [check, f'return {{"items": db.list_{p}({ri.fk}={ri.fk}{sort})}}']
        return [check, f"return db.add_{s}({ri.fk}={ri.fk}, {kw})"]
    if e.method == "GET":
        return [f'return {{"items": db.list_{p}({sort[2:]})}}']
    if e.method == "POST":
        return [f"return db.add_{s}({kw})"]
    if e.method == "PUT":
        return [f"row = db.update_{s}({s}_id=id, {kw})", f"if row is None: {nf}", "return row"]
    if e.method == "DELETE":
        return [f"if not db.delete_{s}({s}_id=id): {nf}", 'return {"deleted": True}']
    return []


def endpoints_for_task(design: ArchitectOutput, task: dict, same_owner_tasks: int = 1) -> list[Endpoint]:
    """The endpoints a backend task is about. With a single backend task: all of them. Otherwise those named in its title/acceptance."""
    if design.resources and task.get("files"):  # a relational design: the router named by the task's file owns its resource's endpoints
        name = task["files"][0].rsplit("/", 1)[-1].removesuffix(".py")
        tables = {t.name for t in design.tables}
        mine = [e for e in design.endpoints if _resource(e.path, tables) == name]
        if mine:
            return mine
    if same_owner_tasks <= 1:
        return design.endpoints
    text = " ".join([task["title"], *task["acceptance"]])
    named = [e for e in design.endpoints if e.path in text or e.path.split("{")[0].rstrip("/") + "/" in text]
    return named or design.endpoints
