"""Matching a reading of a job description to the scenarios: fixed rules, reasons built from the numbers, and the plug-in point for generated scenarios (Part B)."""
import pytest

from app.scenarios.jobs import match
from app.scenarios.jobs.extract import extract_keywords, prepare
from app.scenarios.jobs.match import candidates, rank
from app.scenarios.jobs.samples import sample_text
from app.scenarios.jobs.schema import Candidate, JobExtraction
from app.scenarios.loader import list_scenarios

OWN = {"backend-engineer": "opd-bookings-down", "database-engineer": "opd-double-bookings", "frontend-engineer": "opd-form-says-saved"}


def read(sid):
    return extract_keywords(prepare(sample_text(sid))[0])


def ext(**kw) -> JobExtraction:
    base = dict(role="Engineer", role_family="backend", seniority="mid", domain="healthcare", skills=[], soft_skills=[], app_idea="An app for things.")
    return JobExtraction(**{**base, **kw})


@pytest.mark.parametrize("sid", list(OWN))
def test_each_sample_picks_its_own_scenario(sid):
    e = read(sid)
    ranking = rank(e, candidates(e))
    assert ranking[0].scenario == OWN[sid] and [m.rank for m in ranking] == [1, 2, 3]
    assert ranking[0].parts["role"] == 50 and ranking[0].score > ranking[1].score + 20  # the seat decides, not a coin toss
    assert {m.scenario for m in ranking} == set(OWN.values())


def test_the_score_is_the_sum_of_its_three_parts_and_the_reason_is_built_from_them():
    e = read("database-engineer")
    top = rank(e, candidates(e))[0]
    assert top.score == sum(top.parts.values()) == 100 and top.parts == {"role": 50, "skills": 35, "domain": 15}
    assert "Database engineer seat" in top.reason and "same domain (healthcare)" in top.reason
    for s in top.shared_skills:
        assert s in top.reason and s in e.skills
    other = rank(e, candidates(e))[1]
    assert "differs" not in other.reason and "no skill" not in other.reason  # shares python and sql, same domain
    assert "posting is for a database engineer" in other.reason


def test_domain_never_beats_the_role():
    e = ext(role_family="frontend", domain="healthcare", skills=[])
    top = rank(e, candidates(e))[0]
    assert top.scenario == "opd-form-says-saved"  # all three share the domain; the seat decides


def test_skill_points_cap_at_four_shared_skills():
    c = Candidate(id="x", title="X", role_family="backend", domain="healthcare", skills=["python", "sql", "git", "rest api", "pytest", "docker"])
    five = rank(ext(skills=["python", "sql", "git", "rest api", "pytest"]), [c])[0]
    four = rank(ext(skills=["python", "sql", "git", "rest api"]), [c])[0]
    two = rank(ext(skills=["python", "sql"]), [c])[0]
    assert five.parts["skills"] == four.parts["skills"] == 35 and two.parts["skills"] == 18 and rank(ext(), [c])[0].parts["skills"] == 0


def test_a_full_stack_posting_partly_fits_backend_and_frontend_but_not_database():
    e = ext(role_family="fullstack", domain="e-commerce")
    parts = {m.scenario: m.parts["role"] for m in rank(e, candidates(e))}
    assert parts == {"opd-bookings-down": 30, "opd-form-says-saved": 30, "opd-double-bookings": 0}


def test_a_posting_with_nothing_in_it_still_gets_a_ranking_in_catalog_order():
    e = extract_keywords("We are a friendly team.")
    ranking = rank(e, candidates(e))
    assert [m.scenario for m in ranking] == [s.id for s in list_scenarios()] and {m.score for m in ranking} == {0}


def test_ties_keep_the_order_the_candidates_came_in():
    a = Candidate(id="a", title="A", role_family="backend", domain="fintech", skills=["python"])
    b = a.model_copy(update={"id": "b", "title": "B"})
    assert [m.scenario for m in rank(ext(domain="fintech"), [b, a])] == ["b", "a"]


def test_the_domain_is_compared_after_normalising_it():
    c = Candidate(id="a", title="A", role_family="backend", domain="healthcare", skills=["python"])
    assert rank(ext(domain="Hospital systems"), [c])[0].parts["domain"] == 15


def test_a_generated_scenario_is_one_more_candidate_through_the_provider_hook(monkeypatch):
    """Part B's contract: a provider returns Candidates for a reading; they are ranked with the shipped scenarios and nothing else changes."""
    e = read("backend-engineer")
    gen = Candidate(id="gen-payments-ledger", title="Ledger drift", role_family="backend", domain="fintech", skills=["python", "fastapi", "postgresql", "rest api"], kind="generated")
    monkeypatch.setattr(match, "EXTRA_PROVIDERS", [lambda extraction: [gen] if extraction.domain == "fintech" else []])
    ranking = rank(e, candidates(e))
    assert ranking[0].scenario == "gen-payments-ledger" and ranking[0].kind == "generated" and ranking[0].parts["domain"] == 15
    assert [m.kind for m in ranking[1:]] == ["existing"] * 3
    assert "gen-payments-ledger" not in [m.scenario for m in rank(read("frontend-engineer"), candidates(read("frontend-engineer")))]  # the provider offered nothing for e-commerce


def test_a_scenario_without_a_fit_block_is_not_offered():
    s = list_scenarios()[0].model_copy(update={"fit": None})
    assert candidates(None, [s]) == []
