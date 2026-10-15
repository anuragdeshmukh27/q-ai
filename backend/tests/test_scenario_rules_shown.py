"""Step 5, second hand-test: the rules are shown before the incident starts ("How you are scored") and Priya's first step says what is expected in the channel."""
import json
import re
import shutil

import pytest

from app.config import load_agents
from app.scenarios.loader import ScenarioError, load_scenario
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import RULES
from scenario_helpers import ScenarioLLM
from test_scenario_debrief import manager, start

SCN = load_scenario("opd-bookings-down")
RUBRIC = load_rubric(SCN)
NAMES = {a.id: a.name for a in load_agents().values()}


def test_every_rule_has_a_sentence_for_the_learner_and_the_scoring_lists_them_by_criterion_and_judge():
    scoring = RUBRIC.scoring()
    assert [(c["name"], NAMES[c["judge"]], len(c["rules"])) for c in scoring] == [("Communication", "Aarav", 4), ("Diagnosis", "Karan", 4), ("Fix quality", "Vikram", 4), ("Testing", "Ananya", 4), ("Ownership", "Aarav", 4)]
    rules = {r["id"]: r["plain"] for c in scoring for r in c["rules"]}
    assert set(rules) <= set(RULES) and len(rules) == 20  # the rules of this rubric (the registry also holds the other scenarios' rules) and all(len(t) > 25 and t.endswith(".") for t in rules.values())
    assert "within 2 minutes" in rules["first_update"] and "within a minute" in rules["answered_requests"] and "backend/api/appointments.py or doctors.py" in rules["read_the_route"]
    assert "tests/regression/" in rules["regression_test_added"] and "before you save any file" in rules["reproduced_first"] and "at most one hint" in rules["few_hints"].lower()
    assert not [t for t in rules.values() if re.search(r"\b(architect|planner|reviewer|qa)\b", t)]  # names, not role ids


def test_a_rule_without_a_sentence_for_the_learner_is_refused(tmp_path):
    shutil.copytree(SCN.folder, tmp_path / SCN.id, ignore=shutil.ignore_patterns("seed"))
    path = tmp_path / SCN.id / "rubric.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["criteria"][0]["rules"][0]["plain"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    scn = load_scenario(SCN.id)
    scn.root = tmp_path
    with pytest.raises(ScenarioError, match="plain"):
        load_rubric(scn)


def test_priyas_first_step_says_what_is_expected_in_the_channel():
    first = SCN.guide[0]
    assert first.id == "run-tests" and "Post a first update in #incident-opd within 2 minutes" in first.text and "answer Aarav within a minute when he asks" in first.text


def test_the_rules_come_with_the_start_of_the_incident_and_the_session(tmp_path):
    client, mgr, settings = manager(tmp_path, ScenarioLLM())
    pid, s = start(client, mgr)
    try:
        started = next(e for e in s.bus.history if e["type"] == "scenario_started")
        assert started["scoring"] == RUBRIC.scoring() and len(started["scoring"]) == 5
        assert client.get(f"/api/projects/{pid}/session").json()["scoring"] == RUBRIC.scoring()
    finally:
        s.orch.stop()
        mgr.shutdown()
