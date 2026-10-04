"""Escalation buttons (Retry this step, Re-plan, Stop build) and demo-mode approvals that wait for the presenter."""
import json
import threading
from pathlib import Path

import pytest

from api_helpers import ObservedFake, make_settings, wait_for
from app import orchestrator as orch_mod
from app.llm import StructuredResult
from app.registry import ModelRegistry
from app.schemas import PlannerOutput
from app.session import SessionManager, Settings
from test_orchestrator import FakeLLM, make

ROOT = Path(__file__).resolve().parents[2]


# --- orchestrator level ---------------------------------------------------------------------------

def _failed_build(tmp_path, monkeypatch, llm=None):
    monkeypatch.setattr(orch_mod, "MAX_REPLANS", 0)
    llm = llm or FakeLLM(broken_local="Rohan")
    o, bus = make(tmp_path, llm)
    res = o.run()
    assert not res.ok
    assert {t["id"]: t["status"] for t in res.tasks} == {"t1": "done", "t2": "failed", "t3": "blocked", "t4": "blocked"}
    return o, bus, llm


def test_retry_this_step_runs_the_failed_task_again_and_finishes_the_build(tmp_path, monkeypatch):
    o, bus, llm = _failed_build(tmp_path, monkeypatch)
    llm.broken_local = None  # the model is back
    start, task = o.prepare_recovery("backend")
    assert start == "tasks" and task["id"] == "t2"
    res = o.resume("retry", start, task)
    assert res.ok, res.problems
    assert all(t["status"] == "done" for t in res.tasks) and {"t1", "t2", "t3", "t4"} <= {t["id"] for t in res.tasks}  # QA ran too (q1)


def test_replan_lets_the_planner_split_the_failed_task_then_the_build_finishes(tmp_path, monkeypatch):
    class Replanner(FakeLLM):
        def call(self, model_id, messages, schema_model, temperature=0.2):
            if schema_model is PlannerOutput and "The failed task" in messages[1]["content"]:
                new = {"tasks": [{"id": "t5", "title": "API router, smaller", "owner": "backend", "depends_on": ["t1"], "files": ["backend/api/calculator.py"],
                                  "acceptance": ["POST /api/calculate returns 201"]}]}
                return StructuredResult(PlannerOutput.model_validate(new), model_id, 1, 1, 1, 0.0, "{}")
            return super().call(model_id, messages, schema_model, temperature)

    o, bus, llm = _failed_build(tmp_path, monkeypatch, Replanner(broken_local="Rohan"))
    llm.broken_local = None
    start, task = o.prepare_recovery("backend")
    res = o.resume("replan", start, task)
    assert res.ok, res.problems
    ids = [t["id"] for t in res.tasks]
    assert "t5" in ids and "t2" not in ids and all(t["status"] == "done" for t in res.tasks)
    assert any(e["type"] == "plan_created" and e.get("replan") for e in bus.history)


def test_nothing_to_retry_is_a_plain_message_not_a_crash(tmp_path):
    o, _ = make(tmp_path, FakeLLM())
    assert o.run().ok
    with pytest.raises(ValueError, match="Nothing has stopped"):
        o.prepare_recovery("backend")


def test_stop_build_ends_the_running_task_without_retry_or_replan(tmp_path):
    class StopsInTheMiddle(FakeLLM):
        def call(self, model_id, messages, schema_model, temperature=0.2):
            if schema_model.__name__ == "Action" and "You are Rohan" in messages[0]["content"]:
                o.stop()  # the human presses Stop while the backend engineer is working
            return super().call(model_id, messages, schema_model, temperature)

    o, bus = make(tmp_path, StopsInTheMiddle())
    res = o.run()
    assert not res.ok and o.stopped.is_set()
    st = {t["id"]: t["status"] for t in res.tasks}
    assert st["t1"] == "done" and st["t2"] == "failed" and st["t3"] == "blocked"
    assert any("stopped by you" in p for p in res.problems)
    assert not any(e["type"] == "plan_created" and e.get("replan") for e in bus.history)


def test_every_escalation_reason_has_plain_words_and_the_three_buttons_exist():
    from app.agent.termination import REASON_TEXT

    src = (ROOT / "frontend" / "src" / "escalation.ts").read_text(encoding="utf-8")
    for reason in [*REASON_TEXT, "no_valid_output", "model_unavailable", "review_unresolved", "merge_conflict", "waiting_human"]:
        assert f"case '{reason}'" in src, reason
    for label in ("Retry this step", "Re-plan", "Stop build"):
        assert label in src


# --- the same buttons over HTTP -------------------------------------------------------------------

def _flaky_manager(tmp_path, monkeypatch, gate=None, broken_calls=6):
    monkeypatch.setattr(orch_mod, "MAX_REPLANS", 0)

    class Flaky(ObservedFake):
        rohan = 0

        def call(self, model_id, messages, schema_model, temperature=0.2):
            if schema_model.__name__ == "Action" and "You are Rohan" in messages[0]["content"]:
                self.rohan += 1
                self.broken_local = "Rohan" if self.rohan <= broken_calls else None  # two failed attempts (3 repeated moves each), then it works
            return super().call(model_id, messages, schema_model, temperature)

    settings = make_settings(tmp_path)
    return settings, SessionManager(settings, ModelRegistry.load(env={}), llm_factory=lambda registry, observer: Flaky(observer, gate))


def _client(settings, mgr):
    from fastapi.testclient import TestClient
    from app.main import create_app

    return TestClient(create_app(settings, mgr))


def _wait_state(c, pid, states):
    return wait_for(lambda: (lambda s: s if s["state"] in states else None)(c.get(f"/api/projects/{pid}").json()), 120, f"state in {states}")


def _create(c, **kw):
    r = c.post("/api/projects", json={"goal": "Build a calculator with history", "mode": "autonomous", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_retry_over_http_after_the_build_stopped(tmp_path, monkeypatch):
    settings, mgr = _flaky_manager(tmp_path, monkeypatch)
    c = _client(settings, mgr)
    try:
        pid = _create(c)
        assert _wait_state(c, pid, ("failed", "done"))["state"] == "failed"
        r = c.post(f"/api/projects/{pid}/escalation", json={"action": "retry", "agent": "backend"})
        assert r.status_code == 200 and "fresh attempts" in r.json()["message"]
        assert _wait_state(c, pid, ("done",))["state"] == "done"
        acts = [e for e in mgr.get(pid).bus.history if e["type"] == "escalation_action"]
        assert acts and acts[0]["action"] == "retry" and acts[0]["agent"] == "backend"
        assert c.post(f"/api/projects/{pid}/escalation", json={"action": "retry", "agent": "backend"}).status_code == 409  # nothing left to retry
        assert c.post(f"/api/projects/{pid}/escalation", json={"action": "dance", "agent": "backend"}).status_code == 400
    finally:
        mgr.shutdown()


def test_retry_clicked_while_the_build_is_running_is_queued_and_applied_when_it_stops(tmp_path, monkeypatch):
    gate = threading.Event()
    settings, mgr = _flaky_manager(tmp_path, monkeypatch, gate=gate)
    c = _client(settings, mgr)
    try:
        pid = _create(c)
        r = c.post(f"/api/projects/{pid}/escalation", json={"action": "retry", "agent": "backend"})
        assert r.status_code == 200 and r.json()["queued"] is True
        gate.set()
        assert _wait_state(c, pid, ("done", "failed"))["state"] == "done"  # t2 failed twice, then the queued retry ran it again
        assert [e.get("queued") for e in mgr.get(pid).bus.history if e["type"] == "escalation_action"] == [True, False]
    finally:
        gate.set()
        mgr.shutdown()


def test_stop_build_over_http(tmp_path, monkeypatch):
    gate = threading.Event()
    settings, mgr = _flaky_manager(tmp_path, monkeypatch, gate=gate)
    c = _client(settings, mgr)
    try:
        pid = _create(c)
        r = c.post(f"/api/projects/{pid}/escalation", json={"action": "stop", "agent": "backend"})
        assert r.status_code == 200 and "stops" in r.json()["message"]
        gate.set()
        assert _wait_state(c, pid, ("done", "failed"))["state"] == "failed"
        assert mgr.get(pid).orch.stopped.is_set()
        assert not any(t["status"] == "running" for t in mgr.get(pid).orch.tasks)
    finally:
        gate.set()
        mgr.shutdown()


# --- demo mode: the first approvals of a recording wait for the presenter --------------------------

def _hold_manager(tmp_path, hold=3, n=5):
    """A tiny synthetic recording: n approvals (each: needed, waiting, resolved, back to work), then the end."""
    rec = tmp_path / "rec" / "hold-demo"
    rec.mkdir(parents=True)
    events = [{"type": "project_created", "slug": "x", "goal": "g", "preset": "fastapi-vanilla", "path": ""}]
    for i in range(n):
        events += [{"type": "approval_needed", "id": f"a{i}", "agent": "architect", "kind": "write", "summary": f"write file {i}", "details": {}},
                   {"type": "agent_state", "agent": "architect", "state": "waiting_human"},
                   {"type": "approval_resolved", "id": f"a{i}", "agent": "architect", "kind": "write", "approve": True, "by": "human"},
                   {"type": "agent_state", "agent": "architect", "state": "thinking"}]
    events.append({"type": "project_done", "ok": True, "seconds": 1, "problems": []})
    (rec / "events.jsonl").write_text("\n".join(json.dumps({"seq": i, "ts": 1000.0 + i * 0.01, **e}) for i, e in enumerate(events)), encoding="utf-8")
    meta = {"name": "hold-demo", "goal": "g", "ok": True, "problems": [], "preset": "fastapi-vanilla", "recorded_at": "2026-01-01 00:00:00", "events": len(events)}
    if hold:
        meta["hold_approvals"] = hold
    (rec / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    settings = Settings(workspace=tmp_path / "ws", recordings=tmp_path / "rec", leaderboard_db=tmp_path / "q.db", q_mode="replay", max_gap=0.0, approval_timeout=30.0)
    return settings, SessionManager(settings, ModelRegistry.load(env={}), llm_factory=lambda *a: pytest.fail("replay must never build a model client"))


def _replay(c):
    r = c.post("/api/projects", json={"goal": "g", "mode": "supervised", "demo": True, "recording": "hold-demo", "speed": 1000})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_replay_waits_at_the_first_three_approvals_and_auto_approves_the_rest(tmp_path):
    settings, mgr = _hold_manager(tmp_path, hold=3, n=5)
    c = _client(settings, mgr)
    try:
        pid = _replay(c)
        got: list[dict] = []
        with c.websocket_connect(f"/ws/{pid}") as ws:
            def pull_until(pred):
                while True:
                    e = ws.receive_json()
                    got.append(e)
                    if pred(e):
                        return e

            for i, ok in enumerate([True, False, True]):  # approve, reject, approve
                pull_until(lambda e, i=i: e["type"] == "approval_needed" and e["id"] == f"a{i}")
                pull_until(lambda e: e["type"] == "agent_state" and e["state"] == "waiting_human")  # the office marker
                # paused on this approval: it is the only pending one, and nothing has played past it
                wait_for(lambda i=i: [a["id"] for a in c.get(f"/api/projects/{pid}").json()["pending_approvals"]] == [f"a{i}"], 5, "the approval to be pending")
                assert c.get(f"/api/projects/{pid}").json()["state"] == "replaying"
                assert not any(x["type"] == "approval_needed" and x["id"] == f"a{i + 1}" for x in mgr.get(pid).bus.history)
                assert c.post(f"/api/projects/{pid}/approvals/a{i}", json={"approve": ok}).status_code == 200
                res = pull_until(lambda e, i=i: e["type"] == "approval_resolved" and e["id"] == f"a{i}")
                assert res["approve"] is ok and res["by"] == "human"
            pull_until(lambda e: e["type"] == "project_done")
        resolved = {e["id"]: e for e in got if e["type"] == "approval_resolved"}
        assert sorted(resolved) == ["a0", "a1", "a2", "a3", "a4"]  # one answer each: the recorded answers of the clicked ones were skipped
        assert resolved["a1"]["approve"] is False and resolved["a1"]["note"] == "in the recording this was approved"
        assert "note" not in resolved["a0"]
        assert [resolved[k]["by"] for k in ("a3", "a4")] == ["recording-auto", "recording-auto"] and all(resolved[k]["approve"] for k in ("a3", "a4"))
        assert _wait_state(c, pid, ("done",))["state"] == "done"
        assert [e["state"] for e in got if e["type"] == "agent_state"][-1] == "thinking"  # the employee goes back to work
    finally:
        mgr.shutdown()


def test_other_replays_label_recorded_answers_as_approved_during_recording(tmp_path):
    settings, mgr = _hold_manager(tmp_path, hold=0, n=2)
    c = _client(settings, mgr)
    try:
        pid = _replay(c)
        assert _wait_state(c, pid, ("done",))["state"] == "done"
        assert [e["by"] for e in mgr.get(pid).bus.history if e["type"] == "approval_resolved"] == ["recording", "recording"]  # nobody clicked: never "human"
    finally:
        mgr.shutdown()


def test_the_escalation_buttons_say_so_in_a_replay(tmp_path):
    settings, mgr = _hold_manager(tmp_path, hold=0, n=1)
    c = _client(settings, mgr)
    try:
        pid = _replay(c)
        r = c.post(f"/api/projects/{pid}/escalation", json={"action": "retry", "agent": "backend"})
        assert r.status_code == 409 and "live build" in r.json()["detail"]
    finally:
        mgr.shutdown()


def test_only_the_todo_approvals_recording_pauses():
    root = ROOT / "recordings"
    assert json.loads((root / "todo-approvals" / "meta.json").read_text(encoding="utf-8"))["hold_approvals"] == 3
    others = [p for p in root.glob("*/meta.json") if p.parent.name != "todo-approvals"]
    assert others and not any("hold_approvals" in json.loads(p.read_text(encoding="utf-8")) for p in others)
