"""Integrator: merges agent branches into main, resolves conflicts with the model, runs the full test suite.

Conflicts are rare by design (every agent owns different paths). When one happens the model proposes a resolution
for each conflicted file; in Supervised/Assisted mode a human approves it. Anything unresolvable aborts the merge
and escalates, leaving main untouched.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from .agent.planning import AgentFailed, structured_step
from .approvals import request_approval
from .config import PROMPTS_DIR, AgentConfig
from .repo import GitError, MergeOutcome, Repo
from .llm import LLMClient

_MARKERS = re.compile(r"^(<<<<<<<|=======|>>>>>>>)", re.MULTILINE)
MAX_CONFLICT_CHARS = 9000


class Resolution(BaseModel):
    content: str
    summary: str = ""


@dataclass
class MergeResult:
    ok: bool
    branch: str
    conflicts: list[str]
    resolved: list[str]
    reason: str = ""


def run_suite(root: Path, timeout: float = 120) -> tuple[bool, str, str]:
    """Run the project's pytest on a checkout. Returns (passed, last summary line, full output)."""
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rfE", "--tb=short", "-p", "no:cacheprovider"], cwd=root,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired:
        return False, f"test run timed out after {timeout:.0f}s", ""
    lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
    summary = next((l for l in reversed(lines) if re.search(r"passed|failed|error|no tests", l)), lines[-1] if lines else r.stderr[-200:])
    return r.returncode == 0, summary.strip(" ="), r.stdout


class Integrator:
    def __init__(self, agent: AgentConfig, repo: Repo, llm: LLMClient, model_id: str, emit: Callable[..., object],
                 mode: str = "supervised", approver=None):
        self.agent, self.repo, self.llm, self.model_id, self.emit = agent, repo, llm, model_id, emit
        self._mode, self.approver = mode, approver

    @property
    def mode(self) -> str:
        return self._mode() if callable(self._mode) else self._mode

    def merge(self, agent_id: str, title: str) -> MergeResult:
        branch = self.repo.branch(agent_id)
        self.emit("agent_state", agent=self.agent.id, state="executing")
        with self.repo.lock:
            outcome = self.repo.merge_into_main(agent_id, f"[integrator] merge {branch}: {title}"[:100])
            resolved: list[str] = []
            reason = ""
            if not outcome.ok:
                if outcome.conflicts:
                    resolved, reason = self._resolve(outcome, branch)
                else:
                    reason = outcome.detail
            result = MergeResult(not reason, branch, outcome.conflicts, resolved, reason)
        if result.ok:
            passed, summary, _ = run_suite(self.repo.root)
            self.emit("merge_result", agent=self.agent.id, branch=branch, ok=True, conflicts=outcome.conflicts, resolved=resolved, tests_passed=passed, summary=summary)
        else:
            self.emit("merge_result", agent=self.agent.id, branch=branch, ok=False, conflicts=outcome.conflicts, resolved=resolved, tests_passed=False, summary=reason)
            self.emit("escalation", agent=self.agent.id, task=f"merge {branch}", reason="merge_conflict", detail=reason, iterations=0, recent=[])
            self.emit("agent_state", agent=self.agent.id, state="waiting_human")
            return result
        self.emit("agent_state", agent=self.agent.id, state="idle")
        return result

    # -- conflicts ------------------------------------------------------------------
    def _resolve(self, outcome: MergeOutcome, branch: str) -> tuple[list[str], str]:
        """Returns (resolved files, failure reason). On failure the merge is aborted."""
        proposals: dict[str, str] = {}
        for rel in outcome.conflicts:
            path = self.repo.root / rel
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > MAX_CONFLICT_CHARS:
                return self._abort(f"{rel} is too large to resolve automatically")
            try:
                res = self._propose(rel, text)
            except AgentFailed as e:
                return self._abort(f"no valid resolution for {rel}: {e.reason}")
            problem = _check_resolution(rel, res.content)
            if problem:
                return self._abort(f"the proposed resolution for {rel} is invalid: {problem}")
            proposals[rel] = res.content
            self.emit("agent_thought", agent=self.agent.id, text=f"{rel}: {res.summary or 'resolved'}", model=self.model_id, tokens=0, seconds=0)
        if self.mode != "autonomous":
            summary = f"resolve merge conflict in {', '.join(proposals)} ({branch})"
            details = {"files": list(proposals), "proposal": {k: v[:600] for k, v in proposals.items()}}
            if not request_approval(self.emit, self.approver, self.agent.id, "merge_conflict", summary, details):
                return self._abort("the conflict resolution was not approved")
        for rel, content in proposals.items():
            (self.repo.root / rel).write_text(content, encoding="utf-8", newline="\n")
        try:
            self.repo.finish_merge()
        except GitError as e:
            return self._abort(str(e))
        return list(proposals), ""

    def _abort(self, reason: str) -> tuple[list[str], str]:
        self.repo.abort_merge()
        return [], reason

    def _propose(self, rel: str, text: str) -> Resolution:
        system = (PROMPTS_DIR / self.agent.system_prompt_file).read_text(encoding="utf-8").replace("{name}", self.agent.name).replace("{role}", self.agent.role)
        user = f"File: {rel}\n\n```\n{text}\n```"
        res, _ = structured_step(self.agent, self.llm, self.model_id, system, user, Resolution, lambda r: [m for m in [_check_resolution(rel, r.content)] if m], self.emit, max_attempts=2)
        return res


def _check_resolution(rel: str, content: str) -> str:
    if not content.strip():
        return "empty file"
    if _MARKERS.search(content):
        return "conflict markers are still present"
    if rel.endswith(".py"):
        try:
            compile(content, rel, "exec")
        except SyntaxError as e:
            return f"not valid Python ({e.msg} on line {e.lineno})"
    return ""
