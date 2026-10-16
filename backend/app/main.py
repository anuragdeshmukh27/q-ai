"""Q's HTTP + WebSocket API. Run from backend/:  .venv\\Scripts\\python.exe -m uvicorn app.main:create_app --factory --port 8000

Q_MODE=live (default) | record (every live build is recorded) | replay (every build is a replay; no model, no network).
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from .approvals import UnknownApproval
from .config import load_env
from .leaderboard import baseline_report
from .metrics import read_metrics
from .cost import load_pricing
from .presets import list_presets, load_preset
from .projectfiles import ProjectFileError, branch_diff, commit_diff, commits, file_tree, read_project_file
from .recording import RecordingError, list_recordings, load_recording
from .scenarios.jobs.modelcall import MODEL_ID
from .scenarios.jobs.samples import list_samples
from .scenarios.jobs.service import JobBody, JobRequestError, analyze as analyze_job
from .scenarios.loader import ScenarioError, list_scenarios
from .scenarios.progress import build_progress, read_report, render_markdown, report_path
from .scenarios.reports import History
from .session import CreateRequest, Session, SessionError, SessionManager, Settings

ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


class ApprovalDecision(BaseModel):
    approve: bool


class ModeBody(BaseModel):
    mode: str


class SpeedBody(BaseModel):
    speed: float


class OverrideBody(BaseModel):
    model: str | None = None


class EscalationBody(BaseModel):
    action: str
    agent: str = ""


class FileBody(BaseModel):
    path: str
    content: str


class AutoplayBody(BaseModel):
    variant: str
    speed: int = 1
    job: JobBody | None = None  # a job description the run is started from (the check that role-fit emphasis leaves the standard score alone)


class StartBody(BaseModel):
    job: JobBody | None = None  # start the scenario for a job description (/api/jd/analyze showed the person why it fits)


class AutoplaySpeedBody(BaseModel):
    speed: int


class ChannelBody(BaseModel):
    text: str
    to: str | None = None


class AskBody(BaseModel):
    text: str
    as_task: bool = False


def create_app(settings: Settings | None = None, manager: SessionManager | None = None) -> FastAPI:
    load_env()
    settings = settings or Settings.from_env()
    mgr = manager or SessionManager(settings)
    board = mgr.board

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        mgr.shutdown()

    app = FastAPI(title="Q", lifespan=lifespan)
    app.state.manager = mgr
    app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(SessionError)
    async def _session_error(_: Request, e: SessionError):
        return JSONResponse({"detail": str(e)}, status_code=e.status)

    @app.exception_handler(ProjectFileError)
    async def _file_error(_: Request, e: ProjectFileError):
        return JSONResponse({"detail": str(e)}, status_code=e.status)

    @app.exception_handler(RecordingError)
    async def _recording_error(_: Request, e: RecordingError):
        return JSONResponse({"detail": str(e)}, status_code=400)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, __: Exception):  # never show a stack trace
        return JSONResponse({"detail": "Something went wrong on the server. Try again."}, status_code=500)

    def session(pid: str) -> Session:
        return mgr.get(pid)

    def project_root(pid: str):
        s = session(pid)
        if not s.root or not s.root.is_dir():
            raise SessionError("This project has no files yet.", 409)
        return s.root

    # -- general ----------------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"ok": True, "q_mode": settings.q_mode}

    @app.get("/api/config")
    def config():
        return {"q_mode": settings.q_mode, "presets": {n: load_preset(n).description for n in list_presets()},
                "modes": ["assisted", "supervised", "autonomous", "simulation"], "recordings": list_recordings(settings.recordings)}

    @app.get("/api/recordings")
    def recordings():
        return list_recordings(settings.recordings)

    @app.get("/api/agents")
    def agents():
        return [a.model_dump() for a in mgr.roster.values()]

    @app.get("/api/models")
    def models():
        reg = mgr.registry
        return [{**m.model_dump(), "available": reg.is_available(m.id), "local": m.local} for m in reg.models.values()]

    @app.get("/api/metrics")
    def metrics():
        m = read_metrics()
        sch = mgr.scheduler
        return {**m, "loaded": sch.loaded() if sch else [], "budget_gb": sch.snapshot()["budget_gb"] if sch else None}

    @app.get("/api/leaderboard")
    def leaderboard():
        """Role x model benchmark scores plus what the router picks for each employee now, and why."""
        caps = {a.id: a.model_capability for a in mgr.roster.values()}
        mgr.router.refresh()
        return {**board.summary(), "router": mgr.router.table(list(caps), caps), "margin": mgr.router.margin, "min_runs": mgr.router.min_runs,
                "safe_default": mgr.router.default_model("coding").id, "note": mgr.registry.router_config.get("note", "")}

    @app.get("/api/costs")
    def costs():
        """What each recorded build used: tokens, GPU electricity here, and the same tokens at the cloud prices of config/pricing.yaml."""
        rows = []
        for meta in list_recordings(mgr.settings.recordings):
            try:
                ev = load_recording(mgr.settings.recordings, meta["name"]).events()
            except RecordingError:
                continue
            report = next((e for e in reversed(ev) if e["type"] == "cost_report"), None)
            if report:
                rows.append({"name": meta["name"], "title": meta.get("title", meta["name"]), **{k: v for k, v in report.items() if k not in ("seq", "ts", "type")}})
        return {"rows": rows, "pricing": load_pricing()}

    @app.get("/api/baseline")
    def baseline():
        """Team vs a single agent on the same goals and the same model (scripts/baseline.py), with who wrote the code in every build."""
        return baseline_report()

    # -- projects -----------------------------------------------------------------
    class FinishPick(BaseModel):
        gaps: list[str] = []

    @app.post("/api/projects/{pid}/finish")
    def finish_pick(pid: str, body: FinishPick):
        """Finish my project: the human's choice of gaps to fix (the build waits for it unless it was started with auto_fix)."""
        return mgr.get(pid).finish_pick(body.gaps)

    @app.post("/api/projects", status_code=201)
    def create_project(req: CreateRequest):
        return mgr.create(req).status()

    @app.get("/api/projects")
    def list_projects():
        return [{"id": s.id, "goal": s.goal, "kind": s.kind, "state": s.state, "created": s.created} for s in mgr.sessions.values()]

    @app.get("/api/projects/{pid}")
    def project_status(pid: str):
        return session(pid).status()

    @app.get("/api/projects/{pid}/events")
    def project_events(pid: str, after: int = -1):
        return session(pid).bus.history[max(after + 1, 0):]

    @app.post("/api/projects/{pid}/mode")
    def set_mode(pid: str, body: ModeBody):
        s = session(pid)
        s.set_mode(body.mode)
        return {"mode": s.mode}

    @app.post("/api/projects/{pid}/speed")
    def set_speed(pid: str, body: SpeedBody):
        s = session(pid)
        if s.kind != "replay":
            raise SessionError("Speed only applies to Demo mode replays.", 409)
        return {"speed": s.set_speed(body.speed)}

    # -- approvals ------------------------------------------------------------------
    @app.get("/api/projects/{pid}/approvals")
    def approvals(pid: str):
        return session(pid).approvals.all()

    @app.post("/api/projects/{pid}/approvals/{aid}")
    def decide(pid: str, aid: str, body: ApprovalDecision):
        try:
            decided = session(pid).approvals.resolve(aid, body.approve)
        except UnknownApproval:
            raise HTTPException(404, "approval not found") from None
        if not decided:
            raise HTTPException(409, "that approval was already decided")
        return {"id": aid, "approve": body.approve}

    # -- employees ------------------------------------------------------------------
    @app.post("/api/projects/{pid}/agents/{agent_id}/model")
    def override_model(pid: str, agent_id: str, body: OverrideBody):
        return {"overrides": session(pid).set_override(agent_id, body.model)}

    @app.post("/api/projects/{pid}/agents/{agent_id}/ask")
    def ask(pid: str, agent_id: str, body: AskBody):
        text = body.text.strip()
        if not text or len(text) > 2000:
            raise SessionError("write a message of 1 to 2000 characters")
        return session(pid).ask(agent_id, text, body.as_task)

    @app.post("/api/projects/{pid}/escalation")
    def escalation(pid: str, body: EscalationBody):
        return session(pid).escalation(body.action, body.agent)

    # -- simulation: tasks the human works on ------------------------------------------------
    @app.post("/api/projects/{pid}/tasks/{tid}/submit")
    def submit_task(pid: str, tid: str):
        """Run the tests in the human's worktree; green work is reviewed and merged. Answers {ok, stage: tests | review | accepted | stopped, summary, failed, items}."""
        return session(pid).submit_task(tid)

    @app.get("/api/projects/{pid}/tasks/{tid}/doc")
    def task_doc(pid: str, tid: str):
        """The task document as markdown source (served as plain text so a browser tab shows it instead of downloading it)."""
        return PlainTextResponse(session(pid).task_doc(tid), media_type="text/plain; charset=utf-8")

    # -- simulation scenarios: a ready-made incident, its channel, guide and session log --------------------
    @app.get("/api/scenarios")
    def scenarios():
        """The scenario cards for the picker (the script, the facts and the guide stay on the server)."""
        try:
            return [s.public() for s in list_scenarios()]
        except ScenarioError:
            raise SessionError("The scenarios could not be loaded.", 500) from None

    @app.post("/api/scenarios/{sid}/start", status_code=201)
    def start_scenario(sid: str, body: StartBody | None = None):
        """A project from the scenario's seed: no design or planning calls, one human task for the scenario's role, the AI team on call. With `job`, the briefing and the role-fit emphasis are adapted to it."""
        return mgr.start_scenario(sid, job=body.job if body else None).status()

    # -- job descriptions: read one, rank the scenarios against it ---------------------------------------------------
    @app.get("/api/jd/samples")
    def jd_samples():
        """The bundled sample job descriptions (backend, database, frontend)."""
        return list_samples()

    @app.post("/api/jd/analyze")
    def jd_analyze(body: JobBody):
        """Read a pasted job description or a sample (the 7b when it can, else the keyword reader; the answer says which) and rank the scenarios against it."""
        try:
            return analyze_job(body, mgr.make_llm(None), lambda: mgr.registry.is_available(MODEL_ID))
        except JobRequestError as e:
            raise SessionError(str(e), 400) from None

    @app.post("/api/scenarios/{sid}/autoplay", status_code=201)
    def start_autoplay(sid: str, body: AutoplayBody):
        """"Watch a run": a scripted learner (variant strong or weak) plays the scenario through the same calls a person makes. The attempt is a demo: marked in its report, not in the learner's history."""
        return mgr.start_autoplay(sid, body.variant, body.speed, job=body.job).status()

    @app.post("/api/projects/{pid}/autoplay/speed")
    def autoplay_speed(pid: str, body: AutoplaySpeedBody):
        return session(pid).set_autoplay_speed(body.speed)

    @app.post("/api/projects/{pid}/autoplay/stop")
    def autoplay_stop(pid: str):
        """Stop the scripted run and the session with it; nothing of a demo is kept."""
        return session(pid).stop_autoplay()

    @app.post("/api/projects/{pid}/channel")
    def channel_post(pid: str, body: ChannelBody):
        """The learner posts in the incident channel. Answers at once; a teammate who was asked replies as a `channel_message` event."""
        text = body.text.strip()
        if not text or len(text) > 1000:
            raise SessionError("write a message of 1 to 1000 characters")
        return session(pid).channel_post(text, body.to)

    @app.get("/api/projects/{pid}/session")
    def session_info(pid: str):
        """The scenario session so far: clock, logged events with their ids, hints, guide, channel."""
        return session(pid).session_info()

    @app.get("/api/projects/{pid}/report")
    def debrief_report(pid: str, format: str = "json"):
        """The debrief report of a scenario attempt (404 until the fix is accepted and the team has met). `?format=md` answers the markdown that is saved in the project."""
        if format not in ("json", "md"):
            raise SessionError("format must be json or md")
        out = session(pid).report(markdown=format == "md")
        return PlainTextResponse(out, media_type="text/plain; charset=utf-8") if format == "md" else out

    # -- my progress: the learner's real attempts across the scenarios (demo runs never count) ----------------------------
    @app.get("/api/progress")
    def progress():
        """Everything the My progress page shows: attempts per scenario, the five skills, the weakest one with a gap quoted from its report, the suggested next step."""
        return build_progress(mgr.settings.workspace)

    @app.get("/api/progress/export")
    def progress_export(format: str = "json"):
        """The same data as a download: `?format=md` or `json`."""
        if format not in ("json", "md"):
            raise SessionError("format must be json or md")
        data = build_progress(mgr.settings.workspace)
        body, media = (render_markdown(data), "text/markdown; charset=utf-8") if format == "md" else (json.dumps(data, indent=1), "application/json")
        return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="q-progress.{format}"'})

    @app.get("/api/progress/report/{scenario}/{attempt}")
    def progress_report(scenario: str, attempt: int, format: str = "json"):
        """The saved report of one of the learner's real attempts (404 when the history has no such attempt or the report file is gone; a demo's is never served)."""
        if format not in ("json", "md"):
            raise SessionError("format must be json or md")
        record = next((a for a in History(mgr.settings.workspace, scenario).attempts() if a["attempt"] == attempt and a.get("kind") != "demo"), None)
        report = read_report(mgr.settings.workspace, str(record.get("project", "")), attempt, scenario) if record else None
        if report is None:
            raise SessionError("That report is no longer saved.", 404)
        if format == "json":
            return report
        path = report_path(mgr.settings.workspace, record["project"], attempt, "md")
        try:
            return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/plain; charset=utf-8")
        except (OSError, AttributeError):
            raise SessionError("That report is no longer saved.", 404) from None

    @app.delete("/api/progress")
    def progress_reset():
        """Clear the learner's attempt history. Demo histories, saved reports and recordings stay; refused while a debrief is still writing the history."""
        if mgr.debrief_running():
            raise SessionError("A debrief is still going; reset when it has finished.", 409)
        return {"cleared": History.clear_learner(mgr.settings.workspace)}

    @app.get("/api/projects/{pid}/tasks/{tid}/guide")
    def task_guide(pid: str, tid: str):
        return PlainTextResponse(session(pid).guide_doc(tid), media_type="text/plain; charset=utf-8")

    # -- simulation: the in-app IDE for the role the human plays -------------------------------
    @app.get("/api/projects/{pid}/ide/{role}/tree")
    def ide_tree(pid: str, role: str):
        """The files of the role's worktree: {task, ready, running, files: [{path, size, owner, writable}], names}."""
        return session(pid).ide_tree(role)

    @app.get("/api/projects/{pid}/ide/{role}/file")
    def ide_read(pid: str, role: str, path: str, auto: bool = False):
        return session(pid).ide_read(role, path, auto)

    @app.put("/api/projects/{pid}/ide/{role}/file")
    def ide_write(pid: str, role: str, body: FileBody):
        """Save a file inside the role's owned paths while the role has an open human task (403 elsewhere, 409 without a task)."""
        return session(pid).ide_write(role, body.path, body.content)

    @app.get("/api/projects/{pid}/ide/{role}/search")
    def ide_search(pid: str, role: str, q: str):
        """Search every file of the role's folder (read-only ones too): {query, matches, files, truncated, results: [{path, count, lines: [{line, text}]}]}."""
        return session(pid).ide_search(role, q)

    @app.post("/api/projects/{pid}/ide/{role}/tests")
    def ide_tests(pid: str, role: str):
        """Run the suite in the background: `human_test_output` lines, then one `human_test_result {task, ok, passed, failed, tests, summary}`."""
        return session(pid).ide_run_tests(role)

    # -- the built app ----------------------------------------------------------------
    @app.get("/api/projects/{pid}/app")
    def app_status(pid: str):
        return session(pid).app()

    @app.post("/api/projects/{pid}/app")
    def app_start(pid: str):
        s = session(pid)
        return s.app() if s.app()["running"] else s.start_app()

    # -- files, commits, diffs ------------------------------------------------------------
    @app.get("/api/projects/{pid}/files")
    def files(pid: str):
        return file_tree(project_root(pid))

    @app.get("/api/projects/{pid}/file")
    def file_content(pid: str, path: str):
        return read_project_file(project_root(pid), path)

    @app.get("/api/projects/{pid}/commits")
    def project_commits(pid: str):
        return commits(project_root(pid))

    @app.get("/api/projects/{pid}/commits/{sha}")
    def project_commit(pid: str, sha: str):
        return commit_diff(project_root(pid), sha)

    @app.get("/api/projects/{pid}/diff")
    def project_diff(pid: str, branch: str):
        return branch_diff(project_root(pid), branch)

    # -- event stream -----------------------------------------------------------------
    @app.websocket("/ws/{pid}")
    async def stream(ws: WebSocket, pid: str):
        s = mgr.sessions.get(pid)
        await ws.accept()
        if s is None:
            await ws.close(code=4404, reason="project not found")
            return
        try:
            nxt = max(int(ws.query_params.get("after", "-1")) + 1, 0)
        except ValueError:
            nxt = 0
        gone = asyncio.Event()

        async def watch():  # client messages are ignored; this only notices a disconnect
            try:
                while True:
                    await ws.receive_text()
            except Exception:
                gone.set()

        watcher = asyncio.create_task(watch())
        try:
            while not gone.is_set():
                for e in await asyncio.to_thread(s.bus.wait_for, nxt, 0.5):
                    await ws.send_json(e)
                    nxt = e["seq"] + 1
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            watcher.cancel()

    return app
