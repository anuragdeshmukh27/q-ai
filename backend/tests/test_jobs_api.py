"""The job-description endpoints and starting a scenario for a job, through the API. The model is scripted; nothing needs Ollama."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.registry import ModelRegistry
from app.scenarios.jobs.adapt import BriefOutput
from app.scenarios.jobs.extract import ModelReading
from app.scenarios.jobs.samples import sample_text
from app.session import SessionManager

from api_helpers import make_settings, wait_for
from jobs_helpers import JobLLM
from test_jobs_adapt import GOOD

ONE = "opd-bookings-down"
OWN = {"backend-engineer": ONE, "database-engineer": "opd-double-bookings", "frontend-engineer": "opd-form-says-saved"}


def manager(tmp_path, llm, model_available=True):
    settings = make_settings(tmp_path)
    registry = ModelRegistry.load(env={})
    registry.is_available = lambda model_id: model_available  # type: ignore[method-assign]
    mgr = SessionManager(settings, registry, llm_factory=lambda registry, observer: llm)
    return TestClient(create_app(settings, mgr)), mgr


def events(s, type_):
    return [e for e in s.bus.history if e["type"] == type_]


@pytest.fixture
def api(tmp_path):
    client, mgr = manager(tmp_path, JobLLM())
    yield client, mgr
    mgr.shutdown()


def test_the_samples_are_served(api):
    client, _ = api
    s = client.get("/api/jd/samples").json()
    assert [x["id"] for x in s] == ["backend-engineer", "database-engineer", "frontend-engineer"] and all(x["title"] and len(x["text"]) > 500 for x in s)


@pytest.mark.parametrize("sid,scenario", list(OWN.items()))
def test_analyzing_each_sample_recommends_its_own_scenario(api, sid, scenario):
    client, _ = api
    r = client.post("/api/jd/analyze", json={"sample_id": sid})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["recommended"] == scenario and [m["rank"] for m in a["ranking"]] == [1, 2, 3] and a["ranking"][0]["scenario"] == scenario
    assert a["job"] == {"source": "sample", "sample_id": sid, "chars": len(sample_text(sid).strip()), "clipped": False}
    assert a["extraction"]["source"] == "keywords" and a["extraction"]["reason"]  # the scripted model has no reading: the keywords were used, and it says why
    assert all(m["reason"] and set(m["parts"]) == {"role", "skills", "domain"} for m in a["ranking"])


def test_a_pasted_text_is_analyzed_and_a_scripted_model_reading_is_shown_as_the_model_s(tmp_path):
    reading = ModelReading(role="Backend Engineer", role_family="backend", seniority="senior", domain="fintech", skills=["Python", "FastAPI"], soft_skills=["ownership"], app_idea="A payments ledger service.")
    client, mgr = manager(tmp_path, JobLLM(reading=reading))
    a = client.post("/api/jd/analyze", json={"text": sample_text("backend-engineer")}).json()
    assert a["job"]["source"] == "paste" and a["extraction"]["source"] == "model" and a["extraction"]["seniority"] == "senior" and a["extraction"]["skills"] == ["python", "fastapi"]
    assert a["recommended"] == ONE
    mgr.shutdown()


def test_without_the_model_the_keyword_reader_answers_and_says_so(tmp_path):
    client, mgr = manager(tmp_path, JobLLM(reading=None), model_available=False)
    a = client.post("/api/jd/analyze", json={"sample_id": "frontend-engineer"}).json()
    assert a["extraction"]["source"] == "keywords" and "not installed" in a["extraction"]["reason"] and a["recommended"] == "opd-form-says-saved"
    mgr.shutdown()


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "   \n "}, {"sample_id": "nope"}, {"sample_id": "backend-engineer", "text": "Backend Engineer Python"}])
def test_bad_requests_are_refused_with_a_message(api, body):
    client, _ = api
    r = client.post("/api/jd/analyze", json=body)
    assert r.status_code == 400 and r.json()["detail"]


def test_a_huge_paste_is_cut_and_flagged(api):
    client, _ = api
    r = client.post("/api/jd/analyze", json={"text": "Backend Engineer\n" + "Python and SQL and REST APIs. " * 20000})
    assert r.status_code == 200 and r.json()["job"]["clipped"] is True and r.json()["job"]["chars"] <= 5000


# -- starting for a job ----------------------------------------------------------------------------------------------

def start(client, mgr, sid, job=None):
    r = client.post(f"/api/scenarios/{sid}/start", json={"job": job} if job is not None else {})
    return r


def test_a_scenario_started_for_a_job_carries_the_job_in_its_first_event(tmp_path):
    client, mgr = manager(tmp_path, JobLLM(), model_available=False)
    r = start(client, mgr, ONE, {"sample_id": "backend-engineer"})
    assert r.status_code == 201, r.text
    s = mgr.get(r.json()["id"])
    started = wait_for(lambda: next(iter(events(s, "scenario_started")), None), 30, "scenario_started")
    j = started["job"]
    assert j["role"] == "Backend Engineer" and j["domain"] == "fintech" and j["sample_id"] == "backend-engineer" and j["reader"] == "keywords"
    assert 3 <= len(j["key_skills"]) <= 5 and j["match"]["rank"] == 1 and j["match"]["of"] == 3 and set(j["weights"]) == {"communication", "diagnosis", "fix_quality", "testing", "ownership"}
    assert j["briefing"]["source"] == "template" and "Backend engineer seat" in j["briefing"]["text"]
    assert "posting" not in str(started.get("job", {}).get("text", ""))  # the posting text itself is not broadcast
    s.orch.stop()
    mgr.shutdown()


def test_a_scenario_started_without_a_job_has_no_job_anywhere(api):
    client, mgr = api
    r = start(client, mgr, ONE)
    s = mgr.get(r.json()["id"])
    started = wait_for(lambda: next(iter(events(s, "scenario_started")), None), 30, "scenario_started")
    assert "job" not in started and not events(s, "job_briefing") and s.orch.job is None
    s.orch.stop()


def test_the_scenario_the_learner_picks_instead_is_explained_too(tmp_path):
    client, mgr = manager(tmp_path, JobLLM(), model_available=False)
    r = start(client, mgr, "opd-form-says-saved", {"sample_id": "backend-engineer"})
    s = mgr.get(r.json()["id"])
    started = wait_for(lambda: next(iter(events(s, "scenario_started")), None), 30, "scenario_started")
    assert started["job"]["match"]["rank"] == 3 and "Frontend engineer seat" in started["job"]["briefing"]["text"] and started["role"] == "frontend"
    s.orch.stop()
    mgr.shutdown()


@pytest.mark.parametrize("job", [{}, {"text": "  "}, {"sample_id": "nope"}, {"sample_id": "backend-engineer", "text": "x y z"}])
def test_a_bad_job_refuses_the_start_and_starts_nothing(api, job):
    client, mgr = api
    r = start(client, mgr, ONE, job)
    assert r.status_code == 400 and r.json()["detail"] and not mgr.sessions


def test_the_extraction_the_person_saw_comes_back_and_is_checked(tmp_path):
    client, mgr = manager(tmp_path, JobLLM(), model_available=False)
    shown = {"role": "Backend Engineer", "role_family": "backend", "seniority": "senior", "domain": "fintech", "skills": ["python", "cobol"], "soft_skills": [], "app_idea": "A payments ledger.", "source": "model"}
    r = start(client, mgr, ONE, {"sample_id": "backend-engineer", "extraction": shown})
    s = mgr.get(r.json()["id"])
    j = wait_for(lambda: next(iter(events(s, "scenario_started")), None), 30, "scenario_started")["job"]
    assert j["reader"] == "model" and j["seniority"] == "senior" and j["key_skills"] == ["python"]  # cobol is not in the posting: dropped
    s.orch.stop()
    mgr.shutdown()


def test_the_briefing_is_upgraded_by_the_model_after_the_start(tmp_path):
    client, mgr = manager(tmp_path, JobLLM(brief=BriefOutput(paragraph=GOOD)))
    s = mgr.get(start(client, mgr, ONE, {"sample_id": "backend-engineer"}).json()["id"])
    assert wait_for(lambda: next(iter(events(s, "scenario_started")), None), 30, "start")["job"]["briefing"]["source"] == "template"  # the start never waited for the model
    e = wait_for(lambda: next(iter(events(s, "job_briefing")), None), 30, "the briefing")
    assert e["source"] == "model" and e["text"] == GOOD and s.orch.job.briefing.source == "model"
    s.orch.stop()
    mgr.shutdown()


def test_a_briefing_that_fails_the_check_leaves_the_template_and_says_why(tmp_path):
    client, mgr = manager(tmp_path, JobLLM(brief=BriefOutput(paragraph=GOOD.replace("Python", "Kubernetes"))))
    s = mgr.get(start(client, mgr, ONE, {"sample_id": "backend-engineer"}).json()["id"])
    e = wait_for(lambda: next(iter(events(s, "job_briefing")), None), 30, "the briefing")
    assert e["source"] == "template" and "kubernetes" in e["reason"] and "Backend engineer seat" in e["text"] and s.orch.job.briefing.reason == e["reason"]
    s.orch.stop()
    mgr.shutdown()
