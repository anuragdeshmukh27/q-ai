"""The starting page for a relational design: a feed of posts with a detail view (the open post, its comments below it, the add-comment form under them).

Like `uistub` for a single resource: the form, the feed built with `UI.renderFeed` (a vote column, title, "by author · time ago", "💬 N comments"),
a button for every endpoint of an item (Edit, Delete, each action) and the nested child list are all implied by the contract, so they are generated and
the Frontend engineer refines them. Every request is its own small function with its literal URL and method, because the generated UI tests look for
them (`called_from_a_button`). The vote buttons are `actions` with a `slot` ("up" / "down"), which the kit draws in the vote column. app.js stays under
the reviewer's 150-line limit.
"""
from __future__ import annotations

import json

from .relations import child_of
from .schemas import ArchitectOutput, ResourceInfo, singular
from .uistub import (AUTHOR_NAMES, BODY, CATEGORY_FIRST, RATING, TITLE_NAMES, _input, _label, edit_fields_for, esc, fmt_of, head_html, header_html,
                     notice_html)

SYMBOLS = {"upvote": "\\u25b2", "downvote": "\\u25bc", "like": "\\u2665", "dislike": "\\u25bc"}  # JS escapes: the file stays plain ASCII
EMPTY = "Nothing here yet. Add the first one above."


def _cap(name: str) -> str:
    return "".join(w.capitalize() for w in name.split("_"))


def _title(ri: ResourceInfo) -> str:
    texts = [f for f in ri.fields if f.type == "string" and not f.options]
    return next((f.name for n in TITLE_NAMES for f in texts if f.name == n), texts[0].name if texts else ri.fields[0].name)


def _roles(ri: ResourceInfo, compact: bool) -> dict:
    """Which field plays which part in a row: the title, the author of the byline, paragraphs, captioned detail lines, badges and numbers."""
    texts = [f.name for f in ri.fields if f.type == "string" and not f.options]
    author = next((n for n in AUTHOR_NAMES for t in texts if t == n), "")
    if compact:  # a comment has no title unless it has a field that is not the author and not a body (a loan: the member, an issue: its title)
        title = next((t for t in texts if t != author and not BODY.search(t)), "") if not any(t in TITLE_NAMES[:2] for t in texts) else _title(ri)
    else:
        title = _title(ri)
    rest = [t for t in texts if t not in (title, author)]
    return {"title": title, "author": author, "details": rest, "labels": [t for t in rest if not BODY.search(t)]}


def _form(ri: ResourceInfo, ids: str, button: str, prefix: str) -> str:
    inputs = "\n            ".join(_input(f, prefix) for f in ri.fields if f.type != "boolean")
    return (f'<form id="{ids}" class="stack">\n        <div class="form-row">\n            {inputs}\n        </div>\n'
            f'        <div id="{prefix}error" class="alert alert-error"></div>\n        <div><button id="{prefix}add" type="submit">{button}</button></div>\n      </form>')


SORT_SELECT = '<div class="form-row"><div class="field" style="flex: 0 0 180px"><label for="{id}">Sort by</label><select id="{id}"><option value="new">Newest</option><option value="top">Top</option></select></div></div>'


def _numbers(ri: ResourceInfo) -> list:
    return [f for f in ri.fields if f.type in ("number", "integer")]


def page(design: ArchitectOutput, title: str = "") -> str:
    from .look import look_of

    look = look_of(design)
    parent = next(r for r in design.resources if not r.parent)
    child = child_of(design, parent)
    heading = title or _label(parent.name)
    sort = "\n      " + SORT_SELECT.format(id="sort") if parent.sorts else ""
    stats = '\n      <div id="stats"></div>' if _numbers(parent) else ""
    detail = ""
    if child:
        csort = "\n      " + SORT_SELECT.format(id="child-sort") if child.sorts else ""
        cstats = '\n    <div id="child-stats"></div>' if _numbers(child) else ""
        detail = f"""
  <div id="detail" class="stack" style="display: none">
    <button id="close" type="button" class="btn-secondary btn-sm detail-back">&larr; Back to {esc(_label(parent.name).lower())}</button>
    <div id="post"></div>{cstats}
    <section class="card">
      <h2 class="card-title">{esc(_label(child.name))} <span id="child-count" class="badge badge-info"></span></h2>{csort}
      <div id="children"></div>
    </section>
    <section class="card">
      <h2 class="card-title">Add a {esc(child.singular)}</h2>
      {_form(child, "child-form", "Add " + child.singular, "child-")}
    </section>
  </div>"""
    return f"""{head_html(heading, look)}
<body>
  <main class="container stack layout-feed">
    {header_html(heading, look)}{notice_html(look)}
    <!-- request-hook:top -->
  <div id="feed-view" class="stack">{stats}
    <section class="card">
      <h2 class="card-title">New {esc(parent.singular)}</h2>
      {_form(parent, "form", "Add", "")}
    </section>
    <section class="card">
      <h2 class="card-title">{esc(_label(parent.name))} <span id="count" class="badge badge-info"></span></h2>{sort}
      <div id="list"></div>
    </section>
  </div>{detail}
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
"""


def _score(ri: ResourceInfo) -> str:
    return f"item.{ri.counters[0]} - item.{ri.counters[1]}" if len(ri.counters) >= 2 else f"item.{ri.counters[0]}"


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
        out.append(f'async function {a.name}{S}(id) {{ await fetch("{base}/" + id + "/{a.name}", {{ method: "POST" }}); await {reload}(); }}')
    return out


def _row(ri: ResourceInfo, fields_const: str, compact: bool, opens: bool = False) -> list[str]:
    """The option lines of one row of the feed."""
    S, j = _cap(ri.singular), json.dumps
    roles = _roles(ri, compact)
    out = []
    if roles["title"]:
        out.append(f"    title: {j(roles['title'])},")
    if roles["author"]:
        out.append(f"    author: {j(roles['author'])},")
    if roles["details"]:
        out.append(f"    details: {j(roles['details'])},")
    numbers = _numbers(ri)
    labels = {n: _label(n) for n in roles["labels"]}
    if labels:
        out.append(f"    labels: {j(labels)},")
    options = [f.name for f in ri.fields if f.options]
    if options:
        out.append(f"    badges: {j(options)},")
    if numbers:
        out += [f"    values: {j([f.name for f in numbers])},", f"    formats: {j({f.name: fmt_of(f) for f in numbers})},"]
    if ri.counters:
        out.append(f"    score: {_score(ri)},")
    if opens:
        out += ["    comments: item.commentCount,", f"    noun: {j(singular(opens))},", "    onOpen: open ? () => openItem(item) : undefined,"]
    if compact:
        out.append("    compact: true,")
    booleans = [f.name for f in ri.fields if f.type == "boolean"]
    if booleans:  # a yes/no field (certificate, paid) is a checkbox in the row: ticking it saves the whole item at once
        out += [f"    done: {j(booleans[0])},",
                f"    onToggle: (checked) => save{S}(item.id, {{ ...Object.fromEntries({fields_const}.map((f) => [f.name, item[f.name]])), {booleans[0]}: checked }}),"]
    actions = []
    increments = [a for a in ri.actions if a.kind == "increment"]
    for a in ri.actions:
        if a.kind == "increment":
            slot = "up" if a is increments[0] else "down"
            actions.append(f'{{ label: "{SYMBOLS.get(a.name, "+")}", slot: "{slot}", title: {j(_label(a.name))}, onClick: () => {a.name}{S}(item.id) }}')
        else:
            actions.append(f"{{ label: {j(_label(a.name))}, onClick: () => {a.name}{S}(item.id) }}")
    actions += [f'{{ label: "Edit", onClick: () => UI.form("Edit", {fields_const}, item, (values) => save{S}(item.id, values)) }}',
                f'{{ label: "Delete", kind: "danger", onClick: () => remove{S}(item.id) }}']
    out.append("    actions: [\n      " + ",\n      ".join(actions) + ",\n    ],")
    return out


def _stat_call(ri: ResourceInfo, target: str, items: str, child: bool) -> str:
    j = json.dumps
    numbers = _numbers(ri)
    parts = [f"noun: {j(ri.singular)}", f"plural: {j(ri.name.replace('_', ' '))}"]
    rating = [f for f in numbers if RATING.search(f.name)]
    averages = (rating if child else numbers)[:2]
    if averages:
        parts.append("averages: [" + ", ".join(f'{{ field: {j(f.name)}, label: {j("Average " + _label(f.name).lower())}, format: {j(fmt_of(f))} }}' for f in averages) + "]")
    by = next((f.name for f in ri.fields if f.options and CATEGORY_FIRST.search(f.name)), next((f.name for f in ri.fields if f.options), ""))
    if by and not child:
        parts.append(f"by: {j(by)}")
    return f"UI.statStrip({target}, {items}, {{ {', '.join(parts)} }});"


def _submit(form: str, error: str, url: str, fields: list, after: list[str]) -> list[str]:
    body = ", ".join(_read(f) for f in fields)
    return [f'$("{form}").addEventListener("submit", async (ev) => {{', "  ev.preventDefault();", f'  $("{error}").textContent = "";',
            f"  const res = await fetch({url}, {{ method: \"POST\", headers: {{ \"Content-Type\": \"application/json\" }}, body: JSON.stringify({{ {body} }}) }});",
            "  const data = await res.json();", "  if (!res.ok) {",
            f'    $("{error}").textContent = typeof data.detail === "string" ? data.detail : "Please check your input";', "    return;", "  }",
            f'  $("{form}").reset();', '  UI.toast("Added", "success");', *after, "});"]


def _read(f) -> str:
    el = f'$("{getattr(f, "dom", f.name)}")'
    if f.type == "boolean":
        return f"{f.name}: false"  # not in the form: a new item is not done yet
    return f"{f.name}: parseFloat({el}.value)" if f.type in ("number", "integer") else f"{f.name}: {el}.value"


def script(design: ArchitectOutput, title: str = "") -> str:
    parent = next(r for r in design.resources if not r.parent)
    child = child_of(design, parent)
    j = json.dumps
    P, C = _cap(parent.singular), (_cap(child.singular) if child else "")
    out = ['const $ = (id) => document.getElementById(id);', 'const list = $("list");', 'const count = $("count");']
    if child:
        out.append("let current = null; // the " + parent.singular + " whose " + child.name + " are open")
    out.append(f"const {parent.singular.upper()}_FIELDS = {j(edit_fields_for([f for f in parent.fields]))};")
    if child:
        out.append(f"const {child.singular.upper()}_FIELDS = {j(edit_fields_for(child.fields))};")
    for ri, reload in [(parent, "load")] + ([(child, "loadChildren")] if child else []):
        out += _functions(ri, reload, ri is parent and bool(child))
    sort = '$("sort").value' if parent.sorts else '"new"'
    out += [f"const {parent.singular}Options = (item, open) => ({{", *_row(parent, f"{parent.singular.upper()}_FIELDS", False, child.name if child else False), "});"]
    if child:
        out += [f"const {child.singular}Options = (item) => ({{", *_row(child, f"{child.singular.upper()}_FIELDS", True), "});"]
        out += ["async function withCounts(items) {  // the number of " + child.name + " of every " + parent.singular,
                "  await Promise.all(items.map(async (i) => {",
                f'    const r = await fetch("/api/{parent.name}/" + i.id + "/{child.name}");',
                "    i.commentCount = r.ok ? (await r.json()).items.length : 0;", "  }));", "  return items;", "}"]
    out += ["async function load() {", "  UI.loading(list);", f'  const res = await fetch("/api/{parent.name}"' + (' + "?sort=" + ' + sort if parent.sorts else "") + ");",
            "  const data = await res.json();", "  const items = " + ("await withCounts(data.items)" if child else "data.items") + ";",
            f'  count.textContent = UI.count(items.length, {j(parent.singular.replace("_", " "))}, {j(parent.name.replace("_", " "))});',
            "  // request-hook:loaded"]
    if _numbers(parent):
        out.append("  " + _stat_call(parent, '$("stats")', "items", False))
    out.append(f'  UI.renderFeed(list, items, (item) => {parent.singular}Options(item, true), "{EMPTY}");')
    if child:
        out.append("  if (current) {\n    current = items.find((i) => i.id === current.id) || current;\n    showItem();\n  }")
    out.append("}")
    if child:
        csort = ' + "?sort=" + $("child-sort").value' if child.sorts else ""
        out += ["async function loadChildren() {", '  const box = $("children");', "  UI.loading(box);",
                f'  const res = await fetch("/api/{parent.name}/" + current.id + "/{child.name}"{csort});', "  const data = await res.json();",
                f'  $("child-count").textContent = UI.count(data.items.length, {j(child.singular.replace("_", " "))}, {j(child.name.replace("_", " "))});']
        if _numbers(child):
            out.append("  " + _stat_call(child, '$("child-stats")', "data.items", True))
        out += [f'  UI.renderFeed(box, data.items, {child.singular}Options, "No {child.name.replace("_", " ")} yet. Add the first one below.");', "}",
                f"function showItem() {{\n  UI.renderFeed($(\"post\"), [current], (item) => {parent.singular}Options(item, false));\n}}",
                "function openItem(item) {", "  current = item;", '  $("feed-view").style.display = "none";', '  $("detail").style.display = "";', "  showItem();", "  loadChildren();", "}",
                "function closeDetail() {", "  current = null;", '  $("detail").style.display = "none";', '  $("feed-view").style.display = "";', "  load();", "}"]
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
