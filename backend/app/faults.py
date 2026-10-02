"""Deliberate fault injection, used to prove the QA -> owner -> fix loop.

`inject_fault(root)` makes one small, realistic mistake in the built app on `main` (flip an operator, change a status code,
reverse an ordering) and keeps it only if the test suite then fails, so the bug is guaranteed to be detectable.
The change is committed with a `[fault-injection]` message and reported by an event; it is never silent.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .repo import run_git
from .integrator import run_suite

_FLIP = {ast.Add: ("+", "-"), ast.Sub: ("-", "+"), ast.Mult: ("*", "/")}


@dataclass
class Fault:
    file: str
    description: str
    owner: str


def _flip_operator(source: str) -> tuple[str, str] | None:
    """Flip the first +, - or * between two operands on one line (AST-located, so strings and comments are never touched)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    lines = source.splitlines(keepends=True)
    for node in sorted((n for n in ast.walk(tree) if isinstance(n, ast.BinOp) and type(n.op) in _FLIP), key=lambda n: (n.lineno, n.col_offset)):
        if node.left.end_lineno != node.right.lineno or node.lineno != node.right.lineno:
            continue
        old, new = _FLIP[type(node.op)]
        line = lines[node.right.lineno - 1]
        a, b = node.left.end_col_offset, node.right.col_offset
        # ast offsets are in UTF-8 bytes
        raw = line.encode("utf-8")
        gap = raw[a:b].decode("utf-8")
        if old not in gap:
            continue
        lines[node.right.lineno - 1] = (raw[:a] + gap.replace(old, new, 1).encode("utf-8") + raw[b:]).decode("utf-8")
        return "".join(lines), f"line {node.lineno}: `{old}` became `{new}`"
    return None


def _regex(pattern: str, repl: str, what: str) -> Callable[[str], tuple[str, str] | None]:
    def mutate(source: str) -> tuple[str, str] | None:
        new, n = re.subn(pattern, repl, source, count=1)
        return (new, what) if n else None
    return mutate


MUTATORS: list[Callable[[str], tuple[str, str] | None]] = [
    _flip_operator,
    _regex(r"operator\.add\b", "operator.sub", "`operator.add` became `operator.sub`"),
    _regex(r"status_code=400", "status_code=500", "an error status 400 became 500"),
    _regex(r"ORDER BY (\w+) DESC", r"ORDER BY \1 ASC", "result ordering reversed"),
]


def _owner_of(rel: str) -> str:
    return "database" if rel.startswith("database/") else "frontend" if rel.startswith(("static/", "frontend/")) else "backend"


def inject_fault(root: Path, subdirs: tuple[str, ...] = ("backend/api", "database")) -> Fault | None:
    """Apply the first mutation that makes the suite fail, commit it on main, and return what was done (None if nothing worked)."""
    files = sorted(p for d in subdirs for p in (root / d).glob("*.py") if p.name != "__init__.py" and p.stem != "connection")
    for mutate in MUTATORS:
        for p in files:
            original = p.read_text(encoding="utf-8")
            changed = mutate(original)
            if not changed:
                continue
            new_source, what = changed
            p.write_text(new_source, encoding="utf-8", newline="\n")
            passed, _, _ = run_suite(root)
            rel = p.relative_to(root).as_posix()
            if not passed:
                run_git(root, "add", "-A")
                run_git(root, "commit", "-m", f"[fault-injection] {rel}: {what}")
                return Fault(rel, what, _owner_of(rel))
            p.write_text(original, encoding="utf-8", newline="\n")  # undetectable by the tests: try another mutation
    return None
