"""Project sessions: one per build the UI watches. A session is either a live build (the real orchestrator in a thread)
or a replay of a recording. Both publish the same event stream on their own EventBus and keep the same state, so the UI cannot tell them apart.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from .agent.planning import AgentFailed
from .approvals import ApprovalQueue
from .config import PROMPTS_DIR, WORKSPACE, ROOT, AgentConfig, load_agents
from .events import EventBus
from .llm import LLMClient
from .orchestrator import ENGINEERS, Orchestrator
from .ports import PortError, PortManager
from .presets import list_presets, load_preset
from .providers.base import ProviderError
from .recording import Recorder, RecordingError, check_name, load_recording, restore_snapshot
from .registry import ModelRegistry

MODES = ("assisted", "supervised", "autonomous")


class SessionError(Exception):
    """Safe to show in the UI. `status` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Settings:
    workspace: Path = WORKSPACE
    recordings: Path = ROOT / "recordings"
    leaderboard_db: Path = ROOT / "data" / "q.db"
    q_mode: str = "live"  # live | record | replay
    approval_timeout: float = 600.0
    max_gap: float = 3.0  # replay never waits longer than this (at 1x) between two events

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        env = os.environ if env is None else env
        s = cls()
        if env.get("Q_RECORDINGS_DIR"):
            s.recordings = Path(env["Q_RECORDINGS_DIR"])
        if env.get("Q_WORKSPACE_DIR"):
            s.workspace = Path(env["Q_WORKSPACE_DIR"])
        if env.get("Q_DB"):
            s.leaderboard_db = Path(env["Q_DB"])
        mode = env.get("Q_MODE", "live").strip().lower()
        s.q_mode = mode if mode in ("live", "record", "replay") else "live"
        return s


class CreateRequest(BaseModel):
    goal: str
    preset: str | None = None
    mode: str = "supervised"
    demo: bool = False  # replay a recording (no model, no network)
    recording: str | None = None  # which recording to replay (default: the newest good one)
    record_as: str | None = None  # record this live build under that name
    speed: float = 1.0
    inject_fault: bool = False
    parallel: int = 2


class AskReply(BaseModel):
    reply: str


# -- state tracking (derived from events, so live and replay share it) ------------------------------

class Tracker:
    def __init__(self, roster: dict[str, AgentConfig]):
        self._lock = threading.Lock()
        self.agents = {a.id: {"id": a.id, "name": a.name, "role": a.role, "state": "idle", "model": None, "iteration": 0, "max_iterations": 0,
                              "task": None, "thought": "", "files": [], "tests": None, "log": []} for a in roster.values()}
        self.slug = self.preset = self.app_url = ""
        self.tasks: list[dict] = []
        self.progress = {"done": 0, "total": 0, "percent": 0}
        self.bugs: list[dict] = []
        self.problems: list[str] = []
        self.finished: dict | None = None

    def on_event(self, e: dict) -> None:
        t, a = e["type"], self.agents.get(e.get("agent", ""))
        with self._lock:
            if t == "agent_state" and a:
                a["state"] = e["state"]
            elif t == "iteration" and a:
                a["iteration"], a["max_iterations"] = e["n"], e["max"]
            elif t == "agent_thought" and a:
                a["thought"], a["model"] = e["text"], e.get("model")
            elif t == "task_assigned" and a:
                a["task"], a["model"], a["iteration"] = {"id": e["task"], "title": e["title"]}, e.get("model"), 0
            elif t == "tool_call" and a:
                arg = next(iter(e["args"].values()), "")
                a["log"] = (a["log"] + [f"{e['tool']} {str(arg).splitlines()[0][:60] if arg else ''}".strip()
                                         + ("" if e["ok"] else " (failed)")])[-12:]
            elif t == "file_changed" and a and e["path"] not in a["files"]:
                a["files"].append(e["path"])
            elif t == "test_result" and a:
                a["tests"] = {"ok": e["passed"], "failed": len(e.get("failed", [])), "summary": e.get("summary", "")}
            elif t == "project_created":
                self.slug, self.preset = e["slug"], e["preset"]
            elif t == "plan_created":
                old = {x["id"]: x.get("status", "pending") for x in self.tasks}
                self.tasks = [{**x, "status": old.get(x["id"], "pending")} for x in e["tasks"]]
            elif t == "project_progress":
                self.progress = {"done": e["done"], "total": e["total"], "percent": e["percent"]}
                for x in self.tasks:
                    x["status"] = e["tasks"].get(x["id"], x["status"])
            elif t == "bug_filed":
                self.bugs.append({"id": e["bug"], "owner": e["owner"], "title": e["title"], "fixed": False})
            elif t == "bug_fixed":
                for b in self.bugs:
                    if b["id"] == e["bug"]:
                        b["fixed"] = True
            elif t == "app_running":
                self.app_url = e["url"]
            elif t == "project_done":
                self.finished = {"ok": e["ok"], "seconds": e["seconds"]}
                self.problems = list(e.get("problems", []))

    def snapshot(self) -> dict:
        with self._lock:
            return {"agents": [dict(a, files=list(a["files"]), log=list(a["log"])) for a in self.agents.values()], "tasks": [dict(x) for x in self.tasks],
                    "progress": dict(self.progress), "bugs": [dict(b) for b in self.bugs], "app_url": self.app_url, "problems": list(self.problems),
                    "slug": self.slug, "preset": self.preset, "finished": self.finished}


# -- one session ------------------------------------------------------------------------------------

class Session:
    def __init__(self, sid: str, req: CreateRequest, kind: str, mgr: "SessionManager"):
        self.id, self.goal, self.kind, self.mgr = sid, req.goal, kind, mgr
        self.bus = EventBus()
        self.tracker = Tracker(mgr.roster)
        self.bus.subscribe(self.tracker.on_event)
        self.mode = req.mode
        self.state = "starting"
        self.created = time.time()
        self.overrides: dict[str, str] = {}
        self.approvals = ApprovalQueue(self.bus.emit, mgr.settings.approval_timeout)
        self.recorder: Recorder | None = None
        self.orch: Orchestrator | None = None
        self.root: Path | None = None
        self.recording: dict | None = None
        self.speed = max(0.1, min(float(req.speed), 1000.0))
        self.chats: dict[str, list[dict]] = {}
        self._thread: threading.Thread | None = None
        self._extra = threading.Lock()
        self._stop = threading.Event()
        self.bus.subscribe(self._watch)

    def _watch(self, e: dict) -> None:
        if e["type"] == "project_created" and self.kind == "live":
            self.root = Path(e["path"])

    # -- live ---------------------------------------------------------------------
    def start_live(self, req: CreateRequest) -> None:
        mgr = self.mgr
        if req.record_as or mgr.settings.q_mode == "record":
            name = req.record_as or f"rec-{time.strftime('%Y%m%d-%H%M%S')}"
            self.recorder = Recorder(mgr.settings.recordings, name, req.goal, overwrite=bool(req.record_as))
            self.bus.subscribe(self.recorder.on_event)
        llm = mgr.make_llm(self.recorder.on_llm if self.recorder else None)
        self.orch = Orchestrator(req.goal, mgr.registry, llm, self.bus, mode=self.mode, approver=self.approvals, preset=req.preset,
                                 base=mgr.settings.workspace, overrides=self.overrides, local_only=True, ports=mgr.ports,
                                 max_parallel=req.parallel, inject_fault=req.inject_fault)
        self._thread = threading.Thread(target=self._run_live, name=f"build-{self.id}", daemon=True)
        self._thread.start()

    def _run_live(self) -> None:
        self.state = "running"
        ok, problems = False, []
        try:
            res = self.orch.run()  # type: ignore[union-attr]
            ok, problems = res.ok, res.problems
        except Exception:
            self.bus.emit("error", agent="orchestrator", message="the build stopped unexpectedly")
            problems = ["the build stopped unexpectedly"]
        self.state = "done" if ok else "failed"
        if self.recorder:
            try:
                self.recorder.finalize(self.root, ok, problems)
            except (RecordingError, OSError) as e:
                self.recorder.abort()
                self.bus.emit("error", agent="orchestrator", message=f"the recording could not be saved: {e}"[:200])

    # -- replay -------------------------------------------------------------------
    def start_replay(self, req: CreateRequest) -> None:
        try:
            rec = load_recording(self.mgr.settings.recordings, req.recording)
        except RecordingError as e:
            raise SessionError(str(e), 404) from None
        self.recording = rec.meta
        self._thread = threading.Thread(target=self._run_replay, args=(rec,), name=f"replay-{self.id}", daemon=True)
        self._thread.start()

    def _sleep(self, seconds: float) -> None:
        """Wait `seconds` of recorded time at the current speed; speed changes take effect within 50 ms."""
        end = time.monotonic() + seconds / self.speed
        while not self._stop.is_set():
            left = end - time.monotonic()
            if left <= 0:
                return
            self._stop.wait(min(left, 0.05))

    def _run_replay(self, rec) -> None:
        self.state = "replaying"
        dest = self.mgr.settings.workspace / f"replay-{self.id}"
        restored = False
        if rec.bundle:
            try:
                self.root = restore_snapshot(rec.bundle, dest)
                restored = True
            except RecordingError:
                self.bus.emit("error", agent="orchestrator", message="the saved project could not be restored; files and Open app are unavailable")
        prev_ts = None
        ok = True
        for e in rec.events():
            if self._stop.is_set():
                return
            if prev_ts is not None:
                self._sleep(min(max(e["ts"] - prev_ts, 0.0), self.mgr.settings.max_gap))
            prev_ts = e["ts"]
            data = {k: v for k, v in e.items() if k not in ("seq", "ts", "type")}
            data["replayed"] = True
            if e["type"] == "project_created":
                data["slug"], data["path"] = (dest.name, str(dest)) if restored else (data.get("slug", ""), "")
            elif e["type"] == "app_running":
                url = self._restart_restored_app(dest, rec.meta.get("preset", "")) if restored else ""
                if not url:
                    continue  # nothing to open: skip the stale recorded URL
                data.update(url=url, port=int(url.rsplit(":", 1)[-1]), project=dest.name)
            elif e["type"] == "project_done":
                ok = bool(e.get("ok"))
                data["app_url"] = self.tracker.app_url
            self.bus.emit(e["type"], **data)
        self.state = "done" if ok else "failed"

    def _restart_restored_app(self, dest: Path, preset_name: str) -> str:
        try:
            p = load_preset(preset_name)
            return self.mgr.ports.start(dest.name, dest, p.run_cmd, p.health_path).url
        except (PortError, Exception):
            self.bus.emit("error", agent="orchestrator", message="the recorded app could not be started again")
            return ""

    def set_speed(self, speed: float) -> float:
        self.speed = max(0.1, min(float(speed), 1000.0))
        return self.speed

    # -- controls -----------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise SessionError(f"mode must be one of: {', '.join(MODES)}")
        self.mode = mode
        if self.orch:
            self.orch.mode = mode
        self.bus.emit("mode_changed", mode=mode)
        if mode == "autonomous":
            self.approvals.release_all(True, "mode")

    def set_override(self, agent_id: str, model_id: str | None) -> dict:
        if agent_id not in self.mgr.roster:
            raise SessionError("unknown employee", 404)
        if self.kind == "replay":
            raise SessionError("Demo mode replays a recording; model changes apply to live builds.", 409)
        if model_id:
            reg = self.mgr.registry
            if model_id not in reg.models:
                raise SessionError("unknown model", 404)
            if not reg.is_available(model_id):
                raise SessionError("that model is not available (disabled, or its API key is not set in .env)", 409)
            self.overrides[agent_id] = model_id
            if self.orch and not reg.get(model_id).local:
                self.orch.local_only = False  # an explicit, visible choice from the human
        else:
            self.overrides.pop(agent_id, None)
        self.bus.emit("model_override", agent=agent_id, model=model_id)
        return dict(self.overrides)

    def ask(self, agent_id: str, text: str, as_task: bool) -> dict:
        agent = self.mgr.roster.get(agent_id)
        if agent is None:
            raise SessionError("unknown employee", 404)
        if self.kind == "replay" or self.orch is None:
            raise SessionError("Demo mode replays a recording; employees can only be asked during a live build.", 409)
        self.bus.emit("message_sent", **{"from": "human", "to": agent_id, "text": text})
        if as_task:
            if agent_id not in ENGINEERS:
                raise SessionError(f"{agent.name} is not an engineer; give build tasks to the Backend, Frontend or Database engineer.")
            if self.orch.root is None:
                raise SessionError("The project has not been designed yet; ask again in a moment.", 409)
            task = self.orch.add_request(agent_id, text)
            if self.state in ("done", "failed") and self._extra.acquire(blocking=False):
                threading.Thread(target=self._run_extra, name=f"request-{self.id}", daemon=True).start()
            return {"task": task["id"], "reply": f"{agent.name}: on it ({task['id']})."}
        try:
            model = self.orch._model(agent)
            memory = self.orch.memory
            context = (f"Project goal: {self.goal}\n" + (memory.context_for(agent_id) if memory else "")).strip()
            system = (PROMPTS_DIR / "ask_employee.md").read_text(encoding="utf-8").replace("{name}", agent.name).replace("{role}", agent.role)
            history = self.chats.setdefault(agent_id, [])[-6:]
            messages = [{"role": "system", "content": f"{system}\n\nContext:\n{context}"}, *history, {"role": "user", "content": text}]
            reply = self.orch.llm.call(model.id, messages, AskReply).parsed.reply.strip()  # type: ignore[attr-defined]
        except Exception as e:  # never leak a trace: AgentFailed/ProviderError messages are already user-safe
            msg = e.reason if isinstance(e, AgentFailed) else str(e) if isinstance(e, ProviderError) else "could not answer right now"
            raise SessionError(msg[:200], 503) from None
        self.chats[agent_id] += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        self.bus.emit("message_sent", **{"from": agent_id, "to": "human", "text": reply})
        return {"reply": reply}

    def _run_extra(self) -> None:
        try:
            self.state = "running"
            self.orch.finish_requests()  # type: ignore[union-attr]
            self.state = "done" if self.orch.tests_passed and not self.orch.problems else "failed"  # type: ignore[union-attr]
        finally:
            self._extra.release()

    def app(self) -> dict:
        app = self.mgr.ports.get(self.root.name) if self.root else None
        return {"running": bool(app), "url": app.url if app else ""}

    def start_app(self) -> dict:
        if not self.root or not self.root.is_dir():
            raise SessionError("There is no built project to run yet.", 409)
        preset = load_preset(self.tracker.preset or "fastapi-vanilla")
        try:
            app = self.mgr.ports.start(self.root.name, self.root, preset.run_cmd, preset.health_path)
        except PortError as e:
            raise SessionError(str(e)[:200], 503) from None
        self.bus.emit("app_running", url=app.url, port=app.port, project=self.root.name)
        return {"running": True, "url": app.url}

    def stop(self) -> None:
        self._stop.set()
        self.approvals.release_all(False, "shutdown")

    def status(self) -> dict:
        snap = self.tracker.snapshot()
        return {"id": self.id, "goal": self.goal, "kind": self.kind, "state": self.state, "mode": self.mode, "speed": self.speed,
                "created": self.created, "events": len(self.bus.history), "overrides": dict(self.overrides), "recording": self.recording,
                "pending_approvals": self.approvals.pending(), "app": self.app(), **snap}


# -- all sessions -----------------------------------------------------------------------------------

class SessionManager:
    def __init__(self, settings: Settings, registry: ModelRegistry | None = None, llm_factory: Callable[..., LLMClient] | None = None):
        self.settings = settings
        self.registry = registry or ModelRegistry.load()
        self.roster = load_agents()
        self.ports = PortManager()
        self._llm_factory = llm_factory
        self.sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def make_llm(self, observer) -> LLMClient:
        return self._llm_factory(self.registry, observer) if self._llm_factory else LLMClient(self.registry, observer=observer)

    def get(self, sid: str) -> Session:
        s = self.sessions.get(sid)
        if s is None:
            raise SessionError("project not found", 404)
        return s

    def create(self, req: CreateRequest) -> Session:
        goal = req.goal.strip()
        if not goal or len(goal) > 1000:
            raise SessionError("describe the goal in 1 to 1000 characters")
        req.goal = goal
        if req.mode not in MODES:
            raise SessionError(f"mode must be one of: {', '.join(MODES)}")
        if req.preset and req.preset not in list_presets():
            raise SessionError(f"unknown preset; choose one of: {', '.join(list_presets())}")
        if req.record_as:
            check_name(req.record_as)  # RecordingError -> 400 via the API layer
        demo = req.demo or self.settings.q_mode == "replay"
        with self._lock:
            if not demo and any(s.kind == "live" and s.state in ("starting", "running") for s in self.sessions.values()):
                raise SessionError("A build is already running; the GPU runs one build at a time.", 409)
            s = Session(uuid.uuid4().hex[:8], req, "replay" if demo else "live", self)
            self.sessions[s.id] = s
            try:
                s.start_replay(req) if demo else s.start_live(req)
            except Exception:
                del self.sessions[s.id]
                raise
        return s

    def shutdown(self) -> None:
        for s in self.sessions.values():
            s.stop()
        self.ports.stop_all()
