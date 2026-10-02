"""Contract-derived starting files, so a 7B engineer fills small gaps instead of writing a file from nothing.

Everything here is deterministic: names, paths, status codes, request/response models and SQL come straight from
the Architect's design. The engineer replaces the `raise NotImplementedError` bodies.
"""
from __future__ import annotations

import re

from .schemas import ArchitectOutput, Endpoint, FieldSpec

PY_TYPES = {"string": "str", "number": "float", "integer": "int", "boolean": "bool", "array": "list[dict]", "object": "dict"}


def _words(path: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", re.sub(r"\{[^}]*\}", "", path.lower())) if w and w != "api"]


def _camel(parts: list[str]) -> str:
    return "".join(p.capitalize() for p in parts)


def _model(name: str, fields: list[FieldSpec]) -> str:
    body = "\n".join(f"    {f.name}: {PY_TYPES[f.type]}" for f in fields)
    return f"class {name}(BaseModel):\n{body}\n"


def schema_sql(design: ArchitectOutput) -> str:
    stmts = []
    for t in design.tables:
        cols = ", ".join(f"{c.name} {c.type} {c.constraints}".strip() for c in t.columns)
        stmts.append(f"CREATE TABLE IF NOT EXISTS {t.name} ({cols});")
    return " ".join(stmts)


def db_stub(design: ArchitectOutput) -> str:
    out = [
        '"""Data access functions (stubs generated from the database schema). Fill in the bodies."""',
        "from database.connection import connect",
        "",
        f'SCHEMA = "{schema_sql(design)}"',
        "",
    ]
    for f in design.db_functions:
        out += [
            "",
            f"def {f.signature.strip()}:",
            f'    """{f.description}"""',
            "    # with connect(SCHEMA) as conn:  ... use ? placeholders, return dict(row) / [dict(r) for r in rows]",
            "    raise NotImplementedError",
            "",
        ]
    return "\n".join(out).rstrip() + "\n"


def _route(e: Endpoint, response_model: str | None, request_model: str | None, func: str) -> str:
    params = re.findall(r"\{(\w+)\}", e.path)
    args = [f"{p}: int" for p in params] + ([f"req: {request_model}"] if request_model else [])
    deco_extra = (f", status_code={e.response_status}" if e.response_status != 200 else "") + (f", response_model={response_model}" if response_model else "")
    notes = [f"# {e.summary}"] + [f'# error: raise HTTPException(status_code={x.status}, detail="{x.detail}")' for x in e.errors]
    body = "\n".join("    " + n for n in notes)
    return f'@router.{e.method.lower()}("{e.path}"{deco_extra})\ndef {func}({", ".join(args)}):\n{body}\n    raise NotImplementedError\n'


def route_stub(design: ArchitectOutput, endpoints: list[Endpoint], db_module: str | None) -> str:
    out = ['"""Route stubs generated from the API contract. Fill in the bodies; keep paths, models and status codes."""',
           "import operator", "from fastapi import APIRouter, HTTPException", "from pydantic import BaseModel"]
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
