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
from pathlib import Path

from .schemas import ArchitectOutput, Endpoint, declares_blank_error, required_text


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "case"


def _server_filled(key: str) -> bool:
    """Response fields whose value the server decides (timestamps, ids): a test can check they exist but not what they say.
    Every test starts with an empty database, so an Architect example that expects id 2 or 3 could never pass."""
    return key == "id" or key.endswith("_id") or key.endswith(("_at", "_on", "_time", "_date")) or key in ("timestamp", "created", "updated", "date", "time", "datetime")


def _seed_for(design: ArchitectOutput, e: Endpoint) -> Endpoint | None:
    """The POST that creates the thing a `/{id}` endpoint works on (same collection path, or any valid POST as a fallback)."""
    posts = [p for p in design.endpoints if p.method == "POST" and "{" not in p.path and _payload(p) is not None]
    base = e.path.split("/{")[0]
    return next((p for p in posts if p.path == base), posts[0] if posts else None)


def _test_for(e: Endpoint, i: int, ex, design: ArchitectOutput | None = None) -> list[str]:
    params = re.findall(r"\{(\w+)\}", e.path)
    path = e.path
    for p in params:
        path = path.replace("{" + p + "}", str(ex.request.get(p)))
    rest = {k: v for k, v in ex.request.items() if k not in params}
    verb = e.method.lower()
    name = f"test_{verb}_{_slug(e.path)}_{i}_{_slug(ex.description)}"
    call = f"client.{verb}({path!r}"
    lists = ex.status < 300 and any(isinstance(v, list) and v for v in ex.response.values())  # a populated list in the example
    seed = _seed_for(design, e) if design is not None and (params or lists) and ex.status < 300 and e.method != "POST" else None
    if seed is not None and params:
        # A success case on `/{id}` needs a row to exist: create one through the contract's own POST and use the id it returns.
        key = next((f.name for f in seed.response_fields if f.name in params), "id")
        path_expr = e.path
        for p in params:
            path_expr = path_expr.replace("{" + p + "}", "{seed[" + repr(key) + "]}")
        call = f"client.{verb}(f{path_expr!r}"
    if rest:
        call += f", {'params' if e.method in ('GET', 'DELETE') else 'json'}={rest!r}"
    call += ")"
    lines = [f"def {name}():"]
    if seed is not None:
        lines += [f"    seed = client.post({seed.path!r}, json={_payload(seed)!r})",
                  "    assert seed.status_code < 300, seed.text", "    seed = seed.json()"]
    lines += [f"    r = {call}", f"    assert r.status_code == {ex.status}, r.text"]
    if ex.status < 300:
        lines.append("    data = r.json()")
        lines += [f"    assert {f.name!r} in data" for f in e.response_fields]
        for k, v in ex.response.items():
            if _server_filled(k):
                continue  # the database fills it in (a timestamp): the example's value is invented, and "k in data" above already checks it exists
            if isinstance(v, list) and v:
                # The example's rows were invented by the Architect; what the app stores comes from the seeding POST, so check the shape, not the rows.
                lines.append(f"    assert isinstance(data[{k!r}], list)" + (f" and len(data[{k!r}]) >= 1" if seed is not None else ""))
            else:
                lines.append(f"    assert data[{k!r}] == pytest.approx({v!r})" if isinstance(v, (int, float)) and not isinstance(v, bool)
                             else f"    assert data[{k!r}] == {v!r}")
    else:
        for k, v in ex.response.items():
            lines.append(f"    assert r.json()[{k!r}] == {v!r}")
    return lines + ["", ""]


def api_test_source(design: ArchitectOutput, resource: str | None = None) -> str:
    """The contract tests. A relational design has one file per resource (`resource` names it), so a router task sees only its own tests."""
    from .relations import endpoints_for_resource
    from .relation_tests import relation_tests

    mine = [r for r in design.resources if resource in (None, r.name)]
    endpoints = [e for r in mine for e in endpoints_for_resource(design, r.name)] if design.resources else design.endpoints
    out = ['"""Contract tests generated from the API contract examples. Do not edit; fix the code instead."""',
           "import itertools", "", "import pytest", "from fastapi.testclient import TestClient", "", "from backend.main import app", "", "client = TestClient(app)", "_n = itertools.count(1)  # makes unique values differ", "", ""]
    for e in endpoints:
        for i, ex in enumerate(e.examples, 1):
            out += _test_for(e, i, ex, design)
    for r in mine:
        out += relation_tests(design, r)
    return "\n".join(out).rstrip() + "\n"


def ui_page_test_source(design: ArchitectOutput) -> str:
    look = design.look
    if look is not None and look.layout == "shell":
        from .shell import shell_page_test

        return shell_page_test(design)
    extra: list[str] = []
    if look is not None:  # the theme and the "Not in this version" note were chosen by rules: a page that drops them is wrong
        extra += ["", "", "def test_page_keeps_its_theme():", "    import re",
                  f"    assert re.search(r'data-theme=[\"\\']{look.theme}[\"\\']', client.get('/').text), \"keep data-theme on <html>: it selects the UI kit theme\""]
        if look.not_included:
            extra += ["", "", "def test_page_says_what_is_left_out():",
                      "    assert 'Not in this version' in client.get('/').text, \"keep the note that lists what this version leaves out (Not in this version: ...)\""]
    return "\n".join([
        '"""UI smoke test generated from the API contract. Do not edit; fix the page instead."""',
        "from fastapi.testclient import TestClient", "", "from backend.main import app", "", "client = TestClient(app)", "", "",
        "def test_page_is_served_and_loads_its_assets():",
        "    r = client.get('/')",
        "    assert r.status_code == 200 and '/static/app.js' in r.text and '/static/style.css' in r.text",
        "    assert '/static/ui-kit.css' in r.text  # the UI kit is always linked",
        "", "",
        "def test_assets_are_served():",
        "    assert client.get('/static/style.css').status_code == 200",
        "    assert client.get('/static/ui-kit.css').status_code == 200",
        "    assert client.get('/static/app.js').status_code == 200",
        "", "",
        "def test_element_ids_are_unique():",
        "    import collections, re",
        "    ids = re.findall(r'\\sid=[\"\\']([^\"\\']+)[\"\\']', client.get('/').text)",
        "    dup = sorted(i for i, n in collections.Counter(ids).items() if n > 1)",
        "    assert not dup, (f'these element ids appear more than once: {dup}. getElementById only finds the first one, so the others stay stale. '",
        "                     'Give each element its own id, or move the element instead of copying it.')",
        *extra,
    ]) + "\n"


def list_view_fields(design: ArchitectOutput) -> list[str]:
    """The item fields a list view must show: what the user enters (POST fields) plus the keys of the listed items in the contract's examples.
    Ids, foreign keys and server-filled timestamps are not "important fields"; a field shorter than 3 characters cannot be searched for reliably."""
    lists = [e for e in design.endpoints if e.method == "GET" and "{" not in e.path and any(f.type == "array" for f in e.response_fields)]
    if not lists:
        return []
    names: list[str] = []
    for r in design.resources:  # a relational page shows what the user entered and the counters, for the parent and for the child
        names += [f.name for f in r.fields] + r.counters
    for e in design.endpoints:
        if e.method == "POST" and "{" not in e.path:
            names += [f.name for f in e.request_fields]
    for e in lists:
        for ex in e.examples:
            for v in ex.response.values():
                if isinstance(v, list):
                    names += [k for item in v if isinstance(item, dict) for k in item]
    out: list[str] = []
    for n in names:
        if n != "id" and not n.endswith("_id") and not _server_filled(n) and len(n) >= 3 and n not in out:
            out.append(n)
    return out


def category_fields(design: ArchitectOutput) -> dict[str, list[str]]:
    """Categorical fields (priority, status, category...) and their human labels, from the contract."""
    out: dict[str, list[str]] = {}
    for e in design.endpoints:
        for f in [*e.request_fields, *e.response_fields]:
            if f.options:
                out.setdefault(f.name, f.options)
    return out


def item_endpoints(design: ArchitectOutput) -> list[Endpoint]:
    """Endpoints that act on ONE listed item (PUT/PATCH/DELETE with an id in the path, and a vote/toggle action): every one needs a button in the list."""
    actions = {a.name for r in design.resources for a in r.actions}
    return [e for e in design.endpoints if (e.method in ("PUT", "PATCH", "DELETE") and "{" in e.path)
            or (e.method == "POST" and e.path.rsplit("/", 1)[-1] in actions and e.path.count("{") == 1 and "{" in e.path)]


_CATEGORY_TEST = r'''

def test_categories_are_shown_as_labels_not_numbers():
    js = client.get('/static/app.js').text
    page = client.get('/').text
    for field, labels in __CATEGORIES__.items():
        for label in labels:
            assert label in page + js, f"the label '{label}' of '{field}' appears nowhere: build the select from the contract's labels"
        assert not re.search(r'<option[^>]*value=["\']\d+["\']', page), f"a select has a numeric option value; '{field}' must send its label (High), not a number (3)"
        assert not re.search(r'(?:parseInt|parseFloat|Number)\([^)]*\b' + field + r'\b', js), f"'{field}' is converted to a number; send and show the label as it is"
        assert not re.search(r'\b' + field + r'\s*:\s*-?\d', js), f"'{field}' is given a numeric value; use one of its labels {labels}"
'''

_ACTIONS_TEST = r'''

def test_every_item_endpoint_has_a_button_in_the_list():
    js = client.get('/static/app.js').text
    assert 'actions' in js, "the list rows have no buttons: pass actions: [{ label: 'Delete', ... }] to UI.renderList"
__CALLS__
'''


def ui_script_test_source(design: ArchitectOutput) -> str:
    if design.look is not None and design.look.layout == "shell":
        from .shell import shell_script_test

        return shell_script_test(design)
    paths = sorted({re.sub(r"/\{.*$", "", e.path) for e in design.endpoints})
    fields = list_view_fields(design)
    cats = category_fields(design)
    items = item_endpoints(design)
    out = ['"""UI script test generated from the API contract. Do not edit; fix the script instead."""',
           "import re", "", "from fastapi.testclient import TestClient", "", "from backend.main import app", "", "client = TestClient(app)", "", "",
           "def test_script_calls_every_endpoint():",
           "    js = client.get('/static/app.js').text",
           "    assert 'fetch' in js"]
    out += [f"    assert {p!r} in js" for p in paths]
    if fields:
        out += ["", "",
                "def test_list_view_shows_every_field_of_an_item():",
                "    js = client.get('/static/app.js').text",
                f"    for field in {fields!r}:",
                "        # read as a property of an item (item.field, item['field']) or named for UI.renderList (a quoted name in a list or object);",
                "        # the add form's own use of the name does not count",
                "        assert re.search(r'(?:[.]|\\[\\s*[\\'\"])' + field + r'\\b|[\\'\"]' + field + r'[\\'\"]\\s*[\\],}]', js), (",
                "            f\"the list never uses the item field '{field}'. Show EVERY important field of each item, not just the title \"",
                "            \"(for example the description as muted text and a priority, status or category as a badge).\")"]
    if cats:
        out.append(_CATEGORY_TEST.replace("__CATEGORIES__", repr(cats)))
    if items:
        calls = []
        for e in items:
            base, _, rest = e.path.partition("/{")
            calls += [f"    assert called_from_a_button(js, {e.method!r}, {base + '/'!r}, {rest.partition('}')[2]!r}), (",
                      f"        \"{e.method} {e.path} is never called from a list button: add a button to `actions` of every row whose onClick leads to this call\")"]
        if any(e.method in ("PUT", "PATCH") and e.path.endswith("}") for e in items):
            calls.append("    assert re.search(r'edit', js, re.I), \"add an Edit button to every row\"")
        if any(e.method == "DELETE" and e.path.endswith("}") for e in items):
            calls.append("    assert re.search(r'delete|remove', js, re.I), \"add a Delete button to every row\"")
        booleans = [f.name for e in design.endpoints if e.method in ("PUT", "PATCH") for f in e.request_fields if f.type == "boolean"]
        if booleans:
            calls.append(f"    assert 'onToggle' in js, \"{booleans[0]} is a yes/no field: show a checkbox in each row so ticking it saves at once (done: '{booleans[0]}', onToggle: (checked) => save(item.id, {{ ...item, {booleans[0]}: checked }}))\"")
        helpers = (Path(__file__).parent / "ui_script_checks.py").read_text(encoding="utf-8").split("import re\n", 1)[1]
        out += ["", "", helpers.strip("\n"), _ACTIONS_TEST.replace("__CALLS__", "\n".join(calls))]
    for r in (r for r in design.resources if r.parent):
        out += ["", "", f"def test_script_loads_the_{r.name}_of_the_open_{r.parent}_from_the_nested_path():",
                "    js = client.get('/static/app.js').text",
                f"    assert '/api/{r.parent}/' in js and '/{r.name}' in js, \"the open item's {r.name} come from GET /api/{r.parent}/<id>/{r.name}; adding one POSTs to the same path\""]
    if any(r.sorts for r in design.resources):
        out += ["", "", "def test_the_list_can_be_sorted():", "    js = client.get('/static/app.js').text",
                "    assert 'sort=' in js, \"the page must offer the sort it promises: a select (new / top) sent to the API as ?sort=\""]
    if any(re.search(r"\bfilter", f, re.I) for f in design.ui_features):
        out += ["", "", "def test_the_list_can_be_filtered():",
                "    js = client.get('/static/app.js').text",
                "    assert '.filter(' in js, \"the page must offer the filter it promises: a select with All plus the labels, applied with items.filter(...) before UI.renderList\""]
    return "\n".join(out).rstrip() + "\n"


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
            if required_text(f) and not design.resources and not declares_blank_error(e):  # a relational design tests this in its per-resource file
                from .relation_tests import blank_message

                out += [f"def test_{verb}_{slug}_rejects_blank_{_slug(f.name)}():",
                        f"    r = client.{verb}({e.path!r}, json={{**{payload!r}, {f.name!r}: '   '}})",
                        "    assert r.status_code == 400, r.text", f"    assert r.json() == {{'detail': {blank_message(f.name)!r}}}", "", ""]
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
            for e in item_endpoints(design):
                if design.resources and not e.path.startswith(post.path + "/"):
                    continue  # PUT/DELETE of another resource (the comments of a post) are covered by the relation tests
                params = re.findall(r"\{(\w+)\}", e.path)
                if len(params) != 1 or not e.path.endswith("}") or "{" in e.path.split("/{")[0]:
                    continue
                path_expr = e.path.replace("{" + params[0] + "}", "{seed['id']}")
                head = [f"    r = client.{post.method.lower()}({post.path!r}, json={payload!r})", "    assert r.status_code < 300, r.text", "    seed = r.json()"]
                if e.method == "DELETE":
                    out += [f"def test_delete_{_slug(e.path)}_removes_the_item():", *head,
                            f"    r = client.delete(f{path_expr!r})", f"    assert r.status_code == {e.response_status}, r.text",
                            f"    assert client.get({get.path!r}).json()[{key!r}] == []", "", ""]
                    continue
                names = [f.name for f in e.request_fields]
                if not names or not set(names) <= set(payload):
                    continue
                body = {k: payload[k] for k in names}
                text = next((f.name for f in e.request_fields if f.type == "string" and not f.options and body[f.name]), None)
                if text:
                    body[text] = body[text] + " v2"
                out += [f"def test_{e.method.lower()}_{_slug(e.path)}_updates_the_item():", *head,
                        f"    r = client.{e.method.lower()}(f{path_expr!r}, json={body!r})", f"    assert r.status_code == {e.response_status}, r.text",
                        f"    items = client.get({get.path!r}).json()[{key!r}]", "    assert len(items) == 1"]
                if text:
                    out += [f"    assert items[0][{text!r}] == {body[text]!r}"]
                out += ["", ""]
            for c in clears[:1]:
                out += [f"def test_clearing_empties_the_list():",
                        f"    client.{post.method.lower()}({post.path!r}, json={payload!r})",
                        f"    r = client.delete({c.path!r})",
                        "    assert r.status_code < 300, r.text",
                        f"    assert client.get({get.path!r}).json()[{key!r}] == []",
                        "", ""]
    return "\n".join(out).rstrip() + "\n"
