"""Step 5: the rubric file, the scoring rules over the log of a session, the verifier of the wording and the report. No model and no server."""
import copy
import json
import re
import shutil
import threading
import time
from pathlib import Path

import pytest

from app.config import load_agents
from app.llm import StructuredResult
from app.scenarios import scoring
from app.scenarios.loader import ScenarioError, load_scenario
from app.scenarios.reports import History, build_report, render_markdown
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import Facts, clock, event_text, score
from app.scenarios.wording import PointWording, WordingOutput, Wordsmith, quote_matches, verify_points

from scenario_fixtures import APPT, DOCT, MIGRATION, REGRESSION, STRONG, STRONG_FACTS, STRONG_SCORES, SUBMIT_OK, WEAK, WEAK_FACTS, WEAK_SCORES, facts, make_log
from scenario_helpers import ScenarioLLM

ID = "opd-bookings-down"
SCN = load_scenario(ID)
RUBRIC = load_rubric(SCN)
NAMES = {a.id: a.name for a in load_agents().values()}


def scores(f: Facts) -> dict:
    return {r.id: r.score for r in score(RUBRIC, f)}


def finding(f: Facts, rule: str):
    return next(x for r in score(RUBRIC, f) for x in r.findings if x.rule == rule)


# -- the rubric file ---------------------------------------------------------------------------------------

def test_the_shipped_rubric_has_five_criteria_with_judges_descriptors_and_four_rules_each():
    assert RUBRIC.id == SCN.rubric == "opd-bookings-down-v1" and RUBRIC.version == 1 and RUBRIC.max_total == 100
    assert [(c.name, NAMES[c.judge]) for c in RUBRIC.criteria] == [("Communication", "Aarav"), ("Diagnosis", "Karan"), ("Fix quality", "Vikram"), ("Testing", "Ananya"), ("Ownership", "Aarav")]
    for c in RUBRIC.criteria:
        assert sorted(c.descriptors) == ["0", "1", "2", "3", "4"] and len(c.rules) == 4 and c.signals and all(r.advice for r in c.rules)
    assert {r.id for c in RUBRIC.criteria for r in c.rules} <= set(scoring.RULES) and len(scoring.RULES) == 20


def copy_rubric(tmp_path) -> Path:
    shutil.copytree(SCN.folder, tmp_path / ID, ignore=shutil.ignore_patterns("seed"))
    return tmp_path / ID / "rubric.json"


def broken(tmp_path, change) -> Path:
    path = copy_rubric(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    change(raw)
    path.write_text(json.dumps(raw), encoding="utf-8")
    return tmp_path


RUBRIC_BREAKS = [
    ("a rule that does not exist", lambda r: r["criteria"][0]["rules"][0].update(id="telepathy"), "unknown rule"),
    ("a criterion with three rules", lambda r: r["criteria"][1]["rules"].pop(), "exactly 4 rules"),
    ("a missing descriptor", lambda r: r["criteria"][2]["descriptors"].pop("3"), "descriptor"),
    ("a judge who does not work here", lambda r: r["criteria"][3].update(judge="nobody"), "not an employee"),
    ("an unknown signal", lambda r: r["criteria"][0]["signals"].append("vibes"), "unknown signal"),
    ("marks that do not add up to 100", lambda r: r.update(weight=4), "100 marks"),
    ("a rubric for another scenario", lambda r: r.update(scenario="other"), "for 'other'"),
    ("an id the scenario does not name", lambda r: r.update(id="opd-bookings-down-v2"), "must equal the scenario's rubric"),
]


@pytest.mark.parametrize("what,change,message", RUBRIC_BREAKS, ids=[b[0] for b in RUBRIC_BREAKS])
def test_a_broken_rubric_is_refused_with_a_message_that_says_why(tmp_path, what, change, message):
    root = broken(tmp_path, change)
    scn = load_scenario(ID)  # the shipped scenario, whose folder is replaced by the broken copy
    scn.root = root
    with pytest.raises(ScenarioError, match=re.escape(message)):
        load_rubric(scn)


def test_a_scenario_without_a_rubric_file_is_refused(tmp_path):
    path = copy_rubric(tmp_path)
    path.unlink()
    scn = load_scenario(ID)
    scn.root = tmp_path
    with pytest.raises(ScenarioError, match="rubric.json is missing"):
        load_rubric(scn)


# -- the rules on a strong run and a weak run ----------------------------------------------------------------

def test_a_strong_run_scores_every_point():
    f = facts(STRONG, STRONG_FACTS)
    assert scores(f) == STRONG_SCORES and sum(scores(f).values()) * RUBRIC.weight == 100
    findings = [x for r in score(RUBRIC, f) for x in r.findings]
    assert len(findings) == 20 and all(x.kind == "strength" and x.advice == "" for x in findings) and [x.id for x in findings] == [f"F{i:02d}" for i in range(1, 21)]


def test_a_weak_run_scores_what_it_earned_and_every_gap_cites_a_real_entry():
    f = facts(WEAK, WEAK_FACTS)
    assert scores(f) == WEAK_SCORES and sum(scores(f).values()) * RUBRIC.weight == 20
    log = {e["id"] for e in f.log}
    for r in score(RUBRIC, f):
        for x in r.findings:
            assert x.events and set(x.events) <= log and x.text.endswith(".")
            assert (x.kind == "gap") == bool(x.advice)
    assert sum(1 for r in score(RUBRIC, f) for x in r.findings if x.kind == "strength") == 4


def test_each_rule_cites_the_entries_that_prove_it():
    strong, weak = facts(STRONG, STRONG_FACTS), facts(WEAK, WEAK_FACTS)
    ev = lambda f, kind, **m: next(e for e in f.log if e["kind"] == kind and all(e.get(k) == v for k, v in m.items()))  # noqa: E731
    assert finding(strong, "first_update").events[0] == ev(strong, "message_posted")["id"]
    assert finding(strong, "read_the_migration").events[0] == ev(strong, "file_opened", path=MIGRATION)["id"]
    assert finding(strong, "regression_test_added").events[0] == ev(strong, "file_saved", path=REGRESSION)["id"]
    assert finding(strong, "reported_the_outcome").events[0] == ev(strong, "message_posted", message="C003")["id"]
    assert finding(strong, "reproduced_first").events[0] == ev(strong, "test_result")["id"]  # the first run's result line, "12 failed, 89 passed in 4.1s"
    # the gaps point at the moment that shows them
    assert finding(weak, "first_update").events[0] == ev(weak, "message_posted")["id"] and "05:30" in finding(weak, "first_update").text
    assert finding(weak, "no_nudges").events[0] == ev(weak, "team_message", ref="lead-nudge")["id"]
    assert finding(weak, "reproduced_first").events[0] == ev(weak, "file_saved", path=APPT)["id"] and "started editing at 01:00; the first test run came at 07:00" in finding(weak, "reproduced_first").text
    assert finding(weak, "no_pointer_needed").events[0] == ev(weak, "hint_given", n=1)["id"]
    assert finding(weak, "no_red_submit").events[0] == ev(weak, "submit_result", stage="tests")["id"]
    assert finding(weak, "review_clean").events[0] == ev(weak, "submit_result", stage="review")["id"]
    assert finding(weak, "few_hints").events[0] == ev(weak, "hint_given", n=2)["id"]
    assert finding(weak, "old_name_gone").text == f"slot_time is still used in {APPT}."


def test_time_to_first_update_and_the_leads_request():
    def with_post(t):
        steps = [s for s in STRONG if s[1] != "message_posted"] + [(t, "message_posted", {"message": "C9", "text": "slot_at is the new column", "to": []})]
        steps.sort(key=lambda s: s[0])
        if t > 90:  # the lead asks for an update when nothing was posted by 90 s
            steps.append((90, "team_message", {"message": "C8", "from": "architect", "text": "Any update?", "source": "scripted", "ref": "lead-update"}))
            steps.sort(key=lambda s: s[0])
        return facts(steps, STRONG_FACTS)

    assert finding(with_post(100), "first_update").kind == "strength"  # the limit is 120 s
    late = with_post(160)
    assert finding(late, "first_update").kind == "gap" and "02:40" in finding(late, "first_update").text
    assert finding(late, "answered_requests").kind == "gap" and "70 s later" in finding(late, "answered_requests").text  # asked at 90 s, answered at 160 s (the limit is 60 s)
    assert finding(with_post(60), "answered_requests").kind == "strength"  # posted before the lead had to ask


def test_every_file_with_the_old_name_must_be_fixed_and_the_rerun_decides_the_suite_rule():
    left = Facts(make_log(STRONG), old_name_files=[APPT, DOCT], rerun={"ok": False, "passed": 99, "failed": 3})
    assert finding(left, "old_name_gone").kind == "gap" and APPT in finding(left, "old_name_gone").text
    red = finding(left, "suite_green_on_main")
    assert red.kind == "gap" and "3 of 102 fail" in red.text
    none = Facts(make_log(STRONG), rerun=None)
    assert finding(none, "suite_green_on_main").kind == "gap" and "could not be re-run" in finding(none, "suite_green_on_main").text


def test_a_regression_test_only_counts_when_it_fails_on_the_seed_and_passes_on_the_fix():
    def with_reg(reg):
        return Facts(make_log(STRONG), **{**STRONG_FACTS, "regression": reg})

    ok = with_reg({"path": REGRESSION, "fails_on_seed": True, "passes_on_main": True})
    assert finding(ok, "regression_test_proves_fix").kind == "strength"
    passes_on_seed = finding(with_reg({"path": REGRESSION, "fails_on_seed": False, "passes_on_main": True}), "regression_test_proves_fix")
    assert passes_on_seed.kind == "gap" and "also passes on the broken code" in passes_on_seed.text
    broken_fix = finding(with_reg({"path": REGRESSION, "fails_on_seed": True, "passes_on_main": False}), "regression_test_proves_fix")
    assert broken_fix.kind == "gap" and "fails on your own fix" in broken_fix.text
    assert scores(with_reg({"path": REGRESSION, "fails_on_seed": False, "passes_on_main": True}))["testing"] == 3


def test_a_session_that_never_ran_a_test_or_posted_still_has_a_citation_for_every_point():
    steps = [(0, "session_started", {"scenario": ID, "role": "backend"}), (30, "file_saved", {"role": "backend", "path": APPT, "added": 1, "removed": 1, "size": 1}),
             (90, "team_message", {"message": "C1", "from": "architect", "text": "Any update?", "source": "scripted", "ref": "lead-update"}),
             (100, "submit", {"task": "h1"}), (110, "submit_result", {"task": "h1", "ok": False, "stage": "scope", "summary": "outside your files", "failed": [], "review_items": 0}),
             (120, "session_finished", {"ok": False})]
    f = Facts(make_log(steps))
    assert scores(f) == {"communication": 1, "diagnosis": 1, "fix_quality": 3, "testing": 1, "ownership": 1}
    results = score(RUBRIC, f)
    assert all(x.events and set(x.events) <= {e["id"] for e in f.log} for r in results for x in r.findings)
    assert finding(f, "no_scope_rejection").kind == "gap" and finding(f, "within_time_box").text == "The fix was not accepted."


def test_scoring_is_a_pure_function_of_the_log():
    a, b = facts(STRONG, STRONG_FACTS), facts(STRONG, STRONG_FACTS)
    assert [vars(x) for r in score(RUBRIC, a) for x in r.findings] == [vars(x) for r in score(RUBRIC, b) for x in r.findings]
    assert clock(63.9) == "01:03" and clock(-4) == "00:00"


# -- event text and quotes ---------------------------------------------------------------------------------------

def test_event_text_is_what_a_quote_must_match():
    f = facts(WEAK, WEAK_FACTS)
    by = lambda kind, **m: next(e for e in f.log if e["kind"] == kind and all(e.get(k) == v for k, v in m.items()))  # noqa: E731
    assert event_text(by("message_posted")) == "ok still on it" and event_text(by("file_saved", path=DOCT)) == f"Saved {DOCT} (+1 -1 lines)"
    assert event_text(by("submit_result", stage="tests")) == "3 tests still fail" and event_text(by("hint_given", n=2)) == "Hint 2 from Karan: I did not touch backend/. Have a look at database/migrations/0007."
    assert event_text(by("file_opened", path=MIGRATION)) == MIGRATION and event_text(by("submit")) == "Submit for review"
    msg = by("message_posted")
    assert quote_matches("OK still on it", msg) and quote_matches("“ok still on it…”", msg) and not quote_matches("ok it is fixed", msg) and not quote_matches("", msg)
    assert not quote_matches("ok", msg)  # too short to prove anything unless it is the whole text


# -- the verifier of the wording ---------------------------------------------------------------------------------

def findings_and_log():
    f = facts(WEAK, WEAK_FACTS)
    return [x for r in score(RUBRIC, f) for x in r.findings], f.log


def point(finding_id, event, quote, note="You were slow to update.", advice="Post earlier."):
    return PointWording(finding=finding_id, event=event, quote=quote, note=note, advice=advice)


def test_the_verifier_keeps_a_point_whose_event_and_quote_hold():
    findings, log = findings_and_log()
    f1 = next(x for x in findings if x.rule == "first_update")
    kept, dropped = verify_points([point(f1.id, f1.events[0], "still on it")], findings, log)
    assert list(kept) == [f1.id] and kept[f1.id].quote == "still on it" and dropped == []


def test_the_verifier_drops_invented_ids_and_quotes_and_records_why():
    findings, log = findings_and_log()
    f1 = next(x for x in findings if x.rule == "first_update")
    f2 = next(x for x in findings if x.rule == "no_nudges")
    other = next(e["id"] for e in log if e["kind"] == "test_run")  # a real entry that is not evidence for f1
    claims = [
        point(f1.id, "E999", "still on it"),                                           # the entry does not exist
        point(f1.id, f1.events[0], "I ran the tests five times"),                      # the quote is not in the entry
        point(f1.id, other, "Run tests (ide)"),                                         # real entry and quote, but not evidence for this point
        point("F99", f1.events[0], "still on it"),                                      # a point that does not exist
        point(f2.id, f2.events[0], "No update from you for 5 minutes", note="Look at E777 for the proof."),  # the sentence cites an entry that does not exist
        point(f2.id, f2.events[0], "No update from you for 5 minutes", note=" "),         # no sentence
    ]
    kept, dropped = verify_points(claims, findings, log)
    assert kept == {}
    reasons = [d.reason for d in dropped]
    assert reasons[0] == "event E999 is not in the session log" and "the quote is not in" in reasons[1] and "not evidence for this point" in reasons[2]
    assert reasons[3] == "there is no finding F99" and "does not exist" in reasons[4] and reasons[5] == "the point has no sentence"
    assert [d.finding for d in dropped] == [f1.id, f1.id, f1.id, "", f2.id, f2.id]


def test_a_second_sentence_for_the_same_point_is_dropped():
    findings, log = findings_and_log()
    f1 = next(x for x in findings if x.rule == "first_update")
    kept, dropped = verify_points([point(f1.id, f1.events[0], "still on it"), point(f1.id, f1.events[0], "still on it", note="Another one.")], findings, log)
    assert len(kept) == 1 and dropped[0].reason == "a second sentence for the same point"


# -- the wording call: the model, or the template when it cannot be used --------------------------------------------

class WordingLLM(ScenarioLLM):
    def __init__(self, points=None, fail=False, delay=0.0):
        super().__init__(fail=fail, delay=delay)
        self.points = points
        self.wording_calls = 0

    def call(self, model_id, messages, schema_model, temperature=0.2):
        if schema_model is WordingOutput:
            self.wording_calls += 1
            if self.delay:
                time.sleep(self.delay)
            if self.fail:
                from app.providers.base import ProviderError
                raise ProviderError("Ollama is not running")
            self.prompt = messages[0]["content"]
            return StructuredResult(WordingOutput(points=self.points or []), model_id, 1, 10, 5, 0.01, "{}")
        return super().call(model_id, messages, schema_model, temperature)


def test_the_model_is_asked_to_word_points_that_are_already_decided():
    findings, log = findings_and_log()
    llm = WordingLLM([point("F01", "E001", "x")])
    points, reason = Wordsmith(llm, available=lambda: True).word(findings, log)
    assert reason == "" and len(points) == 1 and llm.wording_calls == 1
    assert "[GAP]" in llm.prompt and "[STRENGTH]" in llm.prompt and "WORD FOR WORD" in llm.prompt and "ok still on it" in llm.prompt and "E" in llm.prompt


@pytest.mark.parametrize("llm,available,timeout,reason", [
    (WordingLLM(fail=True), True, 5, "error"),
    (WordingLLM(delay=1.0, points=[point("F01", "E001", "x")]), True, 0.2, "timeout"),
    (WordingLLM([point("F01", "E001", "x")]), False, 5, "unavailable"),
    (WordingLLM([]), True, 5, "invalid"),
    (None, True, 5, "unavailable"),
])
def test_the_wording_falls_back_to_the_template_when_the_model_cannot_be_used(llm, available, timeout, reason):
    findings, log = findings_and_log()
    points, why = Wordsmith(llm, available=lambda: available, timeout=timeout).word(findings, log)
    assert points is None and why == reason


def test_a_second_wording_call_while_the_first_is_going_is_not_made():
    findings, log = findings_and_log()
    slow = WordingLLM(delay=1.0, points=[point("F01", "E001", "x")])
    ws = Wordsmith(slow, timeout=5)
    first = threading.Thread(target=ws.word, args=(findings, log))
    first.start()
    time.sleep(0.2)
    assert ws.word(findings, log) == (None, "busy")
    first.join()


# -- the report -----------------------------------------------------------------------------------------------------

def report_for(steps, extra, wording=None, dropped=None, reason="", history=None, attempt=1):
    f = facts(steps, extra)
    return build_report(scenario=SCN, rubric=RUBRIC, attempt=attempt, project="opd-bookings-down", facts=f, results=score(RUBRIC, f), names=NAMES, wording=wording, dropped=dropped,
                        wording_reason=reason, history=history)


def test_the_report_of_a_strong_run():
    r = report_for(STRONG, STRONG_FACTS)
    assert r["total"] == 100 and r["max"] == 100 and r["attempt"] == 1 and r["rubric"] == {"id": "opd-bookings-down-v1", "version": 1}
    assert [(c["id"], c["score"], c["judge_name"]) for c in r["criteria"]] == [("communication", 4, "Aarav"), ("diagnosis", 4, "Karan"), ("fix_quality", 4, "Vikram"), ("testing", 4, "Ananya"), ("ownership", 4, "Aarav")]
    assert len(r["rows"]) == 20 and all(x["kind"] == "strength" and x["verified"] and x["quote"] and x["worded_by"] == "template" and x["advice"] == "" for x in r["rows"])
    fair = r["fairness"]
    assert (fair["points"], fair["quoted"], fair["matched"], fair["dropped"], fair["rubric"]) == (20, 20, 20, [], "v1") and fair["tests_rerun"] == {"ok": True, "passed": 102, "total": 102}
    assert r["focus"] and "full-marks" in r["focus"][0] and r["attempts"] == [r["attempts"][0]] and r["attempts"][0]["total"] == 100
    assert set(r["events"]) == {e for x in r["rows"] for e in x["events"]} and r["files"] == {"md": ".q/reports/attempt-1.md", "json": ".q/reports/attempt-1.json"}


def test_the_report_of_a_weak_run_has_gaps_with_advice_and_a_focus_list():
    r = report_for(WEAK, WEAK_FACTS)
    assert r["total"] == 20 and [c["score"] for c in r["criteria"]] == [0, 0, 2, 0, 2]
    gaps = [x for x in r["rows"] if x["kind"] == "gap"]
    assert len(gaps) == 16 and all(x["advice"] for x in gaps)
    assert len(r["focus"]) == 3 and r["focus"][0] == next(x["advice"] for x in r["rows"] if x["criterion"] == "communication" and x["kind"] == "gap")
    first = next(x for x in r["rows"] if x["rule"] == "first_update")
    assert first["quote"] == "ok still on it" and first["t"] == 330.0 and first["source"] == "#incident-opd · You" and r["events"][first["event"]]["text"] == "ok still on it"
    assert r["criteria"][0]["descriptor"] == RUBRIC.criterion("communication").descriptors["0"]


def test_wording_that_survived_the_verifier_replaces_the_template_and_the_drops_are_listed():
    f = facts(WEAK, WEAK_FACTS)
    findings = [x for res in score(RUBRIC, f) for x in res.findings]
    f1 = next(x for x in findings if x.rule == "first_update")
    kept, dropped = verify_points([point(f1.id, f1.events[0], "ok still on it", note="Your first update said nothing about the cause.", advice="Name the column in your first post."),
                                   point("F02", "E999", "never happened", note="You never ran the tests.")], findings, f.log)
    r = report_for(WEAK, WEAK_FACTS, kept, dropped, reason="")
    row = next(x for x in r["rows"] if x["rule"] == "first_update")
    assert row["worded_by"] == "model" and row["note"] == "Your first update said nothing about the cause." and row["advice"] == "Name the column in your first post."
    assert r["fairness"]["dropped"] == [{"finding": "F02", "text": "You never ran the tests.", "reason": "event E999 is not in the session log"}]
    assert r["fairness"]["wording"] == {"source": "mixed", "reason": "", "model_points": 1, "copied": 0} and r["fairness"]["points"] == 20 and r["fairness"]["matched"] == 20
    assert r["total"] == 20  # the wording never changes a score


def test_a_row_whose_quote_is_wrong_is_never_shown():
    f = facts(WEAK, WEAK_FACTS)
    findings = [x for res in score(RUBRIC, f) for x in res.findings]
    f1 = next(x for x in findings if x.rule == "first_update")
    forged = {f1.id: PointWording(finding=f1.id, event=f1.events[0], quote="we fixed it at 01:00", note="x", advice="y")}  # as if the verifier had been skipped
    r = report_for(WEAK, WEAK_FACTS, forged)
    row = next(x for x in r["rows"] if x["rule"] == "first_update")
    assert row["worded_by"] == "template" and row["quote"] == "ok still on it"
    assert r["fairness"]["dropped"][0]["reason"].startswith("the quote is not in") and r["fairness"]["matched"] == r["fairness"]["points"]


def test_the_markdown_report_lists_every_criterion_the_fairness_checks_and_the_attempts(tmp_path):
    r = report_for(WEAK, WEAK_FACTS, history=[{"attempt": 1, "total": 20, "scores": {}, "project": "a", "finished_at": "x", "elapsed": 1}], attempt=2)
    md = render_markdown(r, NAMES)
    assert md.startswith("# Debrief: Production incident: Bookings are down") and "**Attempt 2: 20/100**" in md
    assert "| Diagnosis | Karan | 0/4 |" in md and "## Fix quality 2/4" in md and "**GAP** 05:30 · #incident-opd · You · E" in md and "“ok still on it”" in md
    assert "Quotes matched to the session log: 20/20" in md and "Tests re-run, not guessed: 102/102" in md and "Same rubric for every attempt: v1" in md
    assert "## Focus for the next attempt" in md and "- Attempt 1: 20/100" in md


# -- the attempt history ---------------------------------------------------------------------------------------------

def test_attempts_are_numbered_from_the_finished_ones_and_the_history_survives(tmp_path):
    h = History(tmp_path, ID)
    assert h.attempts() == [] and h.next_number() == 1
    rec = lambda n, total: {"attempt": n, "total": total, "scores": {"communication": total // 5}, "project": f"p{n}", "finished_at": "2026-10-12T10:00:00", "elapsed": 100.0}  # noqa: E731
    assert [a["attempt"] for a in h.add(rec(1, 60))] == [1] and h.next_number() == 2
    h.add(rec(2, 80))
    assert [(a["attempt"], a["total"]) for a in History(tmp_path, ID).attempts()] == [(1, 60), (2, 80)] and History(tmp_path, ID).next_number() == 3
    h.add(rec(2, 85))  # the same attempt recorded twice replaces the first record
    assert [(a["attempt"], a["total"]) for a in h.attempts()] == [(1, 60), (2, 85)]
    assert History(tmp_path, "another-scenario").next_number() == 1


def test_a_damaged_history_file_starts_over_instead_of_stopping_a_session(tmp_path):
    h = History(tmp_path, ID)
    h.path.parent.mkdir(parents=True)
    h.path.write_text("{not json", encoding="utf-8")
    assert h.attempts() == [] and h.next_number() == 1
    h.path.write_text('{"attempt": 3}', encoding="utf-8")  # valid JSON, wrong shape
    assert h.attempts() == []


def test_the_report_carries_the_earlier_attempts_and_this_one():
    prior = [{"attempt": 1, "total": 60, "scores": {"communication": 3}, "project": "p1", "finished_at": "x", "elapsed": 200.0}]
    r = report_for(STRONG, STRONG_FACTS, history=prior, attempt=2)
    assert [(a["attempt"], a["total"]) for a in r["attempts"]] == [(1, 60), (2, 100)] and r["files"]["md"].endswith("attempt-2.md")
