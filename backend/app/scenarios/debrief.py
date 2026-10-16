"""The debrief: after the submit is accepted the team walks to the meeting room, the suite is re-run on the merged project, the rubric is scored, each judge says their
criterion in #incident-opd, and the report is written (`.q/reports/attempt-N.md` and `.json`) and published.

Order: `debrief_started` (the office walks to the meeting room) -> measure (re-run the suite on main, look for the old name, run the learner's new test on the seed) ->
score (deterministic rules) -> word (the 7b, verified; template wording when it cannot be used) -> the judges speak, one post each (`channel_message` with source `debrief`) ->
the report is saved and published (`debrief_report`) -> `debrief_ended` (everyone walks back). Nothing here is added to the session log: the log is the evidence.
"""
from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ..humanide import SuiteRun, summary_line
from .measures import MEASURES
from .reports import History, attach_voices, build_report, write_report
from .rubric import Rubric
from .scoring import Facts, clock, score
from .wording import Wordsmith, build_voices

if TYPE_CHECKING:
    from .build import ScenarioBuild

REGRESSION_GLOB = "tests/regression/test_*.py"
SEED_TIMEOUT = 90.0  # seconds for the learner's new test on the seed
BUBBLE_CHARS = 78


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip(" ,;:.") + "…"


def scan_old_name(root: Path, folder: str, name: str) -> list[str]:
    """The Python files under `folder` that still use `name` (as a whole word), relative to `root`."""
    word = re.compile(rf"\b{re.escape(name)}\b")
    out: list[str] = []
    for p in sorted((Path(root) / folder).rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            if word.search(p.read_text(encoding="utf-8", errors="replace")):
                out.append(p.relative_to(root).as_posix())
        except OSError:
            continue
    return out


def fails_on_seed(seed_dir: Path, project: Path, rel: str) -> bool:
    return run_on_seed(seed_dir, project, rel)[0]


def run_on_seed(seed_dir: Path, project: Path, rel: str) -> tuple[bool, str]:
    """The learner's new test, put into a fresh copy of the seed (the project as it was before the fix): it has to fail there, and fail by an assertion or an error of the
    test run (exit code 1), not because the file cannot be loaded (exit code 2) or holds no test (5). Returns (it failed that way, pytest's summary line, "1 failed in 0.4s")."""
    tmp = Path(tempfile.mkdtemp(prefix="q-seed-"))
    try:
        copy = tmp / "seed"
        shutil.copytree(seed_dir, copy, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.db", ".worktrees"))
        target = copy / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(project) / rel, target)
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--color=no", rel], cwd=copy, capture_output=True, text=True, timeout=SEED_TIMEOUT)
        return r.returncode == 1, summary_line(r.stdout, "")
    except (OSError, subprocess.TimeoutExpired):
        return False, "could not be run"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def moment_of(criterion: dict, rows: list[dict]) -> dict | None:
    """The moment a judge talks about: the first gap of the criterion (with its tip), else its first strength (with what to keep doing)."""
    mine = [r for r in rows if r["criterion"] == criterion["id"]]
    gap = next((r for r in mine if r["kind"] == "gap"), None)
    row = gap or (mine[0] if mine else None)
    if row is None:
        return None
    return {"t": row["t"], "quote": _clip(row["quote"], 90), "note": row["note"], "tip": row["advice"] if gap and gap["advice"] else criterion["keep"]}


def judge_post(criterion: dict, rows: list[dict]) -> tuple[str, str]:
    """(the post, the speech bubble) of a judge: the score, one quoted moment with its timestamp, one tip. A criterion that is not full marks quotes a gap and gives that gap's
    advice; a full one quotes a strength and says what to keep doing."""
    mine = [r for r in rows if r["criterion"] == criterion["id"]]
    gap = next((r for r in mine if r["kind"] == "gap"), None)
    row = gap or (mine[0] if mine else None)
    tip = (gap["advice"] if gap and gap["advice"] else criterion["keep"])
    head = f"{criterion['name']} {criterion['score']}/{criterion['max']}."
    quoted = f" At {clock(row['t'])}: “{_clip(row['quote'], 90)}” {row['note']}" if row else ""
    return f"{head}{quoted} Tip: {tip}", _clip(f"{head} {tip}", BUBBLE_CHARS)


class Debrief:
    def __init__(self, build: "ScenarioBuild", rubric: Rubric, wordsmith: Wordsmith, history: History, attempt: int, pace: float = 3.5,
                 rerun: Callable[[Path], dict] | None = None):
        self.build, self.rubric, self.wordsmith, self.history, self.attempt, self.pace = build, rubric, wordsmith, history, attempt, pace
        self._rerun = rerun or self._run_suite
        self.report: dict | None = None
        self._halted = threading.Event()
        self._thread: threading.Thread | None = None
        self._suite: SuiteRun | None = None  # the re-run of the suite on main while it is going
        self.started = False

    # -- running it ---------------------------------------------------------------
    def start(self) -> None:
        if self.started:
            return
        self.started = True
        self._thread = threading.Thread(target=self._guarded, name="debrief", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._halted.set()
        suite = self._suite
        if suite is not None:  # the re-run ends now, not when pytest is done
            suite.kill()

    def join(self, timeout: float = 120.0) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _guarded(self) -> None:
        try:
            self._run()
        except Exception as e:  # a failing debrief must not leave the office in the meeting room
            self.build.emit("debrief_failed", reason=f"{type(e).__name__}: {e}"[:200])
            self.build.emit("debrief_ended", ok=False)

    def _wait(self, seconds: float) -> None:
        if seconds > 0:
            self._halted.wait(seconds)

    def _run(self) -> None:
        b = self.build
        names = {a.id: a.name for a in b.agents.values()}
        judges = [{"id": c.judge, "name": names.get(c.judge, c.judge), "criterion": c.id} for c in self.rubric.criteria]
        b.emit("debrief_started", attempt=self.attempt, rubric=self.rubric.public(), judges=judges)
        b.director.announce("planner", f"Debrief time for attempt {self.attempt}: everyone to the meeting room. Vikram re-runs the whole suite on main first.")
        self._wait(self.pace)
        if self._halted.is_set():
            return b.emit("debrief_ended", ok=False)
        facts = self.measure()
        if self._halted.is_set():  # Stop came while the project was being measured: nothing is scored, written or kept
            return b.emit("debrief_ended", ok=False)
        results = score(self.rubric, facts)
        report = build_report(scenario=b.scenario, rubric=self.rubric, attempt=self.attempt, project=b.root.name if b.root else "", facts=facts, results=results, names=names,
                              history=self.history.attempts(), kind=b.kind, variant=b.variant)
        # the points are final: the model only says them aloud (each judge's line, the coach paragraph), and a line that says anything else is dropped
        moments = {c["id"]: m for c in report["criteria"] if (m := moment_of(c, report["rows"]))}
        lines, coach, dropped, reason = build_voices(report, self.wordsmith, moments, lambda c: judge_post(c, report["rows"]))
        attach_voices(report, lines, coach, dropped, reason)
        for c in report["criteria"]:
            if self._halted.is_set():
                return b.emit("debrief_ended", ok=False)
            said = lines[c["id"]]
            b.director.announce(c["judge"], said["text"], bubble=said["bubble"], debrief=True, criterion=c["id"], score=c["score"], voice=said["source"])
            self._wait(self.pace)
        if self._halted.is_set():
            return b.emit("debrief_ended", ok=False)
        if b.root:
            write_report(b.root, report, names)
        self.history.add(report["attempts"][-1])
        self.report = report
        b.emit("debrief_report", report=report)
        before = [a for a in report["attempts"] if a["attempt"] != report["attempt"]]
        gain = f" (attempt {before[-1]['attempt']}: {before[-1]['total']})" if before else ""
        b.director.announce("planner", f"Report is ready: {report['total']}/{report['max']}{gain}. Open the Debrief tab for the evidence.", debrief=True)
        self._wait(self.pace)
        b.emit("debrief_ended", ok=True)

    # -- what is measured after the submit -------------------------------------------------------
    def _run_suite(self, root: Path) -> dict:
        self._suite = suite = SuiteRun(root, lambda line: None)
        if self._halted.is_set():  # Stop read `_suite` before it was set: this run is the one to end
            suite.kill()
        return suite.run()

    def measure(self) -> Facts:
        """The session log plus what Q checks itself on the merged project: the suite re-run, the files that still say the old name, the learner's new test on the seed."""
        b = self.build
        log = b.log.events()
        root = b.root
        old_name_files: list[str] = []
        rerun: dict | None = None
        regression: dict | None = None
        rule = next((r for c in self.rubric.criteria for r in c.rules if r.id == "old_name_gone"), None)
        if root and Path(root).is_dir() and not self._halted.is_set():
            if rule:
                old_name_files = scan_old_name(root, str(rule.params.get("folder", "backend")), str(rule.params.get("old_name", "")))
            try:
                rerun = self._rerun(root)
            except Exception:  # the suite could not be started: the rubric says so, the score does not guess
                rerun = None
            saved = [e["path"] for e in log if e["kind"] == "file_saved" and fnmatch.fnmatch(str(e.get("path", "")), REGRESSION_GLOB)]
            if saved and (Path(root) / saved[-1]).is_file() and not self._halted.is_set():
                rel = saved[-1]
                mine = [t for t in (rerun or {}).get("tests", []) if t["id"].startswith(rel + "::")]
                failed_on_seed, seed_summary = run_on_seed(b.scenario.seed_dir, root, rel)
                ok_main = sum(1 for t in mine if t["outcome"] == "passed")
                regression = {"path": rel, "fails_on_seed": failed_on_seed, "passes_on_main": bool(mine) and ok_main == len(mine), "seed_summary": seed_summary or None,
                              "main_summary": f"{ok_main} passed" + (f", {len(mine) - ok_main} failed" if len(mine) != ok_main else "") if mine else None}
        scan = (str(rule.params.get("folder", "backend")), str(rule.params.get("old_name", ""))) if rule else None
        measured: dict[str, dict] = {}
        for name in self.rubric.measures:  # what this scenario's rubric measures on the merged project besides the suite
            try:
                measured.update(MEASURES[name](Path(root), b.scenario.seed_dir, {})) if root and Path(root).is_dir() else None
            except Exception:  # a measure that cannot run is "not measured": the rules say so, the score does not guess
                continue
        return Facts(log, minutes=b.scenario.minutes, old_name_files=old_name_files, rerun=rerun, regression=regression, scan=scan, measured=measured)
