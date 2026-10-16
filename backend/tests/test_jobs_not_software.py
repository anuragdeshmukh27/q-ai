"""A posting that is not for a software engineering job (sales, nursing, accounting) is read as what it is: its own title, no made-up domain or app idea, no model call, and a closest
scenario that is only a closest. The hand-test: "Sales Executive: we need a friendly person to sell insurance ..." came out as a Software engineer in fintech with a payments app."""
import pytest

from app.scenarios.jobs.adapt import build_context
from app.scenarios.jobs.extract import extract_keywords, read_job, revalidate
from app.scenarios.jobs.modelcall import ModelGate
from app.scenarios.jobs.schema import JobExtraction
from app.scenarios.jobs.service import JobBody, analyze, resolve
from app.scenarios.loader import load_scenario
from app.scenarios.rubric import load_rubric

from jobs_helpers import JobLLM, SAMPLE_IDS
from test_jobs_extract import reading
from test_jobs_api import manager  # noqa: F401  (the API fixture helper)

SALES = "Sales Executive: we need a friendly person to sell insurance, meet targets and talk to customers."
# "monitoring" and "react" are words of the skill vocabulary and everyday English both; "patients" and "hospital" are really in the text, so the domain is supported
NURSE = ("Registered Nurse - City Hospital\nWe are hiring a registered nurse for a busy surgical ward. You will care for patients, give medication, keep monitoring their vital signs "
         "and react calmly in an emergency. Night shifts. Kind, patient and reliable.")
ACCOUNTANT = "Accountant\nPrepare the monthly accounts, run payroll, reconcile the ledger and file the tax returns. Two years of experience. Good with spreadsheets."
CIVIL = "Civil Engineer: design and inspect bridges and roads on site, read drawings and manage the contractors. 5+ years."

CASES = [
    (SALES, "Sales Executive", "not stated"),
    (NURSE, "Registered Nurse", "healthcare"),
    (ACCOUNTANT, "Accountant", "not stated"),  # "ledger" alone does not make it fintech
    (CIVIL, "Civil Engineer", "not stated"),  # "engineer" in a title is not a software job
]


@pytest.mark.parametrize("text,title,domain", CASES)
def test_the_keyword_reader_keeps_the_postings_own_title_and_makes_nothing_up(text, title, domain):
    e = extract_keywords(text)
    assert (e.role, e.software_job, e.role_family, e.domain, e.skills, e.soft_skills, e.app_idea) == (title, False, "other", domain, [], [], "")
    assert e.source == "keywords"


@pytest.mark.parametrize("text,title,domain", CASES)
def test_the_model_is_not_asked_and_the_reason_says_why(text, title, domain):
    llm = JobLLM(reading=reading())  # a model that would answer "Backend Engineer, fintech" if it were asked
    clean, _, e = read_job(text, llm, available=lambda: True, gate=ModelGate())
    assert llm.calls == [] and e.role == title and not e.software_job and e.source == "keywords" and "no software" in e.reason


def test_no_scenario_fits_a_posting_that_is_not_a_software_job():
    got = analyze(JobBody(text=SALES))
    assert got["extraction"]["software_job"] is False and got["extraction"]["role"] == "Sales Executive" and got["extraction"]["app_idea"] == ""
    assert len(got["ranking"]) == 3 and all(m["score"] == 0 and m["parts"] == {"role": 0, "skills": 0, "domain": 0} for m in got["ranking"])
    assert all("not a software engineering job" in m["reason"] for m in got["ranking"]) and got["recommended"] == got["ranking"][0]["scenario"]  # the closest is still offered


def test_a_nurse_in_a_hospital_does_not_match_the_healthcare_scenarios_on_domain_alone_as_a_software_fit():
    got = analyze(JobBody(text=NURSE))
    assert got["extraction"]["domain"] == "healthcare" and got["extraction"]["software_job"] is False
    assert all(m["parts"]["role"] == 0 and m["parts"]["skills"] == 0 for m in got["ranking"])


def test_a_browser_cannot_turn_it_into_a_model_reading_of_a_software_job():
    forged = JobExtraction(role="Software engineer", role_family="backend", seniority="mid", domain="fintech", skills=["python"], app_idea="A payments service.", source="model")
    e = revalidate(forged, SALES)
    assert e.role == "Sales Executive" and not e.software_job and e.domain == "not stated" and e.skills == []


def test_the_briefing_says_it_is_only_the_closest_scenario_and_the_role_fit_is_the_standard_score():
    scenario = load_scenario("opd-bookings-down")
    ctx = resolve(JobBody(text=NURSE), scenario, load_rubric(scenario))
    assert "does not look like a software engineering job" in ctx.briefing.text and "closest one" in ctx.briefing.text and "Registered Nurse" in ctx.briefing.text
    assert set(ctx.weights.values()) == {1.0} and all(v == [] for v in ctx.weight_reasons.values())


@pytest.mark.parametrize("sid", SAMPLE_IDS)
def test_the_bundled_samples_are_still_software_jobs(sid):
    from app.scenarios.jobs.samples import sample_text
    e = extract_keywords(sample_text(sid))
    assert e.software_job and e.role_family != "other" and e.skills and e.app_idea


@pytest.mark.parametrize("text", ["Python developer", "We build a web application with SQL and React.", "Looking for a QA engineer to write automated tests.", "Backend", "Site reliability engineer"])
def test_short_software_postings_are_still_software_jobs(text):
    assert extract_keywords(text).software_job


def test_the_api_answers_for_a_non_software_posting(tmp_path):
    client, mgr = manager(tmp_path, JobLLM(reading=reading()))
    a = client.post("/api/jd/analyze", json={"text": SALES}).json()
    assert a["extraction"]["role"] == "Sales Executive" and a["extraction"]["software_job"] is False and a["extraction"]["domain"] == "not stated"
    assert a["extraction"]["role_family"] == "other" and a["extraction"]["app_idea"] == "" and a["extraction"]["source"] == "keywords"
    mgr.shutdown()
