"""Adapting a scenario to a job description: the weights (bounds and normalisation), the role-fit score, the key skills and the briefing with its verifier."""
import itertools

import pytest

from app.config import load_agents
from app.scenarios.jobs.adapt import BriefOutput, JobError, build_context, emphasised, key_skills, normalise, role_fit, template_briefing, verify_briefing, weights_for, word_briefing
from app.scenarios.jobs.extract import extract_keywords, prepare
from app.scenarios.jobs.modelcall import ModelGate
from app.scenarios.jobs.samples import sample_text
from app.scenarios.loader import load_scenario
from app.scenarios.reports import build_report
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import score

import scenario_fixtures as one
import scenario_fixtures_double as two
import scenario_fixtures_frontend as three
from jobs_helpers import JobLLM

CRITERIA = ["communication", "diagnosis", "fix_quality", "testing", "ownership"]
NAMES = {a.id: a.name for a in load_agents().values()}
SCN = {sid: load_scenario(sid) for sid in ("opd-bookings-down", "opd-double-bookings", "opd-form-says-saved")}
SAMPLE = {"opd-bookings-down": "backend-engineer", "opd-double-bookings": "database-engineer", "opd-form-says-saved": "frontend-engineer"}
CRIT_NAMES = {c.id: c.name for c in load_rubric(SCN["opd-bookings-down"]).criteria}


def ctx_for(sid):
    s = SCN[sid]
    text, clipped = prepare(sample_text(SAMPLE[sid]))
    return build_context(scenario=s, rubric=load_rubric(s), extraction=extract_keywords(text), text=text, clipped=clipped, source="sample", sample_id=SAMPLE[sid]), s


# -- weights -----------------------------------------------------------------------------------------------------

def test_a_posting_that_asks_for_nothing_in_particular_weighs_everything_the_same():
    w, why = weights_for("We are a friendly team. Come and work with us.", CRITERIA)
    assert w == {c: 1.0 for c in CRITERIA} and all(v == [] for v in why.values())


def test_a_posting_that_asks_for_everything_equally_also_weighs_everything_the_same():
    text = "communication, debugging, code review, testing, ownership. " * 3
    w, _ = weights_for(text, CRITERIA)
    assert set(w.values()) == {1.0}


def test_a_posting_that_leans_on_testing_weighs_testing_most_and_says_which_phrases():
    text = "Testing matters: unit tests, integration tests, pytest, TDD and CI/CD. We also like clear communication."
    w, why = weights_for(text, CRITERIA)
    assert max(w, key=w.get) == "testing" and w["testing"] > w["communication"] > w["ownership"]
    assert "pytest" in why["testing"] and "communicat" in why["communication"] and why["ownership"] == []


@pytest.mark.parametrize("raw", [
    {c: 2.5 for c in CRITERIA}, {c: 1.0 for c in CRITERIA}, {**{c: 1.0 for c in CRITERIA}, "testing": 2.5}, {**{c: 2.5 for c in CRITERIA}, "testing": 1.0},
    {"a": 50.0, "b": 0.01, "c": 1.0}, {"a": 0.0, "b": 0.0, "c": 0.0}, {"a": 100, "b": 100, "c": 100, "d": 0.001}, {"only": 7.0},
])
def test_weights_stay_in_bounds_and_average_one(raw):
    w = normalise(raw)
    assert set(w) == set(raw) and all(0.5 <= v <= 2.0 for v in w.values()) and abs(sum(w.values()) - len(raw)) <= 0.03 * len(raw)


def test_weights_keep_the_order_of_the_raw_values():
    raw = {"a": 1.0, "b": 1.5, "c": 2.0, "d": 2.5, "e": 1.0}
    w = normalise(raw)
    assert w["d"] >= w["c"] >= w["b"] >= w["a"] and w["a"] == w["e"]


def test_every_combination_of_hits_gives_bounded_weights():
    for hits in itertools.product(range(0, 5), repeat=5):
        raw = {c: 1.0 + 0.5 * min(h, 3) for c, h in zip(CRITERIA, hits)}
        w = normalise(raw)
        assert all(0.5 <= v <= 2.0 for v in w.values()) and abs(sum(w.values()) - 5) <= 0.06, (hits, w)


def test_the_weights_of_the_same_posting_are_always_the_same():
    t = sample_text("backend-engineer")
    assert weights_for(t, CRITERIA) == weights_for(t, CRITERIA)


# -- role fit ----------------------------------------------------------------------------------------------------

def reports():
    out = {}
    for sid, fx in (("opd-bookings-down", one), ("opd-double-bookings", two), ("opd-form-says-saved", three)):
        s = SCN[sid]
        rubric = load_rubric(s)
        for variant, steps, extra in (("strong", fx.STRONG, fx.STRONG_FACTS), ("weak", fx.WEAK, fx.WEAK_FACTS)):
            f = fx.facts(steps, extra, minutes=s.minutes)
            out[(sid, variant)] = build_report(scenario=s, rubric=rubric, attempt=1, project=sid, facts=f, results=score(rubric, f), names=NAMES, history=[])
    return out


REPORTS = reports()


def scores_of(report):
    return {c["id"]: c["score"] for c in report["criteria"]}


def test_equal_weights_give_the_standard_score_on_every_fixture():
    for report in REPORTS.values():
        assert role_fit(scores_of(report), 4, {c: 1.0 for c in CRITERIA}) == report["total"]
        assert role_fit(scores_of(report), 4, {}) == report["total"]  # a criterion without a weight counts 1.0


def test_a_full_marks_run_is_full_role_fit_whatever_the_weights():
    for sid in SCN:
        strong = REPORTS[(sid, "strong")]
        assert strong["total"] == 100
        assert role_fit(scores_of(strong), 4, {"communication": 0.5, "diagnosis": 2.0, "fix_quality": 0.5, "testing": 1.0, "ownership": 1.0}) == 100


def test_emphasis_moves_role_fit_the_way_the_weights_say():
    weights = {"communication": 0.5, "diagnosis": 0.5, "fix_quality": 2.0, "testing": 0.5, "ownership": 1.5}  # sums to 5
    weak1 = REPORTS[("opd-bookings-down", "weak")]
    assert weak1["total"] == 20 and role_fit(scores_of(weak1), 4, weights) == 35  # fix quality (2/4) and ownership (2/4) count more
    weak2 = REPORTS[("opd-double-bookings", "weak")]
    assert weak2["total"] == 30 and role_fit(scores_of(weak2), 4, weights) == 55  # fix quality is 4/4 there
    testing_heavy = {"communication": 0.5, "diagnosis": 0.5, "fix_quality": 0.5, "testing": 2.0, "ownership": 1.5}
    assert role_fit(scores_of(weak2), 4, testing_heavy) < weak2["total"]  # the weak run did no testing: more weight on it hurts


def test_role_fit_of_nothing_is_zero():
    assert role_fit({}, 4, {}) == 0 and role_fit({"a": 0}, 4, {"a": 1.0}) == 0


# -- key skills and the context -----------------------------------------------------------------------------------

def test_key_skills_put_the_ones_the_incident_exercises_first_and_stop_at_five():
    e = extract_keywords(sample_text("backend-engineer"))
    k = key_skills(e, SCN["opd-bookings-down"].fit.skills)
    assert 3 <= len(k) <= 5 and set(k) <= set(e.skills) and k[0] in SCN["opd-bookings-down"].fit.skills
    assert key_skills(e, ["docker", "aws"])[:2] == ["docker", "aws"]
    assert key_skills(extract_keywords("Engineer"), ["python"]) == []


@pytest.mark.parametrize("sid", list(SAMPLE))
def test_the_context_of_each_sample_holds_everything_the_report_saves(sid):
    ctx, s = ctx_for(sid)
    assert ctx.match.scenario == sid and ctx.match.rank == 1 and [m.scenario for m in ctx.ranking][0] == sid and len(ctx.ranking) == 3
    assert set(ctx.weights) == set(CRITERIA) and set(ctx.weight_reasons) == set(CRITERIA) and 3 <= len(ctx.key_skills) <= 5
    assert ctx.briefing.source == "template" and s.title in ctx.briefing.text and ctx.source == "sample" and ctx.sample_id == SAMPLE[sid]


def test_a_scenario_without_a_fit_block_cannot_be_adapted():
    s = SCN["opd-bookings-down"].model_copy(update={"fit": None})
    with pytest.raises(JobError):
        build_context(scenario=s, rubric=load_rubric(s), extraction=extract_keywords("Backend Engineer\nPython"), text="x", clipped=False, source="paste")


def test_the_context_for_a_scenario_that_is_not_the_best_fit_still_explains_it():
    s = SCN["opd-form-says-saved"]
    text, _ = prepare(sample_text("backend-engineer"))
    ctx = build_context(scenario=s, rubric=load_rubric(s), extraction=extract_keywords(text), text=text, clipped=False, source="paste")
    assert ctx.match.rank == 3 and ctx.ranking[0].scenario == "opd-bookings-down" and "Frontend engineer seat" in ctx.match.reason


def test_the_template_briefing_names_the_seat_the_skills_and_the_emphasis():
    ctx, s = ctx_for("opd-form-says-saved")
    t = ctx.briefing.text
    assert "Frontend engineer seat" in t and "25 minutes" in t and "javascript" in t and "Fix quality" in t and "most" in t
    flat = template_briefing(extract_keywords("Backend Engineer\nPython and SQL."), SCN["opd-bookings-down"], ctx.match, {c: 1.0 for c in CRITERIA}, CRIT_NAMES, ["python", "sql"])
    assert "equal your standard score" in flat
    assert emphasised({c: 1.0 for c in CRITERIA}, CRIT_NAMES) == []


# -- the briefing verifier ---------------------------------------------------------------------------------------------

GOOD = ("This incident puts you in the Backend engineer seat for 25 minutes: the posting asks for Python, FastAPI and pytest, and “Production incident: Bookings are down” "
        "exercises all three, so you will practise them on a real fault.")


def check(text, sid="opd-bookings-down"):
    ctx, s = ctx_for(sid)
    return verify_briefing(text, ctx.extraction, s, CRIT_NAMES)


def test_a_grounded_paragraph_passes():
    assert check(GOOD) is None


@pytest.mark.parametrize("text,why", [
    ("Too short.", "characters"),
    (GOOD.replace("Python", "Kubernetes"), "Kubernetes"),
    (GOOD + " You will also use Terraform and GraphQL.", "skill"),
    (GOOD.replace("25 minutes", "40 minutes"), "number 40"),
    (GOOD + " Your reviewer is the architect.", "role id"),
    (GOOD + " Great job on your communication, diagnosis and testing skills.", "praise"),
    (GOOD + " The incident ends at 08:45.", "time"),
    (GOOD + " You will use SomeWidgetKit.", "SomeWidgetKit"),
    (GOOD + " It is a “foo bar service” incident.", "quoted"),
    ("The posting asks for Python, FastAPI and pytest, and the incident exercises all three, so you will practise them on a real fault in a hospital booking app.", "seat"),
    ("x " * 400, "characters"),
])
def test_a_paragraph_with_anything_not_in_the_facts_is_refused(text, why):
    assert why.lower() in (check(text) or "").lower()


def test_the_model_wording_is_used_when_it_passes_and_the_template_stays_otherwise():
    ctx, s = ctx_for("opd-bookings-down")
    ok, why = word_briefing(ctx, s, CRIT_NAMES, JobLLM(brief=BriefOutput(paragraph=GOOD)), available=lambda: True, gate=ModelGate())
    assert why == "" and ok.source == "model" and ok.text == GOOD
    bad, why = word_briefing(ctx, s, CRIT_NAMES, JobLLM(brief=BriefOutput(paragraph=GOOD.replace("Python", "Kubernetes"))), available=lambda: True, gate=ModelGate())
    assert bad is None and "kubernetes" in why
    for llm, avail in ((JobLLM(fail=True), True), (JobLLM(invalid=True), True), (JobLLM(brief=BriefOutput(paragraph=GOOD)), False), (None, True)):
        got, why = word_briefing(ctx, s, CRIT_NAMES, llm, available=lambda a=avail: a, gate=ModelGate())
        assert got is None and why


def test_a_slow_model_leaves_the_template_in_place():
    ctx, s = ctx_for("opd-bookings-down")
    got, why = word_briefing(ctx, s, CRIT_NAMES, JobLLM(brief=BriefOutput(paragraph=GOOD), delay=1.0), available=lambda: True, timeout=0.1, gate=ModelGate())
    assert got is None and "took more than" in why
