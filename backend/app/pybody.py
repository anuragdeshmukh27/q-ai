"""Replace the body of one Python function, leaving the rest of the file untouched.

This is how a small model fills a generated stub: it only writes the lines inside the function, so the
imports, models, decorators and signatures that came from the contract can never be damaged.
"""
from __future__ import annotations

import ast
import re
import textwrap

_DEF_LINE = re.compile(r"\s*(@|(async\s+)?def\s)")
SHRINK_MIN_LINES = 5  # bodies shorter than this may be rewritten freely


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) and isinstance(node.value.value, str)


def _body_of(code: str, name: str) -> str:
    """The model sent the whole function (def line included): keep only its body lines. "" if that is not possible."""
    try:
        tree = ast.parse(textwrap.dedent(code))
    except SyntaxError:
        return ""
    fn = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    if fn is None:
        return ""
    lines = textwrap.dedent(code).splitlines()
    first = fn.body[1] if _is_docstring(fn.body[0]) and len(fn.body) > 1 else fn.body[0]
    return "\n".join(lines[first.lineno - 1:fn.end_lineno])


def replace_function_body(source: str, name: str, body: str) -> tuple[str, str]:
    """Returns (new_source, "") or ("", problem). A leading docstring, comments and the signature are kept."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return "", f"the file does not parse (line {e.lineno}: {e.msg}); rewrite it with write_file instead"
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    matches = [n for n in funcs if n.name == name]
    if not matches:
        names = sorted({n.name for n in funcs})
        asked = [w for w in re.split(r"[\s,;]+", name.strip()) if w]
        if len(asked) > 1 and all(w in names for w in asked):
            return "", f"implement takes ONE function name per call; you sent {len(asked)} ({', '.join(asked)}). Call implement once for each of them."
        return "", f"no function named {name!r} in the file. Functions there: {', '.join(names) or 'none'}"
    if not body.strip():
        return "", "the body is empty"
    if _DEF_LINE.match(body) or re.search(rf"^(async\s+)?def\s+{re.escape(name)}", body, re.M):
        body = _body_of(body, name)
        if not body:
            return "", "give only the lines INSIDE the function (its body), not the def line or decorators"
    fn = matches[0]
    lines = source.splitlines()
    if fn.body[0].lineno == fn.lineno:
        return "", "that function is written on one line; rewrite the whole file with write_file instead"
    replace_from = fn.body[0].end_lineno if _is_docstring(fn.body[0]) else fn.body[0].lineno - 1
    indent = " " * (fn.col_offset + 4)
    new_body = [indent + line if line.strip() else line for line in textwrap.dedent(body).strip("\n").splitlines()]
    old_body = [l for l in lines[replace_from:fn.end_lineno] if l.strip()]
    if len(old_body) >= SHRINK_MIN_LINES and len([l for l in new_body if l.strip()]) * 2 < len(old_body):
        # A bug fix that sends only the changed line would delete the rest of the function. Show the current body to copy and edit.
        current = textwrap.dedent("\n".join(old_body))
        return "", (f"implement replaces the WHOLE body of {name} (now {len(old_body)} lines) and you sent {len([l for l in new_body if l.strip()])}. "
                    f"To change one line, send the complete body with that line changed. Current body:\n{current}")
    out = lines[:replace_from] + new_body + lines[fn.end_lineno:]
    return "\n".join(out) + ("\n" if source.endswith("\n") else ""), ""


def undefined_calls(tree: "ast.AST") -> list[str]:
    """Names that are called as plain functions but are bound nowhere in the module (not defined, imported, assigned, a parameter or a builtin).
    Conservative on purpose: any binding anywhere counts, so this only reports calls that are certain to raise NameError."""
    import builtins

    bound: set[str] = set(dir(builtins))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)
        elif isinstance(n, ast.arg):
            bound.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            bound.update(n.names)
        elif isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names):
            return []  # a star import binds names we cannot see
    seen: list[str] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id not in bound and n.func.id not in seen:
            seen.append(n.func.id)
    return seen


def undefined_variables(tree: "ast.AST", function: str) -> tuple[list[str], list[str]]:
    """Names READ inside `function` that are certain to raise NameError: not one of its parameters, not assigned in it (loop, with, except, comprehension,
    nested function), not bound at the top of the module (def, class, import, assignment) and not a builtin.
    -> (those names in order of appearance, the function's parameters). A 7B model writes `appointment_id` where the route's path parameter is `id`."""
    import builtins

    fn = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function), None)
    if fn is None:
        return [], []
    params = [a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs, *([fn.args.vararg] if fn.args.vararg else []), *([fn.args.kwarg] if fn.args.kwarg else [])]]
    bound: set[str] = set(dir(builtins)) | {"__file__", "__doc__", "__spec__"}
    for stmt in tree.body:  # the module's own names; function and class bodies are their own scopes
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(stmt.name)
            continue
        for n in ast.walk(stmt):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                if any(a.name == "*" for a in n.names):
                    return [], params  # a star import binds names we cannot see
                bound.update((a.asname or a.name).split(".")[0] for a in n.names)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                bound.add(n.id)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(n.name)
    for n in ast.walk(fn):  # everything bound anywhere inside the function counts (conservative: scopes are not told apart)
        if isinstance(n, ast.arg):
            bound.add(n.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            bound.update(n.names)
    out: list[str] = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in bound and n.id not in out:
            out.append(n.id)
    return out, params
