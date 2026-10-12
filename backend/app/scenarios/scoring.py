"""Scoring: deterministic rules over the session log. No model is involved in a score.

A rubric criterion is four rules worth one point each. A rule looks at the session log (and, for a few, at facts Q measured after the submit: the files that still say
the old name, the re-run of the suite, the learner's regression test run on the seed) and answers with an `Outcome`: passed or not, the log entries that prove it (the
candidates, best first) and one factual sentence. Passed is a STRENGTH, not passed is a GAP. The score of a criterion is the number of rules that passed; the total is
the sum times the rubric's weight (5 per point: 5 criteria x 4 points x 5 = 100).

Which entry a point quotes: the first candidate that no earlier point already quotes, so a report does not repeat one quote four times when another entry proves the
point as well. All the candidates stay in the point's `events`.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Callable

from ..config import load_agents

if TYPE_CHECKING:
    from .rubric import Rubric

SCOPED_TESTS = "tests/"


@lru_cache(maxsize=1)
def _roster() -> dict[str, str]:
    try:
        return {a.id: a.name for a in load_agents().values()}
    except Exception:  # the roster file is missing: ids stay as they are
        return {}


def display_name(employee_id: str) -> str:
    """The name a learner knows an employee by (database -> Karan); anything else is returned as it is."""
    return _roster().get(employee_id, employee_id)


def clock(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def event_text(e: dict) -> str:
    """The words of a log entry: what a quote of it must match. The same text is shown as the entry's detail. Only names a learner knows (Karan, never `database`)."""
    k = e.get("kind")
    if k == "session_started":
        return f"Session started: {e.get('scenario', '')}"
    if k == "file_opened":
        return str(e.get("path", ""))
    if k == "file_saved":
        added = int(e.get("added", 0))
        if e.get("created"):
            return f"Created {e.get('path', '')} (+{added} lines)" if added else f"Created {e.get('path', '')} (empty file)"
        return f"Saved {e.get('path', '')} (+{added} -{e.get('removed', 0)} lines)"
    if k == "search":
        n, files = int(e.get("matches", 0)), int(e.get("files", 0))
        return f"Searched for “{e.get('query', '')}”: " + (f"{n} match{'es' if n != 1 else ''} in {files} file{'s' if files != 1 else ''}" if n else "no match")
    if k == "test_run":
        return "Run tests" if e.get("trigger", "ide") == "ide" else "Run tests for Submit"
    if k == "test_result":
        return str(e.get("summary", ""))
    if k in ("message_posted", "team_message"):
        return str(e.get("text", ""))
    if k == "hint_given":
        text = str(e.get("text", "")).strip()
        return f"Hint {e.get('n', '')} from {display_name(str(e.get('from', '')))}" + (f": {text}" if text else "")
    if k == "submit":
        return "Submit for review"
    if k == "submit_result":
        return str(e.get("summary", "")) or ("Accepted" if e.get("ok") else "Not accepted")
    if k == "session_finished":
        return "Session finished: " + ("fixed" if e.get("ok") else "not fixed")
    return ""


def source_label(e: dict) -> str:
    """Where a log entry happened, for the report: the channel (with who spoke), the IDE, Submit."""
    k = e.get("kind")
    if k == "team_message":
        return f"#incident-opd · {display_name(str(e.get('from', '')))}"
    return {"message_posted": "#incident-opd · You", "hint_given": "#incident-opd (hint)", "file_opened": "IDE · file opened", "file_saved": "IDE · file saved",
            "search": "IDE · search", "test_run": "IDE · tests", "test_result": "IDE · tests", "submit": "Submit", "submit_result": "Submit"}.get(str(k), "Session")


@dataclass
class Outcome:
    ok: bool
    events: list[str]  # the entries that prove it, best first (the first not quoted yet is the moment the point quotes)
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
    label: str = ""  # the rule in a few words (the rubric's), for the criterion's summary


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

    def last(self, kind: str, pred: Callable[[dict], bool] | None = None) -> dict | None:
        found = self.of(kind, pred)
        return found[-1] if found else None

    def before(self, a: dict, b: dict | None) -> bool:
        """`a` happened before `b` (ids are in order); with no `b` everything counts."""
        return b is None or self._index[a["id"]] < self._index[b["id"]]

    def after(self, a: dict, b: dict | None) -> bool:
        return b is not None and self._index[a["id"]] > self._index[b["id"]]

    def team(self, ref: str) -> dict | None:
        return self.first("team_message", lambda e: e.get("ref") == ref)

    @property
    def production_edits(self) -> list[dict]:
        return self.of("file_saved", lambda e: not str(e.get("path", "")).startswith(SCOPED_TESTS))

    @property
    def first_edit(self) -> dict | None:
        """The first save of any file, a new test included: from then on the learner is changing things."""
        return self.first("file_saved")

    @property
    def accepted(self) -> dict | None:
        return self.first("submit_result", lambda e: bool(e.get("ok")))

    @property
    def anchor(self) -> dict:
        """The entry a point cites when nothing the learner did can be quoted: the accepted submit, else the end of the log."""
        return self.accepted or self.log[-1]

    def result_of(self, run: dict | None) -> dict | None:
        """The test_result that ends a test_run (the first one after it with the same trigger)."""
        if run is None:
            return None
        return self.first("test_result", lambda e: self.after(e, run) and e.get("trigger") == run.get("trigger"))

    def searched(self, pattern: str, before: dict | None = None) -> dict | None:
        """The first search of the learner whose query matches `pattern` and that found something (before `before`, when given)."""
        rx = re.compile(pattern, re.I)
        return self.first("search", lambda e: int(e.get("matches", 0)) > 0 and bool(rx.search(str(e.get("query", "")))) and self.before(e, before))

    def tail(self) -> list[str]:
        """The entries of the end of the session, best first: a point that has nothing of its own to quote can take another of these when its first is already quoted."""
        submit_result = self.last("test_result", lambda e: e.get("trigger") == "submit")
        return _ids(self.first("submit"), self.accepted, submit_result, self.last("session_finished"))

    def final_green(self) -> dict | None:
        """The last green run of the learner's own before the first submit."""
        submit = self.first("submit")
        return self.last("test_result", lambda e: bool(e.get("ok")) and e.get("trigger") == "ide" and self.before(e, submit))


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
        lead_reply = f.first("team_message", lambda e: e.get("from") == "architect" and post is not None and e.get("ref") == post.get("message"))
        return Outcome(True, _ids(lead_reply, post, f.anchor), "You updated the channel before the lead had to ask.")
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
        posts = f.of("message_posted")
        return Outcome(True, _ids(*(posts[1:] + posts[:1]), f.anchor), "No quiet stretch of five minutes: the lead never had to nudge you.")
    return Outcome(False, _ids(nudges[0], *nudges[1:]), f"The lead had to nudge you {len(nudges)} time{'s' if len(nudges) != 1 else ''} after quiet stretches (first at {clock(nudges[0]['t'])}).")


@rule
def names_the_cause(f: Facts, p: dict) -> Outcome:
    pattern = re.compile(str(p.get("pattern", "slot_at|slot_time")), re.I)
    posts = f.of("message_posted")
    hits = [e for e in posts if pattern.search(str(e.get("text", "")))]
    if hits:
        return Outcome(True, _ids(*hits), f"At {clock(hits[0]['t'])} you told the team what you had found.")
    return Outcome(False, _ids(posts[-1] if posts else None, f.anchor), "None of your posts says what was broken." if posts else "You never said what was broken.")


# -- Diagnosis --------------------------------------------------------------------------------------------

@rule
def reproduced_first(f: Facts, p: dict) -> Outcome:
    edit = f.first_edit
    run = f.first("test_run")
    if run is not None and f.before(run, edit):
        result = f.result_of(run)
        shown = f" ({result['summary']})" if result and result.get("summary") else ""
        return Outcome(True, _ids(result, run), f"You ran the tests at {clock(run['t'])}{shown}, before the first edit.")
    if edit is None:
        return Outcome(False, _ids(f.anchor), "You never ran the tests before submitting.")
    if run is None:
        return Outcome(False, _ids(edit), f"You started editing at {clock(edit['t'])} and never ran the tests first.")
    return Outcome(False, _ids(edit, run), f"You started editing at {clock(edit['t'])}; the first test run came at {clock(run['t'])}.")


def _read_before_edit(f: Facts, pattern: str, what: str, search: str = "") -> Outcome:
    edit = f.first_edit
    opened = f.of("file_opened", lambda e: not e.get("auto") and fnmatch.fnmatch(str(e.get("path", "")), pattern))
    early = [e for e in opened if f.before(e, edit)]
    if early:
        return Outcome(True, _ids(*early), f"You opened {what} at {clock(early[0]['t'])}, before the first edit.")
    found = f.searched(search, edit) if search else None
    if found is not None:
        return Outcome(True, _ids(found), f"You searched the project for “{found.get('query', '')}” at {clock(found['t'])}, before the first edit.")
    if opened:
        return Outcome(False, _ids(opened[0], edit), f"You opened {what} at {clock(opened[0]['t'])}, after you had started editing.")
    return Outcome(False, _ids(edit, f.anchor), f"You never opened {what}.")


@rule
def read_the_route(f: Facts, p: dict) -> Outcome:
    return _read_before_edit(f, str(p.get("pattern", "backend/api/*")), "the failing route")


@rule
def read_the_migration(f: Facts, p: dict) -> Outcome:
    """Opened the migration, or searched the whole project for the name (`search`), before the first edit."""
    return _read_before_edit(f, str(p.get("pattern", "database/migrations/*")), "the migration", str(p.get("search", "")))


@rule
def no_pointer_needed(f: Facts, p: dict) -> Outcome:
    """A scripted pointer from a teammate counts against you only when you had not found the answer yourself by then."""
    pointer = f.first("hint_given", lambda e: e.get("reason") == "timeline")
    mig = str(p.get("pattern", "database/migrations/*"))
    found_by = f.first("file_opened", lambda e: not e.get("auto") and fnmatch.fnmatch(str(e.get("path", "")), mig) and (pointer is None or f.before(e, pointer)))
    if pointer is not None and found_by is None:
        return Outcome(False, _ids(pointer), f"A teammate had to point you at the database change at {clock(pointer['t'])}.")
    route = f.first("file_opened", lambda e: not e.get("auto") and "api" in str(e.get("path", "")))
    return Outcome(True, _ids(found_by, f.first("search"), route, f.first("message_posted"), f.result_of(f.first("test_run")), f.anchor), "No scripted pointer was needed: you found where to look yourself.")


# -- Fix quality ------------------------------------------------------------------------------------------

@rule
def old_name_gone(f: Facts, p: dict) -> Outcome:
    name, folder = str(p.get("old_name", "slot_time")), str(p.get("folder", "backend"))
    edits = f.production_edits
    looked = f.searched(re.escape(name))
    if not f.old_name_files:
        return Outcome(True, _ids(edits[-1] if edits else None, looked, *edits[:-1], f.anchor), f"No file under {folder}/ says {name} any more.")
    return Outcome(False, _ids(edits[-1] if edits else None, f.anchor), f"{name} is still used in {', '.join(f.old_name_files[:4])}.")


@rule
def suite_green_on_main(f: Facts, p: dict) -> Outcome:
    r = f.rerun
    if r is None:
        return Outcome(False, _ids(f.anchor), "The suite could not be re-run on the merged project.")
    qa = f.team("react-accepted-qa")
    mine = f.first("test_result", lambda e: e.get("trigger") == "submit" and bool(e.get("ok")))
    total = r.get("passed", 0) + r.get("failed", 0)
    if r.get("ok"):
        return Outcome(True, _ids(qa, mine, f.anchor), f"I re-ran the whole suite on the merged project: {r.get('passed', 0)} of {total} pass.")
    return Outcome(False, _ids(f.anchor), f"I re-ran the whole suite on the merged project: {r.get('failed', 0)} of {total} fail.")


@rule
def small_change(f: Facts, p: dict) -> Outcome:
    limit = int(p.get("max_lines", 20))
    edits = f.production_edits
    if not edits:
        return Outcome(False, _ids(f.anchor), "You changed nothing under backend/.")
    lines = sum(int(e.get("added", 0)) + int(e.get("removed", 0)) for e in edits)
    ranked = sorted(edits, key=lambda e: int(e.get("added", 0)) + int(e.get("removed", 0)), reverse=True)
    if lines <= limit:
        return Outcome(True, _ids(*ranked), f"{lines} lines changed in {len({e['path'] for e in edits})} file(s): small and targeted.")
    return Outcome(False, _ids(*ranked), f"{lines} lines changed, more than the {limit} the problem needs.")


@rule
def review_clean(f: Facts, p: dict) -> Outcome:
    sent = f.of("submit_result", lambda e: not e.get("ok") and e.get("stage") == "review")
    if not sent:
        return Outcome(True, _ids(f.accepted, f.first("submit"), f.anchor), "The Reviewer read your change and sent nothing back.")
    return Outcome(False, _ids(sent[0]), f"The Reviewer sent your change back {len(sent)} time{'s' if len(sent) != 1 else ''}.")


# -- Testing ----------------------------------------------------------------------------------------------

@rule
def green_before_submit(f: Facts, p: dict) -> Outcome:
    submit = f.first("submit")
    green = f.final_green()
    last_save = f.last("file_saved", lambda e: f.before(e, submit))
    if green is not None and (last_save is None or f.before(last_save, green)):
        return Outcome(True, _ids(green), f"Your own run at {clock(green['t'])} was green, after your last change and before you submitted.")
    if green is not None:
        return Outcome(False, _ids(last_save, green), f"Your last green run ({clock(green['t'])}) came before your last change ({clock(last_save['t'])}), so the final code was not tested before you submitted.")
    return Outcome(False, _ids(submit, f.anchor), "You submitted without a green run of your own first.")


@rule
def no_red_submit(f: Facts, p: dict) -> Outcome:
    red = f.of("submit_result", lambda e: not e.get("ok") and e.get("stage") == "tests")
    if not red:
        ok_run = f.first("test_result", lambda e: e.get("trigger") == "submit" and bool(e.get("ok")))
        return Outcome(True, _ids(ok_run, f.first("submit"), f.anchor), "No submit was refused for failing tests.")
    return Outcome(False, _ids(red[0]), f"A submit at {clock(red[0]['t'])} was refused because tests still failed.")


def _regression_saves(f: Facts, pattern: str) -> list[dict]:
    """The saves of the learner's regression test, the ones that hold lines first (creating the empty file is only the start)."""
    saves = f.of("file_saved", lambda e: fnmatch.fnmatch(str(e.get("path", "")), pattern))
    return sorted(saves, key=lambda e: (-int(int(e.get("added", 0)) > 0), -f._index[e["id"]]))


@rule
def regression_test_added(f: Facts, p: dict) -> Outcome:
    saves = _regression_saves(f, str(p.get("pattern", "tests/regression/test_*.py")))
    if saves:
        return Outcome(True, _ids(*saves), f"You added a regression test at {clock(saves[0]['t'])}.")
    return Outcome(False, _ids(f.first("submit"), f.anchor), "No new test covers the bug you fixed.")


@rule
def regression_test_proves_fix(f: Facts, p: dict) -> Outcome:
    r = f.regression
    saves = _regression_saves(f, "tests/regression/test_*.py")
    if r is None or not saves:
        return Outcome(False, _ids(f.first("submit"), f.anchor), "Without a new test, nothing shows the bug cannot come back unnoticed.")
    path = str(r.get("path", ""))
    reds = f.of("test_result", lambda e: any(str(t).startswith(path) for t in e.get("failed", [])))
    green = f.final_green()
    if r.get("fails_on_seed") and r.get("passes_on_main"):
        return Outcome(True, _ids(*reds, *saves, green), "I ran your new test on the broken code and on your fix: it fails before and passes after.")
    if not r.get("fails_on_seed"):
        return Outcome(False, _ids(*saves), "Your new test also passes on the broken code, so it would not have caught the bug.")
    return Outcome(False, _ids(*saves), "Your new test fails on your own fix.")


# -- Ownership --------------------------------------------------------------------------------------------

@rule
def within_time_box(f: Facts, p: dict) -> Outcome:
    done = f.accepted
    if done is None:
        return Outcome(False, _ids(f.anchor), "The fix was not accepted.")
    thanks = f.team("react-accepted-lead")
    limit = f.minutes * 60
    ids = _ids(done, thanks, f.last("session_finished"))
    if done["t"] <= limit:
        return Outcome(True, ids, f"Accepted at {clock(done['t'])}, inside the {f.minutes}-minute time box.")
    return Outcome(False, ids, f"Accepted at {clock(done['t'])}, after the {f.minutes}-minute time box.")


@rule
def few_hints(f: Facts, p: dict) -> Outcome:
    limit = int(p.get("max_hints", 1))
    hints = f.of("hint_given")
    if len(hints) <= limit:
        return Outcome(True, _ids(*reversed(hints), f.anchor, f.last("session_finished")), f"{len(hints)} hint{'s' if len(hints) != 1 else ''} used (up to {limit} is fine).")
    return Outcome(False, _ids(hints[limit], *hints[:limit], *hints[limit + 1:]), f"{len(hints)} hints used: every answer to a question of yours counts.")


@rule
def no_scope_rejection(f: Facts, p: dict) -> Outcome:
    out = f.of("submit_result", lambda e: not e.get("ok") and e.get("stage") == "scope")
    if not out:
        return Outcome(True, _ids(*reversed(f.production_edits), f.first("submit"), f.anchor), "You stayed inside the files your role may edit.")
    return Outcome(False, _ids(out[0]), "A submit was refused because it changed files outside your role.")


@rule
def reported_the_outcome(f: Facts, p: dict) -> Outcome:
    green = f.final_green()
    done = f.accepted
    post = f.first("message_posted", lambda e: green is not None and f.after(e, green) and (done is None or f.before(e, done)))
    if post is not None:
        return Outcome(True, _ids(post), f"At {clock(post['t'])} you told the team the fix was ready.")
    return Outcome(False, _ids(green, f.anchor), "You never told the channel that the fix was ready.")


def score(rubric: Rubric, facts: Facts) -> list[CriterionResult]:
    """Every criterion's rules, in the rubric's order. Finding ids are F01, F02, ... in the same order. A point quotes the first of its entries that no earlier point quotes."""
    out: list[CriterionResult] = []
    used: set[str] = set()
    n = 0
    for c in rubric.criteria:
        res = CriterionResult(c.id, 0)
        for r in c.rules:
            o = RULES[r.id](facts, r.params)
            if not o.events:
                o.events = [facts.anchor["id"]]
            tail = facts.tail()
            if all(i in tail for i in o.events):  # nothing but the end of the session to quote: the other entries of the end will do as well
                o.events += [i for i in tail if i not in o.events]
            pick = next((i for i in o.events if i not in used), o.events[0])
            used.add(pick)
            o.events = [pick] + [i for i in o.events if i != pick]
            n += 1
            res.findings.append(Finding(f"F{n:02d}", c.id, r.id, "strength" if o.ok else "gap", o.events, o.text, "" if o.ok else r.advice, r.label))
            res.score += 1 if o.ok else 0
        out.append(res)
    return out
