"""Project sessions: one per build the UI watches. A session is either a live build (the real orchestrator in a thread)
or a replay of a recording. Both publish the same event stream on their own EventBus and keep the same state, so the UI cannot tell them apart.
"""
from __future__ import annotations

import os
import re
import shutil
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
from .llm import LLMClient, agent_context
from .humanide import IDEError, search_worktree
from .orchestrator import ENGINEERS, Orchestrator
from .ports import PortError, PortManager
from .presets import list_presets, load_preset
from .providers.base import ProviderError
from .recording import Recorder, RecordingError, check_name, load_recording, restore_snapshot
from .leaderboard import SHIPPED_RESULTS, Leaderboard
from .registry import ModelRegistry, ollama_installed_probe
from .router import Router
from .scenarios.autoplay import CLOCK_FACTOR, SPEEDS, VARIANTS, AutoplayRunner, ScaledClock, VirtualClock
from .scenarios.build import ScenarioBuild
from .scenarios.director import Replier
from .scenarios.loader import Scenario, ScenarioError, load_scenario
from .scenarios.reports import History
from .scenarios.rubric import Rubric, load_rubric
from .scenarios.wording import Wordsmith
from .scheduler import MetricsSampler, ModelScheduler
from .scope import classify_goal

REPLY_MODEL = "qwen25-coder-7b"  # the teammates of a scenario answer the learner with this local model (qwen2.5-coder:7b)
MODES = ("assisted", "supervised", "autonomous", "simulation")  # simulation: the AI employees work as in supervised, and the human takes the roles in `human_roles`


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
    shipped_results: Path | None = SHIPPED_RESULTS  # pre-recorded benchmark runs committed with the repo
    q_mode: str = "live"  # live | record | replay
    approval_timeout: float = 600.0
    max_gap: float = 3.0  # replay never waits longer than this (at 1x) between two events
    polish: bool = True  # live builds end with the Frontend UI polish task (Q_POLISH=0 turns it off)
    fast_live: bool = True  # live builds skip an unneeded polish pass and allow one LLM review round per task (Q_FAST_LIVE=0 turns it off)
    debrief_pace: float = 3.5  # seconds between the judges' posts in the debrief meeting (Q_DEBRIEF_PACE; tests use 0)
    autoplay_virtual: bool = False  # an autoplay run keeps its session time on a clock that only the script moves (tests: a whole incident without waiting)

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
        s.polish = env.get("Q_POLISH", "1").strip().lower() not in ("0", "false", "no", "off")
        s.fast_live = env.get("Q_FAST_LIVE", "1").strip().lower() not in ("0", "false", "no", "off")
        try:
            s.debrief_pace = max(0.0, float(env.get("Q_DEBRIEF_PACE", s.debrief_pace)))
        except ValueError:
            pass
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
    fast_live: bool | None = None  # None: the server default (on); False turns the live-demo shortcuts off for this build
    record_info: dict[str, str] | None = None  # recording card text for the demo picker: title, app, feature
    then_ask: list[dict[str, str]] | None = None  # recorded builds only: Ask-employee tasks sent after the build ({agent, text}), part of the recording
    import_from: str | None = None  # Finish my project: a folder or a GitHub URL of a half-built project (the goal is then derived from it)
    auto_fix: bool = False  # Finish my project: fix every gap found without waiting for the human to choose
    human_roles: list[str] | None = None  # simulation mode: the engineers a human plays ("database" | "backend" | "frontend"); default ["backend"]
    overrides: dict[str, str] | None = None  # live builds: a model for some employees from the first call on ({employee id: model id}), the same as the Employee inspector's override but set at the start


class AskReply(BaseModel):
    reply: str


# -- state tracking (derived from events, so live and replay share it) ------------------------------

class Tracker:
    def __init__(self, roster: dict[str, AgentConfig]):
        self._lock = threading.Lock()
        self.agents = {a.id: {"id": a.id, "name": a.name, "role": a.role, "state": "idle", "model": None, "iteration": 0, "max_iterations": 0,
                              "task": None, "thought": "", "files": [], "tests": None, "log": []} for a in roster.values()}
        self.slug = self.preset = self.app_url = ""
        self.run_cmd, self.health_path = "", "/"  # set for an imported project (Finish my project): how its app is started
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
                self.run_cmd, self.health_path = e.get("run_cmd", ""), e.get("health_path", "/")
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
            elif t == "project_resumed":  # an Ask-employee request on a finished project: in progress again, nobody is celebrating
                self.finished = None
                for ag in self.agents.values():
                    if ag["state"] == "celebrating":
                        ag["state"] = "idle"

    def snapshot(self) -> dict:
        with self._lock:
            return {"agents": [dict(a, files=list(a["files"]), log=list(a["log"])) for a in self.agents.values()], "tasks": [dict(x) for x in self.tasks],
                    "progress": dict(self.progress), "bugs": [dict(b) for b in self.bugs], "app_url": self.app_url, "problems": list(self.problems),
                    "slug": self.slug, "preset": self.preset, "finished": self.finished}


def remove_tree(root: Path) -> None:
    """Delete a project folder; git's object files are read-only on Windows, so a plain rmtree leaves them behind."""
    def writable(func, path, _exc) -> None:
        try:
            os.chmod(path, 0o700)
            func(path)
        except OSError:
            pass
    shutil.rmtree(root, onerror=writable)


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
        self.overrides: dict[str, str] = dict(req.overrides or {})
        self.approvals = ApprovalQueue(self._emit_approval, mgr.settings.approval_timeout, lambda a: self.tracker.agents.get(a, {}).get("state", "idle"))
        self.recorder: Recorder | None = None
        self.orch: Orchestrator | None = None
        self.root: Path | None = None
        self.recording: dict | None = None
        self.speed = max(0.1, min(float(req.speed), 1000.0))
        self.chats: dict[str, list[dict]] = {}
        self.sampler: MetricsSampler | None = None
        self.fast_live = False
        self.autoplay: AutoplayRunner | None = None  # a scripted learner is playing this scenario session ("Watch a run")
        self.scenario: Scenario | None = None  # a scenario session (Simulation mode, step 4): the channel, the guide and the session log belong to it
        self.record_info = req.record_info
        self.then_ask = req.then_ask or []
        self._thread: threading.Thread | None = None
        self._extra = threading.Lock()
        self._stop = threading.Event()
        self.pending_recovery: tuple[str, str] | None = None  # a Retry / Re-plan clicked while the build was still running
        self.bus.subscribe(self._watch)

    def _emit_approval(self, type_: str, **fields):
        """Approval events of a replay carry the replay flag like every other replayed event (the presenter's click is part of the replay)."""
        return self.bus.emit(type_, **({**fields, "replayed": True} if self.kind == "replay" else fields))

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
        fast = mgr.settings.fast_live if req.fast_live is None else req.fast_live
        if req.import_from:  # Finish my project: the same team, on an imported project and its own branch
            from .finish.build import FinishBuild
            self.orch = FinishBuild(req.import_from, mgr.registry, llm, self.bus, auto_fix=req.auto_fix, mode=self.mode, approver=self.approvals,
                                    base=mgr.settings.workspace, overrides=self.overrides, local_only=True, ports=mgr.ports, max_parallel=1,
                                    fast_live=fast, router=mgr.router)
        else:
            self.orch = Orchestrator(req.goal, mgr.registry, llm, self.bus, mode=self.mode, approver=self.approvals, preset=req.preset,
                                     base=mgr.settings.workspace, overrides=self.overrides, local_only=True, ports=mgr.ports,
                                     max_parallel=req.parallel, inject_fault=req.inject_fault, polish=mgr.settings.polish,
                                     fast_live=fast, router=mgr.router, human_roles=req.human_roles or ())
        self.fast_live = fast
        if mgr.scheduler is not None:
            mgr.scheduler.emit = self.bus.emit
            self.sampler = MetricsSampler(mgr.scheduler, self.bus.emit, lambda: llm.tokens_per_s).start()
        self._thread = threading.Thread(target=self._run_live, name=f"build-{self.id}", daemon=True)
        self._thread.start()

    def start_scenario(self, scn: Scenario, rubric: Rubric, attempt: int, kind: str = "learner", variant: str = "", clock=None) -> None:
        """The scenario's finished app, one task for the person, the AI team on call (no design or planning calls). `attempt`: the number of this try (1 for the first)."""
        mgr = self.mgr
        llm = mgr.make_llm(None)
        fast = mgr.settings.fast_live
        self.scenario = scn
        replier = Replier(llm, REPLY_MODEL, available=lambda: mgr.registry.is_available(REPLY_MODEL))
        wordsmith = Wordsmith(llm, REPLY_MODEL, available=lambda: mgr.registry.is_available(REPLY_MODEL))
        self.orch = ScenarioBuild(scn, mgr.registry, llm, self.bus, replier=replier, rubric=rubric, wordsmith=wordsmith, attempt=attempt, debrief_pace=mgr.settings.debrief_pace, kind=kind, variant=variant, **({"clock": clock} if clock else {}), approver=self.approvals, base=mgr.settings.workspace, overrides=self.overrides,
                                  local_only=True, ports=mgr.ports, max_parallel=1, fast_live=fast, router=mgr.router)
        self.fast_live = fast
        if mgr.scheduler is not None:
            mgr.scheduler.emit = self.bus.emit
            self.sampler = MetricsSampler(mgr.scheduler, self.bus.emit, lambda: llm.tokens_per_s).start()
        self._thread = threading.Thread(target=self._run_live, name=f"scenario-{self.id}", daemon=True)
        self._thread.start()

    def _run_live(self) -> None:
        self.state = "running"
        ok, problems = False, []
        try:
            res = self.orch.run()  # type: ignore[union-attr]
            ok, problems = res.ok, res.problems
            if self.pending_recovery and not self.orch.stopped.is_set():  # type: ignore[union-attr]
                action, agent = self.pending_recovery
                self.pending_recovery = None
                try:
                    ok, problems = self._recover(action, agent)
                except ValueError:
                    pass  # nothing had stopped after all
            if ok and self.recorder and self.then_ask:
                ok, problems = self._run_followups()
        except Exception:
            self.bus.emit("error", agent="orchestrator", message="the build stopped unexpectedly")
            problems = ["the build stopped unexpectedly"]
        self.state = "done" if ok else "failed"
        if self.sampler:
            self.sampler.stop()
        if self.recorder:
            try:
                self.recorder.finalize(self.root, ok, problems, self.record_info)
            except (RecordingError, OSError) as e:
                self.recorder.abort()
                self.bus.emit("error", agent="orchestrator", message=f"the recording could not be saved: {e}"[:200])

    def _run_followups(self) -> tuple[bool, list[str]]:
        """Recorded builds can include Ask-employee tasks after the build; they run in the same recording, then the project is verified again."""
        for step in self.then_ask:
            time.sleep(2)  # a human reads the finished build first
            self.ask(step["agent"], step["text"], True)
            self.orch.finish_requests()  # type: ignore[union-attr]
        ok = bool(self.orch.tests_passed and not self.orch.problems)  # type: ignore[union-attr]
        return ok, list(self.orch.problems)  # type: ignore[union-attr]

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
        hold_n = int(rec.meta.get("hold_approvals") or 0)  # a recording may stop at its first approvals for the presenter to answer
        held = 0
        outcome = {x["id"]: x.get("approve") for x in rec.events() if x["type"] == "approval_resolved"} if hold_n else {}
        skip_resolved: set[str] = set()  # recorded answers to approvals the presenter answered
        skip_waiting: set[str] = set()  # the recorded 'waiting for a human' that the player has already shown
        for e in rec.events():
            if self._stop.is_set():
                return
            if prev_ts is not None:
                self._sleep(min(max(e["ts"] - prev_ts, 0.0), self.mgr.settings.max_gap))
            prev_ts = e["ts"]
            data = {k: v for k, v in e.items() if k not in ("seq", "ts", "type")}
            data["replayed"] = True
            if e["type"] == "approval_resolved":
                if e["id"] in skip_resolved:
                    continue
                data["by"] = "recording-auto" if hold_n else "recording"  # nobody clicked: it was decided while the recording was made
            elif e["type"] == "agent_state" and e.get("state") == "waiting_human" and e.get("agent") in skip_waiting:
                skip_waiting.discard(e["agent"])
                continue
            elif e["type"] == "approval_needed" and held < hold_n:
                held += 1
                self.bus.emit("approval_needed", **data)
                self.bus.emit("agent_state", agent=e["agent"], state="waiting_human", replayed=True)
                recorded = "approved" if outcome.get(e["id"]) is not False else "denied"
                item = self.approvals.hold(e["id"], e["agent"], e["kind"], e.get("summary", ""), e.get("details", {}), f"in the recording this was {recorded}")
                self.approvals.wait_held(item)
                skip_resolved.add(e["id"])
                skip_waiting.add(e["agent"])
                continue
            if e["type"] == "project_created":
                data["slug"], data["path"] = (dest.name, str(dest)) if restored else (data.get("slug", ""), "")
            elif e["type"] == "app_running":
                url = self._restart_restored_app(dest, rec.meta.get("preset", ""), self.tracker.run_cmd, self.tracker.health_path) if restored else ""
                if not url:
                    continue  # nothing to open: skip the stale recorded URL
                data.update(url=url, port=int(url.rsplit(":", 1)[-1]), project=dest.name)
            elif e["type"] == "project_done":
                ok = bool(e.get("ok"))
                data["app_url"] = self.tracker.app_url
            self.bus.emit(e["type"], **data)
        self.state = "done" if ok else "failed"

    def _restart_restored_app(self, dest: Path, preset_name: str, run_cmd: str = "", health_path: str = "/") -> str:
        try:
            if run_cmd:  # an imported project: the run command was recorded with the project
                return self.mgr.ports.start(dest.name, dest, run_cmd, health_path, ok_below=500).url
            p = load_preset(preset_name)
            return self.mgr.ports.start(dest.name, dest, p.run_cmd, p.health_path).url
        except (PortError, Exception):
            self.bus.emit("error", agent="orchestrator", message="the recorded app could not be started again")
            return ""

    def finish_pick(self, ids: list[str]) -> dict:
        """Finish my project: the gaps the human chose to fix."""
        from .finish.build import FinishBuild
        if self.kind != "live" or not isinstance(self.orch, FinishBuild):
            raise SessionError("This is not a Finish-my-project build.", 409)
        self.orch.pick(ids)
        return {"selected": self.orch.selected or []}

    def set_speed(self, speed: float) -> float:
        self.speed = max(0.1, min(float(speed), 1000.0))
        return self.speed

    # -- controls -----------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise SessionError(f"mode must be one of: {', '.join(MODES)}")
        if self.orch and (mode == "simulation") != (self.mode == "simulation"):  # who plays which role is fixed when the build is created
            raise SessionError("Simulation mode is chosen before the build starts; start a new build to switch into or out of it.", 409)
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
            with agent_context(agent_id):
                reply = self.orch.llm.call(model.id, messages, AskReply).parsed.reply.strip()  # type: ignore[attr-defined]
        except Exception as e:  # never leak a trace: AgentFailed/ProviderError messages are already user-safe
            msg = e.reason if isinstance(e, AgentFailed) else str(e) if isinstance(e, ProviderError) else "could not answer right now"
            raise SessionError(msg[:200], 503) from None
        self.chats[agent_id] += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        self.bus.emit("message_sent", **{"from": agent_id, "to": "human", "text": reply})
        return {"reply": reply}

    # -- simulation: a task the human works on ---------------------------------------------------
    def submit_task(self, tid: str) -> dict:
        if self.kind == "replay" or self.orch is None:
            raise SessionError("Demo mode replays a recording; tasks can only be submitted in a live build.", 409)
        try:
            return self.orch.submit_human_task(tid)
        except ValueError as e:
            raise SessionError(str(e), 409) from None

    def _ide(self, method: str, *args):
        """The in-app IDE: the orchestrator's answer, or a SessionError carrying its user-safe message and status."""
        if self.kind == "replay" or self.orch is None:
            raise SessionError("Demo mode replays a recording; the IDE only works in a live Simulation build.", 409)
        try:
            return getattr(self.orch, method)(*args)
        except IDEError as e:
            raise SessionError(str(e), e.status) from None

    def ide_tree(self, role: str) -> dict:
        return self._ide("ide_tree", role)

    def ide_read(self, role: str, path: str, auto: bool = False) -> dict:
        if auto and isinstance(self.orch, ScenarioBuild):
            return self._ide("ide_read", role, path, True)
        return self._ide("ide_read", role, path)

    def ide_write(self, role: str, path: str, content: str) -> dict:
        return self._ide("ide_write", role, path, content)

    def ide_run_tests(self, role: str) -> dict:
        return self._ide("ide_run_tests", role)

    def ide_search(self, role: str, query: str) -> dict:
        """A project-wide search in the role's folder. A scenario logs it (query and match count) in the session log."""
        if self.kind == "replay" or self.orch is None:
            raise SessionError("Demo mode replays a recording; the IDE only works in a live Simulation build.", 409)
        try:
            if isinstance(self.orch, ScenarioBuild):
                return self.orch.ide_search(role, query)
            return search_worktree(self.orch._ide_worktree(role), query)
        except IDEError as e:
            raise SessionError(str(e), e.status) from None

    # -- a scenario: the incident channel, the guide, the session log ----------------------------------
    def _scenario_build(self) -> ScenarioBuild:
        if self.scenario is None or not isinstance(self.orch, ScenarioBuild):
            raise SessionError("This project is not a scenario.", 409)
        return self.orch

    def channel_post(self, text: str, to: str | None) -> dict:
        orch = self._scenario_build()
        if to and to not in orch.scenario.characters:
            raise SessionError("That teammate is not on this incident.", 400)
        try:
            return orch.director.post(text, to or None)
        except ValueError as e:
            raise SessionError(str(e), 409) from None

    def session_info(self) -> dict:
        """The whole session so far: the scenario, the clock, every logged event (quotable by id), the guide and the channel."""
        orch = self._scenario_build()
        return {"scenario": orch.scenario.public(), "attempt": orch.attempt, "kind": orch.kind, "variant": orch.variant, "scoring": orch.debrief.rubric.scoring() if orch.debrief else [], "started_at": orch.log.started_at, "elapsed": round(orch.log.now(), 1), "state": self.state,
                "summary": orch.log.summary(), "events": orch.log.events(), "guide": orch.guide.state(), "messages": list(orch.director.messages)}

    def report(self, markdown: bool = False) -> dict | str:
        """The debrief report of this attempt (the dict, or the markdown source), once the debrief has finished."""
        orch = self._scenario_build()
        report = orch.debrief.report if orch.debrief else None
        if report is None:
            raise SessionError("There is no report yet: it is written when the fix has been accepted and the team has met.", 404)
        if not markdown:
            return report
        assert self.root
        return (self.root / report["files"]["md"]).read_text(encoding="utf-8")

    def guide_doc(self, tid: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", tid):
            raise SessionError("unknown task", 404)
        if not self.root:
            raise SessionError("The project has no files yet.", 409)
        doc = self.root / ".q" / "guides" / f"{tid}.md"
        if not doc.is_file():
            raise SessionError("There is no guide for that task.", 404)
        return doc.read_text(encoding="utf-8")

    def task_doc(self, tid: str) -> str:
        """The markdown the human reads for one of their tasks (written when the task was handed over)."""
        if not re.fullmatch(r"[A-Za-z0-9_-]+", tid):
            raise SessionError("unknown task", 404)
        if not self.root:
            raise SessionError("The project has no files yet.", 409)
        doc = self.root / ".q" / "tasks" / f"{tid}.md"
        if not doc.is_file():
            raise SessionError("There is no task document for that task.", 404)
        return doc.read_text(encoding="utf-8")

    # -- an employee needs the human: Retry this step, Re-plan, Stop build ----------------------
    def escalation(self, action: str, agent_id: str) -> dict:
        if action not in ("retry", "replan", "stop"):
            raise SessionError("action must be retry, replan or stop")
        if self.kind == "replay" or self.orch is None:
            raise SessionError("Demo mode replays a recording; these buttons work in a live build.", 409)
        if action == "stop":
            return self._stop_build(agent_id)
        if self.state == "running":  # the rest of the team is still working: the step is picked up the moment the build stops
            self.pending_recovery = (action, agent_id)
            message = "Noted. " + ("The step is retried" if action == "retry" else "The Planner re-plans the step") + " as soon as the work that is running now has stopped."
            self.bus.emit("escalation_action", agent=agent_id, action=action, message=message, queued=True)
            return {"message": message, "queued": True}
        try:
            self.orch.prepare_recovery(agent_id)
        except ValueError as e:
            raise SessionError(str(e), 409) from None
        if not self._extra.acquire(blocking=False):
            raise SessionError("Something is already running; try again in a moment.", 409)
        threading.Thread(target=self._run_recovery, args=(action, agent_id), name=f"recover-{self.id}", daemon=True).start()
        return {"message": self._recovery_text(action, agent_id), "queued": False}

    def _recovery_text(self, action: str, agent_id: str) -> str:
        who = self.mgr.roster[agent_id].name if agent_id in self.mgr.roster else "The team"
        return f"{who} tries the step again with fresh attempts." if action == "retry" else "The Planner splits the step differently, then the team carries on."

    def _recover(self, action: str, agent_id: str) -> tuple[bool, list[str]]:
        start, task = self.orch.prepare_recovery(agent_id)  # type: ignore[union-attr]  # ValueError when nothing has stopped
        self.bus.emit("escalation_action", agent=agent_id, action=action, message=self._recovery_text(action, agent_id), queued=False)
        res = self.orch.resume(action, start, task)  # type: ignore[union-attr]
        return res.ok, res.problems

    def _run_recovery(self, action: str, agent_id: str) -> None:
        try:
            self.state = "running"
            try:
                ok, _ = self._recover(action, agent_id)
            except ValueError:
                ok = False
            self.state = "done" if ok else "failed"
        finally:
            self._extra.release()

    def _stop_build(self, agent_id: str) -> dict:
        running = self.state == "running"
        self.pending_recovery = None
        self.orch.stop()  # type: ignore[union-attr]
        self.approvals.release_all(False, "stopped")
        message = ("The team stops after the step in hand. Everything already merged is kept." if running
                   else "Nothing is running; the build stays as it is. Everything already merged is kept.")
        self.bus.emit("escalation_action", agent=agent_id, action="stop", message=message, queued=False)
        for aid, a in list(self.tracker.agents.items()):
            if a.get("state") == "waiting_human":
                self.bus.emit("agent_state", agent=aid, state="idle")
        return {"message": message, "queued": False}

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
        try:
            if self.tracker.run_cmd:
                app = self.mgr.ports.start(self.root.name, self.root, self.tracker.run_cmd, self.tracker.health_path, ok_below=500)
            else:
                preset = load_preset(self.tracker.preset or "fastapi-vanilla")
                app = self.mgr.ports.start(self.root.name, self.root, preset.run_cmd, preset.health_path)
        except PortError as e:
            raise SessionError(str(e)[:200], 503) from None
        self.bus.emit("app_running", url=app.url, port=app.port, project=self.root.name)
        return {"running": True, "url": app.url}

    def stop_autoplay(self) -> dict:
        """The viewer pressed Stop: the script ends, the team and the debrief are halted, and the demo's project folder is removed (nothing of a demo is kept)."""
        runner = self.autoplay
        if runner is None:
            raise SessionError("This is not an autoplay run.", 409)
        runner._stop.set()
        self.stop()
        if self.orch:
            self.orch.stop()  # releases the task, so a Submit that is running comes back
        runner.stop(30)
        if self._thread:
            self._thread.join(30)
        root = self.root
        if root and root.is_dir() and not runner.alive():
            if self.orch:
                self.orch.messages.close()
            remove_tree(root)
        return {"stopped": True, "state": runner.state}

    def set_autoplay_speed(self, speed: int) -> dict:
        if self.autoplay is None:
            raise SessionError("This is not an autoplay run.", 409)
        if speed not in SPEEDS:
            raise SessionError("The speed is 1 or 2.", 400)
        self.autoplay.set_speed(speed)
        return {"speed": speed}

    def stop(self) -> None:
        self._stop.set()
        if self.autoplay:
            self.autoplay._stop.set()
        if isinstance(self.orch, ScenarioBuild):
            self.orch.director.stop()
            if self.orch.debrief:
                self.orch.debrief.stop()
        self.approvals.release_all(False, "shutdown")

    def status(self) -> dict:
        snap = self.tracker.snapshot()
        return {"id": self.id, "goal": self.goal, "kind": self.kind, "state": self.state, "mode": self.mode, "speed": self.speed,
                "created": self.created, "events": len(self.bus.history), "overrides": dict(self.overrides), "recording": self.recording, "fast_live": self.fast_live,
                "pending_approvals": self.approvals.pending(), "app": self.app(), **snap,
                **({"scenario": {**self.scenario.public(), "attempt": self.orch.attempt, "kind": self.orch.kind, "variant": self.orch.variant, "started_at": self.orch.log.started_at, "summary": self.orch.log.summary()}} if self.scenario and isinstance(self.orch, ScenarioBuild) else {})}


# -- all sessions -----------------------------------------------------------------------------------

class SessionManager:
    def __init__(self, settings: Settings, registry: ModelRegistry | None = None, llm_factory: Callable[..., LLMClient] | None = None):
        self.settings = settings
        self.registry = registry or ModelRegistry.load()
        if registry is None and llm_factory is None and settings.q_mode != "replay":
            self.registry.installed_probe = ollama_installed_probe()  # a model that is not pulled in Ollama is never routed to
        self.roster = load_agents()
        self.ports = PortManager()
        self._llm_factory = llm_factory
        self.board = Leaderboard(settings.leaderboard_db, settings.shipped_results)
        self.router = Router(self.registry, self.board)
        # The scheduler talks to the real Ollama; tests that inject a fake LLM have no GPU to schedule.
        self.scheduler = ModelScheduler(self.registry) if llm_factory is None and settings.q_mode != "replay" else None
        self.sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def make_llm(self, observer) -> LLMClient:
        return self._llm_factory(self.registry, observer) if self._llm_factory else LLMClient(self.registry, observer=observer, scheduler=self.scheduler)

    def get(self, sid: str) -> Session:
        s = self.sessions.get(sid)
        if s is None:
            raise SessionError("project not found", 404)
        return s

    def create(self, req: CreateRequest) -> Session:
        if req.import_from:  # Finish my project: decline politely, before anything starts, what Q does not finish
            from .finish.analyze import ImportDeclined
            from .finish.importer import check, fetch, scratch_dir
            try:
                check(fetch(req.import_from, scratch_dir()))
            except ImportDeclined as e:
                raise SessionError(str(e), 422) from None
            req.goal = req.goal.strip() or "Finish the project " + req.import_from.strip().rstrip("/").split("/")[-1].removesuffix(".git")
        goal = req.goal.strip()
        if not goal or len(goal) > 1000:
            raise SessionError("describe the goal in 1 to 1000 characters")
        req.goal = goal
        if req.mode not in MODES:
            raise SessionError(f"mode must be one of: {', '.join(MODES)}")
        if req.mode == "simulation":
            if req.import_from:
                raise SessionError("Simulation mode builds a new app; it cannot be combined with Finish my project.")
            roles = ["backend"] if req.human_roles is None else list(dict.fromkeys(req.human_roles))
            if any(r not in ENGINEERS for r in roles):
                raise SessionError(f"human_roles can only contain: {', '.join(ENGINEERS)}")
            req.human_roles = roles
        elif req.human_roles:
            raise SessionError("human_roles only applies to Simulation mode.")
        if req.preset and req.preset not in list_presets():
            raise SessionError(f"unknown preset; choose one of: {', '.join(list_presets())}")
        if req.record_as:
            check_name(req.record_as)  # RecordingError -> 400 via the API layer
        demo = req.demo or self.settings.q_mode == "replay"
        if not demo and not req.import_from:  # an imported project is not a goal: its name must not be read as one (a 'game' folder)
            scope = classify_goal(goal)
            if scope.level == "impossible":  # refused before any model work, with goals that do work
                raise SessionError(scope.message, 422)
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

    def start_scenario(self, scenario_id: str, kind: str = "learner", variant: str = "", clock=None) -> Session:
        try:
            scn = load_scenario(scenario_id)
            rubric = load_rubric(scn)
        except ScenarioError as e:
            unknown = str(e).startswith("unknown")
            raise SessionError(str(e) if unknown else "That scenario is not available.", 404 if unknown else 500) from None
        with self._lock:
            if any(s.kind == "live" and s.state in ("starting", "running") for s in self.sessions.values()):
                raise SessionError("A build is already running; the GPU runs one build at a time.", 409)
            for other in self.sessions.values():  # the last run's debrief writes the attempt history when it ends: a new run must not read it half-way
                if isinstance(other.orch, ScenarioBuild) and other.orch.debrief is not None:
                    other.orch.debrief.join(5.0)
            s = Session(uuid.uuid4().hex[:8], CreateRequest(goal=scn.goal, mode="simulation", human_roles=[scn.role]), "live", self)
            self.sessions[s.id] = s
            try:
                s.start_scenario(scn, rubric, History(self.settings.workspace, scn.id, kind).next_number(), kind, variant, clock)
            except Exception:
                del self.sessions[s.id]
                raise
        return s

    def start_autoplay(self, scenario_id: str, variant: str, speed: int = 1) -> Session:
        """"Watch a run": a demo session of the scenario played by a script. Its session clock runs faster than real time (the weak run waits five quiet minutes for Aarav's nudge)."""
        if variant not in VARIANTS:
            raise SessionError("The run is strong or weak.", 400)
        if speed not in SPEEDS:
            raise SessionError("The speed is 1 or 2.", 400)
        clock = VirtualClock() if self.settings.autoplay_virtual else ScaledClock(speed, CLOCK_FACTOR[variant])
        s = self.start_scenario(scenario_id, "demo", variant, clock)
        s.autoplay = AutoplayRunner(s, variant, clock, speed).start()
        return s

    def shutdown(self) -> None:
        for s in self.sessions.values():
            s.stop()
        self.ports.stop_all()
