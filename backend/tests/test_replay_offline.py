"""P4 check: a full replayed build through HTTP + WebSocket against the real server process, with the network blocked.

The server runs as a subprocess (tests/offline_server.py) exactly as `uvicorn` would for the browser; only loopback is reachable and
every refused connection is logged. The client is a real HTTP client and a real WebSocket client.
"""
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


def play_replay(server: OfflineServer, recording: str | None = None) -> tuple[str, list[dict]]:
    """Create a replay through HTTP and read its whole event stream over a WebSocket, like the browser."""
    http = httpx.Client(base_url=server.url, timeout=10)
    r = http.post("/api/projects", json={"goal": "Build a calculator with history", "speed": 1000, **({"recording": recording} if recording else {})})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    got = []
    with connect(f"ws://127.0.0.1:{server.port}/ws/{pid}", open_timeout=10) as ws:
        while True:
            e = __import__("json").loads(ws.recv(timeout=60))
            got.append(e)
            if e["type"] == "project_done":
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


@pytest.mark.skipif(not (REPO_RECORDINGS / "calculator-fault" / "meta.json").is_file(), reason="the shipped recording has not been made yet")
def test_the_shipped_calculator_recording_replays_offline_exactly_as_recorded(tmp_path):
    server = OfflineServer(REPO_RECORDINGS, tmp_path / "ws", tmp_path / "q.db")
    try:
        server.wait_ready()
        rec = load_recording(REPO_RECORDINGS, "calculator-fault")
        assert rec.meta["ok"] and rec.meta["snapshot"]
        pid, got = play_replay(server, "calculator-fault")
        check_replay(server, pid, got, rec.events())
        types = {e["type"] for e in got}
        assert {"fault_injected", "bug_filed", "bug_fixed", "review_result", "merge_result", "app_running"} <= types
    finally:
        server.stop()
