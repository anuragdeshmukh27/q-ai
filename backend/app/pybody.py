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
