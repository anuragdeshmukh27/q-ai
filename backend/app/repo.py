"""Git isolation for generated projects: one worktree and branch per agent, merges into main, branch graph.

`workspace/<slug>` is the main checkout (branch `main`). Agent `x` works in `workspace/<slug>/.worktrees/x` on branch
`agent/x`, so parallel agents never touch the same checkout. Only the Integrator merges into `main`.
"""
from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

GENERATED_TEST_DIRS = ("tests/api", "tests/ui", "tests/qa")


class GitError(RuntimeError):
    """A git command failed; the message is short and safe to show."""


@dataclass
class MergeOutcome:
    ok: bool
    conflicts: list[str] = field(default_factory=list)
    detail: str = ""


def run_git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise GitError(f"git {args[0]} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r


class Repo:
    """Thread-safe wrapper around the project's repository. Merges into `main` are serialised by a lock."""

    def __init__(self, root: Path | str, main: str = "main"):
        self.root = Path(root)
        self.main = main  # the integration branch: `main` for a generated project, `q/finish` for an imported one (the user's code stays on `q/base`)
        self.lock = threading.RLock()
        self._worktrees: dict[str, Path] = {}

    # -- worktrees ------------------------------------------------------------------
    def branch(self, agent_id: str) -> str:
        return f"agent/{agent_id}"

    def worktree(self, agent_id: str) -> Path:
        """Create (once) the agent's worktree on branch agent/<id>, starting from the current main."""
        with self.lock:
            if agent_id not in self._worktrees:
                path = self.root / ".worktrees" / agent_id
                if not path.exists():
                    run_git(self.root, "worktree", "add", "-b", self.branch(agent_id), str(path), self.main)
                self._worktrees[agent_id] = path
            return self._worktrees[agent_id]

    def sync(self, agent_id: str) -> None:
        """Bring the agent's branch up to date with main (a fast-forward unless the agent has unmerged work)."""
        wt = self.worktree(agent_id)
        with self.lock:
            r = run_git(wt, "merge", self.main, "--no-edit", "-m", f"[sync] {self.main} into {self.branch(agent_id)}", check=False)
            if r.returncode != 0:
                run_git(wt, "merge", "--abort", check=False)
                raise GitError(f"could not sync {self.branch(agent_id)} with main: {(r.stdout or r.stderr).strip()[:200]}")

    def commit(self, cwd: Path, message: str) -> bool:
        """Stage everything and commit. Returns False when there was nothing to commit."""
        run_git(cwd, "add", "-A")
        if not run_git(cwd, "status", "--porcelain").stdout.strip():
            return False
        run_git(cwd, "commit", "-m", message)
        return True

    def discard_unmerged(self, agent_id: str) -> None:
        """Throw away everything on the agent's branch and in its worktree that is not in main (an abandoned optional task)."""
        wt = self.worktree(agent_id)
        with self.lock:
            run_git(wt, "reset", "--hard", self.main)
            run_git(wt, "clean", "-fd")

    # -- inspection -----------------------------------------------------------------
    def diff_vs_main(self, agent_id: str, skip_generated_tests: bool = False) -> str:
        """What the agent's branch adds on top of main (three-dot diff).

        `skip_generated_tests` leaves out tests/api, tests/ui and tests/qa (written from the contract on QA's behalf, never by the engineer),
        so the Reviewer does not ask the engineer to change files the engineer may not edit."""
        spec = ["--", ".", *(f":(exclude){d}" for d in GENERATED_TEST_DIRS)] if skip_generated_tests else []
        return run_git(self.root, "diff", f"{self.main}...{self.branch(agent_id)}", *spec).stdout

    def on_main(self) -> set[str]:
        """Every file that is tracked on main."""
        return {l.strip() for l in run_git(self.root, "ls-tree", "-r", "--name-only", self.main).stdout.splitlines() if l.strip()}

    def changed_files(self, agent_id: str) -> list[str]:
        out = run_git(self.root, "diff", "--name-only", f"{self.main}...{self.branch(agent_id)}").stdout
        return [l.strip() for l in out.splitlines() if l.strip()]

    def graph(self) -> list[dict]:
        """Every commit with its parents and branch labels, newest first (for the UI's branch graph)."""
        fmt = "%H%x1f%P%x1f%D%x1f%s%x1f%an"
        out = run_git(self.root, "log", "--all", "--topo-order", f"--pretty=format:{fmt}").stdout
        rows = []
        for line in out.splitlines():
            h, parents, refs, subject, author = (line.split("\x1f") + [""] * 5)[:5]
            rows.append({"hash": h[:8], "parents": [p[:8] for p in parents.split()], "refs": [r.strip() for r in refs.split(",") if r.strip()],
                         "subject": subject, "author": author})
        return rows

    # -- integration ----------------------------------------------------------------
    def merge_into_main(self, agent_id: str, message: str) -> MergeOutcome:
        """`git merge --no-ff agent/<id>` on main. On conflict the merge is left open so the Integrator can resolve it."""
        with self.lock:
            run_git(self.root, "checkout", self.main, check=False)
            r = run_git(self.root, "merge", "--no-ff", "-m", message, self.branch(agent_id), check=False)
            if r.returncode == 0:
                return MergeOutcome(True)
            conflicts = self.conflicted_files()
            if conflicts:
                return MergeOutcome(False, conflicts, "merge conflict")
            run_git(self.root, "merge", "--abort", check=False)
            return MergeOutcome(False, [], (r.stderr or r.stdout).strip()[:300])

    def conflicted_files(self) -> list[str]:
        out = run_git(self.root, "diff", "--name-only", "--diff-filter=U").stdout
        return [l.strip() for l in out.splitlines() if l.strip()]

    def finish_merge(self) -> None:
        run_git(self.root, "add", "-A")
        run_git(self.root, "commit", "--no-edit")

    def abort_merge(self) -> None:
        run_git(self.root, "merge", "--abort", check=False)
