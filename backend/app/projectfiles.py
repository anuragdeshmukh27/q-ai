"""Read-only views of a generated project for the UI: file tree, file content, commits and diffs. Everything stays inside the project root."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .repo import GitError, Repo, run_git

HIDDEN = {".git", ".worktrees", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
HIDDEN_FILES = {".env", "messages.db", "app.log"}
MAX_FILE_BYTES = 300_000
MAX_DIFF_CHARS = 200_000
_SHA = re.compile(r"^[0-9a-f]{4,40}$")
_BRANCH = re.compile(r"^(main|agent/[a-z0-9_-]{1,40})$")


class ProjectFileError(Exception):
    """Safe to show in the UI. `status` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _hidden(rel_parts: tuple[str, ...]) -> bool:
    return any(p in HIDDEN for p in rel_parts) or (bool(rel_parts) and rel_parts[-1] in HIDDEN_FILES)


def file_tree(root: Path) -> list[dict]:
    """Flat, sorted list of {path, size} for every visible file."""
    root = Path(root)
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in HIDDEN)
        for f in sorted(files):
            p = Path(dirpath) / f
            rel = p.relative_to(root).parts
            if not _hidden(rel):
                out.append({"path": "/".join(rel), "size": p.stat().st_size})
    return out


def read_project_file(root: Path, rel: str) -> dict:
    root = Path(os.path.realpath(root))
    if not rel or rel.startswith(("/", "\\")) or ".." in Path(rel).parts or ":" in rel:
        raise ProjectFileError("that path is not allowed")
    target = Path(os.path.realpath(root / rel))
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        raise ProjectFileError("that path is not allowed") from None
    if _hidden(parts):
        raise ProjectFileError("that path is not allowed")
    if not target.is_file():
        raise ProjectFileError("file not found", 404)
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ProjectFileError("file is too large to show", 413)
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ProjectFileError("binary files cannot be shown", 415) from None
    return {"path": "/".join(parts), "content": text, "size": len(text)}


def commits(root: Path) -> list[dict]:
    try:
        return Repo(root).graph()
    except GitError:
        return []


def commit_diff(root: Path, sha: str) -> dict:
    if not _SHA.match(sha or ""):
        raise ProjectFileError("not a commit id")
    try:
        parents = run_git(Path(root), "rev-list", "--parents", "-n", "1", sha).stdout.split()[1:]
        if len(parents) > 1:  # a merge: show what it brought into main (against the first parent), which is the per-task diff
            r = run_git(Path(root), "diff", "--stat", "--patch", parents[0], sha)
        else:
            r = run_git(Path(root), "show", "--format=%H%n%s%n%an", "--stat", "--patch", sha)
    except GitError:
        raise ProjectFileError("commit not found", 404) from None
    return {"sha": sha, "merge": len(parents) > 1, "diff": r.stdout[:MAX_DIFF_CHARS], "truncated": len(r.stdout) > MAX_DIFF_CHARS}


def branch_diff(root: Path, branch: str) -> dict:
    """What a branch adds on top of main (three dots), for the diff view."""
    if not _BRANCH.match(branch or ""):
        raise ProjectFileError("not a branch name")
    try:
        r = run_git(Path(root), "diff", f"main...{branch}")
    except GitError:
        raise ProjectFileError("branch not found", 404) from None
    return {"branch": branch, "diff": r.stdout[:MAX_DIFF_CHARS], "truncated": len(r.stdout) > MAX_DIFF_CHARS}
