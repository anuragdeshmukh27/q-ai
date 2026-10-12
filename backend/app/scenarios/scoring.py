"""Scoring: deterministic rules over the session log. No model is involved in a score.

A rubric criterion is four rules worth one point each. A rule looks at the session log (and, for a few, at facts Q measured after the submit: the files that still say
the old name, the re-run of the suite, the learner's regression test run on the seed) and answers with an `Outcome`: passed or not, the ids of the log entries that
prove it (the first one is the moment the point quotes), and one factual sentence. Passed is a STRENGTH, not passed is a GAP. The score of a criterion is the number
of rules that passed; the total is the sum times the rubric's weight (5 per point: 5 criteria x 4 points x 5 = 100).
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .rubric import Rubric

SCOPED_TESTS = "tests/"


def clock(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def event_text(e: dict) -> str:
    """The words of a log entry: what a quote of it must match. The same text is shown as the entry's detail."""
    k = e.get("kind")
    if k == "session_started":
        return f"Session started: {e.get('scenario', '')}"
    if k == "file_opened":
        return str(e.get("path", ""))
    if k == "file_saved":
        return f"Saved {e.get('path', '')} (+{e.get('added', 0)} -{e.get('removed', 0)} lines)"
    if k == "test_run":
        return f"Run tests ({e.get('trigger', 'ide')})"
    if k == "test_result":
        return str(e.get("summary", ""))
    if k in ("message_posted", "team_message"):
        return str(e.get("text", ""))
    if k == "hint_given":
        return f"Hint {e.get('n', '')} from {e.get('from', '')}"
    if k == "submit":
        return "Submit for review"
    if k == "submit_result":
        return str(e.get("summary", "")) or ("Accepted" if e.get("ok") else "Not accepted")
    if k == "session_finished":
        return "Session finished: " + ("fixed" if e.get("ok") else "not fixed")
    return ""


SOURCES = {"message_posted": "#incident-opd", "team_message": "#incident-opd", "hint_given": "#incident-opd (hint)", "file_opened": "IDE · file opened",
           "file_saved": "IDE · file saved", "test_run": "IDE · tests", "test_result": "IDE · tests", "submit": "Submit", "submit_result": "Submit",
           "session_started": "Session", "session_finished": "Session"}


@dataclass
class Outcome:
    ok: bool
    events: list[str]  # the entries that prove it; the first is the moment the point quotes
    text: str  # one factual sentence


@dataclass
class Finding:
    id: str
    criterion: str
    rule: str
    kind: str  # "strength" | "gap"
    events: list[str]
    text: str
    advice: str


@dataclass
class CriterionResult:
    id: str
    score: int
    findings: list[Finding] = field(default_factory=list)


class Facts:
    """What the rules look at: the session log and what was measured after the submit."""

    def __init__(self, events: list[dict], minutes: int = 25, old_name_files: list[str] | None = None, rerun: dict | None = None, regression: dict | None = None):
        self.log = [dict(e) for e in events]
        self.minutes = minutes
        self.old_name_files = list(old_name_files or [])
        self.rerun = rerun  # {ok, passed, failed, summary} of the suite on the merged project, or None when it could not be run
        self.regression = regression  # {path, fails_on_seed, passes_on_main} of the learner's new test, or None when there is none
        self._index = {e["id"]: i for i, e in enumerate(self.log)}

    def of(self, kind: str, pred: Callable[[dict], bool] | None = None) -> list[dict]:
        return [e for e in self.log if e["kind"] == kind and (pred is None or pred(e))]

    def first(self, kind: str, pred: Callable[[dict], bool] | None = None) -> dict | None:
        return next(iter(self.of(kind, pred)), None)

    def before(self, a: dict, b: dict | None) -> bool:
        """`a` happened before `b` (ids are in order); with no `b` everything counts."""
        return b is None or self._index[a["id"]] < self._index[b["id"]]

    def team(self, ref: str) -> dict | None:
        return self.first("team_message", lambda e: e.get("ref") == ref)

    @property
    def production_edits(self) -> list[dict]:
        return self.of("file_saved", lambda e: not str(e.get("path", "")).startswith(SCOPED_TESTS))

    @property
    def first_edit(self) -> dict | None:
        return next(iter(self.production_edits), None)

    @property
    def accepted(self) -> dict | None:
        return self.first("submit_result", lambda e: bool(e.get("ok")))

    @property
    def anchor(self) -> dict:
        """The entry a point cites when nothing the learner did can be quoted: the accepted submit, else the end of the log."""
        return self.accepted or self.log[-1]


RULES: dict[str, Callable[[Facts, dict], Outcome]] = {}


def rule(fn: Callable[[Facts, dict], Outcome]) -> Callable[[Facts, dict], Outcome]:
    RULES[fn.__name__] = fn
    return fn


def _ids(*events: dict | None) -> list[str]:
    seen: list[str] = []
    for e in events:
        if e is not None and e["id"] not in seen:
            seen.append(e["id"])
    return seen


# -- Communication ----------------------------------------------------------------------------------------

@rule
def first_update(f: Facts, p: dict) -> Outcome:
    within = float(p.get("within", 120))
    post = f.first("message_posted")
    if post is None:
        return Outcome(False, _ids(f.team("lead-update"), f.anchor), "You never posted an update in the channel.")
    if post["t"] <= within:
        return Outcome(True, _ids(post), f"First update at {clock(post['t'])}, inside the first {clock(within)}.")
    return Outcome(False, _ids(post), f"Your first update came at {clock(post['t'])}, after the {clock(within)} mark.")


@rule
def answered_requests(f: Facts, p: dict) -> Outcome:
    within = float(p.get("within", 60))
    ask = f.team("lead-update")
    if ask is None:
        post = f.first("message_posted")
        return Outcome(True, _ids(post, f.anchor), "You updated the channel before the lead had to ask.")
    reply = f.first("message_posted", lambda e: f.before(ask, e))
    if reply is not None and reply["t"] - ask["t"] <= within:
        return Outcome(True, _ids(reply, ask), f"You answered the lead's request after {int(reply['t'] - ask['t'])} s.")
    if reply is None:
        return Outcome(False, _ids(ask), f"The lead asked for an update at {clock(ask['t'])} and you never answered.")
    return Outcome(False, _ids(ask, reply), f"The lead asked at {clock(ask['t'])}; your answer came {int(reply['t'] - ask['t'])} s later.")


@rule
def no_nudges(f: Facts, p: dict) -> Outcome:
    nudges = f.of("team_message", lambda e: e.get("ref") == "lead-nudge")
    if not nudges:
        return Outcome(True, _ids(f.first("message_posted"), f.anchor), "No quiet stretch of five minutes: the lead never had to nudge you.")
    return Outcome(False, _ids(nudges[0]), f"The lead had to nudge you {len(nudges)} time{'s' if len(nudges) != 1 else ''} after quiet stretches (first at {clock(nudges[0]['t'])}).")


@rule
def names_the_cause(f: Facts, p: dict) -> Outcome:
    pattern = re.compile(str(p.get("pattern", "slot_at|slot_time")), re.I)
    posts = f.of("message_posted")
    hit = next((e for e in posts if pattern.search(str(e.get("text", "")))), None)
    if hit is not None:
        return Outcome(True, _ids(hit), f"At {clock(hit['t'])} you told the team what you had found.")
    return Outcome(False, _ids(posts[-1] if posts else None, f.anchor), "None of your posts says what was broken." if posts else "You never said what was broken.")


# -- Diagnosis --------------------------------------------------------------------------------------------

@rule
def reproduced_first(f: Facts, p: dict) -> Outcome:
    edit = f.first_edit
    run = f.first("test_run", lambda e: f.before(e, edit))
    if run is not None:
        return Outcome(True, _ids(run), f"You ran the tests at {clock(run['t'])}, before the first edit.")
    if edit is None:
        return Outcome(False, _ids(f.anchor), "You never ran the tests before submitting.")
    return Outcome(False, _ids(edit), f"You edited code at {clock(edit['t'])} before you had run the tests.")


def _read_before_edit(f: Facts, pattern: str, what: str) -> Outcome:
    edit = f.first_edit
    opened = f.first("file_opened", lambda e: not e.get("auto") and fnmatch.fnmatch(str(e.get("path", "")), pattern) and f.before(e, edit))
    if opened is not None:
        return Outcome(True, _ids(opened), f"You opened {what} at {clock(opened['t'])}, before the first edit.")
    late = f.first("file_opened", lambda e: not e.get("auto") and fnmatch.fnmatch(str(e.get("path", "")), pattern))
    if late is not None:
        return Outcome(False, _ids(late, edit), f"You opened {what} at {clock(late['t'])}, after you had started editing.")
    return Outcome(False, _ids(edit, f.anchor), f"You never opened {what}.")


@rule
def read_the_route(f: Facts, p: dict) -> Outcome:
    return _read_before_edit(f, str(p.get("pattern", "backend/api/*")), "the failing route")


@rule
def read_the_migration(f: Facts, p: dict) -> Outcome:
    return _read_before_edit(f, str(p.get("pattern", "database/migrations/*")), "the migration")


@rule
def no_pointer_needed(f: Facts, p: dict) -> Outcome:
    pointer = f.first("hint_given", lambda e: e.get("reason") == "timeline")
    if pointer is None:
        return Outcome(True, _ids(f.first("file_opened", lambda e: not e.get("auto") and "migrations" in str(e.get("path", ""))), f.first("test_run"), f.anchor),
                       "No scripted pointer was needed: you found where to look yourself.")
    return Outcome(False, _ids(pointer), f"A teammate had to point you at the database change at {clock(pointer['t'])}.")


# -- Fix quality ------------------------------------------------------------------------------------------

@rule
def old_name_gone(f: Facts, p: dict) -> Outcome:
    name, folder = str(p.get("old_name", "slot_time")), str(p.get("folder", "backend"))
    last = f.production_edits[-1] if f.production_edits else None
    if not f.old_name_files:
        return Outcome(True, _ids(last, f.anchor), f"No file under {folder}/ says {name} any more.")
    return Outcome(False, _ids(last, f.anchor), f"{name} is still used in {', '.join(f.old_name_files[:4])}.")


@rule
def suite_green_on_main(f: Facts, p: dict) -> Outcome:
    r = f.rerun
    if r is None:
        return Outcome(False, _ids(f.anchor), "The suite could not be re-run on the merged project.")
    total = r.get("passed", 0) + r.get("failed", 0)
    if r.get("ok"):
        return Outcome(True, _ids(f.anchor), f"I re-ran the whole suite on the merged project: {r.get('passed', 0)} of {total} pass.")
    return Outcome(False, _ids(f.anchor), f"I re-ran the whole suite on the merged project: {r.get('failed', 0)} of {total} fail.")


@rule
def small_change(f: Facts, p: dict) -> Outcome:
    limit = int(p.get("max_lines", 20))
    edits = f.production_edits
    if not edits:
        return Outcome(False, _ids(f.anchor), f"You changed nothing under backend/.")
    lines = sum(int(e.get("added", 0)) + int(e.get("removed", 0)) for e in edits)
    biggest = max(edits, key=lambda e: int(e.get("added", 0)) + int(e.get("removed", 0)))
    if lines <= limit:
        return Outcome(True, _ids(biggest), f"{lines} lines changed in {len({e['path'] for e in edits})} file(s): small and targeted.")
    return Outcome(False, _ids(biggest), f"{lines} lines changed, more than the {limit} the problem needs.")


@rule
def review_clean(f: Facts, p: dict) -> Outcome:
    sent = f.of("submit_result", lambda e: not e.get("ok") and e.get("stage") == "review")
    if not sent:
        return Outcome(True, _ids(f.anchor), "The Reviewer read your change and sent nothing back.")
    return Outcome(False, _ids(sent[0]), f"The Reviewer sent your change back {len(sent)} time{'s' if len(sent) != 1 else ''}.")


# -- Testing ----------------------------------------------------------------------------------------------

@rule
def green_before_submit(f: Facts, p: dict) -> Outcome:
    submit = f.first("submit")
    green = f.first("test_result", lambda e: bool(e.get("ok")) and e.get("trigger") == "ide" and f.before(e, submit))
    if green is not None:
        return Outcome(True, _ids(green), f"Your own run at {clock(green['t'])} was green before you submitted.")
    return Outcome(False, _ids(submit, f.anchor), "You submitted without a green run of your own first.")


@rule
def no_red_submit(f: Facts, p: dict) -> Outcome:
    red = f.of("submit_result", lambda e: not e.get("ok") and e.get("stage") == "tests")
    if not red:
        return Outcome(True, _ids(f.anchor), "No submit was refused for failing tests.")
    return Outcome(False, _ids(red[0]), f"A submit at {clock(red[0]['t'])} was refused because tests still failed.")


@rule
def regression_test_added(f: Facts, p: dict) -> Outcome:
    pattern = str(p.get("pattern", "tests/regression/test_*.py"))
    saved = f.first("file_saved", lambda e: fnmatch.fnmatch(str(e.get("path", "")), pattern))
    if saved is not None:
        return Outcome(True, _ids(saved), f"You added a regression test at {clock(saved['t'])}.")
    return Outcome(False, _ids(f.first("submit"), f.anchor), "No new test covers the bug you fixed.")


@rule
def regression_test_proves_fix(f: Facts, p: dict) -> Outcome:
    r = f.regression
    saved = f.first("file_saved", lambda e: fnmatch.fnmatch(str(e.get("path", "")), "tests/regression/test_*.py"))
    if r is None or saved is None:
        return Outcome(False, _ids(f.first("submit"), f.anchor), "Without a new test, nothing shows the bug cannot come back unnoticed.")
    if r.get("fails_on_seed") and r.get("passes_on_main"):
        return Outcome(True, _ids(saved), "I ran your new test on the broken code and on your fix: it fails before and passes after.")
    if not r.get("fails_on_seed"):
        return Outcome(False, _ids(saved), "Your new test also passes on the broken code, so it would not have caught the bug.")
    return Outcome(False, _ids(saved), "Your new test fails on your own fix.")


# -- Ownership --------------------------------------------------------------------------------------------

@rule
def within_time_box(f: Facts, p: dict) -> Outcome:
    done = f.accepted
    if done is None:
        return Outcome(False, _ids(f.anchor), "The fix was not accepted.")
    limit = f.minutes * 60
    if done["t"] <= limit:
        return Outcome(True, _ids(done), f"Accepted at {clock(done['t'])}, inside the {f.minutes}-minute time box.")
    return Outcome(False, _ids(done), f"Accepted at {clock(done['t'])}, after the {f.minutes}-minute time box.")


@rule
def few_hints(f: Facts, p: dict) -> Outcome:
    limit = int(p.get("max_hints", 1))
    hints = f.of("hint_given")
    if len(hints) <= limit:
        return Outcome(True, _ids(hints[-1] if hints else None, f.anchor), f"{len(hints)} hint{'s' if len(hints) != 1 else ''} used (up to {limit} is fine).")
    return Outcome(False, _ids(hints[limit]), f"{len(hints)} hints used: every answer from a teammate counts.")


@rule
def no_scope_rejection(f: Facts, p: dict) -> Outcome:
    out = f.of("submit_result", lambda e: not e.get("ok") and e.get("stage") == "scope")
    if not out:
        return Outcome(True, _ids(f.anchor), "You stayed inside the files your role may edit.")
    return Outcome(False, _ids(out[0]), "A submit was refused because it changed files outside your role.")


@rule
def reported_the_outcome(f: Facts, p: dict) -> Outcome:
    green = f.first("test_result", lambda e: bool(e.get("ok")) and e.get("trigger") == "ide")
    post = f.first("message_posted", lambda e: green is not None and f.before(green, e))
    if post is not None:
        return Outcome(True, _ids(post), f"At {clock(post['t'])} you told the team the fix was ready.")
    return Outcome(False, _ids(green, f.anchor), "You never told the channel that the fix was ready.")


def score(rubric: Rubric, facts: Facts) -> list[CriterionResult]:
    """Every criterion's rules, in the rubric's order. Finding ids are F01, F02, ... in the same order."""
    out: list[CriterionResult] = []
    n = 0
    for c in rubric.criteria:
        res = CriterionResult(c.id, 0)
        for r in c.rules:
            o = RULES[r.id](facts, r.params)
            if not o.events:
                o.events = [facts.anchor["id"]]
            n += 1
            res.findings.append(Finding(f"F{n:02d}", c.id, r.id, "strength" if o.ok else "gap", o.events, o.text, "" if o.ok else r.advice))
            res.score += 1 if o.ok else 0
        out.append(res)
    return out
