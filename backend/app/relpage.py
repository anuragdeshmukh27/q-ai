"""The starting page for a relational design (parent list, children of the open item, vote buttons), generated from the resource model.

Like `uistub` for a single resource: the form, the list built with `UI.renderList`, a button for every endpoint of an item (Edit, Delete, each action)
and the nested child list are all implied by the contract, so they are generated and the Frontend engineer refines them. Every request is its own
small function with its literal URL and method, because the generated UI tests look for them (`called_from_a_button`). app.js stays under the
reviewer's 150-line limit.
"""
from __future__ import annotations

import json

from .relations import child_of
from .schemas import ArchitectOutput, ResourceInfo
from .uistub import TITLE_NAMES, _input, _label, edit_fields_for

SYMBOLS = {"upvote": "\\u25b2", "downvote": "\\u25bc", "like": "\\u2665", "dislike": "\\u25bc"}  # JS escapes: the file stays plain ASCII


def _cap(name: str) -> str:
    return "".join(w.capitalize() for w in name.split("_"))


def _title(ri: ResourceInfo) -> str:
    texts = [f for f in ri.fields if f.type == "string" and not f.options]
    return next((f.name for n in TITLE_NAMES for f in texts if f.name == n), texts[0].name if texts else ri.fields[0].name)


def _form(ri: ResourceInfo, ids: str, button: str, prefix: str) -> str:
    inputs = "\n            ".join(_input(f, prefix) for f in ri.fields)
    return (f'<form id="{ids}" class="stack">\n        <div class="form-row">\n            {inputs}\n        </div>\n'
            f'        <div id="{prefix}error" class="alert alert-error"></div>\n        <div><button id="{prefix}add" type="submit">{button}</button></div>\n      </form>')


SORT_SELECT = '<div class="form-row"><div class="field"><label for="{id}">Sort by</label><select id="{id}"><option value="new">Newest</option><option value="top">Top</option></select></div></div>'


def page(design: ArchitectOutput, title: str = "") -> str:
    parent = next(r for r in design.resources if not r.parent)
    child = child_of(design, parent)
    heading = title or _label(parent.name)
    sort = "\n      " + SORT_SELECT.format(id="sort") if parent.sorts else ""
    detail = ""
    if child:
        csort = "\n      " + SORT_SELECT.format(id="child-sort") if child.sorts else ""
        detail = f"""
    <section class="card" id="detail" style="display: none">
      <h2 class="card-title"><span id="detail-title"></span> <button id="close" type="button" class="btn-secondary btn-sm">Close</button></h2>{csort}
      <div id="children"></div>
      <h3>Add a {child.singular}</h3>
      {_form(child, "child-form", "Add " + child.singular, "child-")}
    </section>"""
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
      <h2 class="card-title">New {parent.singular}</h2>
      {_form(parent, "form", "Add", "")}
    </section>
    <section class="card">
      <h2 class="card-title">{_label(parent.name)} <span id="count" class="badge badge-info"></span></h2>{sort}
      <div id="list"></div>
    </section>{detail}
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
"""


def _score(ri: ResourceInfo) -> str:
    if len(ri.counters) >= 2:
        return f'"Score: " + (i.{ri.counters[0]} - i.{ri.counters[1]})'
    return f'"{_label(ri.counters[0])}: " + i.{ri.counters[0]}'


def _functions(ri: ResourceInfo, reload: str, closes: bool) -> list[str]:
    """remove / save / one function per action for a resource, each with its literal fetch."""
    S, base = _cap(ri.singular), f"/api/{ri.name}"
    out = [f"async function remove{S}(id) {{", f'  await fetch("{base}/" + id, {{ method: "DELETE" }});', '  UI.toast("Removed", "success");']
    if closes:
        out.append("  if (current && current.id === id) closeDetail();")
    out += [f"  await {reload}();", "}"]
    out += [f"async function save{S}(id, values) {{",
            f'  const res = await fetch("{base}/" + id, {{ method: "PUT", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify(values) }});',
            '  if (!res.ok) {', '    UI.toast("Could not save", "error");', "    return false;", "  }", '  UI.toast("Saved", "success");', f"  await {reload}();", "}"]
    for a in ri.actions:
        out += [f"async function {a.name}{S}(id) {{", f'  await fetch("{base}/" + id + "/{a.name}", {{ method: "POST" }});', f"  await {reload}();", "}"]
    if any(f.type == "boolean" for f in ri.fields):
        out += [f"function fieldsOf{S}(item) {{", "  return { " + ", ".join(f"{f.name}: item.{f.name}" for f in ri.fields) + " };", "}"]
    return out


def _row(ri: ResourceInfo, fields_const: str, comments: str = "") -> list[str]:
    S, j = _cap(ri.singular), json.dumps
    title = _title(ri)
    details = [f.name for f in ri.fields if f.type == "string" and not f.options and f.name != title] + (["scoreText"] if ri.counters else [])
    out = [f"    title: {j(title)},"]
    if details:
        out.append(f"    details: {j(details)},")
    options = [f.name for f in ri.fields if f.options]
    if options:
        out.append(f"    badges: {j(options)},")
    formats = {f.name: "num" for f in ri.fields if f.type in ("number", "integer")}
    if formats:
        out.append(f"    formats: {j(formats)},")
    boolean = next((f.name for f in ri.fields if f.type == "boolean"), "")
    if boolean:
        out += [f"    done: {j(boolean)},", f"    onToggle: (checked) => save{S}(item.id, {{ ...fieldsOf{S}(item), {boolean}: checked }}),"]
    elif ri.flags:
        out.append(f"    done: {j(ri.flags[0])},")
    actions = []
    for a in ri.actions:
        text = f'"{SYMBOLS.get(a.name, "+")} " + item.{a.field}' if a.kind == "increment" else j(_label(a.name))
        actions.append(f"{{ label: {text}, onClick: () => {a.name}{S}(item.id) }}")
    if comments:
        actions.append(f'{{ label: {j(_label(comments))}, onClick: () => openItem(item) }}')
    actions += [f'{{ label: "Edit", onClick: () => UI.form("Edit", {fields_const}, item, (values) => save{S}(item.id, values)) }}',
                f'{{ label: "Delete", kind: "danger", onClick: () => remove{S}(item.id) }}']
    out.append("    actions: [\n      " + ",\n      ".join(actions) + ",\n    ],")
    return out


def _submit(form: str, error: str, url: str, fields: list, after: list[str]) -> list[str]:
    body = ", ".join(_read(f) for f in fields)
    return [f'$("{form}").addEventListener("submit", async (ev) => {{', "  ev.preventDefault();", f'  $("{error}").textContent = "";',
            f"  const res = await fetch({url}, {{ method: \"POST\", headers: {{ \"Content-Type\": \"application/json\" }}, body: JSON.stringify({{ {body} }}) }});",
            "  const data = await res.json();", "  if (!res.ok) {",
            f'    $("{error}").textContent = typeof data.detail === "string" ? data.detail : "Please check your input";', "    return;", "  }",
            f'  $("{form}").reset();', '  UI.toast("Added", "success");', *after, "});"]


def _read(f) -> str:
    el = f'$("{getattr(f, "dom", f.name)}")'
    return f"{f.name}: {el}.checked" if f.type == "boolean" else f"{f.name}: parseFloat({el}.value)" if f.type in ("number", "integer") else f"{f.name}: {el}.value"


def script(design: ArchitectOutput, title: str = "") -> str:
    parent = next(r for r in design.resources if not r.parent)
    child = child_of(design, parent)
    j = json.dumps
    P, C = _cap(parent.singular), (_cap(child.singular) if child else "")
    out = ['const $ = (id) => document.getElementById(id);', 'const list = $("list");', 'const count = $("count");']
    if child:
        out.append("let current = null; // the " + parent.singular + " whose " + child.name + " are open")
    out.append(f"const {parent.singular.upper()}_FIELDS = {j(edit_fields_for(parent.fields))};")
    if child:
        out.append(f"const {child.singular.upper()}_FIELDS = {j(edit_fields_for(child.fields))};")
    for ri, reload in [(parent, "load")] + ([(child, "loadChildren")] if child else []):
        if ri.counters:
            out.append(f"const with{_cap(ri.singular)}Score = (i) => ({{ ...i, scoreText: {_score(ri)} }});")
        out += _functions(ri, reload, ri is parent and bool(child))
    sort = '$("sort").value' if parent.sorts else '"new"'
    mapper = f"data.items.map(with{P}Score)" if parent.counters else "data.items"
    out += ["async function load() {", "  UI.loading(list);", f'  const res = await fetch("/api/{parent.name}"' + (' + "?sort=" + ' + sort if parent.sorts else "") + ");",
            "  const data = await res.json();", f'  count.textContent = data.items.length + " " + {j(parent.name.replace("_", " "))};',
            f"  UI.renderList(list, {mapper}, (item) => ({{", *_row(parent, f"{parent.singular.upper()}_FIELDS", child.name if child else ""),
            '  }), "Nothing here yet. Add the first one above.");', "}"]
    if child:
        csort = ' + "?sort=" + $("child-sort").value' if child.sorts else ""
        cmap = f"data.items.map(with{C}Score)" if child.counters else "data.items"
        out += ["async function loadChildren() {", '  const box = $("children");', "  UI.loading(box);",
                f'  const res = await fetch("/api/{parent.name}/" + current.id + "/{child.name}"{csort});', "  const data = await res.json();",
                f"  UI.renderList(box, {cmap}, (item) => ({{", *_row(child, f"{child.singular.upper()}_FIELDS"),
                f'  }}), "No {child.name.replace("_", " ")} yet. Add the first one below.");', "}",
                "function openItem(item) {", "  current = item;", '  $("detail").style.display = "";', f'  $("detail-title").textContent = item.{_title(parent)};', "  loadChildren();", "}",
                "function closeDetail() {", "  current = null;", '  $("detail").style.display = "none";', "}"]
    out += _submit("form", "error", f'"/api/{parent.name}"', parent.fields, ["  await load();"])
    if child:
        out += _submit("child-form", "child-error", f'"/api/{parent.name}/" + current.id + "/{child.name}"', [_Prefixed(f, "child-") for f in child.fields],
                       ["  await loadChildren();"])
        out += ['$("close").addEventListener("click", closeDetail);']
        if child.sorts:
            out.append('$("child-sort").addEventListener("change", loadChildren);')
    if parent.sorts:
        out.append('$("sort").addEventListener("change", load);')
    out += ["", "load();", ""]
    return "\n".join(out)


class _Prefixed:
    """A field whose element id carries a prefix (the child form's inputs are `comment-content`, so they never clash with the parent's)."""

    def __init__(self, f, prefix: str):
        self.name, self.type, self.options = f.name, f.type, f.options
        self.dom = prefix + f.name
