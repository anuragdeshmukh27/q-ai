"""QA: parse test failures, route each bug to the owning engineer, write bug reports.

Generated tests (`tests/api`, `tests/ui`, `tests/qa`) are authoritative: a failure there is always an app bug.
Tests the QA agent wrote itself can be wrong, so the triage call decides between `app_bug` and `test_bug`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from ..config import PROMPTS_DIR, AgentConfig
from ..llm import LLMClient
from .planning import AgentFailed, structured_step

OWNERS = ("backend", "frontend", "database")
OWNER_BY_PREFIX = (("backend/", "backend"), ("static/", "frontend"), ("frontend/", "frontend"), ("database/", "database"))
AUTHORITATIVE = ("tests/api/", "tests/ui/", "tests/qa/", "tests/db/")
MAX_TRACE_CHARS = 1800
_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+?)(?: - (.*))?$", re.MULTILINE)
_SECTION = re.compile(r"^_{3,} (.+?) _{3,}$", re.MULTILINE)
_FRAME = re.compile(r"^((?:backend|database|static|frontend)/[\w/.\-]+\.\w+):(\d+)", re.MULTILINE)


@dataclass
class Failure:
    test_id: str  # tests/test_contract_api.py::test_post_calculate_1_adds
    file: str
    name: str
    message: str
    trace: str

    @property
    def authoritative(self) -> bool:
        return self.file.startswith(AUTHORITATIVE)


def parse_failures(output: str) -> list[Failure]:
    """Failed or errored tests from `pytest -q -rfE --tb=short` output."""
    sections: dict[str, str] = {}
    marks = list(_SECTION.finditer(output))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(output)
        body = output[m.end():end]
        cut = body.find("\n=====")  # the short test summary follows the last section
        sections[m.group(1).strip().split(" ")[-1]] = (body[:cut] if cut >= 0 else body).strip()
    out: list[Failure] = []
    for m in _FAILED.finditer(output):
        test_id, message = m.group(1), (m.group(2) or "").strip()
        file, _, name = test_id.partition("::")
        trace = sections.get(name.split("[")[0], "") or sections.get(file, "")
        out.append(Failure(test_id, file.replace("\\", "/"), name or file, message, trace[-MAX_TRACE_CHARS:]))
    seen: set[str] = set()
    return [f for f in out if not (f.test_id in seen or seen.add(f.test_id))]


def guess_owner(f: Failure) -> str:
    """Deepest app frame in the traceback names the owner; with no app frame, fall back on which test failed."""
    frames = _FRAME.findall(f.trace)
    for path, _ in reversed(frames):
        for prefix, owner in OWNER_BY_PREFIX:
            if path.startswith(prefix):
                return owner
    if f.file.startswith("tests/ui/"):
        return "frontend"
    if "test_db" in f.file or f.file.startswith("tests/db/"):
        return "database"
    return "backend"


class BugTriage(BaseModel):
    verdict: Literal["app_bug", "test_bug"] = Field(description="app_bug: the app breaks the API contract. test_bug: the test itself is wrong")
    owner: Literal["backend", "frontend", "database"] = Field(description="Who must fix it: backend (API logic), frontend (page script), database (data functions)")
    title: str = Field(description="Short bug title")
    expected: str = Field(description="What the contract says should happen")
    actual: str = Field(description="What happens instead, from the failure output")
    suggestion: str = Field(description="Where to look and what to change, one or two sentences")


def run_triage(agent: AgentConfig, llm: LLMClient, model_id: str, f: Failure, contract_text: str, guess: str, emit, hint: bool = True) -> tuple[BugTriage, dict]:
    system = (PROMPTS_DIR / "qa_triage.md").read_text(encoding="utf-8").replace("{name}", agent.name).replace("{role}", agent.role)
    kind = "a generated contract test (it is always right; the app is wrong)" if f.authoritative else "a test written by QA (it may itself be wrong)"
    user = (f"{contract_text}\n\nFailing test: {f.test_id}  [{kind}]\nFailure: {f.message}\n\nOutput:\n{f.trace or '(no traceback)'}"
            + (f"\n\nHint from the traceback: the code that failed belongs to the `{guess}` engineer." if hint else ""))  # the benchmark asks without the hint

    def check(t: BugTriage) -> list[str]:
        return [] if t.title.strip() and t.suggestion.strip() else ["title and suggestion must not be empty"]

    return structured_step(agent, llm, model_id, system, user, BugTriage, check, emit, max_attempts=2)


def triage_or_fallback(agent: AgentConfig, llm: LLMClient, model_id: str, f: Failure, contract_text: str, emit) -> tuple[BugTriage, dict]:
    """Triage with the model; if it is unavailable or invalid, file the bug from the failure itself (owner from the traceback)."""
    guess = guess_owner(f)
    try:
        t, stats = run_triage(agent, llm, model_id, f, contract_text, guess, emit)
    except AgentFailed:
        t = BugTriage(verdict="app_bug" if f.authoritative else "test_bug", owner=guess, title=f"{f.name} fails",
                      expected="the behaviour in the API contract", actual=f.message or "the test fails", suggestion="read the failing test and the code it exercises")
        return t, {"iterations": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0}
    if f.authoritative:
        t.verdict = "app_bug"  # generated tests are the contract made executable
    if t.verdict == "app_bug" and f.trace and _FRAME.search(f.trace):
        t.owner = guess  # a traceback is evidence, the model's opinion is not
    return t, stats


def bug_markdown(bug_id: int, f: Failure, t: BugTriage, status: str = "open") -> str:
    return (f"# Bug {bug_id:03d}: {t.title}\n\n- **Status:** {status}\n- **Owner:** {t.owner}\n- **Test:** `{f.test_id}`\n\n"
            f"## Expected\n{t.expected}\n\n## Actual\n{t.actual}\n\n## Suggestion\n{t.suggestion}\n\n## Failure output\n```\n{f.trace or f.message}\n```\n")
