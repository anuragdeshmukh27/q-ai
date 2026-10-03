"""Contract-derived starting files, so a 7B engineer fills small gaps instead of writing a file from nothing.

Everything here is deterministic: names, paths, status codes, request/response models and SQL come straight from
the Architect's design. The engineer replaces the `raise NotImplementedError` bodies.
"""
from __future__ import annotations

import re

from .schemas import ArchitectOutput, Endpoint, FieldSpec

PY_TYPES = {"string": "str", "number": "float", "integer": "int", "boolean": "bool", "array": "list", "object": "dict"}  # arrays carry no item type in the contract: tags are strings as often as objects


def _words(path: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", re.sub(r"\{[^}]*\}", "", path.lower())) if w and w != "api"]


def _camel(parts: list[str]) -> str:
    return "".join(p.capitalize() for p in parts)


def _model(name: str, fields: list[FieldSpec]) -> str:
    # a categorical field is a Literal of its labels, so FastAPI answers 422 for a value that is not one of them
    body = "\n".join(f"    {f.name}: " + (f"Literal[{', '.join(repr(o) for o in f.options)}]" if f.options and f.type == "string" else PY_TYPES[f.type]) for f in fields)
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


def db_stub(design: ArchitectOutput) -> str:
    cols = json_columns(design)
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
    for f in design.db_functions:
        out += [
            "",
            f"def {f.signature.strip()}:",
            f'    """{f.description}"""',
            f"    # with connect(SCHEMA) as conn:  ... use ? placeholders, return {shape}",
            "    raise NotImplementedError",
            "",
        ]
    return "\n".join(out).rstrip() + "\n"


def _route(e: Endpoint, response_model: str | None, request_model: str | None, func: str) -> str:
    params = re.findall(r"\{(\w+)\}", e.path)
    # GET/DELETE have no body: their request fields are query parameters, i.e. plain function arguments (scalar types only).
    query = [f"{f.name}: {PY_TYPES[f.type]}" for f in e.request_fields if e.method in ("GET", "DELETE") and f.name not in params and f.type in ("string", "number", "integer", "boolean")]
    args = [f"{p}: int" for p in params] + query + ([f"req: {request_model}"] if request_model else [])
    deco_extra = (f", status_code={e.response_status}" if e.response_status != 200 else "") + (f", response_model={response_model}" if response_model else "")
    notes = [f"# {e.summary}"] + [f'# error: raise HTTPException(status_code={x.status}, detail="{x.detail}")' for x in e.errors]
    body = "\n".join("    " + n for n in notes)
    return f'@router.{e.method.lower()}("{e.path}"{deco_extra})\ndef {func}({", ".join(args)}):\n{body}\n    raise NotImplementedError\n'


def route_stub(design: ArchitectOutput, endpoints: list[Endpoint], db_module: str | None) -> str:
    out = ['"""Route stubs generated from the API contract. Fill in the bodies; keep paths, models and status codes."""',
           "import json", "import operator", "import re", "from typing import Literal", "from fastapi import APIRouter, HTTPException", "from pydantic import BaseModel"]
    if db_module:
        out.append(f"from database import {db_module} as db")
    out += ["", "router = APIRouter()", ""]
    for e in endpoints:
        by = re.findall(r"\{(\w+)\}", e.path)
        base = _camel([e.method.lower()] + _words(e.path) + (["by"] + by if by else []))
        func = "handle_" + "_".join([e.method.lower()] + _words(e.path) + (["by"] + by if by else []))
        req = res = None
        if e.method in ("POST", "PUT", "PATCH") and e.request_fields:
            req = base + "Request"
            out += [_model(req, e.request_fields)]
        if e.response_fields:
            res = base + "Response"
            out += [_model(res, e.response_fields)]
        out += [_route(e, res, req, func)]
    return "\n".join(out).rstrip() + "\n"


def endpoints_for_task(design: ArchitectOutput, task: dict, same_owner_tasks: int = 1) -> list[Endpoint]:
    """The endpoints a backend task is about. With a single backend task: all of them. Otherwise those named in its title/acceptance."""
    if same_owner_tasks <= 1:
        return design.endpoints
    text = " ".join([task["title"], *task["acceptance"]])
    named = [e for e in design.endpoints if e.path in text or e.path.split("{")[0].rstrip("/") + "/" in text]
    return named or design.endpoints
