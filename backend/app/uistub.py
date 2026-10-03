"""A working starting page generated from the API contract, like the route and database stubs.

A 7B model asked to hand-write a 120-line `app.js` (labelled selects, an edit dialog, a done toggle, filters, a button for every
item endpoint) rewrites the whole file each round and rarely converges. Everything here follows from the contract, so it is generated:
the form, the list built with `UI.renderList`, an Edit / Delete button for every item endpoint, a checkbox for a yes/no field,
the labelled options as selects and badges. The Frontend engineer receives it as the starting point, runs the tests and refines it.

Returns None for a design that is not a list-and-add app; the engineer then writes the page from scratch as before.
"""
from __future__ import annotations

import json
import re

from .contract_tests import _server_filled
from .schemas import ArchitectOutput, FieldSpec

PLACEHOLDERS = ("Frontend entry point.", "<h1>App</h1>")  # what the preset skeleton ships; anything else is somebody's work
MONEY = re.compile(r"amount|price|cost|total|balance|spent", re.I)
LONG_TEXT = re.compile(r"description|content|notes?|body|details", re.I)
TITLE_NAMES = ("title", "name", "habit", "item", "question", "description", "text")


def _label(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


class Shape:
    """What the contract says about the page: where the list is, what the form sends, which buttons the rows need."""

    def __init__(self, design: ArchitectOutput):
        ep = design.endpoints
        self.list = next((e for e in ep if e.method == "GET" and "{" not in e.path and any(f.type == "array" for f in e.response_fields)), None)
        self.post = next((e for e in ep if e.method == "POST" and "{" not in e.path and e.request_fields), None)
        self.ok = self.list is not None and self.post is not None
        if not self.ok:
            return
        self.key = next(f.name for f in self.list.response_fields if f.type == "array")
        single = lambda e: e.path.endswith("}") and e.path.count("{") == 1  # noqa: E731
        self.put = next((e for e in ep if e.method in ("PUT", "PATCH") and single(e)), None)
        self.delete = next((e for e in ep if e.method == "DELETE" and single(e)), None)
        self.clear = next((e for e in ep if e.method == "DELETE" and "{" not in e.path), None)
        self.inputs = list(self.post.request_fields)
        names = {f.name for f in self.inputs}
        # what comes back beyond what was sent (a calculator's result), except ids and server-filled timestamps
        self.computed = [f for f in self.post.response_fields if f.name not in names and not _server_filled(f.name)]
        self.fields: list[FieldSpec] = [*self.inputs, *self.computed]
        self.options = [f for f in self.fields if f.options]
        self.booleans = [f for f in self.fields if f.type == "boolean"]
        self.texts = [f for f in self.fields if f.type == "string" and not f.options]
        self.numbers = [f for f in self.fields if f.type in ("number", "integer")]
        self.title = next((f for n in TITLE_NAMES for f in self.texts if f.name == n), self.texts[0] if self.texts else None)
        self.noun = (re.sub(r"\{.*", "", self.list.path).rstrip("/").split("/")[-1] or "items").replace("_", " ")
        self.features = " ".join(design.ui_features).lower()


def _input(f: FieldSpec, prefix: str = "") -> str:
    label = f'<label for="{prefix}{f.name}">{_label(f.name)}</label>'
    if f.options:
        opts = "".join(f"<option>{o}</option>" for o in f.options)
        return f'<div class="field">{label}<select id="{prefix}{f.name}">{opts}</select></div>'
    if f.type == "boolean":
        return f'<div class="field field-check"><input id="{prefix}{f.name}" type="checkbox">{label}</div>'
    if f.type in ("number", "integer"):
        return f'<div class="field">{label}<input id="{prefix}{f.name}" type="number" step="{"1" if f.type == "integer" else "any"}"></div>'
    if "date" in f.name:
        return f'<div class="field">{label}<input id="{prefix}{f.name}" type="date"></div>'
    if LONG_TEXT.search(f.name):
        return f'<div class="field">{label}<textarea id="{prefix}{f.name}" rows="2"></textarea></div>'
    return f'<div class="field">{label}<input id="{prefix}{f.name}"></div>'


def _filter_field(s: Shape) -> FieldSpec | None:
    if "filter" not in s.features:
        return None
    return s.options[0] if s.options else (s.booleans[0] if s.booleans else None)


def page_stub(design: ArchitectOutput, title: str = "") -> str | None:
    if design.resources:
        from .relpage import page

        return page(design, title)
    s = Shape(design)
    if not s.ok:
        return None
    heading = title or _label(s.noun)
    form = "\n            ".join(_input(f) for f in s.inputs)
    flt = _filter_field(s)
    controls = []
    if flt is not None:
        labels = flt.options if flt.options else ["Open", "Done"]
        opts = "".join(f"<option>{o}</option>" for o in ["All", *labels])
        controls.append(f'<div class="field"><label for="filter">Show</label><select id="filter">{opts}</select></div>')
    if "search" in s.features and s.texts:
        controls.append('<div class="field grow"><label for="search">Search</label><input id="search" placeholder="Type to search"></div>')
    bar = f'\n          <div class="form-row">{"".join(controls)}</div>' if controls else ""
    total = '\n          <p class="muted">Total: <strong id="total">0</strong></p>' if "total" in s.features and any(MONEY.search(f.name) for f in s.numbers) else ""
    result = '\n      <div id="result" class="alert alert-success"></div>' if s.computed else ""
    clear = '\n          <div style="margin-top: 12px"><button id="clear" type="button" class="btn-secondary btn-sm">Clear all</button></div>' if s.clear else ""
    verb = "Calculate" if s.computed else "Add"  # a calculator does not "add" a row: it works something out
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{heading}</title>
  <link rel="stylesheet" href="/static/ui-kit.css">
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/ui-kit.js"></script>
</head>
<body>
  <main class="container stack">
    <header class="page-header"><h1>{heading}</h1></header>
    <section class="card">
      <h2 class="card-title">{verb}</h2>
      <form id="form" class="stack">
        <div class="form-row">
            {form}
        </div>
        <div id="error" class="alert alert-error"></div>
        <div><button id="add" type="submit">{verb}</button></div>
      </form>{result}
    </section>
    <section class="card">
      <h2 class="card-title">{_label(s.noun)} <span id="count" class="badge badge-info"></span></h2>{bar}{total}
      <div id="list"></div>{clear}
    </section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
"""


def _edit_fields(s: Shape) -> list[dict]:
    return edit_fields_for(s.put.request_fields if s.put else [])


def edit_fields_for(fields: list[FieldSpec]) -> list[dict]:
    """The fields of the Edit dialog (UI.form) for these request fields."""
    out = []
    for f in fields:
        item: dict = {"name": f.name, "label": _label(f.name)}
        if f.options:
            item["options"] = f.options
        elif f.type == "boolean":
            item["type"] = "checkbox"
        elif f.type in ("number", "integer"):
            item["type"] = "number"
        elif "date" in f.name:
            item["type"] = "date"
        elif LONG_TEXT.search(f.name):
            item["type"] = "textarea"
        out.append(item)
    return out


def _read(f: FieldSpec) -> str:
    el = f'document.getElementById("{f.name}")'
    if f.type == "boolean":
        return f"{f.name}: {el}.checked"
    if f.type in ("number", "integer"):
        return f"{f.name}: parseFloat({el}.value)"
    return f"{f.name}: {el}.value"


def _order(s: Shape) -> list[str]:
    """Display order of a row that has no text field (a calculation): number, operation, number ... result."""
    names = [f.name for f in s.inputs]
    ops = [f.name for f in s.options if f in s.inputs]
    nums = [f.name for f in s.inputs if f in s.numbers]
    if len(ops) == 1 and len(nums) >= 2 and len(names) == len(ops) + len(nums):
        names = [nums[0], ops[0], *nums[1:]]
    return names + [f.name for f in s.computed]


def script_stub(design: ArchitectOutput, title: str = "") -> str | None:
    if design.resources:
        from .relpage import script

        return script(design, title)
    s = Shape(design)
    if not s.ok:
        return None
    base_of = lambda e: re.sub(r"/\{.*$", "", e.path)  # noqa: E731
    summary_mode = s.title is None
    flt = _filter_field(s)
    j = json.dumps
    out: list[str] = [
        'const list = document.getElementById("list");',
        'const count = document.getElementById("count");',
        'const errorBox = document.getElementById("error");',
    ]
    if s.put:
        out.append(f"const FIELDS = {j(_edit_fields(s), indent=2)};")
    if summary_mode:
        order = _order(s)
        out += [f"const ORDER = {j(order)};  // how a row reads: the values the user entered, then the computed ones",
                f"const INPUTS = {len(s.inputs)};",
                "",
                "function summary(item) {",
                '  const parts = ORDER.map((f) => (typeof item[f] === "number" ? UI.num(item[f]) : UI.symbol(item[f])));',
                '  parts.splice(INPUTS, 0, "=");',
                '  return parts.join(" ");',
                "}"]
    out.append("")
    # one small function per call, each with its own fetch
    if s.delete:
        out += ["async function remove(id) {",
                f'  await fetch("{base_of(s.delete)}/" + id, {{ method: "DELETE" }});',
                '  UI.toast("Removed", "success");', "  await load();", "}", ""]
    if s.put:
        out += ["async function save(id, values) {",
                f'  const res = await fetch("{base_of(s.put)}/" + id, {{',
                f'    method: "{s.put.method}",',
                '    headers: { "Content-Type": "application/json" },',
                "    body: JSON.stringify(values),", "  });",
                "  if (!res.ok) {", '    UI.toast("Could not save", "error");', "    return false;", "  }",
                '  UI.toast("Saved", "success");', "  await load();", "}", "",
                "function fieldsOf(item) {",
                "  return { " + ", ".join(f"{f.name}: item.{f.name}" for f in s.put.request_fields) + " };",
                "}", ""]
    if s.clear:
        out += ["async function clearAll() {",
                f'  await fetch("{s.clear.path}", {{ method: "DELETE" }});',
                '  UI.toast("Cleared", "success");', "  await load();", "}", ""]
    # the list
    out += ["async function load() {", "  UI.loading(list);", f'  const res = await fetch("{s.list.path}");', "  const data = await res.json();",
            f"  let shown = data.{s.key};"]
    if flt is not None:
        out.append('  const filter = document.getElementById("filter");')
        if flt.options:
            out.append(f'  if (filter.value !== "All") shown = shown.filter((i) => i.{flt.name} === filter.value);')
        else:
            out.append(f'  if (filter.value !== "All") shown = shown.filter((i) => (filter.value === "Done") === !!i.{flt.name});')
    if "search" in s.features and s.texts:
        out += ['  const query = document.getElementById("search").value.toLowerCase();',
                f"  if (query) shown = shown.filter((i) => {j([f.name for f in s.texts])}.some((k) => String(i[k] ?? \"\").toLowerCase().includes(query)));"]
    money = next((f for f in s.numbers if MONEY.search(f.name)), None)
    if "total" in s.features and money:
        out.append(f'  document.getElementById("total").textContent = UI.money(shown.reduce((sum, i) => sum + Number(i.{money.name} || 0), 0));')
    out.append(f'  count.textContent = shown.length + " " + {j(s.noun)};')
    rows = "shown.map((i) => ({ ...i, summary: summary(i) }))" if summary_mode else "shown"
    opts = [f"    title: {j('summary' if summary_mode else s.title.name)},"]
    details = [f.name for f in s.texts if f is not s.title]
    if details:
        opts.append(f"    details: {j(details)},")
    if s.options:
        opts.append(f"    badges: {j([f.name for f in s.options])},")
    formats = {f.name: ("money" if MONEY.search(f.name) else "num") for f in s.numbers if not summary_mode}
    if formats:
        opts.append(f"    formats: {j(formats)},")
    if s.booleans:
        opts.append(f"    done: {j(s.booleans[0].name)},")
        if s.put:
            b = s.booleans[0].name
            opts.append(f"    onToggle: (checked) => save(item.id, {{ ...fieldsOf(item), {b}: checked }}),")
    actions = []
    if s.put:
        actions.append('{ label: "Edit", onClick: () => UI.form("Edit", FIELDS, item, (values) => save(item.id, values)) }')
    if s.delete:
        actions.append('{ label: "Delete", kind: "danger", onClick: () => remove(item.id) }')
    if actions:
        opts.append("    actions: [\n      " + ",\n      ".join(actions) + ",\n    ],")
    out += [f"  UI.renderList(list, {rows}, (item) => ({{", *opts, f'  }}), "Nothing here yet. Add the first one above.");', "}", ""]
    # the form
    out += ['document.getElementById("form").addEventListener("submit", async (ev) => {', "  ev.preventDefault();", '  errorBox.textContent = "";',
            f'  const res = await fetch("{s.post.path}", {{', '    method: "POST",', '    headers: { "Content-Type": "application/json" },',
            "    body: JSON.stringify({ " + ", ".join(_read(f) for f in s.inputs) + " }),", "  });", "  const data = await res.json();",
            "  if (!res.ok) {", '    errorBox.textContent = typeof data.detail === "string" ? data.detail : "Please check your input";', "    return;", "  }"]
    if s.computed:
        out.append('  document.getElementById("result").textContent = "Result: " + ' + ("summary(data)" if summary_mode else "JSON.stringify(data)") + ";")
    else:
        out.append('  document.getElementById("form").reset();')
    out += ['  UI.toast("Added", "success");', "  await load();", "});"]
    if flt is not None:
        out.append('document.getElementById("filter").addEventListener("change", load);')
    if "search" in s.features and s.texts:
        out.append('document.getElementById("search").addEventListener("input", load);')
    if s.clear:
        out.append('document.getElementById("clear").addEventListener("click", clearAll);')
    out += ["", "load();", ""]
    return "\n".join(out)


def is_placeholder(text: str) -> bool:
    return any(p in text for p in PLACEHOLDERS) and len(text) < 600
