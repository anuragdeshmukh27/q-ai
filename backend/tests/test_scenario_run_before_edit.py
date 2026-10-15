"""The Diagnosis rule "the tests run before the first edit", for both scenarios: a run counts when it was STARTED before the first save, whenever its result came in, and the verdict
agrees with the hand-testers' real session logs (no run is lost between the Run tests button and the log)."""
import json
from pathlib import Path

import pytest

from app.scenarios.loader import load_scenario
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import Facts, score

import scenario_fixtures as one
from scenario_fixtures_double import STRONG as TWO_STRONG, STRONG_FACTS as TWO_FACTS

HERE = Path(__file__).parent
FIRST = load_rubric(load_scenario("opd-bookings-down"))
SECOND = load_rubric(load_scenario("opd-double-bookings"))


def reproduced(rubric, f: Facts):
    return next(x for r in score(rubric, f) for x in r.findings if x.rule == "reproduced_first")


def test_the_first_scenario_counts_a_run_started_before_the_first_edit_whose_result_came_after():
    first_edit = next(t for t, k, _ in one.STRONG if k == "file_saved")
    steps = sorted([(first_edit + 1 if (t, k) == (26, "test_result") else t, k, v) for t, k, v in one.STRONG], key=lambda s: s[0])
    x = reproduced(FIRST, one.facts(steps, one.STRONG_FACTS))
    assert x.kind == "strength" and x.text == "You started the tests at 00:20, before the first edit."


@pytest.mark.parametrize("scenario,rubric,strong,extra", [("first", FIRST, one.STRONG, one.STRONG_FACTS), ("second", SECOND, TWO_STRONG, TWO_FACTS)])
def test_a_run_before_the_first_edit_is_credited_and_one_after_it_is_not(scenario, rubric, strong, extra):
    assert reproduced(rubric, Facts(_events(strong), minutes=30, **extra)).kind == "strength"
    first_edit = next(t for t, k, _ in strong if k == "file_saved")
    late = [(t, k, v) for t, k, v in strong if k not in ("test_run", "test_result") or t > first_edit]
    assert reproduced(rubric, Facts(_events(late), minutes=30, **extra)).kind == "gap"


def _events(steps):
    from scenario_fixtures import make_log
    return make_log(sorted(steps, key=lambda s: s[0]))


@pytest.mark.parametrize("name", ["fixtures_real_run_attempt1.jsonl", "fixtures_real_run_attempt2.jsonl", "fixtures_real_run_attempt3.jsonl", "fixtures_real_double_attempt1.jsonl"])
def test_the_verdict_follows_the_real_log(name):
    """Every real attempt: the rule credits a run exactly when the log holds a test_run before the first file_saved."""
    log = [json.loads(x) for x in (HERE / name).read_text(encoding="utf-8").splitlines()]
    edit = next((e for e in log if e["kind"] == "file_saved"), None)
    ran = any(e["kind"] == "test_run" and (edit is None or e["id"] < edit["id"]) for e in log)
    double = "double" in name
    f = Facts(log, minutes=30 if double else 25, scan=None, rerun={"ok": True, "passed": 100, "failed": 0}, regression=None)
    assert (reproduced(SECOND if double else FIRST, f).kind == "strength") == ran
