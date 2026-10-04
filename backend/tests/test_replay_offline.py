"""P4 check: a full replayed build through HTTP + WebSocket against the real server process, with the network blocked.

The server runs as a subprocess (tests/offline_server.py) exactly as `uvicorn` would for the browser; only loopback is reachable and
every refused connection is logged. The client is a real HTTP client and a real WebSocket client.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from websockets.sync.client import connect

from app.recording import load_recording
from api_helpers import record_fake_build, wait_for

TESTS = Path(__file__).resolve().parent
REPO_RECORDINGS = TESTS.parents[1] / "recordings"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class OfflineServer:
    def __init__(self, recordings: Path, workspace: Path, db: Path):
        self.port = free_port()
        self.log = workspace.parent / "net.log"
        self.url = f"http://127.0.0.1:{self.port}"
        env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY") and k != "OLLAMA_HOST"}
        env.update(Q_MODE="replay", Q_RECORDINGS_DIR=str(recordings), Q_WORKSPACE_DIR=str(workspace), Q_DB=str(db), Q_NET_LOG=str(self.log),
                   OLLAMA_HOST="http://127.0.0.1:1", PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen([sys.executable, str(TESTS / "offline_server.py"), str(self.port)], cwd=TESTS.parent, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

    def wait_ready(self) -> None:
        def up():
            assert self.proc.poll() is None, f"server exited: {self.proc.stdout.read()[-800:]}"
            try:
                return httpx.get(self.url + "/api/health", timeout=1).status_code == 200
            except httpx.HTTPError:
                return False
        wait_for(up, 30, "the server to start")

    def attempts(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def stop(self) -> None:
        if self.proc.poll() is None:  # Ctrl-Break lets uvicorn shut down, which also stops the apps it started
            try:
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
                self.proc.wait(15)
            except Exception:
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)


def play_replay(server: OfflineServer, recording: str | None = None, total: int | None = None) -> tuple[str, list[dict]]:
    """Create a replay through HTTP and read its whole event stream over a WebSocket, like the browser.

    Stops at the first project_done, or after `total` events when the recording has more (an Ask-employee request ends with a second project_done)."""
    http = httpx.Client(base_url=server.url, timeout=10)
    r = http.post("/api/projects", json={"goal": "Build a calculator with history", "speed": 1000, **({"recording": recording} if recording else {})})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    got = []
    with connect(f"ws://127.0.0.1:{server.port}/ws/{pid}", open_timeout=10) as ws:
        while True:
            e = __import__("json").loads(ws.recv(timeout=60))
            got.append(e)
            if e["type"] == "project_done" and (total is None or len(got) >= total):
                return pid, got


def check_replay(server: OfflineServer, pid: str, got: list[dict], recorded: list[dict]) -> None:
    http = httpx.Client(base_url=server.url, timeout=10)
    assert [e["type"] for e in got] == [e["type"] for e in recorded]
    assert [e["seq"] for e in got] == list(range(len(got))) and all(e["replayed"] for e in got)
    assert got[-1]["ok"] is True
    status = http.get(f"/api/projects/{pid}").json()
    assert status["state"] == "done" and status["progress"]["percent"] == 100 and all(b["fixed"] for b in status["bugs"])
    # Open app works from the restored snapshot
    assert status["app"]["running"]
    assert httpx.get(status["app"]["url"] + "/health", timeout=5).status_code == 200
    assert httpx.get(status["app"]["url"] + "/", timeout=5).status_code == 200
    # files and git come from the restored project
    tree = [f["path"] for f in http.get(f"/api/projects/{pid}/files").json()]
    assert any(p.startswith("backend/api/") for p in tree) and any(p.startswith("tests/") for p in tree)
    graph = http.get(f"/api/projects/{pid}/commits").json()
    assert any(len(g["parents"]) == 2 for g in graph)
    assert http.get(f"/api/projects/{pid}/events", params={"after": len(got) - 2}).json()[0]["seq"] == len(got) - 1
    # nothing tried to leave the machine or reach Ollama
    assert server.attempts() == []


def test_the_guard_really_blocks_remote_hosts_and_ollama(tmp_path):
    code = ("import offline_server as o, socket, sys\n"
            "o.install()\n"
            "for addr in (('8.8.8.8', 53), ('127.0.0.1', 11434), ('example.com', 80)):\n"
            "    try:\n"
            "        socket.create_connection(addr, timeout=1)\n"
            "        print('CONNECTED', addr); sys.exit(1)\n"
            "    except OSError as e:\n"
            "        print('blocked', e)\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=TESTS, env={**os.environ, "Q_NET_LOG": str(tmp_path / "log")}, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.count("blocked network blocked") == 3, r.stdout + r.stderr
    assert (tmp_path / "log").read_text().splitlines() == ["remote host 8.8.8.8:53", "Ollama port 127.0.0.1:11434", "DNS lookup of example.com"]


@pytest.fixture(scope="module")
def fake_recording(tmp_path_factory):
    settings, status = record_fake_build(tmp_path_factory.mktemp("offrec"))
    return settings.recordings


def test_full_replayed_build_over_http_and_websocket_with_the_network_blocked(fake_recording, tmp_path):
    server = OfflineServer(fake_recording, tmp_path / "ws", tmp_path / "q.db")
    try:
        server.wait_ready()
        pid, got = play_replay(server)
        check_replay(server, pid, got, load_recording(fake_recording, "demo-fault").events())
    finally:
        server.stop()


SHIPPED = sorted(d.name for d in REPO_RECORDINGS.glob("*") if (d / "meta.json").is_file() and not d.name.startswith("."))


def test_the_demo_set_is_complete():
    """The demo picker needs all of these; an empty list would make the parametrized replay test below pass without testing anything."""
    assert {"calculator-fault", "todo-approvals", "ask-employee", "notes-search", "contact-book", "inventory", "reddit-replica", "instagram"} <= set(SHIPPED)


@pytest.mark.parametrize("name", SHIPPED)
def test_every_shipped_recording_replays_offline_exactly_as_recorded_and_its_app_opens(name, tmp_path):
    server = OfflineServer(REPO_RECORDINGS, tmp_path / "ws", tmp_path / "q.db")
    try:
        server.wait_ready()
        rec = load_recording(REPO_RECORDINGS, name)
        recorded = rec.events()
        assert rec.meta["ok"] and rec.meta["snapshot"] and rec.meta.get("title") and rec.meta.get("feature")
        pid, got = play_replay(server, name, total=len(recorded))
        check_replay(server, pid, got, recorded)
        types = [e["type"] for e in got]
        assert {"spec_ready", "review_result", "merge_result", "app_running", "metrics"} <= set(types)
        # the restored app serves its page, the UI kit and every endpoint of the contract that needs no input
        app = httpx.get(f"{server.url}/api/projects/{pid}").json()["app"]["url"]
        page = httpx.get(app + "/", timeout=5).text
        assert "ui-kit" in page and "app.js" in page
        assert "UI." in httpx.get(app + "/static/app.js", timeout=5).text
        contract = httpx.get(f"{server.url}/api/projects/{pid}/file", params={"path": ".q/api_contract.json"}).json()
        text = contract["content"] if isinstance(contract, dict) and "content" in contract else json.dumps(contract)
        for ep in json.loads(text)["endpoints"]:
            if ep["method"] == "GET" and "{" not in ep["path"]:
                assert httpx.get(app + ep["path"], timeout=5).status_code < 500, ep["path"]
        # the speed control works on this recording: 1x, then 2x and 4x while it plays
        http = httpx.Client(base_url=server.url, timeout=10)
        slow = http.post("/api/projects", json={"goal": rec.meta["goal"], "recording": name, "speed": 1}).json()["id"]
        for speed in (2, 4):
            assert http.post(f"/api/projects/{slow}/speed", json={"speed": speed}).json() == {"speed": float(speed)}
        wait_for(lambda: len(http.get(f"/api/projects/{slow}/events").json()) > 10, 30, "events at 4x")
        # the recording's story
        if name == "calculator-fault":
            assert {"fault_injected", "bug_filed", "bug_fixed"} <= set(types)
        if name == "todo-approvals":
            assert types.count("approval_needed") >= 5 and "approval_resolved" in types
        if name == "ask-employee":
            assert types.count("project_done") == 2 and "project_resumed" in types
            assert any(e["type"] == "message_sent" and e["from"] == "human" and e["to"] == "frontend" and "progress bar" in e["text"] for e in got)
            after = got[types.index("project_resumed"):]
            assert any(e["type"] == "file_changed" and e["path"] == "static/index.html" and "progress" in e["diff"].lower() for e in after)
            assert any(e["type"] == "file_changed" and e["path"] == "static/app.js" and "UI.progress" in e["diff"] for e in after)
        if name == "reddit-replica":
            assert any(e["type"] == "look_chosen" and e["layout"] == "feed" for e in got)
        if name == "instagram":
            assert next(e for e in got if e["type"] == "spec_ready")["not_included"]
    finally:
        server.stop()
