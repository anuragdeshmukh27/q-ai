"""Autoplay: a scripted learner plays the scenario live, through the same Session calls the HTTP endpoints make, so a viewer can watch a whole run with nobody typing.

The score, the Director, the Reviewer, the scope check, the verifier and the debrief are the real ones: the script only does what a person does (open a file, search, save, run the
tests, post in the channel, Submit). Because the browser's IDE is made by the person's own clicks, every action is also announced as an `autoplay_*` event that carries its data
(the file's text, the search result), so the screen can follow it without asking the server again (a second read would be a second `file_opened` in the evidence).

    autoplay_started  variant, speed, rate, t, total, labels, doc, tree, task
    autoplay_step     n, total, label, focus ("ide" | "chat" | "debrief")
    autoplay_open_file  path, content, writable, line (a deliberate open, or the IDE's own first file with `auto`)
    autoplay_search   q, result
    autoplay_edit     path, content, writable   (the new text of the file, before it is saved)
    autoplay_speed    speed, rate, t            (the session clock's rate changed: the timer follows it)
    autoplay_ended    reason ("done" | "stopped" | "error"), error

The session clock of an autoplay run is a `ScaledClock`: it runs `rate` times faster than real time (the weak run needs five quiet minutes before Aarav's nudge, and a viewer will not
wait for them), the 1x / 2x switch changes the rate while the run goes on, and everything that reads time (the rules, the Director, the timer) reads that one clock, so a run scores the same
at both speeds. Tests use a `VirtualClock` that moves only when the script says so.
"""
from __future__ import annotations

import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover
    from ..session import Session

ROLE = "backend"
FIX_FILES = ("backend/api/appointments.py", "backend/api/doctors.py")
REGRESSION_PATH = "tests/regression/test_regression_slot_at.py"
MIGRATION = "database/migrations/0007_rename_slot_time_to_slot_at.sql"
VARIANTS = ("strong", "weak")
CLOCK_FACTOR = {"strong": 1.0, "weak": 2.0}  # the weak run needs five quiet session minutes: its session clock runs twice as fast
SPEEDS = (1, 2)
REAL_TIMEOUT = 300.0  # seconds a single wait for the app (a test run, a reply) may take before the run gives up

HERE = Path(__file__).parent


def _data(scenario_id: str, name: str) -> Path:
    return HERE / scenario_id / "autoplay" / name


def regression_test(scenario_id: str = "opd-bookings-down") -> str:
    return _data(scenario_id, "regression_test.txt").read_text(encoding="utf-8")


def reference_fix(files: dict[str, str], scenario_id: str = "opd-bookings-down") -> dict[str, str]:
    """The reference fix applied to `files` (path -> current text): what the files must become. `git apply` of the scenario's own patch."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
        r = subprocess.run(["git", "apply", str(_data(scenario_id, "fix.patch"))], cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"the reference fix does not apply: {r.stderr.strip()[:300]}")
        return {rel: (root / rel).read_text(encoding="utf-8") for rel in files}


# -- clocks ---------------------------------------------------------------------------------------------------------

class ScaledClock:
    """Seconds of session time: real time times `rate`, integrated, so changing the rate never makes the clock jump or run back."""

    def __init__(self, speed: float = 1.0, factor: float = 1.0, base: Callable[[], float] = time.monotonic):
        self._base, self._factor, self._speed = base, factor, float(speed)
        self._t, self._last = 0.0, base()
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            now = self._base()
            self._t += (now - self._last) * self._factor * self._speed
            self._last = now
            return self._t

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def rate(self) -> float:
        return self._factor * self._speed

    def set_speed(self, speed: float) -> None:
        self()  # bring the clock up to date at the old rate first
        with self._lock:
            self._speed = float(speed)


class VirtualClock:
    """A clock that moves only when `advance` is called: a test plays a whole incident without waiting (the real time a test run takes does not count)."""

    def __init__(self) -> None:
        self._t = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._t

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._t += seconds

    speed = 1.0
    rate = 1.0

    def set_speed(self, speed: float) -> None:
        self.speed = float(speed)


class Stopped(Exception):
    """The viewer pressed Stop (or the session ended): the script ends quietly."""


# -- the script -------------------------------------------------------------------------------------------------------

class AutoplayRunner:
    """Plays `variant` ("strong" | "weak") in `session`, a live scenario session whose clock is `clock`."""

    def __init__(self, session: "Session", variant: str, clock, speed: float = 1.0):
        if variant not in VARIANTS:
            raise ValueError(f"unknown variant {variant!r}")
        self.session, self.variant, self.clock, self.speed = session, variant, clock, float(speed)
        self.virtual = isinstance(clock, VirtualClock)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = "starting"  # starting | running | done | stopped | error
        self.error = ""
        self.task = ""
        self.files: dict[str, str] = {}  # what the script has read or written, path -> text
        self.tree: dict = {}
        self.step_no = 0
        self.steps = self._strong() if variant == "strong" else self._weak()

    # -- life ----------------------------------------------------------------------
    @property
    def orch(self):
        return self.session.orch

    def start(self) -> "AutoplayRunner":
        self._thread = threading.Thread(target=self._run, name=f"autoplay-{self.session.id}", daemon=True)
        self._thread.start()
        return self

    def stop(self, wait: float = 20.0) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(wait)

    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def set_speed(self, speed: float) -> None:
        if speed not in SPEEDS:
            raise ValueError("the speed is 1 or 2")
        self.speed = float(speed)
        self.clock.set_speed(self.speed)
        self.emit("autoplay_speed", speed=self.speed, rate=self.clock.rate, t=round(self.clock(), 2))

    def emit(self, type_: str, **fields):
        return self.session.bus.emit(type_, **fields)

    # -- waiting: in session time, so a speed or a clock change never changes what the run does ------------
    def _check(self) -> None:
        if self._stop.is_set() or self.session._stop.is_set():
            raise Stopped()

    def pause(self, seconds: float) -> None:
        """Wait `seconds` of session time (a viewer's pace)."""
        end = self.clock() + seconds
        while self.clock() < end:
            self._check()
            if self.virtual:
                self.clock.advance(min(end - self.clock(), 5.0))
                self._tick()
            else:
                time.sleep(0.05)

    def _tick(self) -> None:
        director = getattr(self.orch, "director", None)
        if director is not None:
            director.tick()  # a virtual clock has no one ticking the Director's own thread in step with it
        time.sleep(0.01)

    def until(self, ready: Callable[[], object], what: str, session_limit: float | None = None):
        """Wait until `ready()` is truthy (events from the app); a virtual clock is advanced while waiting only when `session_limit` says time itself is what is awaited."""
        end = time.monotonic() + REAL_TIMEOUT
        start = self.clock()
        while True:
            self._check()
            got = ready()
            if got:
                return got
            if session_limit is not None and self.clock() - start > session_limit:
                raise TimeoutError(f"timed out waiting for {what}")
            if session_limit is None and time.monotonic() > end:
                raise TimeoutError(f"timed out waiting for {what}")
            if self.virtual and session_limit is not None:
                self.clock.advance(5.0)
                self._tick()
            else:
                time.sleep(0.05)

    def events(self, type_: str) -> list[dict]:
        return [e for e in list(self.session.bus.history) if e["type"] == type_]

    # -- the learner's actions ----------------------------------------------------------------
    def open_file(self, path: str, *, auto: bool = False, line: int | None = None) -> str:
        out = self.session.ide_read(ROLE, path, auto)
        self.files[path] = out["content"]
        writable = any(f["path"] == path and f.get("writable") for f in self.tree.get("files", []))
        self.emit("autoplay_open_file", path=path, content=out["content"], writable=writable, **({"line": line} if line else {}))
        return out["content"]

    def search(self, query: str) -> dict:
        result = self.session.ide_search(ROLE, query)
        self.emit("autoplay_search", q=query, result=result)
        return result

    def save(self, path: str, content: str) -> None:
        """The script types the new text (shown in the editor, unsaved), pauses, and saves it: the same PUT the editor's Save makes."""
        self.emit("autoplay_edit", path=path, content=content, writable=True)
        self.pause(3)
        self.session.ide_write(ROLE, path, content)
        self.files[path] = content
        self.pause(2)

    def run_tests(self, what: str = "the tests") -> dict:
        n = len(self.events("human_test_result"))
        self.session.ide_run_tests(ROLE)
        result = self.until(lambda: next(iter(self.events("human_test_result")[n:]), None), what)
        self.pause(4)  # the viewer reads the result
        return result

    def post(self, text: str, to: str | None = None) -> dict:
        out = self.session.channel_post(text, to)
        self.pause(3)
        return out

    def submit(self, retries: int = 3) -> dict:
        answer: dict = {}
        for _ in range(retries + 1):
            self._check()
            answer = self.session.submit_task(self.task)
            self.pause(4)
            if answer.get("ok") or answer.get("stage") != "review":  # only a send-back from the Reviewer is worth another try
                break
        return answer

    def nudge_seen(self) -> bool:
        return any(m.get("ref") == "lead-nudge" for m in list(self.orch.director.messages))

    # -- the two runs ---------------------------------------------------------------------------
    def _strong(self) -> list[tuple[str, str, Callable[[], None]]]:
        def reproduce() -> None:
            self.pause(6)
            self.post("On it. I am running the tests first to see the failure myself, then I will report what I find.")  # the first update, well inside the 2 minutes
            self.run_tests("the first test run")

        def search() -> None:
            self.search("slot_time")
            self.pause(6)

        def read() -> None:
            self.open_file("backend/api/appointments.py")
            self.pause(5)
            self.open_file(MIGRATION)
            self.pause(5)
            self.open_file("backend/api/doctors.py")
            self.pause(4)

        def tell() -> None:
            self.post("Update: the booking routes still say slot_time, but migration 0007 renamed the column to slot_at. I am fixing both routes now.")
            self.pause(2)

        def regression() -> None:
            self.save(REGRESSION_PATH, regression_test())
            self.run_tests("the regression test, red")

        def fix() -> None:
            fixed = reference_fix({p: self.files[p] for p in FIX_FILES})
            for path in FIX_FILES:
                self.save(path, fixed[path])

        def green() -> None:
            self.run_tests("the green run")

        def report() -> None:
            self.post("Fix is ready: both routes use slot_at and a regression test covers it. Submitting now.")

        return [("Say you are on it, run the tests: they fail", "ide", reproduce), ("Search for slot_time", "ide", search),
                ("Open the routes and migration 0007", "ide", read), ("Tell the team what was found", "chat", tell),
                ("Add a regression test that fails on the bug", "ide", regression), ("Fix both routes", "ide", fix),
                ("Run the tests: green", "ide", green), ("Tell the team the fix is ready", "chat", report),
                ("Submit for review", "ide", self._finish_submit)]

    def _weak(self) -> list[tuple[str, str, Callable[[], None]]]:
        def first_edit() -> None:
            self.pause(8)
            appointments = self.open_file("backend/api/appointments.py", auto=True)
            self.pause(6)
            fixed = reference_fix({"backend/api/appointments.py": appointments, "backend/api/doctors.py": self._read_quiet("backend/api/doctors.py")})
            self.save("backend/api/appointments.py", fixed["backend/api/appointments.py"])
            self.fixed = fixed

        def silence() -> None:
            self.until(self.nudge_seen, "Aarav's nudge", session_limit=900)  # no update, no test run: the team has to ask
            self.pause(6)

        def reply() -> None:
            self.post("Sorry, I am still working on it.")

        def red_submit() -> None:
            answer = self.session.submit_task(self.task)
            self.pause(5)
            if answer.get("ok"):
                raise RuntimeError("the weak run's first submit was accepted; the script expects it to fail")

        def ask() -> None:
            n = len([m for m in list(self.orch.director.messages) if m.get("from") == "database" and m.get("reply_to")])
            self.post("Karan, can you help? I do not know what else could be broken.", "database")
            self.until(lambda: len([m for m in list(self.orch.director.messages) if m.get("from") == "database" and m.get("reply_to")]) > n, "Karan's reply")
            self.pause(5)

        def second_file() -> None:
            self.open_file("backend/api/doctors.py")
            self.pause(4)
            self.save("backend/api/doctors.py", self.fixed["backend/api/doctors.py"])

        return [("Edit the first file without running the tests", "ide", first_edit), ("No update, no tests: nobody hears from the engineer", "chat", silence),
                ("Answer Aarav after the nudge", "chat", reply), ("Submit: the tests fail", "ide", red_submit), ("Ask Karan for help", "chat", ask),
                ("Fix the second route", "ide", second_file), ("Submit again", "ide", self._finish_submit)]

    fixed: dict[str, str] = {}

    def _read_quiet(self, path: str) -> str:
        """The text of a file the script needs but does not show opening (read from the worktree, not through the IDE, so nothing is logged)."""
        wt = self.orch._ide_worktree(ROLE)
        return (Path(wt) / path).read_text(encoding="utf-8")

    def _finish_submit(self) -> None:
        answer = self.submit()
        if not (answer.get("ok") and answer.get("stage") == "accepted"):
            raise RuntimeError(f"the submit was not accepted: {answer.get('stage')} {answer.get('summary', '')}"[:200])

    # -- the run ------------------------------------------------------------------------------
    def _run(self) -> None:
        reason = "done"
        try:
            self.state = "running"
            task = self.until(lambda: next(iter(self.events("human_task_assigned")), None), "the task to be handed over")
            self.task = task["task"]
            self.tree = self.session.ide_tree(ROLE)
            labels = [s[0] for s in self.steps] + ["The debrief meeting and the report"]
            self.emit("autoplay_started", variant=self.variant, speed=self.speed, rate=self.clock.rate, t=round(self.clock(), 2), total=len(labels), labels=labels,
                      task=self.task, doc=self._doc(), tree=self.tree)
            for n, (label, focus, fn) in enumerate(self.steps, 1):
                self.step_no = n
                self.emit("autoplay_step", n=n, total=len(labels), label=label, focus=focus)
                fn()
            self.step_no = len(labels)
            self.emit("autoplay_step", n=len(labels), total=len(labels), label=labels[-1], focus="debrief")
            self.until(lambda: self.events("debrief_ended"), "the debrief to end")
            self.state = "done"
        except Stopped:
            self.state, reason = "stopped", "stopped"
        except Exception as e:  # a script that cannot go on says so and ends: the session stays as it is
            self.state, reason, self.error = "error", "error", f"{type(e).__name__}: {e}"[:300]
        finally:
            self.emit("autoplay_ended", reason=reason, **({"error": self.error} if self.error else {}))

    def _doc(self) -> str:
        try:
            return self.session.task_doc(self.task)
        except Exception:
            return ""
