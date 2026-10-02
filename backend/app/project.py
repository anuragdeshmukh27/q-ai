"""Creating generated projects under workspace/<slug>/ (each its own git repo)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .config import WORKSPACE
from .presets import DEFAULT_PRESET, load_preset

MAX_SLUG = 24  # keep paths short: worktrees nest under the project on Windows


def slugify(text: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (words[:MAX_SLUG].strip("-")) or "project"


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()[:200]}")
    return r.stdout


def create_project(goal: str, preset_name: str = DEFAULT_PRESET, base: Path | None = None, slug: str | None = None) -> Path:
    """Create the project folder from the preset skeleton, git init, and make the first commit on main."""
    base = base or WORKSPACE
    base.mkdir(parents=True, exist_ok=True)
    preset = load_preset(preset_name)
    slug = slugify(slug or goal)
    root, n = base / slug, 1
    while root.exists():
        n += 1
        root = base / f"{slug}-{n}"
    shutil.copytree(preset.skeleton, root)
    (root / ".q" / "goal.md").write_text(f"# Goal\n\n{goal}\n", encoding="utf-8")
    (root / ".q" / "decisions.md").write_text(f"# Decisions\n\n- Preset: {preset.name}\n", encoding="utf-8")
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Q")
    git(root, "config", "user.email", "q@localhost")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "add", "-A")
    git(root, "commit", "-m", "Initial skeleton")
    return root
