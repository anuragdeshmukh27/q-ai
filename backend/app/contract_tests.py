"""Tests generated from the API contract's examples (deterministic; no model writes them).

`api_test_source` -> tests/test_contract_api.py : every example becomes a request with exact status/value assertions.
`ui_test_source`  -> tests/test_contract_ui.py  : the page is served and its script calls every endpoint of the contract.
In P3 the QA agent takes over `tests/**` and extends these.
"""
from __future__ import annotations

import re

from .schemas import ArchitectOutput, Endpoint


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "case"


def _test_for(e: Endpoint, i: int, ex) -> list[str]:
    params = re.findall(r"\{(\w+)\}", e.path)
    path = e.path
    for p in params:
        path = path.replace("{" + p + "}", str(ex.request.get(p)))
    rest = {k: v for k, v in ex.request.items() if k not in params}
    verb = e.method.lower()
    name = f"test_{verb}_{_slug(e.path)}_{i}_{_slug(ex.description)}"
    call = f"client.{verb}({path!r}"
    if rest:
        call += f", {'params' if e.method in ('GET', 'DELETE') else 'json'}={rest!r}"
    call += ")"
    lines = [f"def {name}():", f"    r = {call}", f"    assert r.status_code == {ex.status}, r.text"]
    if ex.status < 300:
        lines.append("    data = r.json()")
        lines += [f"    assert {f.name!r} in data" for f in e.response_fields]
        for k, v in ex.response.items():
            lines.append(f"    assert data[{k!r}] == pytest.approx({v!r})" if isinstance(v, (int, float)) and not isinstance(v, bool)
                         else f"    assert data[{k!r}] == {v!r}")
    else:
        for k, v in ex.response.items():
            lines.append(f"    assert r.json()[{k!r}] == {v!r}")
    return lines + ["", ""]


def api_test_source(design: ArchitectOutput) -> str:
    out = ['"""Contract tests generated from the API contract examples. Do not edit; fix the code instead."""',
           "import pytest", "from fastapi.testclient import TestClient", "", "from backend.main import app", "", "client = TestClient(app)", "", ""]
    for e in design.endpoints:
        for i, ex in enumerate(e.examples, 1):
            out += _test_for(e, i, ex)
    return "\n".join(out).rstrip() + "\n"


def ui_test_source(design: ArchitectOutput) -> str:
    paths = sorted({re.sub(r"/\{.*$", "", e.path) for e in design.endpoints})
    out = ['"""UI smoke tests generated from the API contract. Do not edit; fix the page instead."""',
           "from fastapi.testclient import TestClient", "", "from backend.main import app", "", "client = TestClient(app)", "", "",
           "def test_page_is_served_and_loads_its_script():",
           "    r = client.get('/')",
           "    assert r.status_code == 200 and '/static/app.js' in r.text and '/static/style.css' in r.text",
           "", "",
           "def test_script_is_served_and_calls_every_endpoint():",
           "    js = client.get('/static/app.js').text",
           "    assert 'fetch' in js"]
    out += [f"    assert {p!r} in js" for p in paths]
    return "\n".join(out) + "\n"
