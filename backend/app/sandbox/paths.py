"""Path sandbox: every agent path is resolved inside the agent's worktree.

Rules (all enforced on the lexical path and again on the real path, so links
and junctions cannot be used to escape or to reach `.git`):
  * relative paths only, no traversal out of the root, no Windows special names;
  * `.git` is never readable or writable;
  * reads are allowed project-wide, writes only inside `owned` and outside `forbidden`.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


class SandboxError(Exception):
    """A path or command was rejected by the sandbox. The message is safe to show to the agent."""


_DRIVE = re.compile(r"^[A-Za-z]:")
_BAD_CHARS = set('<>:"|?*')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_SHORT_NAME = re.compile(r"~\d")


def glob_to_regex(pattern: str) -> re.Pattern:
    """`**` crosses directories, `*` and `?` do not. Matching is case-insensitive (Windows)."""
    p = pattern.replace("\\", "/").strip("/")
    out, i = [], 0
    while i < len(p):
        c = p[i]
        if p.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif p.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def _matches(globs: list[re.Pattern], rel: str) -> bool:
    return any(g.match(rel) for g in globs)


def _is_inside(path: str, root: str) -> bool:
    p, r = os.path.normcase(path), os.path.normcase(root)
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:  # different drives
        return False


class PathPolicy:
    def __init__(self, root: Path | str, owned: list[str], forbidden: list[str] | None = None):
        self.root = Path(os.path.realpath(root))
        self._owned = [glob_to_regex(g) for g in owned]
        self._forbidden = [glob_to_regex(g) for g in (forbidden or [])]

    # -- public ---------------------------------------------------------------------
    def resolve_read(self, rel: str) -> Path:
        path, _ = self._resolve(rel)
        return path

    def resolve_write(self, rel: str) -> Path:
        path, lexical = self._resolve(rel)
        real = self._parts_of_real(path)
        for label, parts in (("path", lexical), ("target", real)):
            joined = "/".join(parts)
            if _matches(self._forbidden, joined):
                raise SandboxError(f"write denied: {joined} is forbidden for this agent")
            if not _matches(self._owned, joined):
                raise SandboxError(f"write denied: {joined} is outside this agent's owned paths")
        return path

    def rel(self, path: Path) -> str:
        return "/".join(self._parts_of_real(path))

    # -- internals ------------------------------------------------------------------
    def _lexical_parts(self, rel: str) -> list[str]:
        if not isinstance(rel, str) or not rel.strip():
            raise SandboxError("empty path")
        if any(ord(c) < 32 for c in rel):
            raise SandboxError("invalid characters in path")
        s = rel.replace("\\", "/")
        if s.startswith("/") or _DRIVE.match(s) or s.startswith("~"):
            raise SandboxError("absolute paths are not allowed; use a path relative to the project root")
        parts: list[str] = []
        for part in s.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if not parts:
                    raise SandboxError("path escapes the project root")
                parts.pop()
                continue
            self._check_part(part)
            parts.append(part)
        if not parts:
            raise SandboxError("path must name a file or directory inside the project")
        return parts

    @staticmethod
    def _check_part(part: str) -> None:
        if any(c in _BAD_CHARS for c in part):
            raise SandboxError(f"illegal character in path component {part!r}")
        if part.endswith((".", " ")):
            raise SandboxError(f"path component {part!r} must not end with a dot or space")
        if part.split(".")[0].casefold() in _RESERVED:
            raise SandboxError(f"reserved device name in path: {part!r}")
        if _SHORT_NAME.search(part):
            raise SandboxError(f"8.3 short names are not allowed: {part!r}")

    @staticmethod
    def _check_git(parts: list[str]) -> None:
        if any(p.casefold() == ".git" for p in parts):
            raise SandboxError(".git is not accessible")

    def _resolve(self, rel: str) -> tuple[Path, list[str]]:
        parts = self._lexical_parts(rel)
        self._check_git(parts)
        real = os.path.realpath(os.path.join(self.root, *parts))
        if not _is_inside(real, str(self.root)):
            raise SandboxError("path escapes the project root")
        real_parts = self._parts_of_real(Path(real))
        self._check_git(real_parts)
        return Path(real), parts

    def _parts_of_real(self, path: Path) -> list[str]:
        rel = os.path.relpath(os.path.realpath(path), self.root)
        return [] if rel == "." else rel.replace("\\", "/").split("/")
