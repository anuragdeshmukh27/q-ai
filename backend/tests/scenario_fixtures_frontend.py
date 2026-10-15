"""Two recorded sessions of the "The form says it saved" incident (a strong run and a weak run), built through the real SessionLog like scenario_fixtures.py.
The scores are worked out by hand in the comments and checked in test_scenario_form_says_saved_scoring.py."""
from __future__ import annotations

from app.scenarios.scoring import Facts

from scenario_fixtures import SUBMIT_OK, make_log, team

API_TEST = "tests/api/test_double_booking_api.py"
MAIN = "backend/main.py"
SHELL = "static/shell.js"
REGRESSION = "tests/regression/test_regression_refusals.py"
QA_REPORT = "The booking form says it saved when it did not. Steps: Appointments, + New appointment, Dr. Farhan Ali, 15 Oct 2026, 11:00 (already booked for Sana Sheikh)."
CAUSE = ("Update: the server is right, it answers 409 with a message. The page is wrong: call() in static/shell.js only throws when the answer has no body, "
         "so a 409 with a detail is treated as a success and every form and button says it saved.")

# what the debrief measures on a page that does everything right (the real measure's own texts: a test compares them)
PATHS_OK = "Debrief check of the pages: all 8 refused requests (the booking form, an edit, Complete or Cancel, a delete, a board move, and the doctor and prescription forms) show an error and none says it saved"
MESSAGE_OK = "Debrief check of the messages: in all 8 cases the server's own message is what the person reads"
MEASURED_OK = {
    "refusal_paths": {"text": PATHS_OK, "ok": True, "passed": 8, "of": 8, "failed": []},
    "refusal_message": {"text": MESSAGE_OK, "ok": True, "passed": 8, "of": 8, "failed": []},
}

# Every point: tests first (red), the server's answer and the page code read, told the team what is wrong, a regression test red then green, a one-line fix, green run, closing post, no hints.
STRONG = [
    (0, "session_started", {"scenario": "opd-form-says-saved", "role": "frontend"}),
    (3, "team_message", team("qa-report", "qa", QA_REPORT)),
    (8, "message_posted", {"message": "C002", "text": "On it: running the tests first, then I read what the server answers.", "to": []}),
    (20, "test_run", {"task": "h1", "trigger": "ide"}),
    (28, "test_result", {"task": "h1", "ok": False, "passed": 114, "failed": ["tests/ui/test_refusals.py::test_a_taken_slot_keeps_the_booking_form_open_and_says_why"], "summary": "6 failed, 114 passed in 8.1s", "trigger": "ide"}),
    (35, "search", {"role": "frontend", "query": "409", "matches": 6, "files": 4}),
    (45, "file_opened", {"role": "frontend", "path": API_TEST}),
    (55, "file_opened", {"role": "frontend", "path": MAIN}),
    (68, "file_opened", {"role": "frontend", "path": SHELL}),
    (80, "message_posted", {"message": "C003", "text": CAUSE + " I will fix call().", "to": []}),
    (100, "file_saved", {"role": "frontend", "path": REGRESSION, "added": 16, "removed": 0, "size": 900, "created": True}),
    (105, "test_run", {"task": "h1", "trigger": "ide"}),
    (112, "test_result", {"task": "h1", "ok": False, "passed": 114, "failed": [REGRESSION + "::test_a_refused_request_is_an_error_on_the_page"], "summary": "7 failed, 114 passed in 8.3s", "trigger": "ide"}),
    (130, "file_saved", {"role": "frontend", "path": SHELL, "added": 1, "removed": 1, "size": 45000}),
    (150, "test_run", {"task": "h1", "trigger": "ide"}),
    (158, "test_result", {"task": "h1", "ok": True, "passed": 121, "failed": [], "summary": "121 passed in 8.4s", "trigger": "ide"}),
    (170, "message_posted", {"message": "C004", "text": "Fix is ready: call() now throws for any refused answer, so every form shows the server's message. Submitting.", "to": []}),
    (180, "submit", {"task": "h1"}),
    (181, "test_run", {"task": "h1", "trigger": "submit"}),
    (189, "test_result", {"task": "h1", "ok": True, "passed": 121, "failed": [], "summary": "121 passed in 8.4s", "trigger": "submit"}),
    (190, "submit_result", SUBMIT_OK),
    (190, "session_finished", {"ok": True}),
]
STRONG_FACTS = {"scan": None, "measured": MEASURED_OK, "rerun": {"ok": True, "passed": 121, "failed": 0, "summary": "121 passed"},
                "regression": {"path": REGRESSION, "fails_on_seed": True, "passes_on_main": True}}
STRONG_SCORES = {"communication": 4, "diagnosis": 4, "fix_quality": 4, "testing": 4, "ownership": 4}  # 100

# The weak run: patches the booking form first (no test run, nothing read), no update until Aarav nudges, a late post that does not say what is wrong, a red submit (the other screens still say
# they saved), a question to Rohan, the request function fixed, accepted at the second submit with no regression test and no green run of its own.
WEAK = [
    (0, "session_started", {"scenario": "opd-form-says-saved", "role": "frontend"}),
    (3, "team_message", team("qa-report", "qa", QA_REPORT)),
    (10, "file_opened", {"role": "frontend", "path": SHELL, "auto": True}),
    (60, "file_saved", {"role": "frontend", "path": SHELL, "added": 2, "removed": 1, "size": 45100}),
    (90, "team_message", team("lead-update", "architect", "Any update on the booking form? Please post what you have found so far.")),
    (240, "team_message", team("backend-pointer", "backend", "Heads up from me: the API's answer is right.")),
    (240, "hint_given", {"message": "C004", "from": "backend", "source": "scripted", "reason": "timeline", "question": "", "text": "Heads up from me: the API's answer is right.", "n": 1}),
    (300, "team_message", team("lead-nudge", "architect", "No update from you for 5 minutes. Where are we on the booking form?")),
    (330, "message_posted", {"message": "C005", "text": "Sorry, still working on it. I think the booking form needs to read the answer.", "to": []}),
    (400, "submit", {"task": "h1"}),
    (401, "test_run", {"task": "h1", "trigger": "submit"}),
    (409, "test_result", {"task": "h1", "ok": False, "passed": 116, "failed": ["tests/ui/test_refusals.py::test_a_refused_delete_does_not_say_removed"], "summary": "4 failed, 116 passed in 8.0s", "trigger": "submit"}),
    (411, "submit_result", {"task": "h1", "ok": False, "stage": "tests", "summary": "4 tests still fail", "failed": ["tests/ui/test_refusals.py::test_a_refused_delete_does_not_say_removed"], "review_items": 0}),
    (440, "team_message", team("m6", "backend", "The API answers correctly; look at how the page reads the answer.")),
    (440, "hint_given", {"message": "C006", "from": "backend", "source": "live", "reason": "", "question": "the other screens still fail, why?", "text": "The API answers correctly; look at how the page reads the answer.", "n": 2}),
    (500, "file_saved", {"role": "frontend", "path": SHELL, "added": 3, "removed": 2, "size": 45100}),
    (560, "submit", {"task": "h1"}),
    (561, "test_run", {"task": "h1", "trigger": "submit"}),
    (569, "test_result", {"task": "h1", "ok": True, "passed": 120, "failed": [], "summary": "120 passed in 8.1s", "trigger": "submit"}),
    (571, "submit_result", SUBMIT_OK),
    (571, "session_finished", {"ok": True}),
]
WEAK_FACTS = {"scan": None, "measured": MEASURED_OK, "rerun": {"ok": True, "passed": 120, "failed": 0, "summary": "120 passed"}, "regression": None}
WEAK_SCORES = {"communication": 0, "diagnosis": 0, "fix_quality": 4, "testing": 0, "ownership": 2}  # 30


def facts(steps: list[tuple[float, str, dict]], extra: dict, minutes: int = 25) -> Facts:
    return Facts(make_log(steps), minutes=minutes, **extra)
