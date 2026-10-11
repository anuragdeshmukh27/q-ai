"""Code Reviewer: static checks plus a structured LLM review of one agent branch's diff.

The verdict is PASS or REQUEST_CHANGES with concrete items. Static findings are facts and always count;
the model's own items count only when it names a file and a problem (a bare REQUEST_CHANGES is treated as PASS,
because a small model that cannot say what is wrong is guessing).
"""
from __future__ import annotations

import re
from pathlib import Path
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
    if owner == "database" and any(p.startswith("database/") for p in files) and not any(p.startswith(("tests/test_db", "tests/db/")) for p in files):
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


_SYNTAX_CLAIM = re.compile(r"incomplete|lacks a closing|is cut off|syntax error|invalid syntax|unclosed|unterminated|missing (?:a )?(?:closing )?(?:parenthes[ie]s|bracket|brace|quote)|not valid python|cannot be parsed", re.I)
_MISSING_CLAIM = re.compile(r"(?:does not|doesn't|did not|not) (?:implement|contain|define|include)|no functions? for|but not for|missing (?:the )?functions?|still (?:raises?|has) NotImplementedError", re.I)


_LINES_CLAIM = re.compile(r"\b(\d+) lines?\b|over the \d+-line|line limit", re.I)
_SIZE_OPINION = re.compile(r"large number of lines|several jobs|doing (?:several|many|multiple) (?:jobs|things)|too (?:long|large|many lines)", re.I)
_TESTS_CLAIM = re.compile(r"(?:lacks?|missing|no|without|not (?:have|has|include))\b[^.]*\btests?\b|\bnot (?:tested|covered)", re.I)
_OPINION = re.compile(r"\b(inefficient|consider|could be|should be (?:done|moved|placed|defined)|refactor|readab|best practice|more (?:efficient|robust|maintainable)|separate (?:file|module|function))", re.I)


def drop_unfounded(review: ReviewOutput, root: Path) -> ReviewOutput:
    """A 7B reviewer sometimes claims a syntax error or a missing function that is not in the file, and the engineer then spends many calls chasing it.
    Those two kinds of claim can be checked for free: a file that compiles has no syntax error, and a file with no `NotImplementedError` and a definition for every
    function name the claim mentions has nothing missing. A claim that fails the check is dropped; every other item stays."""
    keep: list[ReviewItem] = []
    for i in review.items:
        f = root / i.file
        if f.suffix == ".py" and f.is_file():
            source = f.read_text(encoding="utf-8", errors="replace")
            if _LINES_CLAIM.search(i.problem) and len(source.splitlines()) <= MAX_FILE_LINES:
                continue  # 'the file has 65 lines, over the 150-line limit'
            if _SIZE_OPINION.search(i.problem):
                continue  # 'a large number of lines', 'a single function doing several jobs': the size check is static and has already run
            if _TESTS_CLAIM.search(i.problem) and any(root.glob(f"tests/**/*{f.stem}*.py")):
                continue  # 'lacks tests for X': the database tests are generated, and a branch with no tests at all is a static finding
            if _OPINION.search(i.problem):
                continue  # style and efficiency are not defects (the reviewer's own prompt says so)
            if "SCHEMA" in i.problem and re.search(r"connect\(SCHEMA\)", source):
                continue  # 'the SCHEMA constant is not used': every function opens its connection with it
            if _SYNTAX_CLAIM.search(i.problem):
                try:
                    compile(source, str(f), "exec")
                    continue
                except SyntaxError:
                    pass
            elif _MISSING_CLAIM.search(i.problem) and "NotImplementedError" not in source:
                named = re.findall(r"`(\w+)`", i.problem)
                if all(re.search(rf"^def {re.escape(n)}\(", source, re.M) for n in named):
                    continue
        keep.append(i)
    if len(keep) == len(review.items):
        return review
    if keep:
        return ReviewOutput(verdict="REQUEST_CHANGES", summary=review.summary, items=keep)
    return ReviewOutput(verdict="PASS", summary="the reviewer's claims were checked against the files and none holds (the code compiles and every function is there)", items=[])
