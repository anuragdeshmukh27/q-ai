"""The in-app IDE for a person's task (simulation mode): a streamed pytest run in the person's worktree and the helpers the endpoints share.

The person edits only inside their role's owned paths (the sandbox's PathPolicy, the same rules an AI engineer works under) and only while that role has an open
human task; everything else is read-only. There is no shell: the test run is the only command the browser can start, and it is always `python -m pytest`."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from .config import AgentConfig
from .projectfiles import MAX_FILE_BYTES, file_tree
from .sandbox.paths import glob_to_regex

MAX_OUTPUT_LINES = 3000
TEST_TIMEOUT = 120.0
PYTEST_ARGS = ["-m", "pytest", "-v", "-rfE", "--tb=short", "-p", "no:cacheprovider", "--color=no"]
_PROGRESS = re.compile(r"^(\S+::.+?) (PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")
_SUMMARY = re.compile(r"^(FAILED|ERROR) (\S+?)(?: - .*)?$")


class IDEError(Exception):
    """Safe to show in the UI. `status` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def owner_of(agents: list[AgentConfig], rel: str) -> str:
    """The employee whose owned paths contain `rel` ("" when nobody's do). The engineers come first: `tests/test_db*.py` is the database engineer's, the rest of `tests/` is QA's."""
    for a in agents:
        if any(glob_to_regex(g).match(rel) for g in a.owned_paths):
            return a.id
    return ""


def parse_results(output: str) -> list[dict]:
    """[{id, outcome}] from `pytest -v -rfE` output: one per test, in order, plus the failures that have no test line (a file that cannot be collected)."""
    tests: list[dict] = []
    seen: set[str] = set()
    for line in output.splitlines():
        if m := _PROGRESS.match(line):
            outcome = m.group(2).lower()
            tests.append({"id": m.group(1).replace("\\", "/"), "outcome": "failed" if outcome == "error" else outcome})
            seen.add(m.group(1))
    for line in output.splitlines():
        if (m := _SUMMARY.match(line)) and m.group(2) not in seen:
            tests.append({"id": m.group(2).replace("\\", "/"), "outcome": "failed"})
            seen.add(m.group(2))
    return tests


def summary_line(output: str, fallback: str = "") -> str:
    lines = [l for l in output.strip().splitlines() if l.strip()]
    found = next((l for l in reversed(lines) if re.search(r"\b(passed|failed|error|errors|no tests ran)\b", l) and not l.startswith(("FAILED", "ERROR"))), "")
    return (found or (lines[-1] if lines else fallback)).strip(" =")


class SuiteRun:
    """One pytest run in a worktree: output lines go to `on_line` as they arrive, `result()` is the outcome. `kill()` ends it (Stop, or a run that hangs)."""

    def __init__(self, worktree: Path, on_line: Callable[[str], object], timeout: float = TEST_TIMEOUT):
        self.worktree, self.on_line, self.timeout = Path(worktree), on_line, timeout
        self.proc: subprocess.Popen | None = None
        self.timed_out = False
        self._killed = threading.Event()

    def kill(self) -> None:
        self._killed.set()
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass

    def run(self) -> dict:
        """Blocks until pytest ends. Returns {ok, passed, failed, tests, summary}."""
        lines: list[str] = []
        sent = 0
        if self._killed.is_set():  # Stop came before the process existed: there is nothing to run
            return {"ok": False, "passed": 0, "failed": 0, "tests": [], "summary": "the test run was stopped"}
        try:
            self.proc = subprocess.Popen([sys.executable, *PYTEST_ARGS], cwd=self.worktree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        except OSError as e:
            return {"ok": False, "passed": 0, "failed": 0, "tests": [], "summary": f"could not start the tests: {e}"}
        if self._killed.is_set():  # ... or between the check and the process: kill kept the flag, and could not see a process yet
            self.kill()
        timer = threading.Timer(self.timeout, self._timeout)
        timer.daemon = True
        timer.start()
        try:
            assert self.proc.stdout is not None
            for raw in self.proc.stdout:
                line = raw.rstrip("\r\n")
                lines.append(line)
                if sent < MAX_OUTPUT_LINES:
                    sent += 1
                    self.on_line(line if sent < MAX_OUTPUT_LINES else f"... output cut after {MAX_OUTPUT_LINES} lines")
            rc = self.proc.wait()
        finally:
            timer.cancel()
        output = "\n".join(lines)
        tests = parse_results(output)
        passed = sum(1 for t in tests if t["outcome"] == "passed")
        failed = sum(1 for t in tests if t["outcome"] == "failed")
        if self.timed_out:
            summary = f"test run timed out after {self.timeout:.0f}s"
        elif self._killed.is_set():
            summary = "the test run was stopped"
        else:
            summary = summary_line(output, "the tests did not run")
        return {"ok": rc == 0 and not self.timed_out and not self._killed.is_set(), "passed": passed, "failed": failed, "tests": tests, "summary": summary}

    def _timeout(self) -> None:
        self.timed_out = True
        self.kill()


MAX_SEARCH_FILES = 40  # files listed in an answer
MAX_SEARCH_LINES = 20  # lines listed per file
MIN_QUERY = 2


def search_worktree(wt: Path, query: str) -> dict:
    """Project-wide search for the person's IDE: every text file of the worktree, the ones the role may not edit included, case-insensitive and literal.
    `matches` and `files` count everything found; `results` lists the first files and lines: [{path, count, lines: [{line, text}]}]."""
    q = query.strip()
    if len(q) < MIN_QUERY or len(q) > 200:
        raise IDEError(f"Type {MIN_QUERY} to 200 characters to search for.", 400)
    needle = q.casefold()
    results: list[dict] = []
    matches = files = 0
    for f in file_tree(wt):
        if f["size"] > MAX_FILE_BYTES:
            continue
        try:
            lines = (Path(wt) / f["path"]).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue  # a binary file (a database, an image) has nothing to find
        hits = [(i, l) for i, l in enumerate(lines, 1) if needle in l.casefold()]
        if not hits:
            continue
        matches += len(hits)
        files += 1
        if len(results) < MAX_SEARCH_FILES:
            results.append({"path": f["path"], "count": len(hits), "lines": [{"line": i, "text": l.strip()[:200]} for i, l in hits[:MAX_SEARCH_LINES]]})
    return {"query": q, "matches": matches, "files": files, "truncated": files > len(results), "results": results}
