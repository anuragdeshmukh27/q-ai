"""The scripted learners of the scenarios ("Watch a run"): for each scenario a strong run and a weak run, as lists of (label, where the screen looks, what to do).

The runner (`autoplay.AutoplayRunner`) owns everything a person can do (open a file, search, save, run the tests, post, Submit) and the waiting; a script only says which of those
to do, in which order, with which text. Scores are the rubric's own: a script is written to play a run, and the test of each scenario asserts the exact score it gets.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover
    from .autoplay import AutoplayRunner

Step = tuple[str, str, Callable[[], None]]


class Script:
    """Base of a scenario's script: `strong()` and `weak()` return the steps."""

    def __init__(self, r: "AutoplayRunner"):
        self.r = r

    def strong(self) -> list[Step]:  # pragma: no cover
        raise NotImplementedError

    def weak(self) -> list[Step]:  # pragma: no cover
        raise NotImplementedError


class BookingsDownScript(Script):
    """"Production incident: Bookings are down" (the backend engineer): the two routes still say the old column name."""

    FIX_FILES = ("backend/api/appointments.py", "backend/api/doctors.py")
    REGRESSION_PATH = "tests/regression/test_regression_slot_at.py"
    MIGRATION = "database/migrations/0007_rename_slot_time_to_slot_at.sql"

    fixed: dict[str, str]

    def __init__(self, r: "AutoplayRunner"):
        super().__init__(r)
        self.fixed = {}

    def strong(self) -> list[Step]:
        from .autoplay import reference_fix, regression_test
        r = self.r

        def reproduce() -> None:
            r.pause(6)
            r.post("On it. I am running the tests first to see the failure myself, then I will report what I find.")  # the first update, well inside the 2 minutes
            r.run_tests("the first test run")

        def search() -> None:
            r.search("slot_time")
            r.pause(10)

        def read() -> None:
            r.open_file("backend/api/appointments.py")
            r.pause(8)
            r.open_file(self.MIGRATION)
            r.pause(8)
            r.open_file("backend/api/doctors.py")
            r.pause(6)

        def tell() -> None:
            r.post("Update: the booking routes still say slot_time, but migration 0007 renamed the column to slot_at. I am fixing both routes now.")
            r.pause(6)

        def regression() -> None:
            r.save(self.REGRESSION_PATH, regression_test(r.scenario_id))
            r.run_tests("the regression test, red")

        def fix() -> None:
            fixed = reference_fix({p: r.files[p] for p in self.FIX_FILES}, r.scenario_id)
            for path in self.FIX_FILES:
                r.save(path, fixed[path])

        def green() -> None:
            r.run_tests("the green run")

        def report() -> None:
            r.post("Fix is ready: both routes use slot_at and a regression test covers it. Submitting now.")

        return [("Say you are on it, run the tests: they fail", "ide", reproduce), ("Search for slot_time", "ide", search),
                ("Open the routes and migration 0007", "ide", read), ("Tell the team what was found", "chat", tell),
                ("Add a regression test that fails on the bug", "ide", regression), ("Fix both routes", "ide", fix),
                ("Run the tests: green", "ide", green), ("Tell the team the fix is ready", "chat", report),
                ("Submit for review", "ide", r.finish_submit)]

    def weak(self) -> list[Step]:
        from .autoplay import reference_fix
        r = self.r

        def first_edit() -> None:
            r.pause(8)
            appointments = r.open_file("backend/api/appointments.py", auto=True)
            r.pause(6)
            fixed = reference_fix({"backend/api/appointments.py": appointments, "backend/api/doctors.py": r.read_quiet("backend/api/doctors.py")}, r.scenario_id)
            r.save("backend/api/appointments.py", fixed["backend/api/appointments.py"])
            self.fixed = fixed

        def silence() -> None:
            r.until(r.nudge_seen, "Aarav's nudge", session_limit=900)  # no update, no test run: the team has to ask
            r.pause(6)

        def reply() -> None:
            r.post("Sorry, I am still working on it.")

        def red_submit() -> None:
            answer = r.session.submit_task(r.task)
            r.pause(5)
            if answer.get("ok"):
                raise RuntimeError("the weak run's first submit was accepted; the script expects it to fail")

        def ask() -> None:
            n = r.replies_from("database")
            r.post("Karan, can you help? I do not know what else could be broken.", "database")
            r.until(lambda: r.replies_from("database") > n, "Karan's reply")
            r.pause(5)

        def second_file() -> None:
            r.open_file("backend/api/doctors.py")
            r.pause(4)
            r.save("backend/api/doctors.py", self.fixed["backend/api/doctors.py"])

        return [("Edit the first file without running the tests", "ide", first_edit), ("No update, no tests: nobody hears from the engineer", "chat", silence),
                ("Answer Aarav after the nudge", "chat", reply), ("Submit: the tests fail", "ide", red_submit), ("Ask Karan for help", "chat", ask),
                ("Fix the second route", "ide", second_file), ("Submit again", "ide", r.finish_submit)]


class DoubleBookingsScript(Script):
    """"Double bookings" (the database engineer): nothing in the database stops a second Booked row for a slot, and three slots already hold two."""

    ID = "opd-double-bookings"
    MIGRATION = "database/migrations/0008_one_booking_per_slot.sql"
    REGRESSION_PATH = "tests/regression/test_regression_double_booking.py"
    SNAPSHOT = "fixtures/prod_snapshot.sql"
    INDEX_MIGRATION = "database/migrations/0006_index_appointments_by_doctor_and_slot.sql"

    def _reference(self) -> str:
        from .autoplay import reference_fix
        return reference_fix({}, self.ID, create=(self.MIGRATION,))[self.MIGRATION]

    def strong(self) -> list[Step]:
        from .autoplay import regression_test
        r = self.r

        def reproduce() -> None:
            r.pause(6)
            r.post("On it. I am running the tests first, then I will look at the data and report what I find.")  # the first update, well inside the 2 minutes
            r.run_tests("the first test run")

        def search() -> None:
            r.search("UNIQUE")
            r.pause(10)

        def read() -> None:
            r.open_file(self.SNAPSHOT)
            r.pause(10)
            r.open_file(self.INDEX_MIGRATION)
            r.pause(8)

        def tell() -> None:
            r.post("Update: three slots already hold two Booked appointments each, and migration 0006 only made a plain index, so nothing in the database stops a second booking. "
                   "I will write migration 0008: cancel the later duplicates (no row deleted) and add a partial unique index.")
            r.pause(6)

        def regression() -> None:
            r.save(self.REGRESSION_PATH, regression_test(self.ID))
            r.run_tests("the regression test, red")

        def fix() -> None:
            r.save(self.MIGRATION, self._reference())

        def green() -> None:
            r.run_tests("the green run")

        def report() -> None:
            r.post("Fix is ready: migration 0008 cancels the later duplicates, keeps every row and adds the partial unique index. Submitting now.")

        return [("Say you are on it, run the tests: they fail", "ide", reproduce), ("Search for UNIQUE", "ide", search),
                ("Open the data and the migration that made the index", "ide", read), ("Tell the team what is missing", "chat", tell),
                ("Add a regression test: book a slot twice", "ide", regression), ("Write migration 0008", "ide", fix),
                ("Run the tests: green", "ide", green), ("Tell the team the fix is ready", "chat", report),
                ("Submit for review", "ide", r.finish_submit)]

    def weak(self) -> list[Step]:
        from .autoplay import _data
        r = self.r

        def first_edit() -> None:
            r.pause(8)
            r.open_file("database/appointments.py", auto=True)
            r.pause(6)
            r.save(self.MIGRATION, _data(self.ID, "naive_0008.sql").read_text(encoding="utf-8"))  # delete the duplicates and add the index, without a test run or a look at the data

        def silence() -> None:
            r.until(r.nudge_seen, "Aarav's nudge", session_limit=900)  # no update, no test run: the team has to ask
            r.pause(6)

        def reply() -> None:
            r.post("Sorry, still working on it. I think I need to remove the duplicate rows.")

        def red_submit() -> None:
            answer = r.session.submit_task(r.task)
            r.pause(5)
            if answer.get("ok"):
                raise RuntimeError("the weak run's first submit was accepted; the script expects it to fail")

        def ask() -> None:
            n = r.replies_from("backend")
            r.post("Rohan, can you help? I do not know what else the database needs.", "backend")
            r.until(lambda: r.replies_from("backend") > n, "Rohan's reply")
            r.pause(5)

        def rewrite() -> None:
            r.pause(4)
            r.save(self.MIGRATION, self._reference())

        return [("Write a migration without running the tests or looking at the data", "ide", first_edit), ("No update, no tests: nobody hears from the engineer", "chat", silence),
                ("Answer Aarav after the nudge", "chat", reply), ("Submit: the tests fail", "ide", red_submit), ("Ask Rohan for help", "chat", ask),
                ("Rewrite the migration", "ide", rewrite), ("Submit again", "ide", r.finish_submit)]


SCRIPTS: dict[str, type[Script]] = {"opd-bookings-down": BookingsDownScript, "opd-double-bookings": DoubleBookingsScript}


def script_for(scenario_id: str, runner: "AutoplayRunner") -> Script:
    try:
        return SCRIPTS[scenario_id](runner)
    except KeyError:
        raise ValueError(f"scenario {scenario_id!r} has no scripted run") from None
