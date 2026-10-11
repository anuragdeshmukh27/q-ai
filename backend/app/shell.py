"""The multi-page app shell: its page, its description and the tests that look at both.

`static/shell.js` and `static/shell.css` are hand-made, locked preset files (a hash router, a sidebar, a dashboard, a list page per resource with search, filters
and sorting, a detail page with a tab per related resource, forms in modals, an About page). What differs between apps is only a description, which is generated
from the contract and the matched skill pack and written into `static/app.js`: `Q.mount({...}, { loaded() { /* request-hook:loaded */ } })`.
The model never writes a layout; a request from the human (Ask employee) edits the two request hooks, as on the older pages.
"""
from __future__ import annotations

import json
import re

from .relations import children_of, parent_of
from .schemas import ArchitectOutput, FieldSpec, Look, ResourceInfo, label as _label, singular
from .skills import pack as _pack

MONEY = re.compile(r"amount|price|cost|total|balance|spent|fare|fee|salary|budget|charge|rent", re.I)
RATING = re.compile(r"(^|_)(rating|stars?)$", re.I)
LONG = re.compile(r"description|content|notes?|body|details|message|comment|reason|about", re.I)
OPTIONAL = re.compile(r"description|notes?|details?|memo|remarks?|bio|about|address|link|website|url|tags?|message", re.I)
LOCALES = {"INR": "en-IN", "USD": "en-US", "EUR": "de-DE", "GBP": "en-GB"}
TITLES = ("title", "caption", "name", "habit", "item", "question", "description", "text")
VERB_TONE = {"complete": "success", "paid": "success", "mark_paid": "success", "check_in": "success", "confirm": "success", "approve": "success", "cancel": "danger", "reject": "danger"}


def _kind(f: FieldSpec, rules, fk_text: bool = False) -> str:
    if f.options:
        return "select"
    if f.type == "boolean":
        return "checkbox"
    if f.type in ("number", "integer"):
        if RATING.search(f.name) and f.type == "integer":
            return "rating"
        if MONEY.search(f.name):
            return "money"
        return "integer" if f.type == "integer" else "number"
    if f.name in rules.phone or re.search(r"phone|mobile", f.name):
        return "phone"
    if f.name in rules.email or "email" in f.name:
        return "email"
    if "date" in f.name:
        return "date"
    if re.search(r"(^|_)time$", f.name):
        return "time"
    if LONG.search(f.name):
        return "longtext"
    return "text"


def _field(f: FieldSpec, rules, vocab: dict) -> dict:
    kind = _kind(f, rules)
    out: dict = {"name": f.name, "label": vocab.get(f.name) or _label(f.name), "kind": kind}
    if f.options:
        out["options"] = list(f.options)
    if f.name in rules.bounds:
        out["min"], out["max"] = (int(v) if float(v).is_integer() else v for v in rules.bounds[f.name])
    elif f.name in rules.positive:
        out["min"] = 1 if f.type == "integer" else 0.01
    elif kind == "rating":
        out["min"], out["max"] = 1, 5
    required = kind not in ("checkbox", "longtext") and not (OPTIONAL.search(f.name) and kind == "text") and "date" not in f.name or f.name in rules.phone or f.name in rules.email
    if kind in ("number", "integer", "money", "rating", "select"):
        required = True
    if required:
        out["required"] = True
    return out


def _title(fields: list[FieldSpec]) -> str:
    texts = [f for f in fields if f.type == "string" and not f.options]
    return next((f.name for n in TITLES for f in texts if f.name == n), texts[0].name if texts else fields[0].name)


def _action_cfg(a, base: str) -> dict:
    out = {"name": a.name, "label": _label(a.name) if a.kind != "increment" else _label(a.name), "kind": a.kind, "field": a.field, "url": f"{base}/{{id}}/{a.name}"}
    if a.kind == "set":
        out["value"] = a.value
        out["tone"] = VERB_TONE.get(a.name, "info")
    return out


def _resource_cfg(ri: ResourceInfo, design: ArchitectOutput, vocab: dict, icons: dict, pack: dict, parent: ResourceInfo | None) -> dict:
    fields = [_field(f, ri.rules, vocab) for f in ri.fields]
    counters = [{"name": c, "label": vocab.get(c) or _label(c), "kind": "counter"} for c in ri.counters]
    flags = [{"name": c, "label": vocab.get(c) or _label(c), "kind": "checkbox"} for c in ri.flags]
    title = _title(ri.fields)
    texts = [f.name for f in ri.fields if f.type == "string" and not f.options and f.name != title]
    plain = [t for t in texts if not LONG.search(t) and not re.search(r"phone|mobile|email|date|time", t)]
    longtext = [f.name for f in ri.fields if f.name != title and LONG.search(f.name)][:1]  # one long text (a comment, a description) is shown cut short at the end of the row
    columns = [title] + [f.name for f in ri.fields if f.name != title and not LONG.search(f.name)][:6] + longtext + [c["name"] for c in counters + flags]
    item = f"/api/{ri.name}"
    cfg: dict = {
        "name": ri.name, "singular": ri.singular, "label": _label(ri.name), "icon": icons.get(ri.name, ""), "parent": ri.parent,
        "children": [c.name for c in children_of(design, ri)],
        "list": f"/api/{parent.name}/{{parent}}/{ri.name}" if parent else item, "create": f"/api/{parent.name}/{{parent}}/{ri.name}" if parent else item,
        "item": f"{item}/{{id}}", "fields": fields, "extra": counters + flags,
        "columns": columns, "detail": [f.name for f in ri.fields] + [c["name"] for c in counters + flags], "title": title,
        "subtitle": [] if parent else plain[:2], "filters": [f.name for f in ri.fields if f.options][:3], "search": [f.name for f in ri.fields if f.type == "string" and not f.options][:6],
        "actions": [_action_cfg(a, item) for a in ri.actions],
    }
    if ri.sorts:
        cfg["sorts"] = list(ri.sorts)
    if ri.rules.transitions and ri.rules.status_field:
        cfg["flow"] = {ri.rules.status_field: ri.rules.transitions}
    if ri.rules.capacity_field and parent is not None:
        status = ri.rules.status_field
        free = next(([o] for f in ri.fields if f.name == status for o in f.options if o.lower() in ("cancelled", "canceled")), [])
        cfg["capacity"] = {"field": ri.rules.capacity_field, "status": status, "free": free}
    return cfg


def _single_cfg(design: ArchitectOutput, vocab: dict, icons: dict) -> list[dict]:
    """A design written by the model (todo, expenses, notes): one resource, read from its endpoints."""
    from .scaffold import PY_TYPES  # noqa: F401
    from .schemas import ResourceRules
    from .uistub import Shape

    s = Shape(design)
    rules = ResourceRules()
    fields = [_field(f, rules, vocab) for f in s.inputs]
    base = re.sub(r"/\{.*$", "", s.put.path if s.put else s.delete.path if s.delete else s.list.path)
    texts = [f.name for f in s.texts if f is not s.title]
    title = s.title.name if s.title else s.fields[0].name
    shown = [f for f in s.fields if f.name != title and f.type != "boolean" and not LONG.search(f.name)]
    extra = [_field(f, rules, vocab) for f in s.computed]
    cfg = {
        "name": re.sub(r"\{.*", "", s.list.path).rstrip("/").split("/")[-1], "singular": s.one.replace(" ", "_"), "label": _label(s.noun.replace(" ", "_")), "icon": icons.get("", ""),
        "parent": "", "children": [], "list": s.list.path, "create": s.post.path, "item": f"{base}/{{id}}", "fields": fields, "extra": extra, "listKey": s.key,
        "columns": [title] + [f.name for f in shown][:6], "detail": [f["name"] for f in fields + extra], "title": title, "subtitle": [t for t in texts if not LONG.search(t) and not re.search(r"date|time|phone|mobile|email", t)][:1],
        "filters": [f.name for f in s.options][:3] + [f.name for f in s.booleans][:1], "search": [f.name for f in s.texts][:6], "actions": [],
    }
    if s.booleans and s.put:
        cfg["toggle"] = s.booleans[0].name
    if s.clear:
        cfg["clear"] = s.clear.path
    if not s.put:
        cfg["noEdit"] = True
    return [cfg]


def _valid_kpi(k: dict, by: dict, primary: str) -> dict | None:
    name = primary if k.get("resource") == "*" else k.get("resource")
    r = by.get(name)
    if r is None:
        return None
    names = {f["name"] for f in [*r["fields"], *r["extra"]]}
    for key in ("field", "with"):
        if k.get(key) and k[key] not in names:
            return None
    for w, v in (k.get("where") or {}).items():
        f = next((x for x in [*r["fields"], *r["extra"]] if x["name"] == w), None)
        if f is None or (f.get("options") and v not in f["options"]):
            return None
    return {**k, "resource": name}


def _defaults(resources: list[dict]) -> tuple[list[dict], list[dict]]:
    first = resources[0]
    kpis = [{"label": r["label"], "resource": r["name"], "agg": "count"} for r in resources[:3]]
    money = next((f for f in first["fields"] if f["kind"] == "money"), None)
    rating = next((f for r in resources for f in r["fields"] if f["kind"] == "rating"), None)
    if money:
        kpis.append({"label": f"Total {money['label'].lower()}", "resource": first["name"], "agg": "sum", "field": money["name"], "format": "money"})
    if rating:
        r = next(r for r in resources if rating in r["fields"])
        kpis.append({"label": f"Average {rating['label'].lower()}", "resource": r["name"], "agg": "avg", "field": rating["name"], "format": "stars"})
    charts = []
    for r in resources:
        sel = next((f for f in r["fields"] if f.get("options")), None)
        if sel:
            charts.append({"title": f"{r['label']} by {sel['label'].lower()}", "resource": r["name"], "by": sel["name"]})
        if r["parent"]:
            charts.append({"title": f"{r['label']} per {singular(r['parent']).replace('_', ' ')}", "resource": r["name"], "per": "parent"})
    return kpis, charts[:4]


def _ui(p: dict) -> dict:
    """The layout accent of a skill pack (its ui: key): where the navigation is, how dense the lists are, how the dashboard charts are drawn."""
    ui = p.get("ui") or {}
    pick = lambda key, allowed, default: ui.get(key) if ui.get(key) in allowed else default  # noqa: E731
    return {"nav": pick("nav", ("side", "top"), "side"), "density": pick("density", ("cozy", "cards", "table"), "cozy"), "charts": pick("charts", ("bars", "columns"), "bars")}


def app_config(design: ArchitectOutput, title: str = "") -> dict:
    look: Look = design.look or Look()
    p = _pack(look.skill) or {}
    vocab, icons = p.get("vocabulary", {}), p.get("icons", {})
    by_res = {r.name: r for r in design.resources}
    if design.resources:
        resources = [_resource_cfg(r, design, vocab, icons, p, by_res.get(r.parent)) for r in design.resources]
    else:
        resources = _single_cfg(design, vocab, icons)
    by = {r["name"]: r for r in resources}
    primary = resources[0]["name"]
    kpis = [k for k in (_valid_kpi(k, by, primary) for k in p.get("kpis", [])) if k]
    charts = []
    for c in p.get("charts", []):
        name = primary if c.get("resource") == "*" else c.get("resource")
        r = by.get(name)
        if r and ((c.get("by") and any(f["name"] == c["by"] for f in [*r["fields"], *r["extra"]])) or (c.get("per") == "parent" and r["parent"])):
            charts.append({**c, "resource": name})
    for k in kpis:  # "Items" of a pack that does not know the resource: the resource's own name
        if k["label"] == "Items" and k.get("agg") == "count":
            k["label"] = by[k["resource"]]["label"]
    dk, dc = _defaults(resources)
    same = lambda a, b: all(a.get(x) == b.get(x) for x in ("resource", "agg", "field", "where"))  # noqa: E731
    if len(kpis) < 2:
        kpis += [k for k in dk if not any(same(k, x) for x in kpis)][: 4 - len(kpis)]
    if not charts:
        charts = dc
    empty = {"default": "Nothing here yet. Add the first one."}
    empty.update(p.get("empty", {}))
    for r in resources:
        empty.setdefault(r["name"], f"No {r['label'].lower()} yet. Add the first {r['singular'].replace('_', ' ')}.")
    for r in resources:  # the main icon of a single resource that the pack does not know: the app's icon
        r["icon"] = r["icon"] or look.icon or "•"
    currency = look.currency or "USD"
    return {
        "title": title or resources[0]["label"], "subtitle": look.subtitle, "icon": look.icon or "✨", "skin": look.skin or "studio", "ui": _ui(p), "currency": currency,
        "locale": LOCALES.get(currency, "en-US"), "notIncluded": list(look.not_included), "empty": empty, "dashboard": {"kpis": kpis[:5], "charts": charts[:4]},
        "resources": resources,
    }


# --- the files ------------------------------------------------------------------------------------------------------------------------------------------

def shell_page(design: ArchitectOutput, title: str = "") -> str:
    skin = (design.look.skin if design.look else "") or "studio"
    name = title or "App"
    return f"""<!doctype html>
<html lang="en" data-skin="{skin}" data-mode="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(name)}</title>
  <link rel="stylesheet" href="/static/ui-kit.css">
  <link rel="stylesheet" href="/static/shell.css">
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/ui-kit.js"></script>
  <script src="/static/shell.js"></script>
</head>
<body>
  <div id="app"><div id="top-slot"><!-- request-hook:top --></div></div>
  <noscript>This app needs JavaScript.</noscript>
  <script src="/static/app.js"></script>
</body>
</html>
"""


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def shell_script(design: ArchitectOutput, title: str = "") -> str:
    cfg = app_config(design, title)
    resources = cfg.pop("resources")
    j = lambda v: json.dumps(v, ensure_ascii=False, separators=(", ", ": "))  # noqa: E731
    head = ",\n".join(f"  {json.dumps(k)}: {j(v)}" for k, v in cfg.items())
    body = ",\n".join(f"    {j(r)}" for r in resources)
    return (f"// Generated from the contract. shell.js draws the pages (dashboard, a list and a detail page per resource) from this description.\n"
            f"Q.mount({{\n{head},\n  \"resources\": [\n{body},\n  ],\n}}, {{\n  loaded(data) {{\n    // request-hook:loaded\n  }},\n}});\n")


# --- the tests of a shell page ---------------------------------------------------------------------------------------------------------------------------

def shell_page_test(design: ArchitectOutput) -> str:
    look = design.look
    extra = []
    if look is not None and look.not_included:
        extra = ["", "", "def test_page_says_what_is_left_out():",
                 "    js = client.get('/static/app.js').text", "    assert 'notIncluded' in js and 'Not in this version' in client.get('/static/shell.js').text, \"keep the description's notIncluded list: the page says what this version leaves out\""]
    return "\n".join([
        '"""UI smoke test generated from the API contract. Do not edit; fix the page instead."""',
        "from fastapi.testclient import TestClient", "", "from backend.main import app", "", "client = TestClient(app)", "", "",
        "def test_page_is_served_and_loads_its_assets():",
        "    r = client.get('/')",
        "    assert r.status_code == 200 and '/static/app.js' in r.text and '/static/shell.js' in r.text and '/static/shell.css' in r.text",
        "    assert '/static/ui-kit.css' in r.text  # the UI kit is always linked",
        "", "",
        "def test_assets_are_served():",
        "    for path in ('/static/style.css', '/static/ui-kit.css', '/static/shell.css', '/static/shell.js', '/static/app.js', '/static/fonts/inter-latin-wght-normal.woff2'):",
        "        assert client.get(path).status_code == 200, path",
        "", "",
        "def test_element_ids_are_unique():",
        "    import collections, re",
        "    ids = re.findall(r'\\sid=[\"\\']([^\"\\']+)[\"\\']', client.get('/').text)",
        "    dup = sorted(i for i, n in collections.Counter(ids).items() if n > 1)",
        "    assert not dup, f'these element ids appear more than once: {dup}'",
        *extra,
    ]) + "\n"


def shell_script_test(design: ArchitectOutput) -> str:
    cfg = app_config(design)
    paths = sorted({re.sub(r"/\{.*$", "", e.path) for e in design.endpoints})
    items = [r for r in cfg["resources"]]
    out = ['"""UI script test generated from the API contract. Do not edit; fix the script instead."""',
           "import re", "import shutil", "import subprocess", "from pathlib import Path", "", "import pytest", "from fastapi.testclient import TestClient", "", "from backend.main import app", "",
           "client = TestClient(app)", "ROOT = Path(__file__).resolve().parents[2]", "", "",
           "def test_script_calls_every_endpoint():", "    js = client.get('/static/app.js').text", "    assert 'Q.mount' in js"]
    out += [f"    assert {p!r} in js" for p in paths]
    out += ["", "", "def test_every_resource_is_a_module_with_its_own_page():", "    js = client.get('/static/app.js').text"]
    for r in items:
        out += [f"    assert '\"name\": \"{r['name']}\"' in js and {r['item']!r} in js and {r['list']!r} in js", ]
        for a in r["actions"]:
            out += [f"    assert {a['url']!r} in js, 'the {a['name']} button of {r['name']} needs its endpoint in the description'"]
    names = []
    for r in items:
        names += [f["name"] for f in r["fields"]]
    out += ["", "", "def test_every_field_is_in_the_description():", "    js = client.get('/static/app.js').text", f"    for field in {sorted(set(names))!r}:",
            "        assert re.search(r'[\\'\"]' + field + r'[\\'\"]', js), f\"the field '{field}' has dropped out of the description\""]
    labels = {}
    for r in items:
        for f in r["fields"]:
            if f.get("options"):
                labels[f"{r['name']}.{f['name']}"] = f["options"]
    if labels:
        out += ["", "", "def test_categories_are_shown_as_labels_not_numbers():", "    js = client.get('/static/app.js').text",
                f"    for field, labels in {labels!r}.items():", "        for label in labels:", "            assert label in js, f\"the label '{label}' of '{field}' is missing\""]
    out += ["", "", "def test_every_route_renders():",
            "    \"\"\"shell.js and app.js run in a small fake browser (tests/ui/shell_smoke.mjs): the dashboard, every list page and a detail page must draw.\"\"\"",
            "    node = shutil.which('node')", "    if node is None:", "        pytest.skip('node is not installed')",
            "    r = subprocess.run([node, str(ROOT / 'tests' / 'ui' / 'shell_smoke.mjs')], cwd=ROOT, capture_output=True, text=True, timeout=90)",
            "    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]"]
    return "\n".join(out).rstrip() + "\n"
