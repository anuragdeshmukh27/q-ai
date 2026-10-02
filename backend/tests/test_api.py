"""P4: HTTP + WebSocket API over the real session layer (scripted fake team), recording, replay, approvals, controls."""
import json
import threading
import time

import pytest

from app.approvals import ApprovalQueue
from app.events import EventBus
from app.leaderboard import Leaderboard
from app.recording import list_recordings, load_recording

from api_helpers import make_client, make_manager, record_fake_build, wait_for


def create(c, **kw):
    body = {"goal": "Build a calculator with history", "mode": "autonomous", **kw}
    r = c.post("/api/projects", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def finished(c, pid):
    return wait_for(lambda: (lambda s: s if s["state"] in ("done", "failed") else None)(c.get(f"/api/projects/{pid}").json()), 120, "build to finish")


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    """One fault-injected fake build, recorded; shared by the read-only tests below."""
    return record_fake_build(tmp_path_factory.mktemp("rec"))


def test_rewriting_identical_documents_does_not_end_a_build(tmp_path):
    """Regression from the first real recording: a retried task makes the Reviewer write the same review file again."""
    from test_orchestrator import FakeLLM, make
    o, _ = make(tmp_path, FakeLLM())
    assert o.run().ok
    reviewer = o.agents["reviewer"]
    o._write(reviewer, ".q/reviews/t1-r1.md", "same text\n")
    o._write(reviewer, ".q/reviews/t1-r1.md", "same text\n")  # used to raise AgentFailed("no change")
    o._write(reviewer, ".q/reviews/t1-r1.md", "different text\n")


# -- recording ---------------------------------------------------------------------

def test_a_live_build_through_the_api_is_recorded_with_events_llm_responses_and_a_snapshot(recorded):
    settings, status = recorded
    assert status["state"] == "done" and status["finished"]["ok"] and status["progress"]["percent"] == 100
    assert [b["fixed"] for b in status["bugs"]] == [True]  # the injected fault was found and fixed
    meta = list_recordings(settings.recordings)[0]
    assert meta["name"] == "demo-fault" and meta["ok"] and meta["snapshot"] and meta["events"] > 50 and meta["llm_calls"] > 5
    rec = load_recording(settings.recordings, "demo-fault")
    types = [e["type"] for e in rec.events()]
    assert types[-1] == "project_done" and {"fault_injected", "bug_filed", "bug_fixed", "merge_result", "review_result"} <= set(types)
    assert len((rec.path / "llm.jsonl").read_text().splitlines()) == meta["llm_calls"]
    assert not list(settings.recordings.glob(".tmp-*"))


def test_an_incomplete_recording_is_never_listed_or_loaded(tmp_path):
    from app.recording import Recorder, RecordingError
    r = Recorder(tmp_path, "half", "goal")
    r.on_event({"seq": 0, "ts": 1.0, "type": "project_created", "slug": "x", "preset": "p", "path": "x"})
    assert list_recordings(tmp_path) == []  # still in the hidden temp folder
    r.finalize(None, False)
    with pytest.raises(RecordingError):
        load_recording(tmp_path, "half")  # no project_done
    with pytest.raises(RecordingError):
        load_recording(tmp_path, "../etc")
    with pytest.raises(RecordingError):
        Recorder(tmp_path, "half", "goal")  # no silent overwrite


# -- replay through the API ----------------------------------------------------------

def replay_client(recorded, tmp_path):
    settings, _ = recorded
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.registry import ModelRegistry
    from app.session import SessionManager, Settings
    s2 = Settings(workspace=tmp_path / "ws2", recordings=settings.recordings, leaderboard_db=tmp_path / "q.db", q_mode="replay", max_gap=0.0)
    mgr = SessionManager(s2, ModelRegistry.load(env={}), llm_factory=lambda *a: pytest.fail("replay must never build a model client"))
    return TestClient(create_app(s2, mgr)), mgr


def test_replay_plays_the_recorded_stream_over_websocket_and_restores_the_project(recorded, tmp_path):
    c, mgr = replay_client(recorded, tmp_path)
    try:
        pid = create(c, demo=True, speed=1000)  # also: Q_MODE=replay forces this
        got = []
        with c.websocket_connect(f"/ws/{pid}") as ws:
            while True:
                e = ws.receive_json()
                got.append(e)
                if e["type"] == "project_done":
                    break
        rec = load_recording(recorded[0].recordings, "demo-fault").events()
        assert [e["type"] for e in got] == [e["type"] for e in rec]
        assert [e["seq"] for e in got] == list(range(len(got))) and all(e["replayed"] for e in got)
        status = finished(c, pid)
        assert status["state"] == "done" and status["kind"] == "replay" and status["progress"]["percent"] == 100
        assert status["app"]["running"] and status["app"]["url"].startswith("http://127.0.0.1:91")
        assert status["slug"].startswith("replay-")
        tree = [f["path"] for f in c.get(f"/api/projects/{pid}/files").json()]
        assert "database/calculations.py" in tree and not any(p.startswith(".git/") for p in tree)
        assert "def " in c.get(f"/api/projects/{pid}/file", params={"path": "database/calculations.py"}).json()["content"]
        graph = c.get(f"/api/projects/{pid}/commits").json()
        assert any("agent/backend" in " ".join(g["refs"]) for g in graph)
        assert c.get(f"/api/projects/{pid}/diff", params={"branch": "agent/backend"}).json()["diff"] == ""  # fully merged: nothing left on the branch
        merge = next(g for g in graph if g["subject"].startswith("[integrator] merge agent/backend") and len(g["parents"]) == 2)
        d = c.get(f"/api/projects/{pid}/commits/{merge['hash']}").json()
        assert d["merge"] and "backend/api/calculator.py" in d["diff"]  # the per-task diff
        # resume: a reconnecting browser asks only for what it missed
        with c.websocket_connect(f"/ws/{pid}?after={len(got) - 3}") as ws:
            assert [ws.receive_json()["seq"] for _ in range(2)] == [len(got) - 2, len(got) - 1]
        assert c.get(f"/api/projects/{pid}/events", params={"after": len(got) - 2}).json()[0]["seq"] == len(got) - 1
    finally:
        mgr.shutdown()


def test_replay_speed_can_change_while_playing_and_unknown_recordings_are_refused(recorded, tmp_path):
    c, mgr = replay_client(recorded, tmp_path)
    try:
        assert c.post("/api/projects", json={"goal": "x", "recording": "nope"}).status_code == 404
        assert c.post("/api/projects", json={"goal": "x", "recording": "../x"}).status_code in (400, 404)
        pid = create(c, speed=1000)
        assert c.post(f"/api/projects/{pid}/speed", json={"speed": 4}).json() == {"speed": 4.0}
        assert c.post(f"/api/projects/{pid}/speed", json={"speed": 99999}).json()["speed"] == 1000.0
        finished(c, pid)
        # employees are not available in a replay
        assert c.post(f"/api/projects/{pid}/agents/backend/ask", json={"text": "hi"}).status_code == 409
        assert c.post(f"/api/projects/{pid}/agents/backend/model", json={"model": "qwen25-coder-7b"}).status_code == 409
    finally:
        mgr.shutdown()


# -- live: files, controls, employees ----------------------------------------------------

def test_live_build_exposes_status_files_and_ask_employee(tmp_path):
    c, settings, mgr = make_client(tmp_path)
    try:
        pid = create(c)
        status = finished(c, pid)
        assert status["state"] == "done" and status["kind"] == "live" and status["finished"]["ok"]
        assert status["app"]["running"] and c.get(f"/api/projects/{pid}/app").json()["running"]
        be = next(a for a in status["agents"] if a["id"] == "backend")
        assert be["name"] == "Rohan" and be["files"] and be["tests"]["ok"] and be["log"]
        assert c.get(f"/api/projects/{pid}/file", params={"path": "../../../etc/passwd"}).status_code == 400
        assert c.get(f"/api/projects/{pid}/file", params={"path": ".git/config"}).status_code == 400
        assert c.get(f"/api/projects/{pid}/file", params={"path": "nope.py"}).status_code == 404
        assert c.get(f"/api/projects/{pid}/commits/zzzz").status_code == 400
        assert c.get(f"/api/projects/{pid}/diff", params={"branch": "--output=x"}).status_code == 400
        # chat with an employee
        r = c.post(f"/api/projects/{pid}/agents/backend/ask", json={"text": "What are you doing?"})
        assert r.status_code == 200 and "API" in r.json()["reply"]
        msgs = [e for e in c.get(f"/api/projects/{pid}/events").json() if e["type"] == "message_sent" and "human" in (e["from"], e["to"])]
        assert [(m["from"], m["to"]) for m in msgs] == [("human", "backend"), ("backend", "human")]
        assert c.post(f"/api/projects/{pid}/agents/qa/ask", json={"text": "build x", "as_task": True}).status_code == 400
        assert c.post(f"/api/projects/{pid}/agents/nobody/ask", json={"text": "hi"}).status_code == 404
        assert c.post(f"/api/projects/{pid}/agents/backend/ask", json={"text": "  "}).status_code == 400
    finally:
        mgr.shutdown()


def test_a_task_given_to_one_engineer_runs_after_the_build_and_the_project_is_reverified(tmp_path):
    holder: list = []
    c, settings, mgr = make_client(tmp_path, llm_holder=holder)
    try:
        pid = create(c)
        finished(c, pid)
        from test_orchestrator import act
        holder[0].scripts["Rohan"] += [act("run_tests"), act("finish", summary="nothing else needed")]
        r = c.post(f"/api/projects/{pid}/agents/backend/ask", json={"text": "Please double check the error format", "as_task": True})
        assert r.status_code == 200 and r.json()["task"] == "r1"
        wait_for(lambda: (lambda s: s["state"] == "done" and any(t["id"] == "r1" and t["status"] == "done" for t in s["tasks"]))(c.get(f"/api/projects/{pid}").json()), 90, "the request")
        assert c.get(f"/api/projects/{pid}").json()["app"]["running"]
    finally:
        mgr.shutdown()


def test_model_override_and_mode_switch(tmp_path):
    c, settings, mgr = make_client(tmp_path)
    try:
        pid = create(c)
        finished(c, pid)
        url = f"/api/projects/{pid}"
        assert c.post(f"{url}/agents/nobody/model", json={"model": "qwen3-4b"}).status_code == 404
        assert c.post(f"{url}/agents/backend/model", json={"model": "nope"}).status_code == 404
        assert c.post(f"{url}/agents/backend/model", json={"model": "gemini-flash"}).status_code == 409  # no API key in this environment
        assert c.post(f"{url}/agents/backend/model", json={"model": "qwen3-4b"}).json() == {"overrides": {"backend": "qwen3-4b"}}
        assert mgr.get(pid).orch.overrides == {"backend": "qwen3-4b"} and c.get(url).json()["overrides"] == {"backend": "qwen3-4b"}
        assert c.post(f"{url}/agents/backend/model", json={"model": None}).json() == {"overrides": {}}
        assert c.post(f"{url}/mode", json={"mode": "nonsense"}).status_code == 400
        assert c.post(f"{url}/mode", json={"mode": "assisted"}).json() == {"mode": "assisted"}
        assert mgr.get(pid).orch.mode == "assisted" and c.get(url).json()["mode"] == "assisted"
        assert any(e["type"] == "mode_changed" and e["mode"] == "assisted" for e in c.get(f"{url}/events").json())
    finally:
        mgr.shutdown()


def test_only_one_live_build_runs_at_a_time(tmp_path):
    gate = threading.Event()
    c, settings, mgr = make_client(tmp_path, gate=gate)
    try:
        create(c)
        r = c.post("/api/projects", json={"goal": "another"})
        assert r.status_code == 409 and "already running" in r.json()["detail"]
    finally:
        gate.set()
        mgr.shutdown()


def test_request_validation_and_friendly_errors(tmp_path):
    c, settings, mgr = make_client(tmp_path)
    try:
        for body in ({"goal": "  "}, {"goal": "x" * 1001}, {"goal": "x", "mode": "yolo"}, {"goal": "x", "preset": "nope"}, {"goal": "x", "record_as": "Bad Name!"}):
            r = c.post("/api/projects", json=body)
            assert r.status_code == 400 and "detail" in r.json(), body
        assert c.post("/api/projects", json={}).status_code == 422
        assert c.get("/api/projects/nope").status_code == 404 and c.get("/api/projects/nope").json()["detail"] == "project not found"
        with pytest.raises(Exception):
            with c.websocket_connect("/ws/nope") as ws:
                ws.receive_json()
        assert c.get("/api/health").json()["ok"] and c.get("/api/agents").json()[0]["desk"]
        assert {m["id"] for m in c.get("/api/models").json()} >= {"qwen25-coder-7b", "gemini-flash"}
        assert "fastapi-vanilla" in c.get("/api/config").json()["presets"]
        pre = c.options("/api/projects", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
        assert pre.headers["access-control-allow-origin"] == "http://localhost:5173"
    finally:
        mgr.shutdown()


def test_leaderboard_endpoint_reads_the_benchmark_table(tmp_path):
    c, settings, mgr = make_client(tmp_path)
    try:
        assert c.get("/api/leaderboard").json() == {"runs": 0, "roles": [], "models": [], "matrix": {}}
        b = Leaderboard(settings.leaderboard_db)
        b.record("qwen25-coder-7b", "backend", "endpoint", True, 4, 12.0, 900, 4.6)
        b.record("qwen25-coder-7b", "backend", "endpoint2", False, 8, 30.0, 1500, 4.7)
        cell = c.get("/api/leaderboard").json()["matrix"]["backend"]["qwen25-coder-7b"]
        assert cell["runs"] == 2 and cell["pass_rate"] == 0.5 and cell["peak_vram_gb"] == 4.7
    finally:
        mgr.shutdown()


# -- approvals ----------------------------------------------------------------------

def test_approval_queue_blocks_until_a_human_decides_and_times_out_to_deny():
    bus = EventBus()
    q = ApprovalQueue(bus.emit, timeout=5)
    out = []
    t = threading.Thread(target=lambda: out.append(q.announce("backend", "install", "pip install x", {"pkg": "x"})))
    t.start()
    wait_for(lambda: q.pending(), 5, "the approval")
    a = q.pending()[0]
    assert a["agent"] == "backend" and a["kind"] == "install" and not out  # the agent thread is blocked
    assert q.resolve(a["id"], True) is True and q.resolve(a["id"], False) is False  # the first decision wins
    t.join(5)
    assert out == [True]
    kinds = [e["type"] for e in bus.history]
    assert kinds.count("approval_needed") == 1 and bus.history[0]["id"] == a["id"] and "approval_resolved" in kinds
    slow = ApprovalQueue(bus.emit, timeout=0.2)
    assert slow.announce("x", "k", "s", {}) is False and bus.history[-1]["by"] == "timeout"
    with pytest.raises(Exception):
        q.resolve("missing", True)


def test_approvals_are_decided_over_http_and_autonomous_mode_releases_pending_ones(recorded, tmp_path):
    c, mgr = replay_client(recorded, tmp_path)
    try:
        pid = create(c)
        s = mgr.get(pid)
        results = []
        for kind in ("a", "b"):
            threading.Thread(target=lambda k=kind: results.append((k, s.approvals.announce("backend", "install", f"pip install {k}", {})))).start()
        wait_for(lambda: len(c.get(f"/api/projects/{pid}/approvals").json()) == 2, 5, "two approvals")
        first = c.get(f"/api/projects/{pid}").json()["pending_approvals"][0]["id"]
        assert c.post(f"/api/projects/{pid}/approvals/{first}", json={"approve": False}).status_code == 200
        assert c.post(f"/api/projects/{pid}/approvals/{first}", json={"approve": True}).status_code == 409
        assert c.post(f"/api/projects/{pid}/approvals/zzz", json={"approve": True}).status_code == 404
        c.post(f"/api/projects/{pid}/mode", json={"mode": "autonomous"})  # releases the other one as approved
        wait_for(lambda: len(results) == 2, 5, "both agents unblocked")
        assert sorted(r[1] for r in results) == [False, True]
        assert not c.get(f"/api/projects/{pid}").json()["pending_approvals"]
    finally:
        mgr.shutdown()
