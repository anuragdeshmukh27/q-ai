"""The coach paragraph's prompt: it says up front what `verify_voice` checks afterwards (three sentences in a fixed shape, only the facts given, no praise words, no criterion names, never
full marks for a full-marks run). The verifier itself is not changed here: a paragraph in the prompt's shape has to pass it, for both scenarios and for a strong and a weak run."""
import pytest

from app.scenarios.scoring import clock
from app.scenarios.wording import Wordsmith, coach_moments, verify_voice

from test_scenario_double_bookings_scoring import report_for as report_two
from test_scenario_voices import good_coach, moments, strong_report, weak_report
from scenario_fixtures_double import STRONG as STRONG_TWO, STRONG_FACTS as STRONG_TWO_FACTS, WEAK as WEAK_TWO, WEAK_FACTS as WEAK_TWO_FACTS

REPORTS = {
    "bookings strong": strong_report,
    "bookings weak": weak_report,
    "double bookings strong": lambda: report_two(STRONG_TWO, STRONG_TWO_FACTS),
    "double bookings weak": lambda: report_two(WEAK_TWO, WEAK_TWO_FACTS),
}
REFUSED = ["great", "good", "excellent", "impressive", "strong", "well done", "showed", "demonstrated", "skills", "problem-solving", "overall"]


def prompt_of(r: dict) -> str:
    return Wordsmith._prompt(r, moments(r))[0]["content"]


@pytest.mark.parametrize("name", REPORTS)
def test_the_prompt_gives_the_coach_its_facts_its_shape_and_its_refused_words(name):
    r = REPORTS[name]()
    prompt, cm = prompt_of(r), coach_moments(r)
    block = prompt[prompt.index("PART 2"):prompt.index("Reply with JSON")]
    assert "exactly three sentences" in block and "Facts you may use (nothing else" in block and "mm:ss" in block
    assert f"the strength at {clock(cm['strength']['t'])}: {cm['strength']['note']}" in block
    if cm["gap"]:
        assert f"the gap at {clock(cm['gap']['t'])}: {cm['gap']['note']}" in block and "Next time, first" in block and f'"At {clock(cm["gap"]["t"])} you' in block
    else:
        assert "the gap at" not in block and "nothing to fix" in block
    assert all(w in block for w in REFUSED) and "Do not write the name of a criterion (Communication, Diagnosis, Fix quality, Testing, Ownership)" in block
    assert f"the total score is {r['total']}/{r['max']}" in block and "focus for the next attempt" in block
    assert prompt.index("PART 1") < prompt.index("PART 2") < prompt.index("Reply with JSON")  # the coach block is a block of its own, not buried in the judges' paragraph


@pytest.mark.parametrize("name", REPORTS)
def test_a_paragraph_in_the_shape_of_the_prompt_passes_the_unchanged_verifier(name):
    r = REPORTS[name]()
    text = good_coach(r) + (f" Next time beat the time of {clock(r['elapsed'])} or move on to the next scenario." if r["total"] >= r["max"] else "")
    assert verify_voice(text, r, None, "coach") is None, verify_voice(text, r, None, "coach")


def test_the_refused_words_in_the_prompt_are_the_ones_the_verifier_refuses():
    """The prompt may not forbid less than the verifier does: every phrase of its list is refused by `verify_voice` (or is a criterion-praise pattern it checks)."""
    r = weak_report()
    cm = coach_moments(r)
    base = good_coach(r)
    for phrase in ("great job", "excellent", "impressive", "well done", "problem-solving", "overall", "showed great communication"):
        assert verify_voice(f"{base} {phrase}.", r, None, "coach"), phrase
    assert verify_voice(base, r, None, "coach") is None and cm["strength"] is not None


def test_the_full_marks_prompt_has_no_gap_and_forbids_asking_for_a_perfect_run():
    for name in ("bookings strong", "double bookings strong"):
        r = REPORTS[name]()
        block = prompt_of(r)[prompt_of(r).index("PART 2"):]
        assert r["total"] == 100 and "the gap at" not in block
        assert "never ask for full marks or a perfect run" in block and "beat the time or to move on to the next scenario" in block
        assert f"Say that the total was {r['total']}/{r['max']}" in block
