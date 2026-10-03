"""App entry point (locked: engineers add routers under backend/api/, they never edit this file).

Every module in backend/api/ that defines a `router` is included automatically.
"""
import importlib
import pkgutil
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
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


_KIT = '<link rel="stylesheet" href="/static/ui-kit.css"><script src="/static/ui-kit.js"></script>'


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    """The page, always carrying the UI kit: it is added to <head> when the page does not already link it."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    if "ui-kit.css" not in html:
        html, n = re.subn(r"<head[^>]*>", lambda m: m.group(0) + _KIT, html, count=1, flags=re.IGNORECASE)
        html = html if n else _KIT + html
    return HTMLResponse(html)


app.mount("/static", StaticFiles(directory=STATIC), name="static")
