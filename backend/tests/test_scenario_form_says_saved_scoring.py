"""The rubric of "The form says it saved": its rules over a strong and a weak session, the measure that runs the pages of the merged project against the real answers of the API, and the report."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import load_agents
from app.scenarios.loader import load_scenario
from app.scenarios.measures import MEASURES, refusals
from app.scenarios.reports import build_report
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import Facts, event_text, score

from scenario_fixtures import make_log
from scenario_fixtures_frontend import API_TEST, CAUSE, MAIN, MEASURED_OK, REGRESSION, SHELL, STRONG, STRONG_FACTS, STRONG_SCORES, WEAK, WEAK_FACTS, WEAK_SCORES, facts

ID = "opd-form-says-saved"
SCN = load_scenario(ID)
RUBRIC = load_rubric(SCN)
NAMES = {a.id: a.name for a in load_agents().values()}
SEED = SCN.seed_dir
FIXES = Path(__file__).parent / "scenario_fixes" / "form-says-saved"
REFERENCE = SCN.folder / "autoplay" / "fix.patch"


def scores(f: Facts) -> dict:
    return {r.id: r.score for r in score(RUBRIC, f)}


def finding(f: Facts, rule: str):
    return next(x for r in score(RUBRIC, f) for x in r.findings if x.rule == rule)


def test_the_rubric_has_the_same_five_criteria_with_rohan_judging_the_diagnosis():
    assert RUBRIC.id == SCN.rubric == "opd-form-says-saved-v1" and RUBRIC.max_total == 100 and RUBRIC.measures == ["refusals"]
    assert [(c.name, NAMES[c.judge]) for c in RUBRIC.criteria] == [("Communication", "Aarav"), ("Diagnosis", "Rohan"), ("Fix quality", "Vikram"), ("Testing", "Ananya"), ("Ownership", "Aarav")]
    assert [[r.id for r in c.rules] for c in RUBRIC.criteria] == [
        ["first_update", "answered_requests", "no_nudges", "names_the_cause"],
        ["reproduced_first", "read_the_response", "found_the_failing_code", "no_pointer_needed"],
        ["every_path_reports_refusal", "refusal_message_shown", "small_change", "suite_green_on_main"],
        ["green_before_submit", "no_red_submit", "regression_test_added", "regression_test_proves_fix"],
        ["within_time_box", "few_hints", "no_scope_rejection", "reported_the_outcome"]]
    assert all(len(c.rules) == 4 and sorted(c.descriptors) == ["0", "1", "2", "3", "4"] for c in RUBRIC.criteria)
    assert "no backend change attempted" in next(r.label for c in RUBRIC.criteria for r in c.rules if r.id == "no_scope_rejection")


def test_a_strong_run_scores_every_point():
    f = facts(STRONG, STRONG_FACTS)
    assert scores(f) == STRONG_SCORES and sum(scores(f).values()) * RUBRIC.weight == 100
    findings = [x for r in score(RUBRIC, f) for x in r.findings]
    assert len(findings) == 20 and all(x.kind == "strength" and x.advice == "" for x in findings)
    assert [e["check"] for e in f.log if e["kind"] == "debrief_check"] == ["rerun", "regression", "change", "counts", "refusal_paths", "refusal_message"]


def test_a_weak_run_scores_30_and_every_gap_cites_a_real_entry():
    f = facts(WEAK, WEAK_FACTS)
    assert scores(f) == WEAK_SCORES and sum(scores(f).values()) * RUBRIC.weight == 30
    log = {e["id"] for e in f.log}
    for r in score(RUBRIC, f):
        for x in r.findings:
            assert x.events and set(x.events) <= log
            assert (x.kind == "gap") == bool(x.advice)


def test_each_new_rule_cites_the_entry_that_proves_it():
    strong, weak = facts(STRONG, STRONG_FACTS), facts(WEAK, WEAK_FACTS)
    by = lambda f, kind, **m: next(e for e in f.log if e["kind"] == kind and all(e.get(k) == v for k, v in m.items()))  # noqa: E731
    assert finding(strong, "read_the_response").events[0] == by(strong, "file_opened", path=API_TEST)["id"]
    assert finding(strong, "read_the_response").text.startswith("You opened what the server answers (tests/api/test_double_booking_api.py)")
    assert finding(strong, "found_the_failing_code").events[0] == by(strong, "file_opened", path=SHELL)["id"]
    assert finding(strong, "every_path_reports_refusal").events[0] == strong.check("refusal_paths")["id"]
    assert finding(strong, "refusal_message_shown").events[0] == strong.check("refusal_message")["id"]
    assert finding(strong, "regression_test_added").events[0] == by(strong, "file_saved", path=REGRESSION)["id"]
    assert finding(weak, "read_the_response").text == "By your first edit at 01:00 you had not opened what the server answers."
    assert finding(weak, "found_the_failing_code").text == "By your first edit at 01:00 you had not opened the code that sends the requests."  # the IDE's own first open does not count
    assert finding(weak, "no_pointer_needed").events[0] == by(weak, "hint_given", n=1)["id"]
    assert finding(weak, "no_pointer_needed").text == "A teammate had to point you at the page code at 04:00."


def test_a_search_counts_as_reading_the_answer_and_the_code_but_only_before_the_first_edit():
    steps = sorted([s for s in STRONG if s[1] != "file_opened"] + [(36, "search", {"role": "frontend", "query": "res.ok", "matches": 3, "files": 1})], key=lambda s: s[0])
    f = facts(steps, STRONG_FACTS)  # the search for 409 (answer) and for res.ok (code), no file opened
    assert finding(f, "read_the_response").kind == "strength" and "searched the project for “409”" in finding(f, "read_the_response").text
    assert finding(f, "found_the_failing_code").kind == "strength" and "searched the project for “res.ok”" in finding(f, "found_the_failing_code").text
    late = sorted([(t + 200 if k == "file_opened" else t, k, v) for t, k, v in STRONG if k != "search"], key=lambda s: s[0])
    assert finding(facts(late, STRONG_FACTS), "read_the_response").kind == "gap"  # opened after the first save
    assert finding(facts(late, STRONG_FACTS), "found_the_failing_code").kind == "gap"


def test_the_pointer_is_not_held_against_a_learner_who_had_opened_the_page_code_first():
    steps = sorted([*STRONG, (240, "hint_given", {"message": "C9", "from": "backend", "source": "scripted", "reason": "timeline", "question": "", "text": "Look at call().", "n": 1})], key=lambda s: s[0])
    assert finding(facts(steps, STRONG_FACTS), "no_pointer_needed").kind == "strength"  # shell.js was opened at 68 s
    weak_steps = sorted([*WEAK, (250, "file_opened", {"role": "frontend", "path": SHELL})], key=lambda s: s[0])
    assert finding(facts(weak_steps, WEAK_FACTS), "no_pointer_needed").kind == "gap"  # opened after the pointer


# -- the measure: the pages of the merged project, run in Node on the real answers of the API ---------------------------

def project_with(tmp_path: Path, patch: Path | None) -> Path:
    root = tmp_path / "merged"
    shutil.copytree(SEED, root, ignore=shutil.ignore_patterns("__pycache__", "fonts"))
    if patch is not None:
        subprocess.run(["git", "apply", str(patch)], cwd=root, check=True)
    return root


def measured(tmp_path, patch: Path | None) -> dict:
    return refusals(project_with(tmp_path, patch), SEED, {})


def test_the_measure_is_registered_and_the_reference_fix_passes_both_checks(tmp_path):
    assert MEASURES["refusals"] is refusals
    m = measured(tmp_path, REFERENCE)
    assert {k: (v["ok"], v["passed"], v["of"]) for k, v in m.items()} == {"refusal_paths": (True, 8, 8), "refusal_message": (True, 8, 8)}
    assert m["refusal_paths"]["text"] == MEASURED_OK["refusal_paths"]["text"] and m["refusal_message"]["text"] == MEASURED_OK["refusal_message"]["text"]  # the fixtures say what the real measure says


NAIVE_RESULTS = [
    # name: (cases that show an error, cases that show the server's message)
    ("naive_create_form_only", (4, 4)),  # the booking form, a bad phone, the doctor and prescription forms look at the answer; edit, buttons, delete and board do not
    ("naive_409_only", (5, 5)),  # a conflict throws; a 400 and a 404 do not
    ("naive_buttons_only", (3, 3)),  # Complete or Cancel, delete and the board look at the answer; no form does
    ("naive_message_lost", (8, 0)),  # every refusal is an error, but nobody reads why
    ("naive_appointments_only", (6, 6)),  # passes the six acceptance tests, but the doctor and prescription forms still say they saved
]


@pytest.mark.parametrize("name,expected", NAIVE_RESULTS, ids=[n for n, _ in NAIVE_RESULTS])
def test_every_naive_fix_fails_the_measure_that_names_its_mistake(tmp_path, name, expected):
    m = measured(tmp_path, FIXES / f"{name}.patch")
    assert (m["refusal_paths"]["passed"], m["refusal_message"]["passed"]) == expected, {k: v["text"] for k, v in m.items()}
    assert not m["refusal_paths"]["ok"] or not m["refusal_message"]["ok"]


def test_the_measure_says_what_went_wrong_in_the_entry_a_point_quotes(tmp_path):
    seed = measured(tmp_path, None)
    assert seed["refusal_paths"]["text"].startswith("Debrief check of the pages: 0 of 8 refused requests show an error; still reported as saved: a taken slot in the booking form")
    only = measured(tmp_path / "b", FIXES / "naive_appointments_only.patch")
    assert only["refusal_paths"]["failed"] == ["a taken email in the doctor form", "a bad number of days in the prescription form"]
    assert "a taken email in the doctor form, a bad number of days in the prescription form" in only["refusal_paths"]["text"]
    lost = measured(tmp_path / "c", FIXES / "naive_message_lost.patch")
    assert lost["refusal_paths"]["ok"] and "reaches the person in 0 of 8 cases" in lost["refusal_message"]["text"]


def test_a_page_that_cannot_run_is_reported_as_such_not_as_a_pass(tmp_path):
    root = project_with(tmp_path, REFERENCE)
    (root / "static" / "shell.js").write_text("this is not javascript (", encoding="utf-8")
    m = refusals(root, SEED, {})
    assert not m["refusal_paths"]["ok"] and m["refusal_paths"]["error"] and "could not be run on your change" in m["refusal_paths"]["text"]
    f = Facts(make_log(STRONG), scan=None, measured=m, rerun={"ok": True, "passed": 121, "failed": 0}, regression=STRONG_FACTS["regression"])
    assert finding(f, "every_path_reports_refusal").text == "The pages could not be run on your change, so no refused request was shown correctly."
    assert scores(f)["fix_quality"] == 2  # a small change and a suite that was green: the two points that do not depend on the pages


def test_a_learner_cannot_change_the_probe_or_the_answers_the_measure_runs_on(tmp_path):
    """The probe, the fake browser and the real answers are the seed's: the merged project's own copies are not used (they are read-only to the learner anyway)."""
    root = project_with(tmp_path, None)  # the broken page
    (root / "tests" / "ui" / "refusals.mjs").write_text("console.log(JSON.stringify({formOpen: true, formError: 'x', toasts: [], writes: []}))\n", encoding="utf-8")
    (root / "tests" / "ui" / "answers.json").write_text("{}", encoding="utf-8")
    assert not refusals(root, SEED, {})["refusal_paths"]["ok"]


def test_a_measure_that_could_not_run_is_a_gap_not_a_guess():
    f = Facts(make_log(STRONG), scan=None, rerun=None)  # no measurement at all
    for rule in ("every_path_reports_refusal", "refusal_message_shown"):
        x = finding(f, rule)
        assert x.kind == "gap" and x.text == "Q could not run the pages on your change." and x.events


def test_fix_quality_follows_the_measure(tmp_path):
    for name, points in (("naive_create_form_only", 2), ("naive_message_lost", 3), ("naive_appointments_only", 2)):
        m = measured(tmp_path / name, FIXES / f"{name}.patch")
        f = Facts(make_log(STRONG), scan=None, measured=m, rerun={"ok": True, "passed": 121, "failed": 0}, regression=STRONG_FACTS["regression"])
        assert scores(f)["fix_quality"] == points, name


def test_a_big_rewrite_is_not_a_small_change():
    steps = [(t, k, {**v, "added": 120, "removed": 80} if v.get("path") == SHELL and k == "file_saved" else v) for t, k, v in STRONG]
    x = finding(facts(steps, STRONG_FACTS), "small_change")
    assert x.kind == "gap" and x.text == "200 lines changed in 1 file, more than the 20 the problem needs."


# -- the report ------------------------------------------------------------------------------------------------

def report_for(steps, extra):
    f = facts(steps, extra)
    return build_report(scenario=SCN, rubric=RUBRIC, attempt=1, project=ID, facts=f, results=score(RUBRIC, f), names=NAMES, history=[])


def test_the_report_of_the_strong_run_quotes_every_point_and_names_the_channel():
    r = report_for(STRONG, STRONG_FACTS)
    assert r["total"] == 100 and [c["score"] for c in r["criteria"]] == [4, 4, 4, 4, 4] and r["fairness"]["dropped"] == []
    assert [c["judge_name"] for c in r["criteria"]] == ["Aarav", "Rohan", "Vikram", "Ananya", "Aarav"]
    assert len(r["rows"]) == 20 and all(row["verified"] for row in r["rows"])
    assert any(row["source"] == "#incident-frontdesk · You" for row in r["rows"]) and not any("#incident-opd" in row["source"] for row in r["rows"])
    quotes = {row["rule"]: row["quote"] for row in r["rows"]}
    assert quotes["every_path_reports_refusal"].startswith("Debrief check of the pages: all 8 refused requests")
    for row in r["rows"]:
        assert row["quote"] in " ".join(event_text(r["events"][e]) for e in row["events"]) or row["quote"].endswith("…")


def test_the_report_of_the_weak_run():
    r = report_for(WEAK, WEAK_FACTS)
    assert r["total"] == 30 and r["fairness"]["dropped"] == [] and "no_scope_rejection" in {row["rule"] for row in r["rows"] if row["kind"] == "strength"}
    assert r["focus"][0].startswith("Post a first update") or r["focus"][0].startswith("Run the tests")


# -- the cause named in the channel ------------------------------------------------------------------------------

def post_only(text: str) -> Facts:
    """The strong run with its one update replaced by `text` (the other post, 'Fix is ready', never names a cause)."""
    return facts([(t, k, {**v, "text": text} if v.get("message") == "C003" else v) for t, k, v in STRONG], STRONG_FACTS)


@pytest.mark.parametrize("text", [
    CAUSE,
    "The page ignores the 409: call() never checks res.ok, so the form closes and says saved.",
    "The page treats a refused answer as a success.",
    "call() swallows the error answer from the server.",
    "It does not check the status of the response, so any answer counts as saved.",
    "The form says it saved even though the server refused the booking.",
    "A 409 is treated like a success by the shell.",
    "The shell never checks res.ok.",
])
def test_the_cause_is_named_when_a_post_says_the_page_ignores_the_refusal(text):
    assert finding(post_only(text), "names_the_cause").kind == "strength"


@pytest.mark.parametrize("text", [
    "Sorry, still working on it. I think the booking form needs to read the answer.",
    "The form says it saved.",
    "Rohan, can you help? The other screens still fail and I do not know why.",
    "Still looking at the page.",
    "Fix is ready: call() now throws for any refused answer, so every form shows the server's message. Submitting now.",
    "On it. I am running the tests first, then I read what the server answers.",
    "I will check the status code next.",
])
def test_a_status_report_or_a_fix_alone_does_not_name_the_cause(text):
    x = finding(post_only(text), "names_the_cause")
    assert x.kind == "gap" and "does not say what was broken" in x.text and "does not treat a refused answer" in x.advice


def test_the_weak_run_does_not_get_the_point_for_saying_it_needs_to_read_the_answer():
    f = facts(WEAK, WEAK_FACTS)
    x = finding(f, "names_the_cause")
    assert x.kind == "gap" and x.text == "Your last post, at 05:30, does not say what was broken."
