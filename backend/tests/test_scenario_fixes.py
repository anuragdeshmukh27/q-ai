"""Step 5 after a real hand-test: hints only for questions, the 4-minute pointer only when it tells the learner something new, the right event for every rule, names instead of
role ids, summaries built from the rules, distinct quotes, honest wording labels, project-wide search. No server except where the API is the thing tested."""
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import load_agents
from app.scenarios.build import diff_stats
from app.scenarios.director import is_question
from app.scenarios.loader import TimelineItem, load_scenario
from app.scenarios.reports import build_report, render_markdown
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import Facts, display_name, event_text, score, source_label

from scenario_fixtures import APPT, DOCT, MIGRATION, REGRESSION, STRONG, STRONG_FACTS, SUBMIT_OK, WEAK, WEAK_FACTS, facts, make_log
from scenario_helpers import ScenarioLLM
from test_scenario_director import Room

SCN = load_scenario("opd-bookings-down")
RUBRIC = load_rubric(SCN)
NAMES = {a.id: a.name for a in load_agents().values()}
STATUS = "Bookings fail since migration 0007 renamed slot_time to slot_at. Fixing now."


def finding(f, rule):
    return next(x for r in score(RUBRIC, f) for x in r.findings if x.rule == rule)


def scored(f):
    return {r.id: r.score for r in score(RUBRIC, f)}


def report(f, **kw):
    return build_report(scenario=SCN, rubric=RUBRIC, attempt=1, project="p", facts=f, results=score(RUBRIC, f), names=NAMES, **kw)


# -- 1. a hint is a question to a teammate, not a status update ---------------------------------------------------

@pytest.mark.parametrize("text,question", [
    ("Karan, what changed on Monday?", True), ("Karan what changed on monday", True), ("Can you check the server log", True), ("I'm stuck, any hint", True), ("How do I search the whole backend", True),
    ("Tell me what Karan changed", True), (STATUS, False), ("Fix is ready: both routes use slot_at now. Submitting.", False), ("What I found: both routes call slot_time. Fixing now.", False),
    ("Karan, fixing the routes now", False), ("Thanks, ETA 10 min", False), ("Update to everyone: booking is fixed", False),
])
def test_a_question_or_a_request_for_help_is_told_from_a_status_update(text, question):
    assert is_question(text) is question


def test_a_status_update_to_everyone_gets_one_acknowledgement_from_the_lead_and_no_hint():
    r = Room(llm=ScenarioLLM())
    r.at(3)
    r.director.post(STATUS)
    r.director.join()
    replies = [m for m in r.said() if m.get("reply_to")]
    assert [(m["from"], m["source"]) for m in replies] == [("architect", "scripted")] and replies[0]["text"] == SCN.acks[0]
    assert r.logged("hint_given") == [] and r.director.hints == 0 and r.llm.chat_calls == 0 and not any(m.get("hint") for m in r.said())


def test_a_status_update_sent_to_a_teammate_is_acknowledged_once_by_that_teammate_and_is_not_a_hint():
    r = Room(llm=ScenarioLLM())
    r.at(3)
    out = r.director.post("Karan, Aarav: " + STATUS, "database")  # picked Karan, names Aarav as well: still one reply
    r.director.join()
    assert out["pending"] == [] and [m["from"] for m in r.said() if m.get("reply_to")] == ["database"]
    assert r.logged("hint_given") == [] and r.llm.chat_calls == 0
    assert "database" not in r.director.asked  # a remark is not a question: the 4-minute pointer is still due


def test_a_question_to_a_teammate_is_answered_and_counted_as_a_hint():
    r = Room(llm=ScenarioLLM("Migration 0007 renamed it."))
    r.at(3)
    r.director.post("Karan, what changed on Monday?")
    r.director.join()
    assert [(m["from"], m["source"], m.get("hint")) for m in r.said("database")] == [("database", "live", True)]
    hints = r.logged("hint_given")
    assert len(hints) == 1 and hints[0]["from"] == "database" and hints[0]["n"] == 1 and hints[0]["text"] == "Migration 0007 renamed it." and "database" in r.director.asked


def test_a_question_to_everyone_is_acknowledged_by_the_lead_only():
    r = Room(llm=ScenarioLLM())
    r.at(3)
    r.director.post("Does anyone know what changed on Monday?")
    r.director.join()
    assert [m["from"] for m in r.said() if m.get("reply_to")] == ["architect"] and r.logged("hint_given") == [] and r.llm.chat_calls == 0


# -- 2. Karan's pointer at 4 minutes -------------------------------------------------------------------------------

def pointers(r):
    return [m for m in r.said("database") if m.get("ref") == "db-pointer"]


def test_the_pointer_comes_at_four_minutes_and_is_a_hint_when_you_have_found_nothing():
    r = Room()
    r.at(3)
    r.at(239)
    assert pointers(r) == []
    r.at(241)
    assert len(pointers(r)) == 1 and pointers(r)[0]["hint"] is True and [h["reason"] for h in r.logged("hint_given")] == ["timeline"]


def test_the_pointer_is_skipped_when_you_opened_the_migration_yourself():
    r = Room()
    r.at(3)
    r.log.add("file_opened", role="backend", path="database/migrations/0007_rename_slot_time_to_slot_at.sql")
    r.at(250)
    assert pointers(r) == [] and r.logged("hint_given") == []


def test_the_pointer_is_skipped_when_you_named_the_cause_in_a_post():
    r = Room()
    r.at(3)
    r.director.post("The routes still say slot_time but the column is slot_at now. Fixing now.")
    r.at(250)
    assert pointers(r) == [] and r.logged("hint_given") == []
    other = Room()
    other.at(3)
    other.director.post("Migration 0007 renamed the column.")
    other.at(250)
    assert pointers(other) == []


def test_the_pointer_is_not_skipped_by_a_file_the_ide_opened_by_itself_or_a_post_that_says_nothing():
    r = Room()
    r.at(3)
    r.log.add("file_opened", role="backend", path="database/migrations/0007_rename_slot_time_to_slot_at.sql", auto=True)
    r.director.post("Still looking, no idea yet.")
    r.at(250)
    assert len(pointers(r)) == 1


def test_the_pointer_is_skipped_when_you_asked_karan_a_question_but_not_for_a_status_update_to_him():
    asked = Room(llm=ScenarioLLM())
    asked.at(3)
    asked.director.post("Karan, what changed?")
    asked.director.join()
    asked.at(250)
    assert pointers(asked) == []
    told = Room(llm=ScenarioLLM())
    told.at(3)
    told.director.post("Karan, still looking at the routes.", "database")
    told.at(250)
    assert len(pointers(told)) == 1


@pytest.mark.parametrize("skip,ok", [("learner_posted", True), (["asked:database", "opened:database/migrations/0007*", "said:slot_at|0007"], True), ("opened:", False), ("said:(", False), ("coffee", False)])
def test_skip_conditions_are_validated(skip, ok):
    base = {"id": "x", "from": "database", "text": "hello", "at": 5, "skip_if": skip}
    if ok:
        assert TimelineItem.model_validate(base).conditions()
    else:
        with pytest.raises(ValidationError):
            TimelineItem.model_validate(base)


def test_a_pointer_that_arrived_after_you_had_found_the_cause_is_not_held_against_you():
    steps = [s for s in WEAK if s[1] != "file_opened" or s[2].get("auto")]
    steps = [s for s in steps if s[0] != 360]
    steps.append((100, "file_opened", {"role": "backend", "path": MIGRATION}))  # opened at 01:40, the pointer came at 04:00
    steps.sort(key=lambda s: s[0])
    f = facts(steps, WEAK_FACTS)
    assert finding(f, "no_pointer_needed").kind == "strength"
    assert finding(facts(WEAK, WEAK_FACTS), "no_pointer_needed").kind == "gap"  # the weak run opened the migration only after the pointer


# -- the run from the hand-test: status updates, migration opened before four minutes ------------------------------------------

def play_my_run():
    """What the fixed engine records when the learner does what the hand-tester did: opens the migration and the route early, posts a status update to everyone, and keeps updating Aarav."""
    r = Room(llm=ScenarioLLM())
    log = r.log
    r.at(3)
    log.add("file_opened", role="backend", path=APPT, auto=True)
    r.at(20)
    log.add("test_run", task="h1", trigger="ide")
    log.add("test_result", task="h1", ok=False, passed=90, failed=["tests/api/test_booking.py::test_booking_an_appointment_returns_201"], summary="15 failed, 90 passed in 33.9s", trigger="ide")
    r.at(40)
    log.add("file_opened", role="backend", path=MIGRATION)
    log.add("file_opened", role="backend", path=DOCT)
    r.at(75)
    r.director.post(STATUS)  # to everyone
    r.at(250)  # the 4-minute mark
    r.at(340)
    r.director.post("Still fixing: the routes first, then a regression test.", "architect")  # a status update to Aarav
    r.at(470)
    log.add("file_saved", role="backend", path=REGRESSION, added=0, removed=0, size=0, created=True)
    log.add("file_saved", role="backend", path=REGRESSION, added=53, removed=0, size=2886, created=False)
    r.at(500)
    r.director.post("Regression test is in, fixing the routes now.", "architect")
    r.at(600)
    log.add("file_saved", role="backend", path=APPT, added=4, removed=4, size=6840, created=False)
    log.add("file_saved", role="backend", path=DOCT, added=1, removed=1, size=5027, created=False)
    log.add("test_run", task="h1", trigger="ide")
    log.add("test_result", task="h1", ok=True, passed=105, failed=[], summary="105 passed in 6.3s", trigger="ide")
    r.at(620)
    r.director.post("Fix is ready: both routes use slot_at now, regression test added, all tests green. Submitting.", "architect")
    r.at(630)
    log.add("submit", task="h1")
    log.add("test_run", task="h1", trigger="submit")
    log.add("test_result", task="h1", ok=True, passed=105, failed=[], summary="105 passed in 5.7s", trigger="submit")
    log.add("submit_result", **SUBMIT_OK)
    r.director.join()
    log.add("session_finished", ok=True)
    return r


def test_my_run_has_no_pointer_no_hints_and_diagnosis_4_of_4():
    r = play_my_run()
    assert r.logged("hint_given") == [] and pointers(r) == [] and r.llm.chat_calls == 0
    replies = [m for m in r.said() if m.get("reply_to")]
    assert len(replies) == 4 and {m["source"] for m in replies} == {"scripted"} and not any(m.get("hint") for m in replies)  # every post was acknowledged, once
    f = Facts(r.log.events(), minutes=25, rerun={"ok": True, "passed": 105, "failed": 0}, regression={"path": REGRESSION, "fails_on_seed": True, "passes_on_main": True})
    got = scored(f)
    assert got["diagnosis"] == 4 and got["ownership"] == 4 and finding(f, "few_hints").text == "0 hints used (up to 1 is fine)."
    first = finding(f, "reproduced_first")
    log = {e["id"]: e for e in f.log}
    assert log[first.events[0]]["kind"] == "test_result" and event_text(log[first.events[0]]) == "15 failed, 90 passed in 33.9s"  # the first run's result line, not "Run tests"


# -- the real log of the hand-test, as the fixed rules read it ------------------------------------------------------------------

def real_log(fixed: bool) -> list[dict]:
    log = [json.loads(x) for x in (Path(__file__).parent / "fixtures_real_run_attempt1.jsonl").read_text(encoding="utf-8").splitlines()]
    if fixed:  # the pointer was skipped (migration opened at 00:40, cause named at 01:15) and the replies to the status updates were acknowledgements, not hints
        log = [e for e in log if e["kind"] != "hint_given" and e.get("message") not in ("C004", "C007", "C011")]
    for i, e in enumerate(log, 1):
        e["id"] = f"E{i:03d}"
    return log


REAL_FACTS = {"old_name_files": [], "rerun": {"ok": True, "passed": 105, "failed": 0}, "regression": {"path": REGRESSION, "fails_on_seed": True, "passes_on_main": True}}


def test_the_hand_test_log_scored_as_it_was_and_after_the_fixes():
    before = Facts(real_log(False), **REAL_FACTS)
    after = Facts(real_log(True), **REAL_FACTS)
    assert scored(before) == {"communication": 3, "diagnosis": 3, "fix_quality": 4, "testing": 4, "ownership": 3}  # 85, what the report said
    assert scored(after) == {"communication": 3, "diagnosis": 3, "fix_quality": 4, "testing": 4, "ownership": 4}  # 90
    assert finding(before, "few_hints").kind == "gap" and finding(after, "few_hints").kind == "strength" and finding(after, "no_pointer_needed").kind == "strength"
    # the first save of any file (08:38, the empty regression test) comes before the first run of the tests (17:55): the tests were not run first
    gap = finding(after, "reproduced_first")
    assert gap.kind == "gap" and gap.text == "You started editing at 08:38 before you had run the tests."
    assert finding(after, "no_nudges").kind == "gap" and "3 times" in finding(after, "no_nudges").text


# -- 3. the right event for every rule: first or last -----------------------------------------------------------------------

def test_reproduced_first_cites_the_first_test_run_and_quotes_its_result_line():
    steps = [s for s in STRONG if s[0] not in (105, 110)]  # leave the first run (20 s) and add a later one
    steps += [(60, "test_run", {"task": "h1", "trigger": "ide"}), (66, "test_result", {"task": "h1", "ok": False, "passed": 80, "failed": ["a"], "summary": "9 failed, 80 passed in 3.9s", "trigger": "ide"})]
    steps.sort(key=lambda s: s[0])
    f = facts(steps, STRONG_FACTS)
    x = finding(f, "reproduced_first")
    by = {e["id"]: e for e in f.log}
    assert by[x.events[0]]["t"] == 26 and event_text(by[x.events[0]]) == "12 failed, 89 passed in 4.1s" and by[x.events[1]]["t"] == 20
    assert x.text == "Your first test run finished at 00:26 (12 failed, 89 passed in 4.1s), before the first edit."  # the time is the quoted result line's


def test_the_first_edit_is_the_first_save_of_any_file_a_test_included():
    steps = [s for s in STRONG if s[0] != 20 and s[0] != 26] + [(104, "test_run", {"task": "h1", "trigger": "ide"})]  # the only early run is after the regression test was saved at 100
    steps.sort(key=lambda s: s[0])
    f = facts(steps, STRONG_FACTS)
    assert f.first_edit["path"] == REGRESSION and finding(f, "reproduced_first").kind == "gap"


def test_green_before_submit_is_the_last_green_run_and_must_come_after_the_last_change():
    green = finding(facts(STRONG, STRONG_FACTS), "green_before_submit")
    assert green.kind == "strength"
    f = facts(STRONG, STRONG_FACTS)
    assert f.log[[e["id"] for e in f.log].index(green.events[0])]["t"] == 156
    stale = [s for s in STRONG] + [(160, "file_saved", {"role": "backend", "path": APPT, "added": 1, "removed": 0, "size": 1, "created": False})]  # saved again after the green run
    stale.sort(key=lambda s: s[0])
    gap = finding(facts(stale, STRONG_FACTS), "green_before_submit")
    assert gap.kind == "gap" and "after your last green run" in gap.text and gap.events[0] != finding(facts(STRONG, STRONG_FACTS), "green_before_submit").events[0]


def test_reported_the_outcome_needs_a_post_after_the_last_green_run():
    steps = [s for s in STRONG if s[1] != "message_posted" or s[0] != 170]  # no closing post
    f = facts(steps, STRONG_FACTS)
    assert finding(f, "reported_the_outcome").kind == "gap"
    early = facts(sorted(steps + [(153, "message_posted", {"message": "C9", "text": "almost there", "to": []})], key=lambda s: s[0]), STRONG_FACTS)  # a post before the last green run does not count
    assert finding(early, "reported_the_outcome").kind == "gap"


def test_the_regression_test_is_quoted_by_the_save_that_holds_its_lines_not_the_empty_file():
    steps = [s for s in STRONG if s[0] != 100] + [(90, "file_saved", {"role": "backend", "path": REGRESSION, "added": 0, "removed": 0, "size": 0, "created": True}),
                                                    (100, "file_saved", {"role": "backend", "path": REGRESSION, "added": 12, "removed": 0, "size": 600, "created": False})]
    steps.sort(key=lambda s: s[0])
    f = facts(steps, STRONG_FACTS)
    by = {e["id"]: e for e in f.log}
    quoted = finding(f, "regression_test_added").events[0]
    assert by[quoted]["added"] == 12 and event_text(by[quoted]) == f"Saved {REGRESSION} (+12 -0 lines)"
    assert f.first_edit["added"] == 0  # the empty file is still the first save


def test_the_old_name_point_quotes_the_debriefs_own_scan_of_the_folder():
    f = facts(STRONG, STRONG_FACTS)
    by = {e["id"]: e for e in f.log}
    x = finding(f, "old_name_gone")
    assert by[x.events[0]]["kind"] == "debrief_check" and event_text(by[x.events[0]]) == "Debrief scan of backend/: no file says slot_time any more"
    left = Facts(make_log(STRONG), old_name_files=[APPT, DOCT], rerun=STRONG_FACTS["rerun"], regression=STRONG_FACTS["regression"])
    y = finding(left, "old_name_gone")
    assert y.kind == "gap" and event_text(next(e for e in left.log if e["id"] == y.events[0])) == f"Debrief scan of backend/: slot_time is still in {APPT}, {DOCT}" and y.text == f"slot_time is still used in {APPT}, {DOCT}."


# -- 4. names, never role ids -----------------------------------------------------------------------------------------------

def test_hints_and_sources_show_employee_names():
    assert [display_name(x) for x in ("database", "architect", "qa", "reviewer", "planner", "unknown")] == ["Karan", "Aarav", "Ananya", "Vikram", "Priya", "unknown"]
    hint = {"id": "E1", "t": 1, "kind": "hint_given", "from": "database", "n": 1, "text": "Check migration 0007."}
    assert event_text(hint) == "Hint 1 from Karan: Check migration 0007." and event_text({**hint, "text": ""}) == "Hint 1 from Karan"
    assert source_label({"kind": "team_message", "from": "architect"}) == "#incident-opd · Aarav" and source_label({"kind": "message_posted"}) == "#incident-opd · You"
    assert event_text({"kind": "test_run", "trigger": "ide"}) == "Run tests" and event_text({"kind": "test_run", "trigger": "submit"}) == "Run tests for Submit"


def test_no_role_id_reaches_the_report_or_its_markdown():
    f = facts(WEAK, WEAK_FACTS)
    r = report(f)
    visible = "\n".join([x["quote"] + " " + x["note"] + " " + x["source"] + " " + x["advice"] for x in r["rows"]] + [c["summary"] for c in r["criteria"]] + [render_markdown(r, NAMES)])
    assert not re.search(r"(from|by|to) (database|architect|qa|reviewer|planner|backend|frontend)\b", visible)
    assert "Hint 1 from Karan" in visible and "(ide)" not in visible


# -- 5. the summary of a criterion comes from its rules --------------------------------------------------------------------------

def test_a_criterion_summary_lists_what_held_and_what_was_missed():
    r = report(Facts(real_log(False), **REAL_FACTS))
    own = next(c for c in r["criteria"] if c["id"] == "ownership")
    assert own["score"] == 3 and own["summary"] == "Held: accepted inside the time box, inside your own files, the team told that the fix was ready. Missed: at most one hint."
    assert "close the loop" not in own["summary"]
    comm = next(c for c in r["criteria"] if c["id"] == "communication")
    assert "Missed: no quiet stretch of five minutes." in comm["summary"] and comm["summary"].startswith("Held: a first update inside two minutes")
    strong = report(facts(STRONG, STRONG_FACTS))
    assert strong["criteria"][0]["summary"].startswith("Everything held: a first update inside two minutes")
    weak = report(facts(WEAK, WEAK_FACTS))
    assert next(c for c in weak["criteria"] if c["id"] == "testing")["summary"].startswith("Nothing held. Missed: a green run of your own before Submit")


def test_every_point_still_cites_an_entry_when_it_is_the_only_one():
    steps = [(0, "session_started", {"scenario": "x", "role": "backend"}), (10, "session_finished", {"ok": False})]
    r = report(Facts(make_log(steps)))
    by = {e["id"]: e for e in Facts(make_log(steps)).log}
    assert len(r["rows"]) == 20 and all((x["event"] in ("E001", "E002") or by[x["event"]]["kind"] == "debrief_check") and x["verified"] for x in r["rows"])


# -- 6. new files --------------------------------------------------------------------------------------------------------------------

def test_a_new_file_counts_every_line_as_added():
    assert diff_stats("", "a\nb\nc\n") == (3, 0) and diff_stats("", "single line without newline") == (1, 0) and diff_stats("", "") == (0, 0)
    assert diff_stats("a\n", "a\nb\n") == (1, 0)
    assert event_text({"kind": "file_saved", "path": "tests/regression/test_x.py", "added": 53, "removed": 0, "created": True}) == "Created tests/regression/test_x.py (+53 -0 lines)"
    assert event_text({"kind": "file_saved", "path": "tests/regression/test_x.py", "added": 0, "removed": 0, "created": True}) == "Created tests/regression/test_x.py (empty file)"
    assert event_text({"kind": "file_saved", "path": "a.py", "added": 1, "removed": 1}) == "Saved a.py (+1 -1 lines)"


# -- 10. search is evidence for the diagnosis ---------------------------------------------------------------------------------------

def test_searching_the_whole_project_for_the_name_counts_as_looking_for_the_cause_before_editing():
    steps = [s for s in STRONG if not (s[1] == "file_opened" and s[2]["path"] == MIGRATION)]  # never opened the migration
    f = facts(steps, STRONG_FACTS)
    assert finding(f, "read_the_migration").kind == "gap"
    searched = sorted(steps + [(45, "search", {"role": "backend", "query": "slot_time", "matches": 12, "files": 5})], key=lambda s: s[0])
    f = facts(searched, STRONG_FACTS)
    x = finding(f, "read_the_migration")
    assert x.kind == "strength" and "searched the project for “slot_time” at 00:45, before the first edit" in x.text
    nothing = sorted(steps + [(45, "search", {"role": "backend", "query": "slot_time", "matches": 0, "files": 0})], key=lambda s: s[0])
    assert finding(facts(nothing, STRONG_FACTS), "read_the_migration").kind == "gap"  # a search that finds nothing is no evidence
    late = sorted(steps + [(135, "search", {"role": "backend", "query": "slot_time", "matches": 3, "files": 2})], key=lambda s: s[0])
    assert finding(facts(late, STRONG_FACTS), "read_the_migration").kind == "gap"  # after the first edit
    assert event_text({"kind": "search", "query": "slot_time", "matches": 1, "files": 1}) == "Searched for “slot_time”: 1 match in 1 file"
    assert event_text({"kind": "search", "query": "zzz", "matches": 0, "files": 0}) == "Searched for “zzz”: no match"
