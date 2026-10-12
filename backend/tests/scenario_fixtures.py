"""Two recorded sessions of the Bookings-are-down incident (what the log of a strong run and of a weak run looks like), built through the real SessionLog so ids and times
are what a session produces. The scores are worked out by hand in the comments and checked in test_scenario_scoring.py."""
from __future__ import annotations

from app.scenarios.scoring import Facts
from app.scenarios.sessionlog import SessionLog

from scenario_helpers import FakeClock

APPT, DOCT = "backend/api/appointments.py", "backend/api/doctors.py"
MIGRATION = "database/migrations/0007_rename_slot_time_to_slot_at.sql"
REGRESSION = "tests/regression/test_regression_slot_at.py"
QA_REPORT = "Booking is down. POST /api/doctors/{id}/appointments returns 500 for every patient. The server log says: TypeError: add_appointment() got an unexpected keyword argument 'slot_time'."


def make_log(steps: list[tuple[float, str, dict]]) -> list[dict]:
    clock = FakeClock()
    log = SessionLog(clock)
    for t, kind, fields in steps:
        clock.t = 1000.0 + t
        log.add(kind, **fields)
    return log.events()


def team(ref: str, who: str, text: str) -> dict:
    return {"message": "C000", "from": who, "text": text, "source": "scripted", "ref": ref}


SUBMIT_OK = {"task": "h1", "ok": True, "stage": "accepted", "summary": "all tests pass; the Reviewer passed it", "failed": [], "review_items": 0}

# Every point: reproduced, read the route and the migration, told the team, regression test red then green, small fix, green run, closing post, no hints.
STRONG = [
    (0, "session_started", {"scenario": "opd-bookings-down", "role": "backend"}),
    (3, "team_message", team("qa-report", "qa", QA_REPORT)),
    (20, "test_run", {"task": "h1", "trigger": "ide"}),
    (26, "test_result", {"task": "h1", "ok": False, "passed": 89, "failed": ["tests/api/test_booking.py::test_booking_an_appointment_returns_201"], "summary": "12 failed, 89 passed in 4.1s", "trigger": "ide"}),
    (40, "file_opened", {"role": "backend", "path": APPT}),
    (48, "file_opened", {"role": "backend", "path": MIGRATION}),
    (55, "message_posted", {"message": "C002", "text": "Update: bookings fail since Monday's deploy. The routes still call slot_time but migration 0007 renamed it to slot_at. Fixing now.", "to": []}),
    (100, "file_saved", {"role": "backend", "path": REGRESSION, "added": 12, "removed": 0, "size": 600}),
    (105, "test_run", {"task": "h1", "trigger": "ide"}),
    (110, "test_result", {"task": "h1", "ok": False, "passed": 89, "failed": [REGRESSION + "::test_booking_an_appointment_still_works_after_the_column_rename"], "summary": "13 failed, 89 passed in 4.3s", "trigger": "ide"}),
    (130, "file_saved", {"role": "backend", "path": APPT, "added": 4, "removed": 4, "size": 4000}),
    (140, "file_saved", {"role": "backend", "path": DOCT, "added": 1, "removed": 1, "size": 3000}),
    (150, "test_run", {"task": "h1", "trigger": "ide"}),
    (156, "test_result", {"task": "h1", "ok": True, "passed": 102, "failed": [], "summary": "102 passed in 4.4s", "trigger": "ide"}),
    (170, "message_posted", {"message": "C003", "text": "Fix is ready: both route files use slot_at now and a regression test covers it. Submitting.", "to": []}),
    (180, "submit", {"task": "h1"}),
    (181, "test_run", {"task": "h1", "trigger": "submit"}),
    (188, "test_result", {"task": "h1", "ok": True, "passed": 102, "failed": [], "summary": "102 passed in 4.4s", "trigger": "submit"}),
    (190, "submit_result", SUBMIT_OK),
    (190, "session_finished", {"ok": True}),
]
STRONG_FACTS = {"old_name_files": [], "rerun": {"ok": True, "passed": 102, "failed": 0, "summary": "102 passed"}, "regression": {"path": REGRESSION, "fails_on_seed": True, "passes_on_main": True}}
STRONG_SCORES = {"communication": 4, "diagnosis": 4, "fix_quality": 4, "testing": 4, "ownership": 4}  # 100

# No test run and nothing opened before the first edit, late and empty updates, nudged, two hints, comment lines left on the old name, a red submit, a send-back.
WEAK = [
    (0, "session_started", {"scenario": "opd-bookings-down", "role": "backend"}),
    (3, "team_message", team("qa-report", "qa", QA_REPORT)),
    (10, "file_opened", {"role": "backend", "path": APPT, "auto": True}),
    (60, "file_saved", {"role": "backend", "path": APPT, "added": 2, "removed": 2, "size": 4000}),
    (90, "team_message", team("lead-update", "architect", "Any update on the booking failure? Please post what you have found so far in this channel, even if it is only 'still looking'.")),
    (240, "team_message", team("db-pointer", "database", "Heads up from me: Monday's migration 0007 renamed appointments.slot_time to slot_at.")),
    (240, "hint_given", {"message": "C004", "from": "database", "source": "scripted", "reason": "timeline", "question": "", "text": "Heads up from me: Monday's migration 0007 renamed appointments.slot_time to slot_at.", "n": 1}),
    (300, "team_message", team("lead-nudge", "architect", "No update from you for 5 minutes. Where are we on the booking fix? The desk is still on paper.")),
    (330, "message_posted", {"message": "C005", "text": "ok still on it", "to": []}),
    (360, "file_opened", {"role": "backend", "path": MIGRATION}),
    (400, "file_saved", {"role": "backend", "path": DOCT, "added": 1, "removed": 1, "size": 3000}),
    (420, "test_run", {"task": "h1", "trigger": "ide"}),
    (428, "test_result", {"task": "h1", "ok": False, "passed": 99, "failed": ["tests/api/test_booking.py::test_editing_an_appointment_moves_its_time"], "summary": "3 failed, 99 passed in 4.0s", "trigger": "ide"}),
    (470, "submit", {"task": "h1"}),
    (471, "test_run", {"task": "h1", "trigger": "submit"}),
    (478, "test_result", {"task": "h1", "ok": False, "passed": 99, "failed": ["tests/api/test_booking.py::test_editing_an_appointment_moves_its_time"], "summary": "3 failed, 99 passed in 4.0s", "trigger": "submit"}),
    (480, "submit_result", {"task": "h1", "ok": False, "stage": "tests", "summary": "3 tests still fail", "failed": ["tests/api/test_booking.py::test_editing_an_appointment_moves_its_time"], "review_items": 0}),
    (500, "team_message", team("m6", "database", "I did not touch backend/. Have a look at database/migrations/0007.")),
    (500, "hint_given", {"message": "C006", "from": "database", "source": "live", "reason": "", "question": "what changed in the table?", "text": "I did not touch backend/. Have a look at database/migrations/0007.", "n": 2}),
    (560, "file_saved", {"role": "backend", "path": APPT, "added": 1, "removed": 1, "size": 4001}),
    (600, "submit", {"task": "h1"}),
    (601, "test_run", {"task": "h1", "trigger": "submit"}),
    (608, "test_result", {"task": "h1", "ok": True, "passed": 102, "failed": [], "summary": "102 passed in 4.4s", "trigger": "submit"}),
    (620, "submit_result", {"task": "h1", "ok": False, "stage": "review", "summary": "the Reviewer asked for 1 change", "failed": [], "review_items": 1}),
    (700, "submit", {"task": "h1"}),
    (701, "test_run", {"task": "h1", "trigger": "submit"}),
    (708, "test_result", {"task": "h1", "ok": True, "passed": 102, "failed": [], "summary": "102 passed in 4.4s", "trigger": "submit"}),
    (720, "submit_result", SUBMIT_OK),
    (720, "session_finished", {"ok": True}),
]
WEAK_FACTS = {"old_name_files": [APPT], "rerun": {"ok": True, "passed": 102, "failed": 0, "summary": "102 passed"}, "regression": None}
WEAK_SCORES = {"communication": 0, "diagnosis": 0, "fix_quality": 2, "testing": 0, "ownership": 2}  # 20


def facts(steps: list[tuple[float, str, dict]], extra: dict, minutes: int = 25) -> Facts:
    return Facts(make_log(steps), minutes=minutes, **extra)
