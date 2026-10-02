"""Tests generated from the API contract's examples (deterministic; no model writes them).

These are the QA agent's test suite (it "writes" them through the sandboxed tool layer):
`api_test_source`         -> tests/api/test_contract_api.py : every example becomes a request with exact status/value assertions.
`ui_page_test_source`     -> tests/ui/test_page.py          : the page is served and links its stylesheet and script.
`ui_script_test_source`   -> tests/ui/test_script.py        : the script calls every endpoint of the contract.
`edge_test_source`        -> tests/qa/test_edge_cases.py    : invalid input (missing / mistyped fields -> 422) and persistence round trips.
The first three exist before the engineers start; the edge cases are added when QA tests the merged app.
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


def ui_page_test_source(design: ArchitectOutput) -> str:
    return "\n".join([
        '"""UI smoke test generated from the API contract. Do not edit; fix the page instead."""',
        "from fastapi.testclient import TestClient", "", "from backend.main import app", "", "client = TestClient(app)", "", "",
        "def test_page_is_served_and_loads_its_assets():",
        "    r = client.get('/')",
        "    assert r.status_code == 200 and '/static/app.js' in r.text and '/static/style.css' in r.text",
        "", "",
        "def test_assets_are_served():",
        "    assert client.get('/static/style.css').status_code == 200",
        "    assert client.get('/static/app.js').status_code == 200",
    ]) + "\n"


def ui_script_test_source(design: ArchitectOutput) -> str:
    paths = sorted({re.sub(r"/\{.*$", "", e.path) for e in design.endpoints})
    out = ['"""UI script test generated from the API contract. Do not edit; fix the script instead."""',
           "from fastapi.testclient import TestClient", "", "from backend.main import app", "", "client = TestClient(app)", "", "",
           "def test_script_calls_every_endpoint():",
           "    js = client.get('/static/app.js').text",
           "    assert 'fetch' in js"]
    out += [f"    assert {p!r} in js" for p in paths]
    return "\n".join(out) + "\n"


# --- QA edge cases ---------------------------------------------------------------------------------------------------

def _payload(e: Endpoint) -> dict | None:
    """A request body known to be valid: the first success example that sends every request field."""
    names = {f.name for f in e.request_fields}
    for ex in e.examples:
        if ex.status < 300 and names <= set(ex.request):
            return {k: v for k, v in ex.request.items() if k in names}
    return None


def edge_test_source(design: ArchitectOutput) -> str:
    out = ['"""QA edge cases generated from the API contract. Do not edit; fix the code instead."""',
           "import pytest", "from fastapi.testclient import TestClient", "", "from backend.main import app", "", "client = TestClient(app)", "", ""]
    posts = []
    for e in design.endpoints:
        if e.method not in ("POST", "PUT", "PATCH") or not e.request_fields or "{" in e.path:
            continue
        payload = _payload(e)
        if payload is None:
            continue
        verb, slug = e.method.lower(), _slug(e.path)
        posts.append((e, payload))
        out += [f"def test_{verb}_{slug}_rejects_empty_body():", f"    assert client.{verb}({e.path!r}, json={{}}).status_code == 422", "", ""]
        for f in e.request_fields:
            bad = {k: v for k, v in payload.items() if k != f.name}
            out += [f"def test_{verb}_{slug}_rejects_missing_{_slug(f.name)}():",
                    f"    assert client.{verb}({e.path!r}, json={bad!r}).status_code == 422", "", ""]
            if f.type in ("number", "integer"):
                wrong = {**payload, f.name: "not a number"}
                out += [f"def test_{verb}_{slug}_rejects_non_numeric_{_slug(f.name)}():",
                        f"    assert client.{verb}({e.path!r}, json={wrong!r}).status_code == 422", "", ""]
    lists = [(e, f.name) for e in design.endpoints if e.method == "GET" and "{" not in e.path for f in e.response_fields if f.type == "array"]
    clears = [e for e in design.endpoints if e.method == "DELETE" and "{" not in e.path]
    for post, payload in posts[:1]:
        for get, key in lists[:1]:
            out += [f"def test_posted_item_shows_up_in_the_list():",
                    f"    r = client.{post.method.lower()}({post.path!r}, json={payload!r})",
                    "    assert r.status_code < 300, r.text",
                    f"    items = client.get({get.path!r}).json()[{key!r}]",
                    "    assert len(items) == 1",
                    "    for k, v in " + repr(payload) + ".items():",
                    "        if k in items[0]:",
                    "            assert items[0][k] == (pytest.approx(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)",
                    "", ""]
            for c in clears[:1]:
                out += [f"def test_clearing_empties_the_list():",
                        f"    client.{post.method.lower()}({post.path!r}, json={payload!r})",
                        f"    r = client.delete({c.path!r})",
                        "    assert r.status_code < 300, r.text",
                        f"    assert client.get({get.path!r}).json()[{key!r}] == []",
                        "", ""]
    return "\n".join(out).rstrip() + "\n"
