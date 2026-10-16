"""The scripted strong and weak runs, started from a job description: the standard score is exactly what it is without one (100 and the weak run's own score), and the report carries the job and a role fit."""
import pytest

from app.scenarios.jobs.adapt import role_fit

from api_helpers import wait_for
from scenario_helpers import ScenarioLLM
from test_autoplay import events, make

pytestmark = pytest.mark.slow  # whole module is slow (see backend/tests/conftest.py)

CASES = [("opd-bookings-down", "backend-engineer", 30), ("opd-double-bookings", "database-engineer", 30), ("opd-form-says-saved", "frontend-engineer", 30)]


def play(client, mgr, scenario, variant, job):
    r = client.post(f"/api/scenarios/{scenario}/autoplay", json={"variant": variant, "speed": 1, "job": job})
    assert r.status_code == 201, r.text
    pid, s = r.json()["id"], mgr.get(r.json()["id"])
    ended = wait_for(lambda: next(iter(events(s, "autoplay_ended")), None), 420, "the run to end")
    assert ended["reason"] == "done", ended
    wait_for(lambda: next(iter(events(s, "debrief_ended")), None), 60, "the debrief")
    return pid, s, client.get(f"/api/projects/{pid}/report").json()


@pytest.fixture
def world(tmp_path):
    client, mgr, settings = make(tmp_path, ScenarioLLM("Karan: slot_time became slot_at in migration 0007."))
    yield client, mgr, settings
    mgr.shutdown()


@pytest.mark.parametrize("scenario,sample,weak", CASES)
def test_the_strong_run_started_from_its_sample_job_description_scores_100(world, scenario, sample, weak):
    client, mgr, _ = world
    pid, s, rep = play(client, mgr, scenario, "strong", {"sample_id": sample})
    assert rep["total"] == 100 and [c["score"] for c in rep["criteria"]] == [4, 4, 4, 4, 4] and rep["scenario"] == scenario and rep["kind"] == "demo"
    assert rep["fairness"]["dropped"] == [] and all(r["verified"] for r in rep["rows"])
    j = rep["job"]
    assert j["sample_id"] == sample and j["source"] == "sample" and j["role_fit"] == 100 and j["standard_total"] == 100 and j["match"]["scenario"] == scenario and j["match"]["rank"] == 1
    assert abs(sum(j["weights"].values()) - 5) < 0.06 and all(0.5 <= w <= 2.0 for w in j["weights"].values())
    started = events(s, "scenario_started")[0]
    assert started["job"]["sample_id"] == sample and started["kind"] == "demo"
    md = client.get(f"/api/projects/{pid}/report?format=md").text
    assert "## Role fit for this job" in md and "**Role fit: 100/100**" in md
    assert not (mgr.settings.workspace / ".q-attempts" / f"{scenario}.json").exists()  # a demo is no attempt, with or without a job


@pytest.mark.parametrize("scenario,sample,weak", CASES)
def test_the_weak_run_scores_what_it_always_scores_and_role_fit_is_an_extra(world, scenario, sample, weak):
    client, mgr, _ = world
    plain_id, _, plain = play(client, mgr, scenario, "weak", None)
    _, _, rep = play(client, mgr, scenario, "weak", {"sample_id": sample})
    assert "job" not in plain
    assert rep["total"] == plain["total"] == weak and [c["score"] for c in rep["criteria"]] == [c["score"] for c in plain["criteria"]]
    scores = {c["id"]: c["score"] for c in rep["criteria"]}
    assert rep["job"]["role_fit"] == role_fit(scores, 4, rep["job"]["weights"]) and rep["job"]["standard_total"] == weak
    assert [(r["rule"], r["kind"]) for r in rep["rows"]] == [(r["rule"], r["kind"]) for r in plain["rows"]]
