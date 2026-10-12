"""Step 5, second hand-test: a point quotes the event it describes (the notes' times, files and counts are the quote's), the debrief's own measurements are quotable entries,
a strong run drops no claim, and the hand-tester's second attempt (85/100) is scored again with the fixes."""
import json
import re
from pathlib import Path

import pytest

from app.config import load_agents
from app.scenarios.loader import load_scenario
from app.scenarios.reports import build_report
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import Facts, clock, event_text, note_matches, score

from scenario_fixtures import REGRESSION, STRONG, STRONG_FACTS, WEAK, WEAK_FACTS, facts

SCN = load_scenario("opd-bookings-down")
RUBRIC = load_rubric(SCN)
NAMES = {a.id: a.name for a in load_agents().values()}
HERE = Path(__file__).parent
TIME = re.compile(r"\b\d{2}:\d{2}\b")
REAL = {"old_name_files": [], "rerun": {"ok": True, "passed": 105, "failed": 0}, "regression": {"path": REGRESSION, "fails_on_seed": True, "passes_on_main": True, "seed_summary": "1 failed in 0.40s", "main_summary": "1 passed"}}


def report(f: Facts) -> dict:
    return build_report(scenario=SCN, rubric=RUBRIC, attempt=2, project="p", facts=f, results=score(RUBRIC, f), names=NAMES)


def attempt2(fixed_ide: bool) -> list[dict]:
    """The session log of the hand-test's attempt 2. `fixed_ide`: the IDE of this step logs the click on the file that was open already (E011: appointments.py, shown by the IDE
    itself after it was remounted, then picked by the learner): a deliberate open, not the IDE's own."""
    log = [json.loads(x) for x in (HERE / "fixtures_real_run_attempt2.jsonl").read_text(encoding="utf-8").splitlines()]
    if fixed_ide:
        next(e for e in log if e["id"] == "E011").pop("auto")
    return log


def rows_by_rule(r: dict) -> dict:
    return {x["rule"]: x for x in r["rows"]}


SESSIONS = {"strong": lambda: facts(STRONG, STRONG_FACTS), "weak": lambda: facts(WEAK, WEAK_FACTS),
            "attempt2": lambda: Facts(attempt2(False), **REAL), "attempt2 with the fixed IDE": lambda: Facts(attempt2(True), **REAL)}


# -- every note is about its quote ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", list(SESSIONS))
def test_every_note_says_only_what_its_quoted_entry_says(name):
    f = SESSIONS[name]()
    r = report(f)
    by = {e["id"]: e for e in f.log}
    assert len(r["rows"]) == 20 and r["fairness"]["dropped"] == []  # nothing was dropped: every point passed the check
    for x in r["rows"]:
        e = by[x["event"]]
        assert x["t"] == e["t"] and x["quote"].rstrip("…") in event_text(e)
        assert note_matches(x["note"], e) is None, (x["rule"], x["note"], event_text(e))
        # the times in the note: the entry's own time, or a time its text says; never another entry's
        assert set(TIME.findall(x["note"])) <= {clock(e["t"])} | set(TIME.findall(event_text(e))), (x["rule"], x["note"])


def test_the_check_refuses_a_note_with_another_entrys_time_file_or_count():
    f = SESSIONS["attempt2"]()
    post = next(e for e in f.log if e["id"] == "E009")
    assert note_matches("At 03:08 you told the team what you had found.", post) is None
    assert "06:55" in note_matches("At 06:55 you told the team what you had found.", post)  # the time of another post
    assert "backend/api/doctors.py" in note_matches("You opened backend/api/doctors.py.", post)
    result = next(e for e in f.log if e["id"] == "E005")
    assert note_matches("12 failed, 89 passed", result) is None and "93" in note_matches("12 failed, 93 passed", result)


def test_a_point_whose_note_does_not_match_its_entry_is_dropped_and_recorded():
    f = SESSIONS["strong"]()
    results = score(RUBRIC, f)
    results[0].findings[0].text = "First update at 09:59, inside the first 2 minutes."  # as if a rule built a wrong sentence
    r = build_report(scenario=SCN, rubric=RUBRIC, attempt=1, project="p", facts=f, results=results, names=NAMES)
    assert len(r["rows"]) == 19 and [d["finding"] for d in r["fairness"]["dropped"]] == ["F01"] and "09:59" in r["fairness"]["dropped"][0]["reason"]
    assert r["fairness"]["points"] == 19 and r["total"] == 100  # the score does not depend on it


# -- the quotes of attempt 2, point by point -------------------------------------------------------------------------------------

def test_the_points_that_were_wrong_in_the_hand_test_quote_what_they_describe():
    f = SESSIONS["attempt2"]()
    r = report(f)
    by = {e["id"]: e for e in f.log}
    rows = rows_by_rule(r)
    cause = rows["names_the_cause"]
    assert cause["event"] == "E009" and cause["note"] == "At 03:08 you told the team what you had found." and cause["t"] == 188.8 and cause["quote"].startswith("Update: bookings fail since migration 0007")
    first = rows["first_update"]
    assert first["event"] == "E009" and first["note"] == "Your first update came at 03:08, later than the 2 minutes asked."
    suite = rows["suite_green_on_main"]
    assert by[suite["event"]]["kind"] == "debrief_check" and suite["quote"] == "Debrief re-run on main: 105 passed"  # not Ananya's chat message
    proof = rows["regression_test_proves_fix"]
    assert by[proof["event"]]["kind"] == "debrief_check" and proof["source"] == "Debrief check"
    assert proof["quote"] == f"Regression test {REGRESSION} on the seed: 1 failed in 0.40s; on main: 1 passed" and "1 error in 0.53s" not in proof["quote"]  # not the learner's own failed run
    assert rows["old_name_gone"]["quote"] == "Debrief scan of backend/: no file says slot_time any more"
    assert rows["small_change"]["quote"] == "Your change against the start: 2 files, 10 lines changed (+5 -5)" and "10 lines changed in 2 files" in rows["small_change"]["note"]
    assert rows["regression_test_added"]["event"] == "E014" and "03:51" in rows["regression_test_added"]["note"]  # the first save that holds lines
    assert rows["reproduced_first"]["quote"] == "12 failed, 89 passed in 12.59s" and rows["reproduced_first"]["note"].startswith("Your first test run finished at 00:41 (12 failed, 89 passed in 12.59s)")


def test_the_debrief_measurements_are_entries_of_their_own_with_the_numbers_in_their_text():
    f = SESSIONS["attempt2"]()
    checks = {e["check"]: e for e in f.log if e["kind"] == "debrief_check"}
    assert set(checks) == {"scan", "rerun", "regression", "change", "counts"} and all(e["id"].startswith("E") and e["t"] == 449.7 for e in checks.values())
    assert checks["counts"]["text"] == "Counted in the session log: 0 hints, 0 nudges from the lead, 0 review send-backs, 0 submits refused for tests, 0 submits refused for scope"
    broken = Facts(attempt2(False), old_name_files=["backend/api/a.py"], rerun={"ok": False, "passed": 99, "failed": 6}, regression={"path": REGRESSION, "fails_on_seed": False, "passes_on_main": True})
    texts = {e["check"]: e["text"] for e in broken.log if e["kind"] == "debrief_check"}
    assert texts["scan"] == "Debrief scan of backend/: slot_time is still in backend/api/a.py" and texts["rerun"] == "Debrief re-run on main: 99 passed, 6 failed"
    assert texts["regression"] == f"Regression test {REGRESSION} on the seed: passed; on main: passed"
    assert [e["text"] for e in Facts(attempt2(False), rerun=None).log if e.get("check") == "rerun"] == ["Debrief re-run on main: the suite could not be run"]


def test_the_session_log_itself_never_gets_the_debrief_entries():
    f = SESSIONS["attempt2"]()
    assert [e["id"] for e in f.session] == [f"E{i:03d}" for i in range(1, 46)] and f.session[-1]["kind"] == "session_finished"
    assert f.anchor["id"] == "E042"  # the accepted submit, not a debrief entry


# -- 2. a strong run drops nothing ---------------------------------------------------------------------------------------------

def test_a_strong_run_drops_no_claim_and_its_first_update_is_the_first_post():
    r = report(SESSIONS["strong"]())
    assert r["fairness"]["dropped"] == [] and r["fairness"]["points"] == r["fairness"]["quoted"] == r["fairness"]["matched"] == 20
    by_rule = rows_by_rule(r)
    assert by_rule["first_update"]["t"] == 55 and by_rule["names_the_cause"]["t"] == 55 and "00:55" in by_rule["first_update"]["note"]


# -- 3. the route read before editing -------------------------------------------------------------------------------------------

def test_either_route_opened_by_you_before_the_first_save_counts_and_the_note_names_it():
    f = SESSIONS["attempt2 with the fixed IDE"]()
    x = rows_by_rule(report(f))["read_the_route"]
    assert x["kind"] == "strength" and x["event"] == "E011" and x["note"] == "You opened the failing route (backend/api/appointments.py) at 03:23, before the first edit."
    other = attempt2(False)
    other.insert(10, {"id": "E0xx", "t": 150.0, "kind": "file_opened", "role": "backend", "path": "backend/api/doctors.py"})  # doctors.py instead, from a search result
    for i, e in enumerate(other, 1):
        e["id"] = f"E{i:03d}"
    y = rows_by_rule(report(Facts(other, **REAL)))["read_the_route"]
    assert y["kind"] == "strength" and "backend/api/doctors.py" in y["note"] and y["quote"] == "backend/api/doctors.py"
    assert score(RUBRIC, f)[1].score == 4


def test_the_hand_test_log_shows_the_ide_opened_the_route_by_itself_every_time_and_no_click_was_logged():
    f = SESSIONS["attempt2"]()
    opens = [(e["id"], e.get("auto", False)) for e in f.session if e["kind"] == "file_opened" and e["path"] == "backend/api/appointments.py"]
    assert opens == [("E002", True), ("E011", True), ("E025", True), ("E038", True)]  # the IDE re-opened it by itself (it was remounted), a click on it was never logged
    x = rows_by_rule(report(f))["read_the_route"]
    assert x["kind"] == "gap" and x["note"] == "You opened the failing route (backend/api/doctors.py) at 05:05, after you had started editing." and score(RUBRIC, f)[1].score == 3


# -- the score of attempt 2 --------------------------------------------------------------------------------------------------------

def test_attempt_2_scored_as_logged_and_with_the_fixed_ide():
    as_logged, fixed = report(SESSIONS["attempt2"]()), report(SESSIONS["attempt2 with the fixed IDE"]())
    assert (as_logged["total"], [c["score"] for c in as_logged["criteria"]]) == (85, [2, 3, 4, 4, 4])  # what the report said
    assert (fixed["total"], [c["score"] for c in fixed["criteria"]]) == (90, [2, 4, 4, 4, 4])
    comm = next(c for c in fixed["criteria"] if c["id"] == "communication")
    assert comm["summary"] == "Held: no quiet stretch of five minutes, the cause named in the channel. Missed: a first update inside two minutes, the lead's request answered at once."
    assert next(c for c in fixed["criteria"] if c["id"] == "diagnosis")["summary"].startswith("Everything held:")
