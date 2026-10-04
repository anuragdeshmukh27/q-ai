"""Reading someone else's half-built project: what it is, what it already does, and what is missing. Rules first, a model second (README features only).

Everything here is deterministic and read-only: the file tree and the framework, the routes (by AST), the tables, the calls the page makes to endpoints that do not exist,
function bodies that are placeholders (`pass`, `...`, `raise NotImplementedError`, `abort(501)`), TODO and FIXME comments, and the result of the project's own tests.
The result is a list of gaps; each gap becomes a task and a generated test (gaptests.py).
"""
from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

IGNORE_DIRS = {".git", ".q", ".worktrees", "node_modules", ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".idea", ".vscode", "dist", "build", ".mypy_cache", "data"}
IGNORE_SUFFIX = (".pyc", ".db", ".sqlite", ".sqlite3", ".log", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2", ".ttf", ".zip", ".lock")
MAX_FILES = 40
VERBS = ("get", "post", "put", "patch", "delete")


class ImportDeclined(Exception):
    """The project is not one Q finishes; the message says what was found and what Q does take."""


@dataclass
class Route:
    method: str
    path: str  # normalised: {name}
    file: str
    function: str
    line: int
    stub: bool = False
    body: dict = field(default_factory=dict)  # field -> annotation, from a pydantic model parameter
    var: str = ""  # the router or application variable the decorator is called on
    prefix: str = ""  # where that router is mounted (so a local path is the full path without it)


@dataclass
class Gap:
    id: str
    kind: str  # todo_body | missing_endpoint | failing_test | todo_comment | readme_feature
    title: str
    file: str
    owner: str  # backend | frontend
    detail: str = ""
    method: str = ""
    path: str = ""
    function: str = ""
    line: int = 0
    test: str = ""
    body_keys: list[str] = field(default_factory=list)
    text: str = ""
    reads: list[str] = field(default_factory=list)  # the keys of the JSON answer the page reads


@dataclass
class Analysis:
    framework: str = ""
    module: str = ""
    var: str = "app"
    entry_file: str = ""
    run_cmd: str = ""
    health_path: str = "/"
    files: list[str] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    fetches: list[dict] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    tests: dict = field(default_factory=dict)
    readme: str = ""
    db_files: list[str] = field(default_factory=list)  # the modules that hold the schema or open the database: engineers may add helpers there

    def public(self) -> dict:
        return {"framework": self.framework, "entry": f"{self.module}:{self.var}", "files": len(self.files), "routes": [asdict(r) | {"body": list(r.body)} for r in self.routes],
                "tables": self.tables, "tests": {k: v for k, v in self.tests.items() if k != "output"}, "gaps": [asdict(g) for g in self.gaps], "run_cmd": self.run_cmd}


# --- the file tree and the framework ------------------------------------------------------------------------------------------------------------------------------

def project_files(root: Path) -> list[str]:
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or any(part in IGNORE_DIRS for part in rel.parts) or p.suffix.lower() in IGNORE_SUFFIX:
            continue
        out.append(rel.as_posix())
    return out


def detect_stack(root: Path, files: list[str]) -> tuple[str, str]:
    """(framework, '') for a FastAPI or Flask project; raises ImportDeclined naming what was found otherwise."""
    pys = [f for f in files if f.endswith(".py")]
    found: dict[str, int] = {}
    for f in pys:
        text = (root / f).read_text(encoding="utf-8", errors="replace")
        for fw in ("fastapi", "flask", "django", "tornado", "aiohttp", "sanic"):
            if re.search(rf"^\s*(?:from|import)\s+{fw}\b", text, re.M):
                found[fw] = found.get(fw, 0) + 1
    names = set(files)
    if "package.json" in names:
        pkg = (root / "package.json").read_text(encoding="utf-8", errors="replace")
        kind = next((n for n in ("express", "next", "react", "vue", "nestjs", "fastify", "koa") if f'"{n}"' in pkg), "")
        raise ImportDeclined(f"I found a Node.js project (package.json{' with ' + kind if kind else ''}). Q finishes Python projects with FastAPI or Flask and a plain HTML/JavaScript page.")
    for marker, label in (("go.mod", "a Go project"), ("Cargo.toml", "a Rust project"), ("pom.xml", "a Java (Maven) project"), ("build.gradle", "a Java (Gradle) project"),
                          ("Gemfile", "a Ruby project"), ("composer.json", "a PHP project"), ("manage.py", "a Django project")):
        if marker in names:
            raise ImportDeclined(f"I found {label} ({marker}). Q finishes Python projects with FastAPI or Flask and a plain HTML/JavaScript page.")
    if found.get("django"):
        raise ImportDeclined("I found a Django project. Q finishes Python projects with FastAPI or Flask and a plain HTML/JavaScript page.")
    if found.get("fastapi") or found.get("flask"):
        return ("fastapi" if found.get("fastapi", 0) >= found.get("flask", 0) else "flask"), ""
    if pys:
        other = ", ".join(sorted(found)) or "no web framework"
        raise ImportDeclined(f"I found a Python project with {other}. Q finishes Python projects with FastAPI or Flask and a plain HTML/JavaScript page.")
    raise ImportDeclined("I did not find a Python project (no .py files). Q finishes Python projects with FastAPI or Flask and a plain HTML/JavaScript page.")


def find_app(root: Path, files: list[str], framework: str) -> tuple[str, str, str]:
    """(module, variable, file) of the FastAPI() or Flask() object."""
    ctor = "FastAPI" if framework == "fastapi" else "Flask"
    found: list[tuple[str, str, str]] = []
    for f in sorted((x for x in files if x.endswith(".py") and not x.startswith("tests/") and "test_" not in Path(x).name), key=lambda x: (x.count("/"), x)):
        try:
            tree = ast.parse((root / f).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and ast.unparse(node.value.func).split(".")[-1] == ctor and isinstance(node.targets[0], ast.Name):
                module = f[:-3].replace("/", ".")
                module = module[: -len(".__init__")] if module.endswith(".__init__") else module
                found.append((module, node.targets[0].id, f))
    if found:
        return next((c for c in found if Path(c[2]).stem in ("main", "app")), found[0])
    raise ImportDeclined(f"I found {framework} code but no module-level {ctor}() application object (a factory such as create_app() is not supported yet).")


# --- routes ----------------------------------------------------------------------------------------------------------------------------------------------------------

def _norm_path(path: str) -> str:
    path = re.sub(r"<(?:[\w.]+:)?(\w+)>", r"{\1}", path)
    return re.sub(r"\{(\w+)(?::[^}]*)?\}", r"{\1}", path) or "/"


def _join(*parts: str) -> str:
    out = "/".join(p.strip("/") for p in parts if p and p.strip("/"))
    return "/" + out


def _const(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def is_stub(fn: ast.AST, source: str = "") -> bool:
    """A function that does nothing yet: only pass, ..., raise NotImplementedError, abort(501) or an empty return (an empty list or dict counts when a TODO is in it)."""
    body = list(fn.body)  # type: ignore[attr-defined]
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body:
        return True

    def trivial(st) -> bool:
        if isinstance(st, ast.Pass):
            return True
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant):
            return True
        if isinstance(st, ast.Raise):
            return "NotImplemented" in (ast.unparse(st.exc) if st.exc else "")
        if isinstance(st, ast.Return):
            return st.value is None or (isinstance(st.value, ast.Constant) and st.value.value is None)
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and ast.unparse(st.value.func).endswith("abort") and st.value.args and ast.unparse(st.value.args[0]) == "501":
            return True
        return False

    if all(trivial(st) for st in body):
        return True
    if len(body) <= 2 and source and re.search(r"TODO|FIXME|placeholder", source, re.I):  # `return {}` / `return []` next to a TODO
        last = body[-1]
        return isinstance(last, ast.Return) and isinstance(last.value, (ast.Dict, ast.List, ast.Constant)) and not (isinstance(last.value, ast.Constant) and last.value.value not in ("", 0, False, None))
    return False


def _model_fields(trees: dict[str, ast.Module]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                fields = {st.target.id: ast.unparse(st.annotation) for st in node.body if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)}
                if fields:
                    out[node.name] = fields
    return out


def extract_routes(root: Path, files: list[str], framework: str) -> list[Route]:
    trees: dict[str, ast.Module] = {}
    sources: dict[str, str] = {}
    for f in files:
        if f.endswith(".py") and not f.startswith("tests/") and not Path(f).name.startswith("test_"):
            src = (root / f).read_text(encoding="utf-8", errors="replace")
            try:
                trees[f] = ast.parse(src)
                sources[f] = src
            except SyntaxError:
                continue
    models = _model_fields(trees)
    own_prefix: dict[tuple[str, str], str] = {}  # (file, variable) -> its own prefix
    include: dict[str, str] = {}  # variable name -> the prefix it is mounted at
    for f, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.targets[0], ast.Name):
                ctor = ast.unparse(node.value.func).split(".")[-1]
                if ctor in ("APIRouter", "Blueprint"):
                    pref = next((_const(k.value) for k in node.value.keywords if k.arg in ("prefix", "url_prefix")), "") or ""
                    own_prefix[(f, node.targets[0].id)] = pref
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("include_router", "register_blueprint") and node.args:
                var = ast.unparse(node.args[0]).split(".")[-1]
                include[var] = next((_const(k.value) for k in node.keywords if k.arg in ("prefix", "url_prefix")), "") or ""
    out: list[Route] = []
    for f, tree in trees.items():
        lines = sources[f].splitlines()
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for dec in fn.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args and _const(dec.args[0]) is not None and isinstance(dec.func.value, ast.Name)):
                    continue
                attr, var, path = dec.func.attr, dec.func.value.id, _const(dec.args[0]) or ""
                if attr in VERBS:
                    methods = [attr.upper()]
                elif attr == "route":
                    ms = next((k.value for k in dec.keywords if k.arg == "methods"), None)
                    methods = [str(_const(e)).upper() for e in ms.elts] if isinstance(ms, (ast.List, ast.Tuple)) else ["GET"]
                else:
                    continue
                full = _norm_path(_join(include.get(var, ""), own_prefix.get((f, var), ""), path))
                segment = "\n".join(lines[fn.lineno - 1:getattr(fn, "end_lineno", fn.lineno)])
                body = {}
                for a in fn.args.args:
                    ann = ast.unparse(a.annotation) if a.annotation is not None else ""
                    if ann in models:
                        body = models[ann]
                for m in methods:
                    out.append(Route(m, full, f, fn.name, fn.lineno, is_stub(fn, segment), body, var, _norm_path(_join(include.get(var, ""), own_prefix.get((f, var), "")))))
    return sorted(out, key=lambda r: (r.file, r.line))


# --- tables, fetch calls, TODO comments ----------------------------------------------------------------------------------------------------------------------------

def extract_tables(root: Path, files: list[str]) -> list[str]:
    names: list[str] = []
    for f in files:
        if f.endswith((".py", ".sql")):
            text = (root / f).read_text(encoding="utf-8", errors="replace")
            names += re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?[\"`]?(\w+)", text, re.I) + re.findall(r"__tablename__\s*=\s*[\"'](\w+)", text)
    return list(dict.fromkeys(names))


def _strings_and_exprs(arg: str) -> list[str]:
    """The URL candidates of a fetch() first argument: every string literal path, with the pieces joined by `+` and `${...}` turned into {x}."""
    out: list[str] = []
    for branch in re.split(r"\s\?\s|\s:\s(?=[\"'`])", arg):  # a ternary: each branch is a candidate
        pieces = re.findall(r"`([^`]*)`|\"([^\"]*)\"|'([^']*)'|(\+)|([\w.\[\]()]+)", branch)
        url, pending_expr = "", False
        for tpl, dq, sq, plus, expr in pieces:
            lit = tpl or dq or sq
            if lit or tpl == "" and dq == "" and sq == "" and not plus and not expr:
                text = re.sub(r"\$\{[^}]*\}", "{x}", lit)
                if pending_expr and not url.endswith("}"):
                    url += "{x}"
                url, pending_expr = url + text, False
            elif expr and url:
                pending_expr = True
        if pending_expr:
            url += "{x}"
        if url.startswith("/") or url.startswith("{x}/"):
            out.append(url)
    return out


def top_level_keys(obj: str) -> list[str]:
    """The keys of an object literal's top level: `a: 1, b, "c": f(x, y)` -> a, b, c."""
    parts, depth, cur, quote = [], 0, "", ""
    for c in obj:
        if quote:
            quote = "" if c == quote else quote
        elif c in "\"'`":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0 and not quote:
            parts.append(cur)
            cur = ""
        else:
            cur += c
    parts.append(cur)
    return [m.group(1) for p in parts if (m := re.match(r"\s*[\"']?(\w+)[\"']?\s*(?::|$)", p))]


def response_reads(text: str, pos: int) -> list[str]:
    """The keys of the response the page reads: `const s = await res.json();` and then `s.events`, `data.items`... up to the end of the function (the next `function` keyword)."""
    after = text[pos:pos + 2500]
    end = re.search(r"^(?:async\s+)?function\b|^[}]\s*$", after[1:], re.M)
    scope = after[:end.start() + 1] if end else after
    var = re.search(r"(?:const|let|var)\s+(\w+)\s*=\s*await\s+\w+\.json\(\)", scope)
    if not var:
        return []
    v = var.group(1)
    keys = re.findall(rf"\b{re.escape(v)}\.(\w+)", scope)
    skip = {"length", "map", "forEach", "filter", "push"}
    return [k for k in dict.fromkeys(keys) if k not in skip]


def extract_fetches(root: Path, files: list[str]) -> list[dict]:
    out: list[dict] = []
    for f in files:
        if not f.endswith((".js", ".html", ".jinja", ".j2")):
            continue
        text = (root / f).read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"fetch\(", text):
            i, depth, j, quote = m.end(), 1, m.end(), ""
            while j < len(text) and depth:
                c = text[j]
                if quote:
                    quote = "" if c == quote and text[j - 1] != "\\" else quote
                elif c in "\"'`":
                    quote = c
                elif c in "([{":
                    depth += 1
                elif c in ")]}":
                    depth -= 1
                j += 1
            args = text[i:j - 1]
            first, depth, quote, cut = args, 0, "", len(args)
            for k, c in enumerate(args):
                if quote:
                    quote = "" if c == quote and args[k - 1] != "\\" else quote
                elif c in "\"'`":
                    quote = c
                elif c in "([{":
                    depth += 1
                elif c in ")]}":
                    depth -= 1
                elif c == "," and depth == 0:
                    cut = k
                    break
            first, rest = args[:cut], args[cut + 1:]
            method = (re.search(r"method\s*:\s*[\"'](\w+)[\"']", rest) or [None, "GET"])[1].upper()
            keys: list[str] = []
            body = re.search(r"JSON\.stringify\(\s*\{(.*)\}\s*\)", rest, re.S)
            if body:
                keys = top_level_keys(body.group(1))
            line = text.count("\n", 0, m.start()) + 1
            reads = response_reads(text, j)
            for url in _strings_and_exprs(first.strip()):
                out.append({"method": method, "path": _norm_path(url.split("?")[0].replace("{x}", "{x}")), "file": f, "line": line, "keys": keys, "reads": reads})
    seen, uniq = set(), []
    for x in out:
        k = (x["method"], x["path"])
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    return uniq


def _route_regex(path: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\\\{\w+\\\}", "[^/]+", re.escape(path)) + "/?$")


def matches(routes: list[Route], method: str, path: str) -> bool:
    probe = re.sub(r"\{\w+\}", "x", path)
    return any(r.method == method and _route_regex(r.path).match(probe) for r in routes)


def _owner(path: str) -> str:
    return "frontend" if path.endswith((".js", ".html", ".css", ".jinja", ".j2")) or path.startswith(("static/", "templates/")) else "backend"


def home_file(routes: list[Route], entry_file: str, path: str) -> str:
    """The file that should hold a new endpoint: the one whose routes share the longest path prefix with it, else the application file."""
    others = [r for r in routes if r.file != entry_file]
    pool = others or routes
    if not pool:
        return entry_file
    return max(pool, key=lambda r: len(os.path.commonprefix([r.path, path]))).file


def readme_items(readme: str) -> list[dict]:
    """The unfinished features of a README checklist (`- [ ] Borrow a book: `POST /books/{id}/borrow` with `member` ...`), by rules: method, path, fields, the whole line."""
    out = []
    for line in readme.splitlines():
        m = re.match(r"\s*[-*]\s*\[ \]\s*(.+)", line)
        if not m:
            continue
        item = m.group(1).strip()
        ep = re.search(r"`(GET|POST|PUT|PATCH|DELETE)\s+(/[^`\s]*)`", item)
        if ep:
            keys = [k for k in re.findall(r"`(\w+)`", item) if k.lower() not in ("get", "post", "put", "patch", "delete") and not k.isupper()]
            out.append({"method": ep.group(1), "path": _norm_path(ep.group(2).split("?")[0]), "title": re.split(r"[:.]", item, 1)[0].strip(), "detail": item, "keys": keys})
    return out


def todo_comments(root: Path, files: list[str]) -> list[tuple[str, int, str]]:
    out = []
    for f in files:
        if f.endswith((".py", ".js", ".html", ".jinja", ".j2", ".css")) and not f.startswith("tests/") and "test_" not in Path(f).name:
            for i, line in enumerate((root / f).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                m = re.search(r"(?:#|//|<!--|/\*)\s*(TODO|FIXME)\b[:\s-]*(.*?)(?:-->|\*/)?\s*$", line)
                if m:
                    out.append((f, i, f"{m.group(1)}: {m.group(2).strip()}".strip(": ")))
    return out


# --- the analysis -------------------------------------------------------------------------------------------------------------------------------------------------

def run_command(framework: str, module: str, var: str) -> str:
    """How the imported app is started ({port} is filled in by the port manager)."""
    if framework == "fastapi":
        return f"python -m uvicorn {module}:{var} --host 127.0.0.1 --port {{port}}"
    return f"python -m flask --app {module}:{var} run --host 127.0.0.1 --port {{port}}"


def analyse(root: Path, run_suite=None, parse_failures=None) -> Analysis:
    files = project_files(root)
    framework, _ = detect_stack(root, files)
    module, var, entry_file = find_app(root, files, framework)
    a = Analysis(framework=framework, module=module, var=var, entry_file=entry_file, files=files)
    a.run_cmd = run_command(framework, module, var)
    a.routes = extract_routes(root, files, framework)
    a.tables = extract_tables(root, files)
    a.db_files = [f for f in files if f.endswith(".py") and not f.startswith("tests/") and not Path(f).name.startswith("test_")
                  and re.search(r"CREATE TABLE|sqlite3\.connect|create_engine\(|__tablename__", (root / f).read_text(encoding="utf-8", errors="replace"))]
    a.fetches = extract_fetches(root, files)
    readme = next((f for f in files if Path(f).name.lower() in ("readme.md", "readme.txt", "readme")), "")
    a.readme = (root / readme).read_text(encoding="utf-8", errors="replace")[:6000] if readme else ""
    plain = [r for r in a.routes if r.method == "GET" and "{" not in r.path]
    a.health_path = "/" if any(r.path == "/" for r in plain) else (plain[0].path if plain else "/")
    gaps: list[Gap] = []

    def add(kind: str, title: str, file: str, **kw) -> Gap:
        g = Gap(f"g{len(gaps) + 1}", kind, title, file, _owner(file), **kw)
        gaps.append(g)
        return g

    sources = {f: (root / f).read_text(encoding="utf-8", errors="replace") for f in files if f.endswith(".py")}
    stub_ranges: dict[str, list[tuple[int, int]]] = {}
    for f, src in sources.items():  # placeholder bodies, routes or not
        if f.startswith("tests/") or Path(f).name.startswith("test_"):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.splitlines()
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            if is_stub(fn, "\n".join(lines[fn.lineno - 1:getattr(fn, "end_lineno", fn.lineno)])) and not fn.name.startswith("__"):
                end = getattr(fn, "end_lineno", fn.lineno)
                stub_ranges.setdefault(f, []).append((fn.lineno, end))
                route = next((r for r in a.routes if r.file == f and r.function == fn.name), None)
                what = f"{route.method} {route.path}" if route else f"{fn.name}()"
                add("todo_body", f"{what} is a placeholder: write its body", f, function=fn.name, line=fn.lineno, method=route.method if route else "", path=route.path if route else "",
                    body_keys=list(route.body) if route else [], detail="\n".join(c.strip().lstrip("#").strip() for c in lines[fn.lineno - 1:end] if c.strip().startswith("#"))[:500] or f"{f}:{fn.lineno}")
    for x in a.fetches:
        if not matches(a.routes, x["method"], x["path"]):
            file = home_file(a.routes, entry_file, x["path"])
            add("missing_endpoint", f"The page calls {x['method']} {x['path']}, which does not exist: add it", file, method=x["method"], path=x["path"], body_keys=x["keys"],
                reads=x.get("reads", []),
                detail=f"called from {x['file']}:{x['line']}")
    for it in readme_items(a.readme):
        if not matches(a.routes, it["method"], it["path"]):
            add("readme_feature", f"README: {it['title']} ({it['method']} {it['path']})", home_file(a.routes, entry_file, it["path"]), method=it["method"], path=it["path"], body_keys=it["keys"],
                detail=it["detail"][:600])
    for f, line, text in todo_comments(root, files):
        if not any(a0 <= line <= b0 for a0, b0 in stub_ranges.get(f, [])):
            add("todo_comment", f"{text}  ({f}:{line})", f, line=line, text=text)
    a.gaps = gaps
    if run_suite is not None:
        passed, summary, out = run_suite(root)
        failures = parse_failures(out) if parse_failures else []
        a.tests = {"passed": passed, "summary": summary, "failed": [f.test_id for f in failures], "output": out[-4000:]}
        for f in failures:
            frames = re.findall(r"^([\w/.\-]+\.py):(\d+)", f.trace, re.M)
            file = next((p for p, _ in reversed(frames) if not p.startswith("tests/") and p in files), entry_file)
            add("failing_test", f"{f.test_id} fails: {f.message[:110]}".strip(), file, test=f.test_id, detail=f.message[:300], text=f.trace[-700:])
    return a


def reconstruct_contract(a: Analysis) -> dict:
    """The API contract as the code has it today, plus what the page and the README expect (the same shape as a generated contract; version 1)."""
    def ep(method: str, path: str, summary: str, keys: list[str], status: str) -> dict:
        return {"method": method, "path": path, "summary": summary, "request": {"fields": [{"name": k, "type": "string"} for k in keys]}, "response": {"status": 200, "fields": []},
                "errors": [], "examples": [], "state": status}

    eps = [ep(r.method, r.path, f"{r.function}() in {r.file}" + (" (placeholder)" if r.stub else ""), list(r.body), "stub" if r.stub else "implemented") for r in a.routes]
    have = {(e["method"], e["path"]) for e in eps}
    for g in a.gaps:
        if g.kind in ("missing_endpoint", "readme_feature") and (g.method, g.path) not in have:
            have.add((g.method, g.path))
            eps.append(ep(g.method, g.path, g.title, g.body_keys, "missing"))
    return {"version": 1, "error_format": {"detail": "string"}, "endpoints": eps}


def dump(a: Analysis) -> str:
    return json.dumps(a.public(), indent=1)
