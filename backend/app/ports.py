"""Port manager: starts a generated app on 9100-9199, health-checks it, and stops it."""
from __future__ import annotations

import atexit
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .sandbox.runner import clean_env, kill_tree, resolve_argv

PORT_RANGE = range(9100, 9200)


class PortError(Exception):
    pass


@dataclass
class RunningApp:
    project: str
    port: int
    pid: int
    url: str


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


class PortManager:
    def __init__(self, ports: range = PORT_RANGE):
        self.ports = ports
        self._apps: dict[str, tuple[RunningApp, subprocess.Popen]] = {}
        self._lock = threading.Lock()
        atexit.register(self.stop_all)

    def get(self, project: str) -> RunningApp | None:
        with self._lock:
            entry = self._apps.get(project)
        if entry and entry[1].poll() is None:
            return entry[0]
        return None

    def _allocate(self) -> int:
        taken = {a.port for a, _ in self._apps.values()}
        for p in self.ports:
            if p not in taken and port_is_free(p):
                return p
        raise PortError("no free port in the 9100-9199 range")

    def start(self, project: str, root: Path, run_cmd: str, health_path: str = "/health", timeout: float = 25) -> RunningApp:
        """Start the app (restarting it if already running) and wait until it answers its health check."""
        self.stop(project)
        with self._lock:
            port = self._allocate()
            argv = resolve_argv(run_cmd.replace("{port}", str(port)).split())
            log = open(Path(root) / ".q" / "app.log", "wb") if (Path(root) / ".q").is_dir() else subprocess.DEVNULL
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                argv, cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                env={**clean_env(), "Q_SEED": "1"}, creationflags=flags,
            )
            app = RunningApp(project, port, proc.pid, f"http://127.0.0.1:{port}")
            self._apps[project] = (app, proc)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                self.stop(project)
                raise PortError(f"the app exited immediately (exit code {proc.returncode}); see .q/app.log")
            try:
                if httpx.get(app.url + health_path, timeout=2).status_code == 200:
                    return app
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
        self.stop(project)
        raise PortError("the app did not become healthy in time")

    def stop(self, project: str) -> None:
        with self._lock:
            entry = self._apps.pop(project, None)
        if entry:
            _, proc = entry
            if proc.poll() is None:
                kill_tree(proc.pid)
                proc.wait(timeout=10)

    def stop_all(self) -> None:
        for project in list(self._apps):
            self.stop(project)
