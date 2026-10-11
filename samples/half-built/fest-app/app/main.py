from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import events, registrations

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Fest app")
app.include_router(events.router, prefix="/api")
app.include_router(registrations.router, prefix="/api")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
