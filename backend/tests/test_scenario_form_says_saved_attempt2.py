"""Hand-test of "The form says it saved", attempt 2 (95/100): the learner named the cause in the FIRST post ("call() in static/shell.js only throws when there is no JSON body, so
refused requests show saved") and the rule said "Your last post does not say what was broken". The post counts; the rule looks at every post, in all three scenarios."""
import json
from pathlib import Path

import pytest

from app.scenarios.loader import load_scenario
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import Facts, score

from scenario_fixtures import make_log
from scenario_fixtures_frontend import CAUSE, MEASURED_OK, REGRESSION

HERE = Path(__file__).parent
FORM = "opd-form-says-saved"
REAL = {"scan": None, "measured": MEASURED_OK, "rerun": {"ok": True, "passed": 121, "failed": 0, "summary": "121 passed"},
        "regression": {"path": "tests/regression/test_regression_refusals.py", "fails_on_seed": True, "passes_on_main": True,
                       "seed_summary": "1 failed in 0.12s", "main_summary": "1 passed"}}
LAST_POST = "Fix is ready: call() throws on every refused request, regression test passes, all green. Submitting."


def real_log() -> list[dict]:
    return [json.loads(x) for x in (HERE / "fixtures_real_form_says_saved_attempt2.jsonl").read_text(encoding="utf-8").splitlines()]


def cause_finding(scenario: str, facts: Facts):
    rubric = load_rubric(load_scenario(scenario))
    return next(x for r in score(rubric, facts) for x in r.findings if x.rule == "names_the_cause")


def test_the_real_first_post_names_the_cause_and_the_attempt_scores_100():
    posts = [e for e in real_log() if e["kind"] == "message_posted"]
    assert [p["id"] for p in posts] == ["E006", "E018"] and "only throws when there is no JSON body" in posts[0]["text"] and "cause" not in posts[1]["text"]
    f = Facts(real_log(), **REAL)
    rubric = load_rubric(load_scenario(FORM))
    results = score(rubric, f)
    assert {r.id: r.score for r in results} == {"communication": 4, "diagnosis": 4, "fix_quality": 4, "testing": 4, "ownership": 4}
    assert sum(r.score for r in results) * rubric.weight == 100  # it was 95: only "the cause named in the channel" was a gap
    found = cause_finding(FORM, f)
    assert found.kind == "strength" and found.events == ["E006"] and found.text == "At 00:21 you told the team what you had found."


@pytest.mark.parametrize("post", [
    CAUSE,
    'Update: the API refuses correctly, but call() in static/shell.js only throws when there is no JSON body, so refused requests show "saved". Fixing call() now.',
    "The server answers 409 and the page still shows saved.",
    "shell.js call() does not throw when the answer has a body.",
    "The page ignores the 409 and tells the user it worked.",
])
def test_these_posts_name_the_cause_of_the_form_scenario(post):
    f = Facts(make_log([(0, "session_started", {"scenario": FORM, "role": "frontend"}), (21, "message_posted", {"message": "C002", "text": post, "to": []})]), **REAL)
    assert cause_finding(FORM, f).kind == "strength"


@pytest.mark.parametrize("post", [
    "On it, looking at the booking form now.",
    "I opened shell.js and call() is a function.",
    "The tests fail, still working.",
    "Fix is ready, submitting.",
])
def test_these_posts_do_not(post):
    f = Facts(make_log([(0, "session_started", {"scenario": FORM, "role": "frontend"}), (21, "message_posted", {"message": "C002", "text": post, "to": []})]), **REAL)
    found = cause_finding(FORM, f)
    assert found.kind == "gap" and found.text == "Your last post, at 00:21, does not say what was broken."


@pytest.mark.parametrize("scenario, role, role_cause", [
    (FORM, "frontend", CAUSE),
    ("opd-bookings-down", "backend", "The deploy renamed slot_time to slot_at in the migration but the route still calls slot_time."),
    ("opd-double-bookings", "database", "There is no unique index on doctor, date and slot, so a second booking gets in."),
])
def test_every_scenario_looks_at_every_post_not_only_the_last(scenario, role, role_cause):
    """The cause is named in the first of three posts; the last two say nothing about it. The rule cites the first."""
    steps = [(0, "session_started", {"scenario": scenario, "role": role}),
             (21, "message_posted", {"message": "C002", "text": role_cause, "to": []}),
             (60, "message_posted", {"message": "C003", "text": "Still working on it.", "to": []}),
             (116, "message_posted", {"message": "C004", "text": LAST_POST, "to": []})]
    f = Facts(make_log(steps), scan=None, rerun={"ok": True, "passed": 1, "failed": 0})
    found = cause_finding(scenario, f)
    assert found.kind == "strength" and found.events[0] == "E002" and found.text == "At 00:21 you told the team what you had found."
    # and without that first post the same last two posts are a gap, and it is the last one that is quoted
    f = Facts(make_log(steps[:1] + steps[2:]), scan=None, rerun={"ok": True, "passed": 1, "failed": 0})
    found = cause_finding(scenario, f)
    assert found.kind == "gap" and found.text == "Your last post, at 01:56, does not say what was broken."
