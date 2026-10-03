"""Pydantic models for the Architect and Planner outputs, plus the semantic checks on them.

Every LLM output is validated twice: by the schema (shape) and by `check_*` (meaning).
`check_*` returns a list of plain-language problems that are fed back to the model.
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
RESERVED_PATHS = {"/", "/health", "/static", "/docs", "/openapi.json", "/redoc"}
FieldType = Literal["string", "number", "integer", "boolean", "array", "object"]


class FieldSpec(BaseModel):
    name: str
    type: FieldType
    description: str = ""
    options: list[str] = Field(default_factory=list, description="For a categorical string field: the allowed values, as human labels in display order (for example Low, Medium, High)")


class ErrorSpec(BaseModel):
    status: int
    detail: str


class ExampleSpec(BaseModel):
    """One concrete request and the status/response it must produce; the contract tests are generated from these."""
    description: str
    request: dict[str, Any] = Field(default_factory=dict, description="Body fields (or query / path parameters) to send")
    status: int
    response: dict[str, Any] = Field(default_factory=dict, description="Keys with exact expected values; omit anything unpredictable")


class Endpoint(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    summary: str
    request_fields: list[FieldSpec] = Field(default_factory=list)
    response_status: int = 200
    response_fields: list[FieldSpec] = Field(default_factory=list)
    errors: list[ErrorSpec] = Field(default_factory=list)
    examples: list[ExampleSpec] = Field(default_factory=list)


class ColumnSpec(BaseModel):
    name: str
    type: Literal["INTEGER", "TEXT", "REAL", "BOOLEAN", "TIMESTAMP"]
    constraints: str = ""


class TableSpec(BaseModel):
    name: str
    columns: list[ColumnSpec]


class DbFunction(BaseModel):
    name: str
    signature: str
    description: str


def singular(name: str) -> str:
    """posts -> post, stories -> story, addresses -> address (names are plural snake_case words)."""
    n = name.lower()
    if n.endswith("ies") and len(n) > 3:
        return n[:-3] + "y"
    if re.search(r"(ss|x|z|ch|sh)es$", n):
        return n[:-2]
    if n.endswith("ss") or len(n) < 2:
        return n
    return n[:-1] if n.endswith("s") else n


class ActionInfo(BaseModel):
    name: str  # upvote, downvote, like, complete
    field: str  # the counter (increment) or yes/no field (toggle) it changes
    kind: Literal["increment", "toggle"]


class ResourceInfo(BaseModel):
    """What the engine knows about one resource of a relational design (filled by `relations.synthesize_design`, never by the model)."""
    name: str  # plural, also the table name
    singular: str
    parent: str = ""  # name of the parent resource, "" for a top-level one
    fk: str = ""  # the child's link column, for example post_id
    fields: list[FieldSpec] = Field(default_factory=list, description="what the user enters (no id, no counters, no link)")
    counters: list[str] = Field(default_factory=list)  # owned by the server, changed only by an increment action
    flags: list[str] = Field(default_factory=list)  # yes/no fields changed only by a toggle action
    actions: list[ActionInfo] = Field(default_factory=list)
    sorts: list[str] = Field(default_factory=list)  # ["new", "top"] or []
    top_by: str = ""  # SQL ordering expression for sort=top, for example "upvotes - downvotes"


class ArchitectOutput(BaseModel):
    preset: str
    architecture: str = Field(description="Short markdown: components and how a request flows through them")
    endpoints: list[Endpoint]
    tables: list[TableSpec] = Field(default_factory=list)
    db_functions: list[DbFunction] = Field(default_factory=list)
    ui_features: list[str] = Field(default_factory=list, description="What the web page must let the user do")
    # Not part of the model's JSON schema: the engine fills it for relational designs (empty = a plain single-resource design, handled as before).
    resources: SkipJsonSchema[list[ResourceInfo]] = Field(default_factory=list)


# Fields that name a category of things. They are strings with human labels (Low / Medium / High), never bare numbers (1 / 2 / 3).
MUST_HAVE_OPTIONS = re.compile(r"(^|_)(priority|status|category|severity|state|stage)$")
NEVER_NUMERIC = re.compile(r"(^|_)(priority|status|category|severity|state|stage|kind|type)$")
# Words SQLite refuses (or misreads) as a bare column name: a field called `group` or `order` breaks the generated SQL.
SQL_RESERVED = {"group", "order", "index", "table", "key", "values", "default", "limit", "check", "references", "select", "where", "from", "by", "primary",
                "unique", "constraint", "column", "references", "transaction", "between", "case", "when", "then", "end", "join", "like", "in", "is", "not",
                "null", "and", "or", "as", "on", "set", "update", "delete", "insert", "into", "drop", "create", "alter", "add", "all", "distinct", "having",
                "offset", "union", "exists", "desc", "asc", "to", "with", "view", "trigger", "match", "natural", "cross", "left", "right", "inner", "outer"}


def reserved_problem(where: str, name: str) -> list[str]:
    if name.lower() in SQL_RESERVED:
        return [f"{where}: '{name}' is an SQL keyword and breaks the generated database code. Rename the field, for example '{name}_name' or '{name}_value'"]
    return []


MAX_ENDPOINTS_PER_RESOURCE = 5  # the prompts ask for 4; one extra is tolerated
MAX_FIELDS_PER_RESOURCE = 6  # without id and timestamps


def check_options(where: str, name: str, ftype: str, options: list[str]) -> list[str]:
    """A categorical field is a string enum with human labels; the UI shows the labels and colours badges by them."""
    reserved = reserved_problem(where, name)
    if reserved:
        return reserved
    if ftype in ("number", "integer") and NEVER_NUMERIC.search(name):
        return [f"{where}: '{name}' is a category, so it must be a string with human labels in `options` (for example Low, Medium, High), not a number"]
    if ftype == "string" and not options and MUST_HAVE_OPTIONS.search(name):
        return [f"{where}: '{name}' is a category: give it `options`, the allowed values as human labels (for example [\"Low\", \"Medium\", \"High\"])"]
    if not options:
        return []
    out: list[str] = []
    if ftype != "string":
        out.append(f"{where}: '{name}' has options, so its type must be string")
    if not 2 <= len(options) <= 8:
        out.append(f"{where}: '{name}' needs between 2 and 8 options")
    if len({o.strip().lower() for o in options}) != len(options):
        out.append(f"{where}: the options of '{name}' must be different from each other")
    for o in options:
        if not o.strip() or re.fullmatch(r"[\d.\s]+", o) or "_" in o or o != o.strip():
            out.append(f"{where}: option {o!r} of '{name}' is not a human label. Write words such as \"High\" or \"In progress\" (no numbers, no snake_case)")
    return out


def _type_ok(ftype: str, value: Any) -> bool:
    if ftype in ("number", "integer"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if ftype == "string":
        return isinstance(value, str)
    if ftype == "boolean":
        return isinstance(value, bool)
    return True


def check_examples(e: Endpoint) -> list[str]:
    """Examples become tests, so they must agree with the contract and cover every success and error case."""
    where = f"{e.method} {e.path}"
    out: list[str] = []
    params = set(re.findall(r"\{(\w+)\}", e.path))
    req_names = {f.name for f in e.request_fields} | params
    resp_names = {f.name for f in e.response_fields}
    statuses = {e.response_status} | {x.status for x in e.errors}
    if not params and not any(x.status == e.response_status for x in e.examples):
        out.append(f"{where}: add an example with status {e.response_status} (the success case)")
    for err in e.errors:
        if not any(x.status == err.status for x in e.examples):
            out.append(f"{where}: add an example that triggers the {err.status} error '{err.detail}' (request values that cause it, response {{\"detail\": \"{err.detail}\"}})")
    for x in e.examples:
        if x.status not in statuses:
            out.append(f"{where}: example '{x.description}' has status {x.status}, which is neither {e.response_status} nor a listed error")
        for f in e.request_fields:
            if f.options and f.name in x.request and x.request[f.name] not in f.options:
                out.append(f"{where}: example '{x.description}' sends {x.request[f.name]!r} for '{f.name}', which is not one of its options {f.options}")
            if f.name in x.request and not _type_ok(f.type, x.request[f.name]):
                out.append(f"{where}: example '{x.description}' sends {x.request[f.name]!r} for the {f.type} field '{f.name}'. Wrong types are answered "
                           "with 422 by FastAPI, not with your error; use a correctly typed value, or remove this example")
        extra = set(x.request) - req_names
        if extra:
            out.append(f"{where}: example '{x.description}' sends {sorted(extra)} which are not request fields")
        missing = [f.name for f in e.request_fields if f.name not in x.request and e.method in ("POST", "PUT", "PATCH")]
        if missing and x.status < 400:
            out.append(f"{where}: example '{x.description}' must send every request field; missing {missing}")
        for p in params:
            if p not in x.request:
                out.append(f"{where}: example '{x.description}' must give the path parameter {p}")
        if x.status < 400:
            echoed = list(x.request.values())  # values may be lists (tags), so no set
            # Server-generated identifiers (id, user_id, ...) are not "computed from the input"; an empty request has nothing to compute from at all.
            computed = {k: v for k, v in x.response.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v not in echoed
                        and k != "id" and not k.endswith("_id")}
            has_numeric_input = any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in x.request.values())
            if computed and x.request and not has_numeric_input:
                out.append(f"{where}: example '{x.description}' expects the computed value(s) {computed} but its request contains no numbers to compute them from. "
                           "Add the missing input fields (for example numbers a and b) to `request_fields` and to the example request")
            for f in e.response_fields:
                if f.options and f.name in x.response and x.response[f.name] not in f.options:
                    out.append(f"{where}: example '{x.description}' expects {x.response[f.name]!r} for '{f.name}', which is not one of its options {f.options}")
            bad = set(x.response) - resp_names
            if bad:
                out.append(f"{where}: example '{x.description}' expects {sorted(bad)} which are not response fields")
        else:
            details = [er.detail for er in e.errors if er.status == x.status]
            if x.response.get("detail") not in details or set(x.response) != {"detail"}:
                out.append(f"{where}: example '{x.description}' (status {x.status}) must have response exactly "
                           f"{{\"detail\": <one of {details}>}}. If it shows a different error, add that error to `errors` first")
    return out


def _resource(path: str, tables: set[str] | None = None) -> str:
    """The resource an endpoint belongs to: its first path word, or (when the design has tables) the LAST path word that names a table,
    so /api/posts/{post_id}/comments belongs to comments and /api/posts/{id}/upvote to posts."""
    parts = [p for p in path.split("/") if p and p != "api" and not p.startswith("{")]
    if tables:
        named = [p for p in parts if p in tables]
        if named:
            return named[-1]
    return parts[0] if parts else path


COUNTER_NAME = re.compile(r"^(upvotes?|downvotes?|votes?|likes?|dislikes?|views?)$")
COUNTERS = ("upvotes", "downvotes", "votes", "likes", "dislikes", "views")
COUNTER_ACTION = {"upvotes": "upvote", "downvotes": "downvote", "votes": "vote", "likes": "like", "dislikes": "dislike", "views": "view"}
MAX_ACTIONS_PER_RESOURCE = 2
MAX_RESOURCES = 2


def check_categories(endpoints: list[Endpoint]) -> list[str]:
    """Categorical fields are labelled string enums everywhere they appear, with the same labels in every endpoint."""
    problems: list[str] = []
    seen: dict[str, list[str]] = {}
    for e in endpoints:
        for f in [*e.request_fields, *e.response_fields]:
            problems += check_options(f"{e.method} {e.path}", f.name, f.type, f.options)
            if f.options:
                seen.setdefault(f.name, f.options)
    for e in endpoints:
        for f in [*e.request_fields, *e.response_fields]:
            if f.name in seen and f.options != seen[f.name] and f.type == "string":
                problems.append(f"{e.method} {e.path}: field '{f.name}' must list the same options everywhere: {seen[f.name]}")
    return list(dict.fromkeys(problems))


def check_caps(endpoints: list[Endpoint], tables: set[str] | None = None, relational: bool = False) -> list[str]:
    """Small designs are what a 7B model builds reliably: at most 4 (tolerated: 5) endpoints and 6 fields per resource.
    A relational design adds up to 2 action endpoints per resource, so it may have 6."""
    problems: list[str] = []
    cap = MAX_ENDPOINTS_PER_RESOURCE + (1 if relational else 0)
    for r in dict.fromkeys(_resource(e.path, tables) for e in endpoints):
        mine = [e for e in endpoints if _resource(e.path, tables) == r]
        if len(mine) > cap:
            problems.append(f"resource '{r}' has {len(mine)} endpoints; use at most 4 (list, add, edit, delete) and do the rest in the browser")
        names = {f.name for e in mine if e.method in ("POST", "PUT", "PATCH") for f in e.request_fields if f.name != "id" and not f.name.endswith("_id")}
        if len(names) > MAX_FIELDS_PER_RESOURCE:
            problems.append(f"resource '{r}' has {len(names)} fields; keep the {MAX_FIELDS_PER_RESOURCE} most important and drop the rest")
    return problems


_FILTER_BY_ORDER = re.compile(r"\b(filter|sort|order)\w*\b[^.]*\b(upvotes?|downvotes?|votes?|likes?|created_at|created|date|newest|latest|top|popular|recent)\b", re.I)


def check_relations(a: "ArchitectOutput") -> list[str]:
    """Foreign keys are integers that nest under their parent, counters belong to the server and change through action endpoints, sorting is a query field."""
    problems: list[str] = []
    tables = {t.name for t in a.tables}
    parents = {singular(n): n for n in tables}
    for e in a.endpoints:
        where = f"{e.method} {e.path}"
        for f in [*e.request_fields, *e.response_fields]:
            if f.name != "id" and f.name.endswith("_id") and f.type != "integer":
                problems.append(f"{where}: '{f.name}' is a foreign key, so its type must be integer (not {f.type})")
        if e.method in ("POST", "PUT", "PATCH"):
            for f in e.request_fields:
                if COUNTER_NAME.match(f.name):
                    problems.append(f"{where}: '{f.name}' is a counter the server owns, so the client never sends it. Remove it from the request fields and add an action "
                                    f"endpoint such as POST /api/<things>/{{id}}/{COUNTER_ACTION.get(f.name if f.name.endswith('s') else f.name + 's', f.name)} that adds 1 and returns the updated item")
                elif e.method == "POST" and "{" not in e.path and f.name.endswith("_id") and f.name[:-3] in parents:
                    problems.append(f"{where}: '{f.name}' links to {parents[f.name[:-3]]}, so the child list is nested: use POST /api/{parents[f.name[:-3]]}/{{{f.name}}}/<children> "
                                    f"(the id is a path parameter, not a body field) and answer 404 when that row does not exist")
        if re.search(r"\{\w+\}/\w+", e.path) and not any(x.status == 404 for x in e.errors):
            problems.append(f"{where}: it works on a row named in the path, so list the error 404 (for example 'Post not found') with an example for it")
        if e.method == "GET":
            for f in e.request_fields:
                if f.name == "sort" and not f.options:
                    problems.append(f"{where}: the query field 'sort' needs options, for example [\"new\", \"top\"]")
    for t in a.tables:
        for c in t.columns:
            if c.name != "id" and c.name.endswith("_id") and c.type != "INTEGER":
                problems.append(f"column {t.name}.{c.name} is a foreign key and must be INTEGER")
    for f in a.ui_features:
        if re.search(r"\bfilter", f, re.I) and _FILTER_BY_ORDER.search(f):
            problems.append(f"ui feature {f!r}: ordering by votes or date is a sort, not a filter. Use the query field `sort` with options [\"new\", \"top\"] on the list endpoint")
    return problems


def check_against_spec(a: ArchitectOutput, spec: "SpecOutput") -> list[str]:
    """The design must implement the product spec it was given: its fields, its labelled options and its operations."""
    problems: list[str] = []
    writes = [f for e in a.endpoints if e.method in ("POST", "PUT", "PATCH") for f in e.request_fields]
    reads = [f for e in a.endpoints for f in e.response_fields]
    for r in spec.resources:
        for f in r.fields:
            # a stored value may be computed by the server (a calculator's result), so it need not be something the client sends
            if not any(w.name == f.name for w in [*writes, *reads]) and not any(f.name in x.description for x in reads if x.type == "array"):
                problems.append(f"the spec's field '{f.name}' of {r.name} appears in no endpoint: add it to the request fields (what the user enters) or to the response fields")
            if f.options:
                for w in [*writes, *reads]:
                    if w.name == f.name and w.options != f.options:
                        problems.append(f"field '{f.name}' must have options {f.options} exactly, as in the spec")
                        break
        ops = {"update": ("PUT", "PATCH"), "delete": ("DELETE",)}
        for op, methods in ops.items():
            if op in r.operations and not any(e.method in methods and "{" in e.path for e in a.endpoints):
                problems.append(f"the spec says {r.name} can be {op}d, so add a {'/'.join(methods)} endpoint with an {{id}} in its path")
        if "create" in r.operations and not any(e.method == "POST" for e in a.endpoints):
            problems.append(f"the spec says {r.name} can be added, so add a POST endpoint")
    return list(dict.fromkeys(problems))


def add_spec_features(a: ArchitectOutput, spec: "SpecOutput | None") -> None:
    """A search box the spec promises must reach the page even when the Architect left it out of `ui_features` (the generated page builds the box from that list)."""
    if spec is None or any("search" in f.lower() for f in a.ui_features):
        return
    if any(re.search(r"\bsearch", f, re.I) for f in spec.features):
        a.ui_features.append("Search box that filters the list by text as you type")


def check_architecture(a: ArchitectOutput, presets: list[str], spec: "SpecOutput | None" = None) -> list[str]:
    problems: list[str] = check_categories(a.endpoints) + check_caps(a.endpoints, {t.name for t in a.tables} or None, bool(a.resources)) + check_relations(a)
    if spec is not None:
        problems += check_against_spec(a, spec)
    if a.preset not in presets:
        problems.append(f"preset must be one of {presets}")
    if not a.endpoints:
        problems.append("define at least one endpoint")
    if a.tables:
        # The schema is run for real: invalid SQL (an inline FOREIGN KEY, a made-up type) would otherwise only surface as a database engineer stuck in a loop.
        from .scaffold import schema_sql

        try:
            sqlite3.connect(":memory:").executescript(schema_sql(a))
        except sqlite3.Error as e:
            problems.append(f"the tables are not valid SQLite ({e}). Use plain columns only: INTEGER, TEXT, REAL, TIMESTAMP; no FOREIGN KEY or REFERENCES. "
                            "Keep ONE table per resource and store lists (tags) as a TEXT column of JSON text")
    seen: set[tuple[str, str]] = set()
    for e in a.endpoints:
        if not e.path.startswith("/api/"):
            problems.append(f"endpoint path {e.path!r} must start with /api/")
        if e.path in RESERVED_PATHS:
            problems.append(f"endpoint path {e.path!r} is reserved")
        if (e.method, e.path) in seen:
            problems.append(f"duplicate endpoint {e.method} {e.path}")
        seen.add((e.method, e.path))
        if not 200 <= e.response_status < 300:
            problems.append(f"{e.method} {e.path}: response_status must be 2xx")
        for err in e.errors:
            if re.search(r"missing|required|not provided|must be a number|invalid (number|type)|wrong type", err.detail, re.I) and err.status in (400, 422):
                problems.append(f"{e.method} {e.path}: error '{err.detail}' is about missing or mistyped fields. FastAPI answers those with 422 by itself, "
                                "so remove it from `errors` (list only business-rule errors such as division by zero or unknown id)")
            if not 400 <= err.status < 500:
                problems.append(f"{e.method} {e.path}: error status {err.status} must be 4xx")
        problems += check_examples(e)
        if a.db_functions and a.tables and e.method in ("POST", "PUT", "PATCH"):
            # What a client sends and stores must flow through the database layer, or the backend ends up calling functions that do not exist.
            sigs = " ".join(f.signature for f in a.db_functions)
            cols = {c.name for t in a.tables for c in t.columns}
            for f in e.request_fields:
                if not re.search(r"\b" + re.escape(f.name) + r"\b", sigs):
                    problems.append(f"{e.method} {e.path}: request field '{f.name}' is not a parameter of any db_function. Add it to the signature of the function that stores it")
                if f.name not in cols:
                    problems.append(f"{e.method} {e.path}: request field '{f.name}' is not a column of any table. Add the column (a list is stored as TEXT)")
        for f in e.request_fields:
            if f.type == "string" and re.search(r"expression|formula|equation|\bcode\b|\bscript\b|\bsql\b", f"{f.name} {f.description}", re.I):
                problems.append(f"{e.method} {e.path}: request field '{f.name}' is free text that the server would have to parse or evaluate. "
                                "That is unsafe and hard to implement. Use explicit typed fields instead (for a calculation: numbers `a`, `b` and a string `operation` "
                                "whose allowed values are listed in its description)")
    tnames = set()
    for t in a.tables:
        if not IDENT.match(t.name):
            problems.append(f"table name {t.name!r} must be snake_case")
        if t.name in tnames:
            problems.append(f"duplicate table {t.name}")
        tnames.add(t.name)
        if not t.columns:
            problems.append(f"table {t.name} has no columns")
        if not any(c.name == "id" for c in t.columns):
            problems.append(f"table {t.name} needs an 'id' INTEGER PRIMARY KEY column")
        for c in t.columns:
            if not IDENT.match(c.name):
                problems.append(f"column {t.name}.{c.name} must be snake_case")
            problems += reserved_problem(f"column {t.name}.{c.name}", c.name)
    if a.tables and not a.db_functions:
        problems.append("tables are defined but db_functions is empty; list the data access functions the backend will call")
    if a.db_functions and not a.tables:
        problems.append("db_functions are defined but there are no tables")
    signatures = " ".join(f.signature for f in a.db_functions)
    for t in a.tables:
        for c in t.columns:
            if c.name != "id" and "DEFAULT" not in c.constraints.upper() and not re.search(r"(?<!\w)" + re.escape(c.name) + r"(?!\w)", signatures):
                problems.append(
                    f"the function that inserts into {t.name} must take `{c.name}` as a parameter: add `{c.name}: <type>` to its signature. "
                    "The database never computes anything; the backend computes values and passes them in. "
                    "Name it add_<thing> and describe it as 'Stores the given values and returns the new row'"
                )
    if a.tables and not any(e.method == "GET" for e in a.endpoints):
        problems.append("data is stored but no GET endpoint reads it back: add a GET endpoint that lists the stored rows so the web page can show them")
    if a.tables and not any(re.match(r"(list|get|find|fetch|read)_", f.name) for f in a.db_functions):
        problems.append("add a db function that reads rows back, named list_<things> (e.g. list_history() -> list[dict])")
    for f in a.db_functions:
        if re.search(r"comput|calculate|calculating", f"{f.name} {f.description}", re.I):
            problems.append(f"db function {f.name} must not compute anything: rename it add_<thing>/list_<things> and make it only store or read rows")
    for f in a.db_functions:
        if not IDENT.match(f.name):
            problems.append(f"db function {f.name!r} must be a snake_case python name")
        elif not f.signature.strip().startswith(f"{f.name}("):
            problems.append(f"db function signature must start with '{f.name}(' (got {f.signature!r})")
    if not a.ui_features:
        problems.append("list at least one ui_feature")
    return problems


# --- product spec (goal enrichment) ---------------------------------------------------

class SpecField(BaseModel):
    name: str = Field(description="snake_case")
    type: Literal["string", "number", "integer", "boolean"]
    options: list[str] = Field(default_factory=list, description="Human labels for a categorical field, e.g. Low, Medium, High")


class SpecAction(BaseModel):
    name: str = Field(description="snake_case verb, e.g. upvote, downvote, like, complete")
    field: str = Field(description="the counter field it adds 1 to (increment), or the yes/no field it flips (toggle)")
    kind: Literal["increment", "toggle"]


class SpecResource(BaseModel):
    name: str = Field(description="plural snake_case, e.g. todos")
    fields: list[SpecField]
    operations: list[Literal["list", "create", "update", "delete", "clear"]] = Field(description="clear = remove every item at once")
    parent: str = Field(default="", description="For a child resource (comments of a post): the name of the parent resource. Empty for a top-level resource. Never add a post_id style field: the link is implied")
    actions: list[SpecAction] = Field(default_factory=list, description="At most 2 one-click actions (vote, like, complete). Counters such as upvotes are fields the server owns, changed only by an action")
    sorts: list[Literal["new", "top"]] = Field(default_factory=list, description="[new, top] when the list can be ordered by newest or by score; needs a counter")


class SpecOutput(BaseModel):
    title: str
    summary: str = Field(description="One sentence: what the app does for the user")
    resources: list[SpecResource] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list, description="What the page lets the user do, as short statements")
    not_included: list[str] = Field(default_factory=list, description="Things the goal suggests that this small version leaves out (login, subreddits, uploads...)")


CHILD_WORDS = {"comments", "answers", "replies", "tasks", "subtasks", "reviews", "responses", "entries", "messages", "lessons", "chapters"}
SERVER_FILLED = re.compile(r"^(id|created_at|updated_at|created|updated|timestamp)$")
_SORT_FEATURE = re.compile(r"\b(filter|sort|order)\w*\b[^.]*\b(upvotes?|downvotes?|votes?|likes?|score|created_at|created|date|newest|latest|top|popular|recent)\b", re.I)
_SEARCH_FEATURE = re.compile(r"\b(search|filter)\w*\b", re.I)


def relations_enabled() -> bool:
    """Q_RELATIONS=0 is the fallback: build only the parent resource (with its actions) and list the child under 'not included'."""
    return os.environ.get("Q_RELATIONS", "1") != "0"


def is_relational(spec: SpecOutput) -> bool:
    return any(r.parent or r.actions for r in spec.resources)


def normalize_spec(spec: SpecOutput, goal: str = "") -> SpecOutput:
    """Repair what is mechanical instead of asking a 7B model to repeat itself (mutates and returns the spec):
    a post_id style field is the link to the parent, counters (upvotes...) are integers owned by the server with an action each,
    at most 2 resources with one parent -> child relation, 'filter by upvotes / created_at' is a sort. What does not fit goes to `not_included`."""
    from .scope import classify_goal

    left: list[str] = list(spec.not_included)
    res = spec.resources
    for r in res:  # 1. a field like post_id names the parent
        for f in list(r.fields):
            if f.name.endswith("_id") and f.name != "id":
                parent = next((p for p in res if p is not r and f.name[:-3] in (singular(p.name), p.name)), None)
                if parent is not None and (not r.parent or r.parent == parent.name):
                    r.parent = parent.name
                    r.fields.remove(f)
        r.fields = [f for f in r.fields if not SERVER_FILLED.match(f.name)]
    names = {r.name for r in res}
    for r in res:
        if r.parent and (r.parent not in names or r.parent == r.name):
            r.parent = ""
    if len(res) > 1 and not any(r.parent for r in res):  # a model often forgets `parent`: comments of posts, tasks of projects are unmistakable
        text = " ".join(spec.features).lower()
        kids = [r for r in res if r.name in CHILD_WORDS]
        child = kids[0] if len(kids) == 1 else None
        owner = next((p for p in res if p is not child and p.name not in CHILD_WORDS), None) if child else res[0]
        if child is None and singular(res[1].name) in text and singular(res[0].name) in text and re.search(r"\b(each|every|per|on a|of a|under|belong)", text):
            child = res[1]
        if child is not None and owner is not None and owner is not child:
            child.parent = owner.name
    # 2. at most 2 resources: the first parent -> child pair, else the first resource
    keep = res[:1]
    child = next((r for r in res if r.parent), None)
    if child is not None and relations_enabled():
        keep = [next(p for p in res if p.name == child.parent), child]
    for r in res:
        if r not in keep:
            left.append(r.name.replace("_", " "))
    for r in keep:
        if r.parent and r.parent not in {k.name for k in keep}:
            r.parent = ""
    spec.resources = keep
    # 3. counters and actions
    for r in keep:
        by = {f.name: f for f in r.fields}
        for f in r.fields:
            if f.name in COUNTERS and not any(a.field == f.name for a in r.actions):
                r.actions.append(SpecAction(name=COUNTER_ACTION[f.name], field=f.name, kind="increment"))
        fixed: list[SpecAction] = []
        for a in r.actions:
            if a.kind == "increment" and a.field not in by:
                guess = next((c for c in (a.field + "s", a.name + "s") if c in COUNTERS), "")
                if guess:
                    a.field = guess
                    if guess not in by:
                        by[guess] = SpecField(name=guess, type="integer")
                        r.fields.append(by[guess])
            if a.field in by and a.name not in {x.name for x in fixed}:
                by[a.field].type, by[a.field].options = ("integer" if a.kind == "increment" else "boolean"), []
                fixed.append(a)
        dropped = fixed[MAX_ACTIONS_PER_RESOURCE:]
        r.actions = fixed[:MAX_ACTIONS_PER_RESOURCE]
        r.fields = [f for f in r.fields if not (f.name in COUNTERS and any(a.field == f.name for a in dropped))]
        r.sorts = ["new", "top"] if any(a.kind == "increment" for a in r.actions) else []
    # 4. features that cannot be built here
    if is_relational(spec):
        features: list[str] = []
        for x in spec.features:
            if _SORT_FEATURE.search(x):
                continue  # ordering by votes or date is the sort select, not a filter
            if _SEARCH_FEATURE.search(x):
                left.append("search and filters")
                continue
            features.append(x)
        if any(r.sorts for r in keep):
            features.append("Sort the list by Newest or Top")
        spec.features = features[:8]
    for label in (classify_goal(goal).left_out if goal else []):  # "login" from the model and "login and accounts" from the rules are one thing
        if not any(label.split()[0].lower() in x.lower() or x.lower() in label.lower() for x in left):
            left.append(label)
    spec.not_included = list(dict.fromkeys(x for x in left if x))[:6]
    return spec


def check_spec(spec: SpecOutput) -> list[str]:
    problems: list[str] = []
    if not spec.features:
        problems.append("list the features the page offers")
    if len(spec.features) > 8:
        problems.append("at most 8 features")
    if len(spec.resources) > MAX_RESOURCES:
        problems.append(f"at most {MAX_RESOURCES} resources: keep the main one and its child, and list anything else in `not_included`")
    if sum(1 for r in spec.resources if r.parent) > 1:
        problems.append("at most one resource may have a parent")
    for r in spec.resources:
        if not IDENT.match(r.name):
            problems.append(f"resource name {r.name!r} must be snake_case")
        if not r.operations:
            problems.append(f"{r.name}: list its operations")
        names = [f.name for f in r.fields]
        if len(names) != len(set(names)):
            problems.append(f"{r.name}: duplicate field names")
        counted = [f for f in r.fields if f.name != "id" and f.name not in COUNTERS]
        if len(counted) > MAX_FIELDS_PER_RESOURCE:
            problems.append(f"{r.name} has {len(counted)} fields; keep the {MAX_FIELDS_PER_RESOURCE} most important (the cap protects reliability)")
        for f in r.fields:
            if not IDENT.match(f.name):
                problems.append(f"{r.name}.{f.name} must be snake_case")
            if f.name.endswith("_id") and f.name != "id":
                problems.append(f"{r.name}.{f.name}: remove it. A child resource names its `parent`; the link is implied")
            problems += check_options(r.name, f.name, f.type, f.options)
        if len(r.actions) > MAX_ACTIONS_PER_RESOURCE:
            problems.append(f"{r.name}: at most {MAX_ACTIONS_PER_RESOURCE} actions")
        for a in r.actions:
            f = next((x for x in r.fields if x.name == a.field), None)
            if not IDENT.match(a.name):
                problems.append(f"{r.name}: action name {a.name!r} must be a snake_case verb")
            elif f is None:
                problems.append(f"{r.name}: action {a.name} changes the field {a.field!r}, which the resource does not have")
            elif (a.kind == "increment") != (f.type in ("number", "integer")):
                problems.append(f"{r.name}: action {a.name} ({a.kind}) does not fit the type of {a.field}")
        if "top" in r.sorts and not any(a.kind == "increment" for a in r.actions):
            problems.append(f"{r.name}: sorting by top needs a counter with an increment action (upvotes)")
    return problems


def spec_text(spec: SpecOutput) -> str:
    """The spec as plain markdown: shown in the Contract tab and given to the Architect."""
    lines = [f"# {spec.title}", "", spec.summary.strip(), ""]
    for r in spec.resources:
        fields = ", ".join(f"{f.name} ({' / '.join(f.options) if f.options else f.type})" for f in r.fields)
        extra = (f" Belongs to {r.parent}." if r.parent else "") + (f" Actions: {', '.join(f'{a.name} ({a.field})' for a in r.actions)}." if r.actions else "") \
            + (f" Sort: {' / '.join(r.sorts)}." if r.sorts else "")
        lines.append(f"**{r.name}**: {fields}. Operations: {', '.join(r.operations)}.{extra}")
    if spec.resources:
        lines.append("")
    lines += ["Features:", *[f"- {x}" for x in spec.features]]
    if spec.not_included:
        lines += ["", f"Not in this version: {', '.join(spec.not_included)}."]
    return "\n".join(lines) + "\n"


# --- planner ------------------------------------------------------------------------

class TaskSpec(BaseModel):
    id: str
    title: str
    owner: Literal["database", "backend", "frontend"]
    depends_on: list[str] = Field(default_factory=list)
    files: list[str] = Field(description="Source files this task creates, e.g. ['database/history.py']")
    acceptance: list[str] = Field(description="Checkable statements, each verified by a test or by reading the file")


class PlannerOutput(BaseModel):
    tasks: list[TaskSpec]


OWNER_PREFIXES = {"database": ("database/",), "backend": ("backend/",), "frontend": ("static/", "frontend/")}


def check_plan(p: PlannerOutput, needs_db: bool, endpoints: list[Endpoint], tables: int = 1) -> list[str]:
    problems: list[str] = []
    ids = [t.id for t in p.tasks]
    if not p.tasks:
        return ["the plan has no tasks"]
    if len(set(ids)) != len(ids):
        problems.append("task ids must be unique")
    n_db = sum(1 for t in p.tasks if t.owner == "database")
    if tables <= 1 and n_db > 1:
        problems.append("use exactly ONE database task with ONE file database/<name>.py for ALL tables and functions: the starting module already contains every table and function")
    if tables > 1 and n_db != tables:
        problems.append(f"the schema has {tables} tables: plan exactly one database task per table, each with its own file database/<table>.py (never one task for all tables)")
    for t in p.tasks:
        if t.owner == "database" and re.search(r"\ball (the )?tables\b", t.title, re.I):
            problems.append(f"{t.id}: a database task covers ONE table; never 'all tables'")
    for t in p.tasks:
        if not re.match(r"^t\d+$", t.id):
            problems.append(f"task id {t.id!r} must look like t1, t2, ...")
        if not t.files:
            problems.append(f"{t.id}: list the file(s) it creates")
        for f in t.files:
            if not f.startswith(OWNER_PREFIXES[t.owner]):
                problems.append(f"{t.id}: file {f!r} is not in {t.owner}'s area {OWNER_PREFIXES[t.owner]}")
            if f.startswith(("backend/main.py", "backend/__init__", "database/connection", "database/__init__", "backend/api/__init__", "static/ui-kit")):
                problems.append(f"{t.id}: {f} is a locked preset file and cannot be a task target")
        if not t.acceptance:
            problems.append(f"{t.id}: add acceptance criteria")
        problems += check_acceptance(t, endpoints)
        for d in t.depends_on:
            if d not in ids:
                problems.append(f"{t.id} depends on unknown task {d}")
            if d == t.id:
                problems.append(f"{t.id} depends on itself")
    by_file: dict[str, str] = {}
    for t in p.tasks:
        for f in t.files:
            if f in by_file:
                problems.append(f"file {f} is in both {by_file[f]} and {t.id}: give every file to exactly one task")
            by_file[f] = t.id
    if not problems and _has_cycle(p):
        problems.append("the dependency graph has a cycle")
    if not problems:
        problems += check_stage_order(p.tasks)
    owners = {t.owner for t in p.tasks}
    if "backend" not in owners:
        problems.append("no backend task: the API endpoints must be implemented")
    if "frontend" not in owners:
        problems.append("no frontend task: the web page must be built")
    if needs_db and "database" not in owners:
        problems.append("the schema has tables but there is no database task")
    if not needs_db and "database" in owners:
        problems.append("there are no tables, so there must be no database task")
    return problems


_BAD_INPUT_400 = re.compile(r"(missing|not provided|required|wrong type|non-?numeric|invalid (number|type|input))[^.]*\b400\b|\b400\b[^.]*(missing|not provided|required|non-?numeric)", re.I)


_DETAIL_TEXT = re.compile(r'"detail"\s*:\s*\\?"([^"\\]+)')


def check_acceptance(t: TaskSpec, endpoints: list[Endpoint] | None = None) -> list[str]:
    """Missing or mistyped fields are answered with 422 by FastAPI itself; a 400 criterion for them cannot be met by simple code.
    With the endpoints at hand, an error the criterion names must be one the contract lists: an engineer follows the task text, and an
    invented 'a must not be empty' check on a number field rejects 0 and breaks the real error case (division by zero)."""
    out = [f"{t.id}: acceptance {a!r} asks for 400 on missing/wrong-type input; FastAPI returns 422 for that automatically, so remove it"
           for a in t.acceptance if _BAD_INPUT_400.search(a)]
    if endpoints is not None:
        details = {x.detail.strip().lower() for e in endpoints for x in e.errors}
        statuses = {x.status for e in endpoints for x in e.errors}
        for a in t.acceptance:
            for d in _DETAIL_TEXT.findall(a):
                if d.strip().lower() not in details:
                    out.append(f"{t.id}: acceptance {a!r} expects the error detail {d!r}, which is not in the API contract. Use only the contract's errors "
                               f"({sorted(details) or 'none'}); do not invent validation, 0 is a valid number")
            for code in re.findall(r"\b(4\d\d)\b", a):
                if int(code) not in statuses and int(code) != 422:
                    out.append(f"{t.id}: acceptance {a!r} expects status {code}, but the contract lists no such error. Remove it")
    return list(dict.fromkeys(out))


def _ancestors(tasks: list[TaskSpec], task_id: str) -> set[str]:
    deps = {t.id: t.depends_on for t in tasks}
    seen: set[str] = set()
    stack = list(deps.get(task_id, []))
    while stack:
        d = stack.pop()
        if d not in seen:
            seen.add(d)
            stack += deps.get(d, [])
    return seen


def check_stage_order(tasks: list[TaskSpec]) -> list[str]:
    """database -> backend must be visible in depends_on, not just in the list order. The frontend codes against the contract,
    so it does not wait for the backend and can be built in parallel with it (P3)."""
    out = []
    for upstream, downstream in (("database", "backend"),):
        for t in (t for t in tasks if t.owner == downstream):
            missing = [u.id for u in tasks if u.owner == upstream and u.id not in _ancestors(tasks, t.id)]
            if missing:
                out.append(f"{t.id} ({downstream}) must depend on the {upstream} task(s) {', '.join(missing)} (set depends_on)")
    return out


def _has_cycle(p: PlannerOutput) -> bool:
    deps = {t.id: set(t.depends_on) for t in p.tasks}
    done: set[str] = set()
    while deps:
        ready = [i for i, d in deps.items() if d <= done]
        if not ready:
            return True
        for i in ready:
            done.add(i)
            del deps[i]
    return False


def topo_order(tasks: list[TaskSpec]) -> list[TaskSpec]:
    """Dependency order; ties keep the planner's order, so DB work precedes backend precedes frontend."""
    rank = {"database": 0, "backend": 1, "frontend": 2}
    remaining, out = list(tasks), []
    done = {d for t in tasks for d in t.depends_on} - {t.id for t in tasks}  # dependencies outside this list are already satisfied
    while remaining:
        ready = sorted((t for t in remaining if set(t.depends_on) <= done), key=lambda t: rank[t.owner])
        if not ready:
            raise ValueError("dependency cycle")
        out.append(ready[0])
        done.add(ready[0].id)
        remaining.remove(ready[0])
    return out


def normalize_plan(p: PlannerOutput) -> PlannerOutput:
    """Repair what is mechanical instead of asking a 7B model to repeat itself (it often sends the same rejected plan three times):
    a file named by two tasks stays with the first one, and a task left with no files is dropped, its dependencies passed on to the tasks that waited for it."""
    seen: set[str] = set()
    dropped: dict[str, list[str]] = {}
    kept: list[TaskSpec] = []
    for t in p.tasks:
        files = [f for f in dict.fromkeys(t.files) if f not in seen]
        if t.files and not files:
            dropped[t.id] = t.depends_on
            continue
        seen.update(files)
        t.files = files
        kept.append(t)
    for t in kept:
        deps: list[str] = []
        for d in t.depends_on:
            seen_ids: set[str] = set()
            while d in dropped and d not in seen_ids:  # follow a dropped task to what it was waiting for
                seen_ids.add(d)
                deps += dropped[d]
                d = ""
                break
            if d:
                deps.append(d)
        t.depends_on = [d for d in dict.fromkeys(deps) if d != t.id and any(k.id == d for k in kept)]
    p.tasks = kept
    return p
