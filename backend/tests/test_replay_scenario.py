"""A recorded simulation scenario replays in Demo mode with no GPU and no Ollama: the whole run (IDE actions, chat, meeting, the Debrief report) comes back from the recording.

The recording is made here with the LLM stubbed and the autoplay script on a virtual clock (the same code path `scripts/record_simulation.py` uses with real Ollama); the replay runs in the
offline server process (network and Ollama blocked) exactly as the browser would use it. The shipped recording, when it is in the repo, gets the same checks."""
import json
from pathlib import Path

import httpx
import pytest
from websockets.sync.client import connect

from app.recording import load_recording
from app.scenarios.reports import History

from api_helpers import wait_for
from test_autoplay import ID, events, make
from test_replay_offline import REPO_RECORDINGS, OfflineServer

SHIPPED = "simulation-bookings-down-strong"
INFO = {"title": "Simulation: Bookings are down (strong)", "app": "Hospital OPD", "feature": "A recorded autoplay run of the incident"}


def replay_all(server: OfflineServer, name: str) -> tuple[str, list[dict]]:
    """Play the recording over HTTP and WebSocket at 1000x and read every event up to the end of the autoplay run."""
    http = httpx.Client(base_url=server.url, timeout=10)
    r = http.post("/api/projects", json={"goal": "Production incident: Bookings are down", "speed": 1000, "recording": name})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    got: list[dict] = []
    with connect(f"ws://127.0.0.1:{server.port}/ws/{pid}", open_timeout=10) as ws:
        while True:
            e = json.loads(ws.recv(timeout=60))
            got.append(e)
            if e["type"] == "autoplay_ended":
                return pid, got


def check_replay(server: OfflineServer, pid: str, got: list[dict], recorded: list[dict], scenario: str = ID) -> dict:
    kinds = lambda evs: [e["type"] for e in evs if e["type"] != "metrics"]  # noqa: E731
    assert kinds(got) == kinds(recorded)
    assert [e["seq"] for e in got] == list(range(len(got))) and all(e["replayed"] for e in got)
    report = next(e for e in got if e["type"] == "debrief_report")["report"]
    assert report == next(e for e in recorded if e["type"] == "debrief_report")["report"]  # the final report of the replay is the recorded one
    # the screen can follow it all without a server: the files, the search, the edits and the test output are events
    needed = {"autoplay_started", "autoplay_step", "autoplay_open_file", "autoplay_search", "autoplay_edit", "human_test_output", "human_test_result", "channel_message", "guide_progress",
              "human_submit_result", "debrief_started", "debrief_report", "debrief_ended"}
    assert needed <= {e["type"] for e in got}
    assert next(e for e in got if e["type"] == "autoplay_started")["doc"].startswith("# ")
    http = httpx.Client(base_url=server.url, timeout=10)
    tree = [f["path"] for f in http.get(f"/api/projects/{pid}/files").json()]  # the Files tab comes from the restored project
    if scenario == ID:
        assert "backend/api/appointments.py" in tree and any(p.startswith("database/migrations/") for p in tree)
        assert "slot_at" in http.get(f"/api/projects/{pid}/file", params={"path": "backend/api/appointments.py"}).json()["content"]
    else:  # "Double bookings": the learner's migration is in the restored project
        assert "database/migrations/0008_one_booking_per_slot.sql" in tree and "fixtures/prod_snapshot.sql" in tree
        assert "WHERE status = 'Booked'" in http.get(f"/api/projects/{pid}/file", params={"path": "database/migrations/0008_one_booking_per_slot.sql"}).json()["content"]
    assert server.attempts() == []  # nothing tried to leave the machine or reach Ollama
    return report


def test_a_stubbed_strong_run_is_recorded_and_replays_offline_with_the_same_final_report(tmp_path):
    client, mgr, settings = make(tmp_path / "rec")
    try:
        s = mgr.start_autoplay(ID, "strong", 1, record_as="sim-test", record_info=INFO)  # the way scripts/record_simulation.py starts a recorded run
        wait_for(lambda: events(s, "autoplay_ended"), 420, "the recorded run")
        wait_for(lambda: (settings.recordings / "sim-test" / "meta.json").is_file(), 60, "the recording to be written")
        live_report = client.get(f"/api/projects/{s.id}/report").json()
    finally:
        mgr.shutdown()
    assert live_report["total"] == 100
    meta = json.loads((settings.recordings / "sim-test" / "meta.json").read_text(encoding="utf-8"))
    assert meta["name"] == "sim-test" and meta["ok"] is True and meta["kind"] == "scenario" and meta["variant"] == "strong" and meta["snapshot"] is True
    assert meta["title"] == INFO["title"] and meta["goal"] and meta["events"] > 100
    rec = load_recording(settings.recordings, "sim-test")  # a scenario recording ends with the run, not at project_done
    recorded = rec.events()
    assert recorded[-1]["type"] == "autoplay_ended" and [e["type"] for e in recorded].count("project_done") == 1
    assert next(e for e in recorded if e["type"] == "debrief_report")["report"]["total"] == 100
    assert History(settings.workspace, ID).attempts() == []  # recording a demo took nothing from the learner's attempts
    server = OfflineServer(settings.recordings, tmp_path / "ws", tmp_path / "q.db")
    try:
        server.wait_ready()
        pid, got = replay_all(server, "sim-test")
        report = check_replay(server, pid, got, recorded)
        assert report["total"] == 100 and report["kind"] == "demo" and report["criteria"] == live_report["criteria"] and report["rows"] == live_report["rows"]
    finally:
        server.stop()


def test_the_replay_list_marks_it_and_a_half_recording_is_not_played(tmp_path):
    from app.recording import RecordingError, list_recordings
    folder = tmp_path / "rec" / "sim-half"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"name": "sim-half", "goal": "g", "ok": True, "kind": "scenario", "recorded_at": "2026-10-13 10:00:00"}), encoding="utf-8")
    (folder / "events.jsonl").write_text(json.dumps({"seq": 0, "ts": 1.0, "type": "scenario_started"}) + "\n", encoding="utf-8")
    assert [m["name"] for m in list_recordings(tmp_path / "rec")] == ["sim-half"]
    with pytest.raises(RecordingError, match="incomplete"):
        load_recording(tmp_path / "rec", "sim-half")
    (folder / "meta.json").write_text(json.dumps({"name": "sim-half", "goal": "g", "ok": True, "recorded_at": "x"}), encoding="utf-8")
    (folder / "events.jsonl").write_text(json.dumps({"seq": 0, "ts": 1.0, "type": "autoplay_ended"}) + "\n", encoding="utf-8")
    with pytest.raises(RecordingError, match="incomplete"):  # only a scenario recording may end this way
        load_recording(tmp_path / "rec", "sim-half")


@pytest.mark.skipif(not (REPO_RECORDINGS / SHIPPED / "meta.json").is_file(), reason="the recording is made with scripts/record_simulation.py (real Ollama) and is not in the repo yet")
def test_the_shipped_simulation_recording_replays_offline_and_its_report_is_the_recorded_one(tmp_path):
    rec = load_recording(REPO_RECORDINGS, SHIPPED)
    assert rec.meta["title"] == "Simulation: Bookings are down (strong)" and rec.meta["ok"] and rec.meta["kind"] == "scenario"
    recorded = rec.events()
    server = OfflineServer(REPO_RECORDINGS, tmp_path / "ws", tmp_path / "q.db")
    try:
        server.wait_ready()
        pid, got = replay_all(server, SHIPPED)
        report = check_replay(server, pid, got, recorded)
        assert report["total"] == 100 and report["kind"] == "demo"
    finally:
        server.stop()


SHIPPED_TWO = "simulation-double-bookings-strong"


@pytest.mark.skipif(not (REPO_RECORDINGS / SHIPPED_TWO / "meta.json").is_file(), reason="record it with: scripts/record_simulation.py --scenario opd-double-bookings --variant strong (real Ollama); not in the repo yet")
def test_the_shipped_double_bookings_recording_replays_offline_and_its_report_is_the_recorded_one(tmp_path):
    rec = load_recording(REPO_RECORDINGS, SHIPPED_TWO)
    assert rec.meta["title"] == "Simulation: Double bookings (strong)" and rec.meta["ok"] and rec.meta["kind"] == "scenario"
    recorded = rec.events()
    server = OfflineServer(REPO_RECORDINGS, tmp_path / "ws", tmp_path / "q.db")
    try:
        server.wait_ready()
        pid, got = replay_all(server, SHIPPED_TWO)
        report = check_replay(server, pid, got, recorded, "opd-double-bookings")
        assert report["total"] == 100 and report["kind"] == "demo" and report["scenario"] == "opd-double-bookings"
    finally:
        server.stop()


def test_a_stubbed_double_bookings_run_is_recorded_and_replays_offline_with_the_same_final_report(tmp_path):
    two = "opd-double-bookings"
    client, mgr, settings = make(tmp_path / "rec")
    try:
        s = mgr.start_autoplay(two, "strong", 1, record_as="sim-two", record_info={"title": "Simulation: Double bookings (strong)", "app": "Hospital OPD", "feature": "x"})
        wait_for(lambda: events(s, "autoplay_ended"), 420, "the recorded run")
        wait_for(lambda: (settings.recordings / "sim-two" / "meta.json").is_file(), 60, "the recording to be written")
        live_report = client.get(f"/api/projects/{s.id}/report").json()
    finally:
        mgr.shutdown()
    assert live_report["total"] == 100 and live_report["scenario"] == two
    recorded = load_recording(settings.recordings, "sim-two").events()
    assert recorded[-1]["type"] == "autoplay_ended" and next(e for e in recorded if e["type"] == "debrief_report")["report"]["total"] == 100
    assert History(settings.workspace, two).attempts() == [] and History(settings.workspace, ID).attempts() == []
    server = OfflineServer(settings.recordings, tmp_path / "ws", tmp_path / "q.db")
    try:
        server.wait_ready()
        pid, got = replay_all(server, "sim-two")
        report = check_replay(server, pid, got, recorded, two)
        assert report["total"] == 100 and report["kind"] == "demo" and report["rows"] == live_report["rows"] and report["scenario"] == two
    finally:
        server.stop()
