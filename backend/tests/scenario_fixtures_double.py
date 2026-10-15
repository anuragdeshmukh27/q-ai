"""Two recorded sessions of the "Double bookings" incident (a strong run and a weak run), built through the real SessionLog like scenario_fixtures.py.
The scores are worked out by hand in the comments and checked in test_scenario_double_bookings_scoring.py."""
from __future__ import annotations

from app.scenarios.scoring import Facts

from scenario_fixtures import SUBMIT_OK, make_log, team

SNAPSHOT = "fixtures/prod_snapshot.sql"
M0006 = "database/migrations/0006_index_appointments_by_doctor_and_slot.sql"
NEW = "database/migrations/0008_one_booking_per_slot.sql"
REGRESSION = "tests/regression/test_regression_double_booking.py"
QA_REPORT = "Double bookings. Two patients were booked with the same doctor at the same date and time. I found three slots in the production snapshot."

# what the debrief measures on a migration that does everything right / the delete-the-duplicates migration
MEASURED_OK = {
    "rows_kept": {"text": "Debrief upgrade of the production snapshot: 30 of 30 appointments are still there", "ok": True, "error": "", "lost": []},
    "duplicates": {"text": "Debrief check of the 3 double-booked slots: 3 keep their earliest booking, 3 of 3 later bookings are cancelled, 3 of 3 say why", "ok": True, "error": "", "slots": 3,
                   "cancelled": 3, "later": 3, "reasons": 3, "earliest_kept": True, "still_double": False},
    "unique_index": {"text": "Debrief check of the index: unique over doctor_id, date and slot_at for Booked rows only; a second Booked row is refused, a Cancelled one is allowed", "ok": True,
                     "error": "", "unique": True, "partial": True, "name": "idx_appointments_one_booking_per_slot", "refuses_second_booked": True, "allows_cancelled": True},
}

# Every point: tests first, the data and the migration read, told the team what is missing, a regression test red then green, the migration, green run, closing post, no hints.
STRONG = [
    (0, "session_started", {"scenario": "opd-double-bookings", "role": "database"}),
    (3, "team_message", team("qa-report", "qa", QA_REPORT)),
    (8, "message_posted", {"message": "C002", "text": "On it: running the tests first, then I look at the data.", "to": []}),
    (20, "test_run", {"task": "h1", "trigger": "ide"}),
    (26, "test_result", {"task": "h1", "ok": False, "passed": 105, "failed": ["tests/db/test_double_bookings.py::test_duplicate_bookings_are_cancelled_not_deleted"], "summary": "5 failed, 105 passed in 6.1s", "trigger": "ide"}),
    (35, "search", {"role": "database", "query": "UNIQUE", "matches": 4, "files": 3}),
    (45, "file_opened", {"role": "database", "path": SNAPSHOT}),
    (55, "file_opened", {"role": "database", "path": M0006}),
    (65, "message_posted", {"message": "C003", "text": "Update: nothing in the database stops a second Booked row: migration 0006 only made a plain index. Three slots already hold duplicates.", "to": []}),
    (100, "file_saved", {"role": "database", "path": REGRESSION, "added": 14, "removed": 0, "size": 900, "created": True}),
    (105, "test_run", {"task": "h1", "trigger": "ide"}),
    (110, "test_result", {"task": "h1", "ok": False, "passed": 105, "failed": [REGRESSION + "::test_booking_the_same_slot_twice_is_refused_with_409"], "summary": "6 failed, 105 passed in 6.3s", "trigger": "ide"}),
    (130, "file_saved", {"role": "database", "path": NEW, "added": 20, "removed": 0, "size": 1200, "created": True}),
    (150, "test_run", {"task": "h1", "trigger": "ide"}),
    (156, "test_result", {"task": "h1", "ok": True, "passed": 111, "failed": [], "summary": "111 passed in 6.4s", "trigger": "ide"}),
    (170, "message_posted", {"message": "C004", "text": "Fix is ready: migration 0008 cancels the later duplicates and adds the partial unique index. Submitting.", "to": []}),
    (180, "submit", {"task": "h1"}),
    (181, "test_run", {"task": "h1", "trigger": "submit"}),
    (188, "test_result", {"task": "h1", "ok": True, "passed": 111, "failed": [], "summary": "111 passed in 6.4s", "trigger": "submit"}),
    (190, "submit_result", SUBMIT_OK),
    (190, "session_finished", {"ok": True}),
]
STRONG_FACTS = {"scan": None, "measured": MEASURED_OK, "rerun": {"ok": True, "passed": 111, "failed": 0, "summary": "111 passed"},
                "regression": {"path": REGRESSION, "fails_on_seed": True, "passes_on_main": True}}
STRONG_SCORES = {"communication": 4, "diagnosis": 4, "fix_quality": 4, "testing": 4, "ownership": 4}  # 100

# The weak run: edits a naive migration first (no test run, nothing read), no update until Aarav nudges, a late post that does name the duplicates, a red submit, a question to Rohan,
# the migration rewritten, accepted at the second submit with no regression test and no green run of its own.
WEAK = [
    (0, "session_started", {"scenario": "opd-double-bookings", "role": "database"}),
    (3, "team_message", team("qa-report", "qa", QA_REPORT)),
    (40, "file_saved", {"role": "database", "path": NEW, "added": 3, "removed": 0, "size": 300, "created": True}),
    (90, "team_message", team("lead-update", "architect", "Any update on the double bookings? Please post what you have found so far.")),
    (240, "team_message", team("backend-pointer", "backend", "Heads up from me: nothing in backend/ checks for a taken slot.")),
    (240, "hint_given", {"message": "C004", "from": "backend", "source": "scripted", "reason": "timeline", "question": "", "text": "Heads up from me: nothing in backend/ checks for a taken slot.", "n": 1}),
    (300, "team_message", team("lead-nudge", "architect", "No update from you for 5 minutes. Where are we on the double bookings?")),
    (330, "message_posted", {"message": "C005", "text": "Sorry, still working on it. I think I need to remove the duplicate rows.", "to": []}),
    (400, "submit", {"task": "h1"}),
    (401, "test_run", {"task": "h1", "trigger": "submit"}),
    (408, "test_result", {"task": "h1", "ok": False, "passed": 107, "failed": ["tests/db/test_double_bookings.py::test_duplicate_bookings_are_cancelled_not_deleted"], "summary": "3 failed, 107 passed in 6.0s", "trigger": "submit"}),
    (410, "submit_result", {"task": "h1", "ok": False, "stage": "tests", "summary": "3 tests still fail", "failed": ["tests/db/test_double_bookings.py::test_duplicate_bookings_are_cancelled_not_deleted"], "review_items": 0}),
    (440, "team_message", team("m6", "backend", "The route only inserts the row; the rule belongs in the database.")),
    (440, "hint_given", {"message": "C006", "from": "backend", "source": "live", "reason": "", "question": "what else could be wrong?", "text": "The route only inserts the row; the rule belongs in the database.", "n": 2}),
    (500, "file_saved", {"role": "database", "path": NEW, "added": 20, "removed": 0, "size": 1200, "created": False}),
    (560, "submit", {"task": "h1"}),
    (561, "test_run", {"task": "h1", "trigger": "submit"}),
    (568, "test_result", {"task": "h1", "ok": True, "passed": 110, "failed": [], "summary": "110 passed in 6.2s", "trigger": "submit"}),
    (570, "submit_result", SUBMIT_OK),
    (570, "session_finished", {"ok": True}),
]
WEAK_FACTS = {"scan": None, "measured": MEASURED_OK, "rerun": {"ok": True, "passed": 110, "failed": 0, "summary": "110 passed"}, "regression": None}
WEAK_SCORES = {"communication": 1, "diagnosis": 0, "fix_quality": 4, "testing": 0, "ownership": 2}  # 35


def facts(steps: list[tuple[float, str, dict]], extra: dict, minutes: int = 30) -> Facts:
    return Facts(make_log(steps), minutes=minutes, **extra)
