"""Third hand-test (attempt 3, 95/100): a near-perfect run shows 0 unbacked claims, the judges' lines the 7b wrote are kept when their facts are right, a gap about something never done
says by when, and the coach paragraph must name a strength and a gap with their times."""
import json
import re
from pathlib import Path

import pytest

from app.config import load_agents
from app.scenarios.debrief import judge_post, moment_of
from app.scenarios.loader import load_scenario
from app.scenarios.reports import attach_voices, build_report, render_markdown
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import Facts, clock, event_text, note_matches, score
from app.scenarios.wording import VoiceLine, VoiceOutput, build_voices, coach_moments, verify_voice

from scenario_fixtures import REGRESSION, WEAK, WEAK_FACTS, facts

SCN = load_scenario("opd-bookings-down")
RUBRIC = load_rubric(SCN)
NAMES = {a.id: a.name for a in load_agents().values()}
REAL = {"old_name_files": [], "rerun": {"ok": True, "passed": 105, "failed": 0}, "regression": {"path": REGRESSION, "fails_on_seed": True, "passes_on_main": True, "seed_summary": "1 failed in 0.41s", "main_summary": "1 passed"}}
TIME = re.compile(r"\b\d{2}:\d{2}\b")


def attempt3_facts() -> Facts:
    log = [json.loads(x) for x in (Path(__file__).parent / "fixtures_real_run_attempt3.jsonl").read_text(encoding="utf-8").splitlines()]
    return Facts(log, minutes=25, **REAL)


def report_of(f: Facts) -> dict:
    return build_report(scenario=SCN, rubric=RUBRIC, attempt=3, project="p", facts=f, results=score(RUBRIC, f), names=NAMES)


def moments(r: dict) -> dict:
    return {c["id"]: m for c in r["criteria"] if (m := moment_of(c, r["rows"]))}


class Stub:
    def __init__(self, out):
        self.out = out

    def speak(self, report, moments):
        return self.out, ""


def what_the_7b_said(r: dict) -> VoiceOutput:
    """What the 7b wrote in the hand-test: for each judge the quoted moment, its time in brackets and the tip, with no criterion and no score in front."""
    out = []
    for c in r["criteria"]:
        m = moments(r)[c["id"]]
        out.append(VoiceLine(criterion=c["id"], line=f"{m['quote']} ({clock(m['t'])}) {m['tip']}"))
    cm = coach_moments(r)
    return VoiceOutput(lines=out, coach=f"At {clock(cm['strength']['t'])} {cm['strength']['note'].rstrip('.')}. At {clock(cm['gap']['t'])} {cm['gap']['note'].rstrip('.')}, so read the newest migration before your first edit next time.")


# -- 1. a near-perfect run shows 0 unbacked claims -----------------------------------------------------------------------------------

def test_attempt_3_scores_95_and_has_no_unbacked_claim():
    r = report_of(attempt3_facts())
    assert r["total"] == 95 and [c["score"] for c in r["criteria"]] == [4, 3, 4, 4, 4]
    assert r["fairness"]["dropped"] == [] and r["fairness"]["points"] == r["fairness"]["quoted"] == r["fairness"]["matched"] == 20


def test_the_judge_lines_of_the_hand_test_are_kept_now_that_the_score_is_put_in_front_in_code():
    r = report_of(attempt3_facts())
    lines, coach, rejected, reason = build_voices(r, Stub(what_the_7b_said(r)), moments(r), lambda c: judge_post(c, r["rows"]))
    assert reason == "" and rejected == [] and {v["source"] for v in lines.values()} == {"model"}
    assert [lines[c["id"]]["text"].split(":")[0] for c in r["criteria"]] == ["Communication 4/4", "Diagnosis 3/4", "Fix quality 4/4", "Testing 4/4", "Ownership 4/4"]
    assert coach["source"] == "model"
    attach_voices(r, lines, coach, rejected, reason)
    assert r["fairness"]["dropped"] == [] and r["fairness"]["ai_rejected"] == [] and r["fairness"]["voices"] == {"judges": "model", "coach": "model", "reason": ""}
    md = render_markdown(r, NAMES)
    assert "- Unbacked claims dropped: 0" in md and "- AI lines not used: 0" in md


def test_a_line_with_a_wrong_fact_is_rejected_apart_from_the_unbacked_claims():
    r = report_of(attempt3_facts())
    said = what_the_7b_said(r)
    said.lines[3] = VoiceLine(criterion="testing", line="Your own run at 09:09 was green, so keep adding a regression test with every bug fix.")  # a time that is not the testing moment's
    lines, coach, rejected, reason = build_voices(r, Stub(said), moments(r), lambda c: judge_post(c, r["rows"]))
    assert [(d.finding, "09:09" in d.reason) for d in rejected] == [("testing", True)] and lines["testing"]["source"] == "template" and lines["communication"]["source"] == "model"
    attach_voices(r, lines, coach, rejected, reason)
    assert r["fairness"]["dropped"] == [] and len(r["fairness"]["ai_rejected"]) == 1  # evidence points are all backed: the run is clean
    assert r["fairness"]["voices"]["judges"] == "mixed"


# -- 2. a gap about something never done says by when --------------------------------------------------------------------------------

def test_never_opened_the_migration_is_worded_by_the_first_edit_and_quotes_it():
    f = attempt3_facts()
    r = report_of(f)
    x = next(row for row in r["rows"] if row["rule"] == "read_the_migration")
    assert x["kind"] == "gap" and x["note"] == "By your first edit at 01:31 you had not opened the migration."
    assert x["event"] == "E009" and x["quote"] == "Created tests/regression/test_regression_slot_at.py (empty file)" and x["t"] == 91.8 and x["source"] == "IDE · file saved"
    assert x["advice"].startswith("Something changed on Monday")


def test_every_gap_of_something_never_done_names_the_moment_it_quotes():
    never = {"first_update", "names_the_cause", "reproduced_first", "read_the_route", "read_the_migration", "green_before_submit", "regression_test_added", "regression_test_proves_fix", "reported_the_outcome"}
    for f in (attempt3_facts(), facts(WEAK, WEAK_FACTS)):
        r = report_of(f)
        by = {e["id"]: e for e in f.log}
        for x in r["rows"]:
            if x["rule"] in never and x["kind"] == "gap" and ("you had not" in x["note"] or "you never told" in x["note"] or "you had no green run" in x["note"]):
                assert re.match(r"^(By your first edit|By your submit|By the accepted submit|By the end of the session|After your green run|By the lead's request) at \d\d:\d\d ", x["note"]), x["note"]
                assert TIME.findall(x["note"]) == [clock(by[x["event"]]["t"])] and note_matches(x["note"], by[x["event"]]) is None


def test_the_weak_run_gaps_read_by_when():
    r = report_of(facts(WEAK, WEAK_FACTS))
    notes = {x["rule"]: x["note"] for x in r["rows"] if x["kind"] == "gap"}
    assert notes["reproduced_first"] == "By your first edit at 01:00 you had not run the tests."
    assert notes["read_the_route"] == "By your first edit at 01:00 you had not opened the failing route."
    assert notes["regression_test_added"] == "By your submit at 07:50 you had not added a test of your own for the bug."
    assert notes["green_before_submit"] == "By your submit at 07:50 you had no green run of your own."


# -- 3. the coach paragraph names a strength and a gap with their times --------------------------------------------------------------------

def test_the_coach_of_the_hand_test_is_refused_as_generic_and_the_summary_is_used():
    r = report_of(attempt3_facts())
    generic = ("You did a great job communicating the status of the incident and explaining your actions clearly. You also demonstrated strong problem-solving skills by identifying and "
               "fixing the issue. Your testing efforts were thorough, and you added a regression test to ensure the fix was effective. Remember to always read the newest migration "
               "before editing to avoid similar issues in the future.")
    problem = verify_voice(generic, r, None, "coach")
    assert problem is not None and "generic praise" in problem
    lines, coach, rejected, reason = build_voices(r, Stub(VoiceOutput(lines=what_the_7b_said(r).lines, coach=generic)), moments(r), lambda c: judge_post(c, r["rows"]))
    assert coach == {"text": r["coach"]["text"], "source": "template"} and [d.finding for d in rejected] == ["coach"]


def test_a_paragraph_without_a_time_of_the_findings_is_refused_and_one_with_both_is_kept():
    r = report_of(attempt3_facts())
    cm = coach_moments(r)
    assert cm["strength"]["kind"] == "strength" and cm["gap"]["rule"] == "read_the_migration"
    plain = "Your fix was small and your tests were thorough, but you never read the newest migration before editing, so do that first next time."
    assert "does not name the strength at" in verify_voice(plain, r, None, "coach")
    with_one = f"At {clock(cm['strength']['t'])} {cm['strength']['note'].rstrip('.')}, and next time read the newest migration before you edit anything at all."
    assert f"does not name the gap at {clock(cm['gap']['t'])}" in verify_voice(with_one, r, None, "coach")
    both = f"At {clock(cm['strength']['t'])} {cm['strength']['note'].rstrip('.')}. At {clock(cm['gap']['t'])} {cm['gap']['note'].rstrip('.')}, so read the newest migration first."
    assert verify_voice(both, r, None, "coach") is None


def test_the_event_the_gap_quotes_is_the_one_the_coach_names():
    r = report_of(attempt3_facts())
    cm = coach_moments(r)
    by = r["events"]
    assert clock(by[cm["gap"]["event"]]["t"]) == clock(cm["gap"]["t"]) and event_text(by[cm["gap"]["event"]]) == cm["gap"]["quote"]
