"""App entry point (locked: engineers add routers under backend/api/, they never edit this file).

Every module in backend/api/ that defines a `router` is included automatically.
"""
import importlib
import pkgutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import api

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="App")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


for _mod in pkgutil.iter_modules(api.__path__):
    _router = getattr(importlib.import_module(f"backend.api.{_mod.name}"), "router", None)
    if _router is not None:
        app.include_router(_router)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
