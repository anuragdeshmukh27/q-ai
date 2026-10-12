"""Scoring: deterministic rules over the session log. No model is involved in a score or in the sentence of a point.

A rubric criterion is four rules worth one point each. A rule looks at the session log, plus what the debrief measured after the submit, and answers with an `Outcome`:
passed or not, the log entry that proves it and one factual sentence about THAT entry. Passed is a STRENGTH, not passed is a GAP. The score of a criterion is the number of
rules that passed; the total is the sum times the rubric's weight (5 per point: 5 criteria x 4 points x 5 = 100).

A point quotes the entry it describes, and every time, file and test count in its sentence is the quoted entry's (`note_matches` checks it; the report drops a point that
fails). Two points may quote the same entry: a repeated quote is better than a wrong one.

What the debrief itself measured has its own entries in the log it scores, kind `debrief_check`, so that a point about them quotes them: the suite re-run on the merged
project, the scan for the old name, the regression test on the seed and on main, the size of the change, the counts of hints, nudges and refused submits.
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


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def event_text(e: dict) -> str:
    """The words of a log entry: what a quote of it must match. The same text is shown as the entry's detail. Only names a learner knows (Karan, never `database`)."""
    k = e.get("kind")
    if k == "session_started":
        return f"Session started: {e.get('scenario', '')}"
    if k == "file_opened":
        return str(e.get("path", ""))
    if k == "file_saved":
        added = int(e.get("added", 0))
        if e.get("created") and not added and not e.get("removed"):
            return f"Created {e.get('path', '')} (empty file)"
        verb = "Created" if e.get("created") else "Saved"
        return f"{verb} {e.get('path', '')} (+{added} -{e.get('removed', 0)} lines)"
    if k == "search":
        n, files = int(e.get("matches", 0)), int(e.get("files", 0))
        return f"Searched for “{e.get('query', '')}”: " + (f"{n} match{'es' if n != 1 else ''} in {files} file{'s' if files != 1 else ''}" if n else "no match")
    if k == "test_run":
        return "Run tests" if e.get("trigger", "ide") == "ide" else "Run tests for Submit"
    if k == "test_result":
        return str(e.get("summary", ""))
    if k in ("message_posted", "team_message", "debrief_check"):
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
    """Where a log entry happened, for the report: the channel (with who spoke), the IDE, Submit, the debrief's own checks."""
    k = e.get("kind")
    if k == "team_message":
        return f"#incident-opd · {display_name(str(e.get('from', '')))}"
    return {"message_posted": "#incident-opd · You", "hint_given": "#incident-opd (hint)", "file_opened": "IDE · file opened", "file_saved": "IDE · file saved",
            "search": "IDE · search", "test_run": "IDE · tests", "test_result": "IDE · tests", "submit": "Submit", "submit_result": "Submit", "debrief_check": "Debrief check"}.get(str(k), "Session")


_TIME = re.compile(r"\b\d{2}:\d{2}\b")
_FILE = re.compile(r"[\w./-]*\w\.(?:py|sql|md|json|js|css|html)\b|\b(?:backend|database|tests|static)/[\w./-]*")
_RESULT_COUNT = re.compile(r"\b(\d+) (?:passed|failed)\b")


def note_matches(note: str, event: dict) -> str | None:
    """None when every time, file and test count in `note` is the quoted entry's (its own time, or what its text says), else what does not match."""
    text = event_text(event)
    ok_times = {clock(event.get("t", 0)), *_TIME.findall(text)}
    for t in _TIME.findall(note):
        if t not in ok_times:
            return f"the time {t} is not the quoted entry's ({clock(event.get('t', 0))})"
    for f in _FILE.findall(note):
        if f.strip(".") not in text:
            return f"the file {f} is not in the quoted entry"
    for n in _RESULT_COUNT.findall(note):
        if not re.search(rf"\b{n}\b", text):
            return f"the count {n} is not in the quoted entry"
    return None


@dataclass
class Outcome:
    ok: bool
    events: list[str]  # the entry the point quotes first, then entries that support it
    text: str  # one factual sentence about the first entry


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
    """What the rules look at: the session log and what the debrief measured after the submit (as `debrief_check` entries after the session's own)."""

    def __init__(self, events: list[dict], minutes: int = 25, old_name_files: list[str] | None = None, rerun: dict | None = None, regression: dict | None = None,
                 scan: tuple[str, str] = ("backend", "slot_time")):
        self.session = [dict(e) for e in events]
        self.minutes = minutes
        self.old_name_files = list(old_name_files or [])
        self.rerun = rerun  # {ok, passed, failed, summary} of the suite on the merged project, or None when it could not be run
        self.regression = regression  # {path, fails_on_seed, passes_on_main, seed_summary?, main_summary?} of the learner's new test, or None when there is none
        self.scan = scan  # (folder, old name) the scan looked for
        self.log = self.session + self._checks()
        self._index = {e["id"]: i for i, e in enumerate(self.log)}

    # -- what the debrief measured, as entries -------------------------------------------------------------
    def _checks(self) -> list[dict]:
        if not self.session:
            return []
        t = self.session[-1]["t"]
        out: list[dict] = []

        def add(check: str, text: str) -> None:
            out.append({"id": f"E{len(self.session) + len(out) + 1:03d}", "t": t, "kind": "debrief_check", "check": check, "text": text})

        folder, name = self.scan
        add("scan", f"Debrief scan of {folder}/: no file says {name} any more" if not self.old_name_files else f"Debrief scan of {folder}/: {name} is still in {', '.join(self.old_name_files[:4])}")
        r = self.rerun
        add("rerun", "Debrief re-run on main: the suite could not be run" if r is None else f"Debrief re-run on main: {r.get('passed', 0)} passed" + (f", {r.get('failed', 0)} failed" if r.get("failed") else ""))
        g = self.regression
        if g is not None:
            add("regression", f"Regression test {g.get('path', '')} on the seed: {g.get('seed_summary') or ('failed' if g.get('fails_on_seed') else 'passed')}; "
                              f"on main: {g.get('main_summary') or ('passed' if g.get('passes_on_main') else 'failed')}")
        files: dict[str, dict] = {}
        for e in self.of("file_saved", lambda e: not str(e.get("path", "")).startswith(SCOPED_TESTS)):
            files[e["path"]] = e  # the last save of a file says how far it is from the start (the stats are against the starting version)
        a, d = sum(int(e.get("added", 0)) for e in files.values()), sum(int(e.get("removed", 0)) for e in files.values())
        add("change", f"Your change against the start: {_plural(len(files), 'file')}, {a + d} lines changed (+{a} -{d})" if files else "Your change against the start: nothing outside the tests changed")
        refused = self.of("submit_result", lambda e: not e.get("ok"))
        add("counts", "Counted in the session log: " + ", ".join([
            _plural(len(self.of("hint_given")), "hint"), _plural(len(self.of("team_message", lambda e: e.get("ref") == "lead-nudge")), "nudge") + " from the lead",
            _plural(sum(1 for e in refused if e.get("stage") == "review"), "review send-back"), _plural(sum(1 for e in refused if e.get("stage") == "tests"), "submit") + " refused for tests",
            _plural(sum(1 for e in refused if e.get("stage") == "scope"), "submit") + " refused for scope"]))
        return out

    def check(self, name: str) -> dict | None:
        return next((e for e in self.log if e["kind"] == "debrief_check" and e.get("check") == name), None)

    # -- the session --------------------------------------------------------------------------------------
    def of(self, kind: str, pred: Callable[[dict], bool] | None = None) -> list[dict]:
        return [e for e in self.session if e["kind"] == kind and (pred is None or pred(e))]

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
        """The entry a point cites when the learner did nothing it could quote: the accepted submit, else the end of the session."""
        return self.accepted or self.session[-1]

    def result_of(self, run: dict | None) -> dict | None:
        """The test_result that ends a test_run (the first one after it with the same trigger)."""
        if run is None:
            return None
        return self.first("test_result", lambda e: self.after(e, run) and e.get("trigger") == run.get("trigger"))

    def searched(self, pattern: str, before: dict | None = None) -> dict | None:
        """The first search of the learner whose query matches `pattern` and that found something (before `before`, when given)."""
        rx = re.compile(pattern, re.I)
        return self.first("search", lambda e: int(e.get("matches", 0)) > 0 and bool(rx.search(str(e.get("query", "")))) and self.before(e, before))

    def final_green(self) -> dict | None:
        """The last green run of the learner's own before the first submit."""
        submit = self.first("submit")
        return self.last("test_result", lambda e: bool(e.get("ok")) and e.get("trigger") == "ide" and self.before(e, submit))


RULES: dict[str, Callable[[Facts, dict], Outcome]] = {}


def _by(e: dict) -> str:
    """"By your first edit at 01:31", "By your submit at 03:00", ...: how a gap about something never done names the moment it quotes (always the quoted entry's own time)."""
    kind = e.get("kind")
    when = clock(e["t"])
    if kind == "file_saved":
        return f"By your first edit at {when}"
    if kind == "submit":
        return f"By your submit at {when}"
    if kind == "submit_result":
        return f"By the accepted submit at {when}" if e.get("ok") else f"By the refused submit at {when}"
    if kind == "test_result":
        return f"After your green run at {when}"
    if kind == "team_message":
        return f"By the lead's request at {when}"
    return f"By the end of the session at {when}"


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
        ask = f.team("lead-update")
        return Outcome(False, _ids(ask, f.anchor), f"{_by(ask or f.anchor)} you had not posted any update in the channel.")
    if post["t"] <= within:
        return Outcome(True, _ids(post), f"First update at {clock(post['t'])}, inside the first {int(within // 60)} minutes.")
    return Outcome(False, _ids(post), f"Your first update came at {clock(post['t'])}, later than the {int(within // 60)} minutes asked.")


@rule
def answered_requests(f: Facts, p: dict) -> Outcome:
    within = float(p.get("within", 60))
    ask = f.team("lead-update")
    if ask is None:
        return Outcome(True, _ids(f.first("message_posted"), f.anchor), "You updated the channel before the lead had to ask.")
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
        return Outcome(True, _ids(f.check("counts")), "No quiet stretch of five minutes: the lead never had to nudge you.")
    return Outcome(False, _ids(nudges[0], *nudges[1:]), f"The lead had to nudge you {len(nudges)} time{'s' if len(nudges) != 1 else ''} after quiet stretches (first at {clock(nudges[0]['t'])}).")


@rule
def names_the_cause(f: Facts, p: dict) -> Outcome:
    pattern = re.compile(str(p.get("pattern", "slot_at|slot_time")), re.I)
    posts = f.of("message_posted")
    hits = [e for e in posts if pattern.search(str(e.get("text", "")))]
    if hits:
        return Outcome(True, _ids(*hits), f"At {clock(hits[0]['t'])} you told the team what you had found.")
    if posts:
        return Outcome(False, _ids(posts[-1], f.anchor), f"Your last post, at {clock(posts[-1]['t'])}, does not say what was broken.")
    return Outcome(False, _ids(f.anchor), f"{_by(f.anchor)} you had not said in the channel what was broken.")


# -- Diagnosis --------------------------------------------------------------------------------------------

@rule
def reproduced_first(f: Facts, p: dict) -> Outcome:
    edit = f.first_edit
    run = f.first("test_run")
    if run is not None and f.before(run, edit):
        result = f.result_of(run)
        if result is not None:
            return Outcome(True, _ids(result, run), f"Your first test run finished at {clock(result['t'])} ({result.get('summary', '')}), before the first edit.")
        return Outcome(True, _ids(run), f"You ran the tests at {clock(run['t'])}, before the first edit.")
    if edit is None:
        return Outcome(False, _ids(f.anchor), f"{_by(f.anchor)} you had not run the tests.")
    return Outcome(False, _ids(edit, run), f"{_by(edit)} you had not run the tests.")


def _read_before_edit(f: Facts, pattern: str, what: str, search: str = "") -> Outcome:
    edit = f.first_edit
    opened = f.of("file_opened", lambda e: not e.get("auto") and fnmatch.fnmatch(str(e.get("path", "")), pattern))
    early = [e for e in opened if f.before(e, edit)]
    if early:
        return Outcome(True, _ids(*early), f"You opened {what} ({early[0]['path']}) at {clock(early[0]['t'])}, before the first edit.")
    found = f.searched(search, edit) if search else None
    if found is not None:
        return Outcome(True, _ids(found), f"You searched the project for “{found.get('query', '')}” at {clock(found['t'])}, before the first edit.")
    if opened:
        return Outcome(False, _ids(opened[0], edit), f"You opened {what} ({opened[0]['path']}) at {clock(opened[0]['t'])}, after you had started editing.")
    return Outcome(False, _ids(edit or f.anchor, f.anchor), f"{_by(edit or f.anchor)} you had not opened {what}.")


@rule
def read_the_route(f: Facts, p: dict) -> Outcome:
    """Either route file of the failing endpoints (`pattern`), opened by you (from the tree, a tab or a search result) before the first edit."""
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
    searched = f.first("search", lambda e: int(e.get("matches", 0)) > 0)
    route = f.first("file_opened", lambda e: not e.get("auto") and "api" in str(e.get("path", "")))
    return Outcome(True, _ids(found_by, searched, route, f.result_of(f.first("test_run")), f.anchor), "No scripted pointer was needed: you found where to look yourself.")


# -- Fix quality ------------------------------------------------------------------------------------------

@rule
def old_name_gone(f: Facts, p: dict) -> Outcome:
    name, folder = str(p.get("old_name", "slot_time")), str(p.get("folder", "backend"))
    if not f.old_name_files:
        return Outcome(True, _ids(f.check("scan")), f"No file under {folder}/ says {name} any more.")
    return Outcome(False, _ids(f.check("scan")), f"{name} is still used in {', '.join(f.old_name_files[:4])}.")


@rule
def suite_green_on_main(f: Facts, p: dict) -> Outcome:
    r = f.rerun
    if r is None:
        return Outcome(False, _ids(f.check("rerun")), "The suite could not be re-run on the merged project.")
    total = r.get("passed", 0) + r.get("failed", 0)
    if r.get("ok"):
        return Outcome(True, _ids(f.check("rerun")), f"I re-ran the whole suite on the merged project: {r.get('passed', 0)} of {total} pass.")
    return Outcome(False, _ids(f.check("rerun")), f"I re-ran the whole suite on the merged project: {r.get('failed', 0)} of {total} fail.")


@rule
def small_change(f: Facts, p: dict) -> Outcome:
    limit = int(p.get("max_lines", 20))
    files: dict[str, dict] = {}
    for e in f.production_edits:
        files[e["path"]] = e
    if not files:
        return Outcome(False, _ids(f.check("change")), "You changed nothing outside the tests.")
    lines = sum(int(e.get("added", 0)) + int(e.get("removed", 0)) for e in files.values())
    if lines <= limit:
        return Outcome(True, _ids(f.check("change")), f"{lines} lines changed in {len(files)} file{'s' if len(files) != 1 else ''}: small and targeted.")
    return Outcome(False, _ids(f.check("change")), f"{lines} lines changed in {len(files)} file{'s' if len(files) != 1 else ''}, more than the {limit} the problem needs.")


@rule
def review_clean(f: Facts, p: dict) -> Outcome:
    sent = f.of("submit_result", lambda e: not e.get("ok") and e.get("stage") == "review")
    if not sent:
        return Outcome(True, _ids(f.check("counts")), "The Reviewer read your change and sent nothing back.")
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
        return Outcome(False, _ids(last_save, green), f"You changed {last_save['path']} at {clock(last_save['t'])}, after your last green run, so the final code was not tested before you submitted.")
    return Outcome(False, _ids(submit, f.anchor), f"{_by(submit or f.anchor)} you had no green run of your own.")


@rule
def no_red_submit(f: Facts, p: dict) -> Outcome:
    red = f.of("submit_result", lambda e: not e.get("ok") and e.get("stage") == "tests")
    if not red:
        return Outcome(True, _ids(f.check("counts")), "No submit was refused for failing tests.")
    return Outcome(False, _ids(red[0]), f"A submit at {clock(red[0]['t'])} was refused because tests still failed.")


def _regression_saves(f: Facts, pattern: str) -> list[dict]:
    """The saves of the learner's regression test that hold lines, first save first (creating the empty file is only the start)."""
    return [e for e in f.of("file_saved", lambda e: fnmatch.fnmatch(str(e.get("path", "")), pattern)) if int(e.get("added", 0)) > 0]


@rule
def regression_test_added(f: Facts, p: dict) -> Outcome:
    saves = _regression_saves(f, str(p.get("pattern", "tests/regression/test_*.py")))
    if saves:
        return Outcome(True, _ids(*saves), f"You added a regression test ({saves[0]['path']}) at {clock(saves[0]['t'])}.")
    return Outcome(False, _ids(f.first("submit"), f.anchor), f"{_by(f.first('submit') or f.anchor)} you had not added a test of your own for the bug.")


@rule
def regression_test_proves_fix(f: Facts, p: dict) -> Outcome:
    r = f.regression
    saves = _regression_saves(f, "tests/regression/test_*.py")
    if r is None or not saves:
        return Outcome(False, _ids(f.first("submit"), f.anchor), f"{_by(f.first('submit') or f.anchor)} no new test of yours showed that the bug cannot come back unnoticed.")
    check = f.check("regression")
    if r.get("fails_on_seed") and r.get("passes_on_main"):
        return Outcome(True, _ids(check), "I ran your new test on the broken code and on your fix: it fails before and passes after.")
    if not r.get("fails_on_seed"):
        return Outcome(False, _ids(check), "Your new test also passes on the broken code, so it would not have caught the bug.")
    return Outcome(False, _ids(check), "Your new test fails on your own fix.")


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
        return Outcome(True, _ids(f.check("counts")), f"{len(hints)} hint{'s' if len(hints) != 1 else ''} used (up to {limit} is fine).")
    return Outcome(False, _ids(hints[limit], *hints[:limit], *hints[limit + 1:]), f"{len(hints)} hints used: every answer to a question of yours counts.")


@rule
def no_scope_rejection(f: Facts, p: dict) -> Outcome:
    out = f.of("submit_result", lambda e: not e.get("ok") and e.get("stage") == "scope")
    if not out:
        return Outcome(True, _ids(f.check("counts")), "You stayed inside the files your role may edit.")
    return Outcome(False, _ids(out[0]), "A submit was refused because it changed files outside your role.")


@rule
def reported_the_outcome(f: Facts, p: dict) -> Outcome:
    green = f.final_green()
    done = f.accepted
    post = f.first("message_posted", lambda e: green is not None and f.after(e, green) and (done is None or f.before(e, done)))
    if post is not None:
        return Outcome(True, _ids(post), f"At {clock(post['t'])} you told the team the fix was ready.")
    return Outcome(False, _ids(green, f.anchor), f"{_by(green or f.anchor)} you never told the channel that the fix was ready.")


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
            res.findings.append(Finding(f"F{n:02d}", c.id, r.id, "strength" if o.ok else "gap", o.events, o.text, "" if o.ok else r.advice, r.label))
            res.score += 1 if o.ok else 0
        out.append(res)
    return out
