"""Importing a project to finish: a local folder, or a GitHub URL (a shallow clone; this is the only thing in Q that needs the internet, and only when you ask for it).

The user's own folder is never touched: the code is copied into workspace/<slug>, committed on the branch `q/base` (exactly what was imported), and all work happens on
`q/finish`. The checks that decline a project (a stack Q does not finish, too many files) run before anything is copied.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..project import git, slugify
from .analyze import IGNORE_DIRS, MAX_FILES, ImportDeclined, detect_stack, project_files

IGNORE_LINES = ["__pycache__/", "*.pyc", "*.db", "*.sqlite", "*.sqlite3", ".pytest_cache/", ".worktrees/", "data/", ".venv/", "node_modules/"]


def is_url(source: str) -> bool:
    return bool(re.match(r"^(https?://|git@|ssh://)", source.strip())) or source.strip().endswith(".git")


def fetch(source: str, scratch: Path) -> Path:
    """The folder that holds the code: the local folder itself, or a fresh shallow clone of the URL."""
    source = source.strip().strip('"')
    if is_url(source):
        dest = scratch / slugify(re.sub(r"\.git$", "", source.rstrip("/")).split("/")[-1] or "repo")
        shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["git", "clone", "--depth", "1", "--quiet", source, str(dest)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        if r.returncode != 0:
            raise ImportDeclined("I could not clone that URL (" + (r.stderr.strip().splitlines() or ["git failed"])[-1][:140] + "). A GitHub import needs the internet; a local folder does not.")
        return dest
    root = Path(source).expanduser()
    if not root.is_dir():
        raise ImportDeclined(f"I could not find the folder {source!r}.")
    return root.resolve()


def check(root: Path) -> tuple[str, list[str]]:
    """(framework, files) of a project Q finishes; raises ImportDeclined, with what was found, for anything else."""
    files = project_files(root)
    if not files:
        raise ImportDeclined("That folder has no files Q can read.")
    framework, _ = detect_stack(root, files)
    if len(files) > MAX_FILES:
        raise ImportDeclined(f"I found {len(files)} files. Q finishes projects of up to about {MAX_FILES} files: a bigger project needs more than finishing the broken ends.")
    return framework, files


def import_project(root: Path, base: Path) -> Path:
    """Copy the checked project into workspace/<slug> and put it under git: `q/base` is exactly what was imported, `q/finish` is where the work happens."""
    base.mkdir(parents=True, exist_ok=True)
    slug = slugify(root.name)
    dest, n = base / slug, 1
    while dest.exists():
        n += 1
        dest = base / f"{slug}-{n}"
    shutil.copytree(root, dest, ignore=shutil.ignore_patterns(*IGNORE_DIRS, "*.pyc", "*.db", "*.sqlite", "*.sqlite3"))
    shutil.rmtree(dest / ".git", ignore_errors=True)  # the user's history stays in the user's folder; this copy has its own
    git(dest, "init", "-b", "q/base")
    git(dest, "config", "user.name", "Q")
    git(dest, "config", "user.email", "q@localhost")
    git(dest, "config", "commit.gpgsign", "false")
    git(dest, "add", "-A")
    git(dest, "commit", "-m", "Imported project (the original, untouched)")
    git(dest, "checkout", "-b", "q/finish")
    ignore = dest / ".gitignore"
    have = ignore.read_text(encoding="utf-8").splitlines() if ignore.is_file() else []
    add = [l for l in IGNORE_LINES if l not in have]
    if add:
        ignore.write_text("\n".join([*have, *add]) + "\n", encoding="utf-8")
    return dest


def scratch_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="q-import-"))
