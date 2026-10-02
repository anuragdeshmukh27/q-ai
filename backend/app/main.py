"""Q's HTTP + WebSocket API. Run from backend/:  .venv\\Scripts\\python.exe -m uvicorn app.main:create_app --factory --port 8000

Q_MODE=live (default) | record (every live build is recorded) | replay (every build is a replay; no model, no network).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .approvals import UnknownApproval
from .config import load_env
from .leaderboard import Leaderboard
from .presets import list_presets, load_preset
from .projectfiles import ProjectFileError, branch_diff, commit_diff, commits, file_tree, read_project_file
from .recording import RecordingError, list_recordings
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


class AskBody(BaseModel):
    text: str
    as_task: bool = False


def create_app(settings: Settings | None = None, manager: SessionManager | None = None) -> FastAPI:
    load_env()
    settings = settings or Settings.from_env()
    mgr = manager or SessionManager(settings)
    board = Leaderboard(settings.leaderboard_db)

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
                "modes": ["assisted", "supervised", "autonomous"], "recordings": list_recordings(settings.recordings)}

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

    @app.get("/api/leaderboard")
    def leaderboard():
        return board.summary()

    # -- projects -----------------------------------------------------------------
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
