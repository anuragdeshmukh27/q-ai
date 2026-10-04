"""Related resources and one-click actions: the contract and the plan, completed by rules.

A 7B Architect cannot hold a consistent two-table contract in one answer (the reddit run: `post_id` as a string, vote counters sent by the client,
comments as a flat resource, "filter by upvotes"). The spec step says WHAT the app has (parent, actions, sorts); this module turns it into the
contract, deterministically, with the same shape every time:

- a child list is nested under its parent: GET/POST /api/posts/{post_id}/comments, 404 when the post does not exist, deleting the post deletes its comments;
- counters (upvotes...) belong to the server: they are response fields, never request fields, and change only through POST /api/posts/{id}/upvote,
  which returns the updated item; a toggle flips a yes/no field the same way;
- ordering is a query field: GET /api/posts?sort=new|top.
Agents still write every function body; the plan has one database task per table and one backend task per router.
"""
from __future__ import annotations

from .schemas import (ActionInfo, ArchitectOutput, ColumnSpec, DbFunction, Endpoint, ErrorSpec, ExampleSpec, FieldSpec, PlannerOutput,
                      ResourceInfo, SpecOutput, TableSpec, TaskSpec, _resource, singular)

PY_TYPES = {"string": "str", "number": "float", "integer": "int", "boolean": "bool"}
SQL_TYPES = {"string": "TEXT", "number": "REAL", "integer": "INTEGER", "boolean": "INTEGER"}
NOT_FOUND_ID = 99999


def label(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def sample(f: FieldSpec):
    """A valid example value for a field (the generated tests send these)."""
    if f.options:
        return f.options[0]
    if f.type == "boolean":
        return False
    if f.type == "integer":
        return 1
    if f.type == "number":
        return 2.5
    if "url" in f.name or "link" in f.name:
        return "https://example.com"
    if "email" in f.name:
        return "ada@example.com"
    if "date" in f.name:
        return "2026-01-15"
    return f"Sample {f.name.replace('_', ' ')}"


def payload(ri: ResourceInfo) -> dict:
    return {f.name: sample(f) for f in ri.fields}


def infos(spec: SpecOutput) -> list[ResourceInfo]:
    out: list[ResourceInfo] = []
    for r in spec.resources:
        counters = [a.field for a in r.actions if a.kind == "increment"]
        flags = [a.field for a in r.actions if a.kind == "toggle"]
        out.append(ResourceInfo(
            name=r.name, singular=singular(r.name), parent=r.parent, fk=f"{singular(r.parent)}_id" if r.parent else "",
            fields=[FieldSpec(name=f.name, type=f.type, options=f.options) for f in r.fields if f.name not in counters + flags],
            counters=counters, flags=flags, actions=[ActionInfo(name=a.name, field=a.field, kind=a.kind) for a in r.actions],
            sorts=list(r.sorts), top_by=" - ".join(counters[:2])))
    return sorted(out, key=lambda x: bool(x.parent))  # the parent first


def item_fields(ri: ResourceInfo) -> list[FieldSpec]:
    """Every key of one item as the API returns it."""
    return [FieldSpec(name="id", type="integer"), *([FieldSpec(name=ri.fk, type="integer")] if ri.fk else []), *ri.fields,
            *[FieldSpec(name=c, type="integer") for c in ri.counters], *[FieldSpec(name=f, type="boolean") for f in ri.flags],
            FieldSpec(name="created_at", type="string")]


def _not_found(name: str) -> str:
    return f"{label(singular(name))} not found"


def _endpoints(ri: ResourceInfo, parent: ResourceInfo | None, child: ResourceInfo | None) -> list[Endpoint]:
    p, s = ri.name, ri.singular
    nf404 = ErrorSpec(status=404, detail=_not_found(p))
    sort = [FieldSpec(name="sort", type="string", description="newest first (new) or highest score first (top)", options=["new", "top"])] if ri.sorts else []
    listing = FieldSpec(name="items", type="array", description="objects with " + ", ".join(f.name for f in item_fields(ri)))
    out: list[Endpoint] = []
    if parent is None:
        base = f"/api/{p}"
        out.append(Endpoint(method="GET", path=base, summary=f"List all {p}" + (", newest first or by score" if sort else ""), request_fields=sort,
                            response_fields=[listing], examples=[ExampleSpec(description=f"lists {p}", status=200)]))
        out.append(Endpoint(method="POST", path=base, summary=f"Add a {s}", request_fields=ri.fields, response_status=201, response_fields=item_fields(ri),
                            examples=[ExampleSpec(description=f"adds a {s}", request=payload(ri), status=201, response=payload(ri))]))
    else:
        base = f"/api/{parent.name}/{{{ri.fk}}}/{p}"
        pnf = ErrorSpec(status=404, detail=_not_found(parent.name))
        pnf_example = lambda extra: ExampleSpec(description=f"rejects an unknown {parent.singular}", request={ri.fk: NOT_FOUND_ID, **extra}, status=404, response={"detail": pnf.detail})  # noqa: E731
        out.append(Endpoint(method="GET", path=base, summary=f"List the {p} of one {parent.singular}", request_fields=sort, response_fields=[listing],
                            errors=[pnf], examples=[pnf_example({})]))
        out.append(Endpoint(method="POST", path=base, summary=f"Add a {s} to a {parent.singular}", request_fields=ri.fields, response_status=201,
                            response_fields=item_fields(ri), errors=[pnf], examples=[pnf_example(payload(ri))]))
    item = f"/api/{p}/{{id}}"
    nf_example = lambda extra: ExampleSpec(description=f"rejects an unknown id", request={"id": NOT_FOUND_ID, **extra}, status=404, response={"detail": nf404.detail})  # noqa: E731
    out.append(Endpoint(method="PUT", path=item, summary=f"Edit one {s}", request_fields=ri.fields, response_fields=item_fields(ri), errors=[nf404],
                        examples=[nf_example(payload(ri))]))
    out.append(Endpoint(method="DELETE", path=item, summary=f"Delete one {s}" + (f" and its {child.name}" if child else ""),
                        response_fields=[FieldSpec(name="deleted", type="boolean")], errors=[nf404], examples=[nf_example({})]))
    for a in ri.actions:
        what = f"adds 1 to {a.field}" if a.kind == "increment" else f"flips {a.field}"
        out.append(Endpoint(method="POST", path=f"{item}/{a.name}", summary=f"{label(a.name)} one {s}: {what} and return the updated {s}",
                            response_fields=item_fields(ri), errors=[nf404], examples=[nf_example({})]))
    return out


def _table(ri: ResourceInfo) -> TableSpec:
    cols = [ColumnSpec(name="id", type="INTEGER", constraints="PRIMARY KEY AUTOINCREMENT")]
    if ri.fk:
        cols.append(ColumnSpec(name=ri.fk, type="INTEGER", constraints="NOT NULL"))
    for f in ri.fields:
        cols.append(ColumnSpec(name=f.name, type=SQL_TYPES[f.type], constraints="NOT NULL DEFAULT 0" if f.type == "boolean" else "NOT NULL"))
    cols += [ColumnSpec(name=c, type="INTEGER", constraints="NOT NULL DEFAULT 0") for c in [*ri.counters, *ri.flags]]
    cols.append(ColumnSpec(name="created_at", type="TIMESTAMP", constraints="DEFAULT CURRENT_TIMESTAMP"))
    return TableSpec(name=ri.name, columns=cols)


def _db_functions(ri: ResourceInfo, child: ResourceInfo | None) -> list[DbFunction]:
    p, s = ri.name, ri.singular
    args = ", ".join(f"{f.name}: {PY_TYPES[f.type]}" for f in ri.fields)
    fk = f"{ri.fk}: int" if ri.fk else ""
    sort_arg = 'sort: str = "new"' if ri.sorts else ""
    join = lambda *a: ", ".join(x for x in a if x)  # noqa: E731
    order = "newest first (ORDER BY id DESC, never ORDER BY created_at: rows added in the same second have the same timestamp)"
    if ri.sorts:
        order = f"sort='new' (the default): newest first (ORDER BY id DESC, never created_at); sort='top': highest score first (ORDER BY {ri.top_by} DESC, id DESC)"
    out = [
        DbFunction(name=f"add_{s}", signature=f"add_{s}({join(fk, args)}) -> dict",
                   description="Inserts a row with these values and returns the new row as a dict (SELECT * FROM the table WHERE id = lastrowid: always SELECT *, so created_at and the counters come back too). Counters and created_at come from their column defaults."),
        DbFunction(name=f"get_{s}", signature=f"get_{s}({s}_id: int) -> dict | None", description="Returns the row as a dict (SELECT *), or None if the id does not exist."),
        DbFunction(name=f"list_{p}", signature=f"list_{p}({join(fk, sort_arg)}) -> list[dict]",
                   description=(f"Returns the rows whose {ri.fk} equals the argument (WHERE {ri.fk} = ?), " if ri.fk else "Returns every row, ") + f"as a list of dicts, ordered {order}."),
        DbFunction(name=f"update_{s}", signature=f"update_{s}({join(f'{s}_id: int', args)}) -> dict | None",
                   description="Updates the user-entered columns of the row (never counters or created_at) and returns the updated row, or None if the id does not exist."),
        DbFunction(name=f"delete_{s}", signature=f"delete_{s}({s}_id: int) -> bool",
                   description=(f"First deletes every {child.singular} of the row (DELETE FROM {child.name} WHERE {child.fk} = ?; every module's SCHEMA creates all tables), then deletes the row. " if child else "Deletes the row. ")
                   + "Returns True if the row existed, else False."),
    ]
    for a in ri.actions:
        sql = (f"UPDATE {p} SET {a.field} = {a.field} + 1 WHERE id = ?" if a.kind == "increment" else f"UPDATE {p} SET {a.field} = 1 - {a.field} WHERE id = ?")
        out.append(DbFunction(name=f"{a.name}_{s}", signature=f"{a.name}_{s}({s}_id: int) -> dict | None",
                              description=f"Runs {sql} and returns the updated row as a dict, or None if the id does not exist."))
    return out


def synthesize_design(spec: SpecOutput) -> ArchitectOutput:
    """The complete design (contract, tables, db functions, page features) for a relational spec."""
    rs = infos(spec)
    by = {r.name: r for r in rs}
    child_of = {r.parent: r for r in rs if r.parent}
    endpoints, tables, funcs, features = [], [], [], []
    for ri in rs:
        endpoints += _endpoints(ri, by.get(ri.parent), child_of.get(ri.name))
        tables.append(_table(ri))
        funcs += _db_functions(ri, child_of.get(ri.name))
        features.append(f"Form to add a {ri.singular} with " + ", ".join(f.name.replace("_", " ") for f in ri.fields) + (" (inside the open parent)" if ri.parent else ""))
        if ri.counters:
            features.append(f"List of {ri.name} showing every field and a Score line, with vote buttons that show the counts")
        if ri.sorts:
            features.append(f"Sort select (Newest or Top) for the {ri.name}")
        if ri.parent:
            features.append(f"Click a {by[ri.parent].singular} (Comments button) to open its {ri.name} with a form to add one")
        features.append(f"Edit and Delete buttons on every {ri.singular}")
    names = " and ".join(r.name for r in rs)
    arch = (f"Two SQLite tables ({names}) with one database module each; every module's schema creates both tables. FastAPI routers, one per resource. " if len(rs) > 1
            else f"One SQLite table ({names}) with one database module. A FastAPI router. ") + \
        "Counters are owned by the server and change only through action endpoints; lists are ordered by the query field sort. A single HTML page lists the items and opens a child list on click."
    return ArchitectOutput(preset="fastapi-vanilla", architecture=arch, endpoints=endpoints, tables=tables, db_functions=funcs, ui_features=features[:8], resources=rs)


# --- plan -------------------------------------------------------------------------------

def plan_for_relations(design: ArchitectOutput) -> PlannerOutput:
    """One database task per table, one backend task per router, then the page: the DAG follows from the contract, so no model has to draw it."""
    rs = design.resources
    tasks: list[TaskSpec] = []

    def add(**kw) -> str:
        tid = f"t{len(tasks) + 1}"
        tasks.append(TaskSpec(id=tid, **kw))
        return tid

    db_ids = [add(title=f"Implement the {r.name} data access functions", owner="database", depends_on=[], files=[f"database/{r.name}.py"],
                  acceptance=[f"database/{r.name}.py defines {', '.join(f.name for f in design.db_functions if f.name.endswith(('_' + r.singular, '_' + r.name)))}",
                              "the tables are created automatically on first use (the SCHEMA constant)", "run_tests passes (the database tests are already written)"])
              for r in rs]
    api_ids: list[str] = []
    for r in rs:
        eps = endpoints_for_resource(design, r.name)
        api_ids.append(add(title=f"Implement the {r.name} API router", owner="backend", depends_on=[*db_ids, *api_ids[-1:]], files=[f"backend/api/{r.name}.py"],
                           acceptance=[f"{e.method} {e.path} answers {e.response_status}" + (f" or {', '.join(str(x.status) for x in e.errors)} when it fails" if e.errors else "") for e in eps][:6]))
    related = any(r.parent or r.counters for r in rs)
    html = add(title="Build the page structure and style", owner="frontend", depends_on=[], files=["static/index.html", "static/style.css"],
               acceptance=["run_tests passes: the generated page already has the add form, the list" + (" and a view for the open item" if related else "") + " and loads /static/app.js"])
    add(title="Write the page script", owner="frontend", depends_on=[html], files=["static/app.js"],
        acceptance=["run_tests passes: the generated script is already complete (form, list" + (", vote buttons, the open item's child list" if related else ", edit and delete buttons")
                    + "); change it only where a failing test points"])
    return PlannerOutput(tasks=tasks)


# --- lookups used by stubs, tests and the orchestrator --------------------------------------

def table_names(design: ArchitectOutput) -> set[str]:
    return {t.name for t in design.tables}


def resource_for_file(design: ArchitectOutput, path: str) -> ResourceInfo | None:
    stem = path.rsplit("/", 1)[-1].removesuffix(".py")
    return next((r for r in design.resources if r.name == stem), None)


def endpoints_for_resource(design: ArchitectOutput, name: str) -> list[Endpoint]:
    tables = table_names(design)
    return [e for e in design.endpoints if _resource(e.path, tables) == name]


def parent_of(design: ArchitectOutput, ri: ResourceInfo) -> ResourceInfo | None:
    return next((r for r in design.resources if r.name == ri.parent), None)


def child_of(design: ArchitectOutput, ri: ResourceInfo) -> ResourceInfo | None:
    return next((r for r in design.resources if r.parent == ri.name), None)
