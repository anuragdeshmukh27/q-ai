"""Code Reviewer: static checks plus a structured LLM review of one agent branch's diff.

The verdict is PASS or REQUEST_CHANGES with concrete items. Static findings are facts and always count;
the model's own items count only when it names a file and a problem (a bare REQUEST_CHANGES is treated as PASS,
because a small model that cannot say what is wrong is guessing).
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from ..config import PROMPTS_DIR, AgentConfig
from ..llm import LLMClient
from .planning import AgentFailed, structured_step

MAX_FILE_LINES = 150
MAX_DIFF_CHARS = 9000
_UNSAFE = re.compile(r"(?<![\w.])(eval|exec)\s*\(")
_SQL_BUILT = re.compile(r"""\.execute\w*\(\s*(f["']|["'][^"']*["']\s*(%|\+|\.format\())""")
_SKIP_PREFIXES = ("tests/", ".q/")


class ReviewItem(BaseModel):
    file: str
    problem: str = Field(description="What is wrong and what to change, one sentence")


class ReviewOutput(BaseModel):
    verdict: Literal["PASS", "REQUEST_CHANGES"]
    summary: str = Field(description="One sentence")
    items: list[ReviewItem] = Field(default_factory=list, description="Empty when the verdict is PASS")


def static_findings(files: dict[str, str]) -> list[ReviewItem]:
    """Deterministic checks on the files a branch added or changed (path -> content)."""
    out: list[ReviewItem] = []
    for path, text in sorted(files.items()):
        if path.startswith(_SKIP_PREFIXES):
            continue
        n = len(text.splitlines())
        if n > MAX_FILE_LINES:
            out.append(ReviewItem(file=path, problem=f"the file has {n} lines; keep files under {MAX_FILE_LINES} by moving code into smaller functions"))
        if path.endswith(".py"):
            if _UNSAFE.search(text):
                out.append(ReviewItem(file=path, problem="eval()/exec() runs input as code (injection); use if/elif or a dict of functions"))
            if _SQL_BUILT.search(text):
                out.append(ReviewItem(file=path, problem="SQL is built from strings; use `?` placeholders and pass the values as a tuple (SQL injection)"))
        if path.endswith((".js", ".html")) and re.search(r"\.innerHTML\s*[+]?=", text):
            out.append(ReviewItem(file=path, problem="innerHTML with data is an XSS risk; use textContent"))
    return out


def missing_tests(files: dict[str, str], owner: str) -> list[ReviewItem]:
    """A database branch must come with its own tests (the generated contract tests cover the API and page, not the data layer)."""
    if owner == "database" and any(p.startswith("database/") for p in files) and not any(p.startswith("tests/test_db") for p in files):
        return [ReviewItem(file="tests/test_db.py", problem="the database functions have no tests; add tests/test_db_<name>.py covering every function")]
    return []


def run_review(
    agent: AgentConfig,
    llm: LLMClient,
    model_id: str,
    task: dict,
    diff: str,
    findings: list[ReviewItem],
    emit,
) -> tuple[ReviewOutput, dict]:
    """Returns the final review (static findings merged in) and usage stats."""
    system = (PROMPTS_DIR / agent.system_prompt_file).read_text(encoding="utf-8").replace("{name}", agent.name).replace("{role}", agent.role)
    crit = "\n".join(f"- {c}" for c in task["acceptance"])
    facts = "\n".join(f"- {f.file}: {f.problem}" for f in findings) or "(none)"
    clipped = diff if len(diff) <= MAX_DIFF_CHARS else diff[:MAX_DIFF_CHARS] + "\n[diff truncated]"
    user = (f"Task {task['id']} by the {task['owner']} engineer: {task['title']}\nAcceptance criteria:\n{crit}\n\n"
            f"Automatic checks already found (these are facts, include them if present):\n{facts}\n\nDiff to review:\n{clipped}")
    try:
        review, stats = structured_step(agent, llm, model_id, system, user, ReviewOutput, _check, emit, max_attempts=2)
    except AgentFailed:
        # The reviewer being unavailable must not block the build; the automatic findings still decide.
        review = ReviewOutput(verdict="PASS", summary="model review unavailable; automatic checks only")
        stats = {"iterations": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0}
    items = [i for i in review.items if i.file.strip() and i.problem.strip()]
    seen = {(i.file, i.problem) for i in findings}
    merged = list(findings) + [i for i in items if (i.file, i.problem) not in seen]
    verdict = "REQUEST_CHANGES" if merged else "PASS"
    summary = review.summary if verdict == review.verdict else ("automatic checks found problems" if merged else review.summary)
    return ReviewOutput(verdict=verdict, summary=summary, items=merged), stats


def _check(r: ReviewOutput) -> list[str]:
    if r.verdict == "REQUEST_CHANGES" and not r.items:
        return ["REQUEST_CHANGES needs at least one item naming the file and the problem; otherwise reply PASS"]
    if r.verdict == "PASS" and r.items:
        return ["PASS must have no items; list items only with REQUEST_CHANGES"]
    return []


def review_markdown(task: dict, review: ReviewOutput, round_no: int) -> str:
    lines = [f"# Review of {task['id']}: {task['title']} (round {round_no})", "", f"**Verdict:** {review.verdict}", "", review.summary, ""]
    lines += [f"- `{i.file}`: {i.problem}" for i in review.items]
    return "\n".join(lines).rstrip() + "\n"
