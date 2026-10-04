"""App entry point (locked: engineers add routers under backend/api/, they never edit this file).

Every module in backend/api/ that defines a `router` is included automatically.
"""
import importlib
import os
import pkgutil
import re
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import api
from backend.validation import BLANK, INVALID

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="App")


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    """An empty required text field is a 400 with a message the form can show; every other invalid request keeps FastAPI's 422."""
    for err in exc.errors():
        if err.get("type") in (BLANK, INVALID):
            return JSONResponse({"detail": err["msg"]}, status_code=400)
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(sqlite3.IntegrityError)
async def refused_by_the_database(request: Request, exc: sqlite3.IntegrityError):
    """A rule kept in the schema (a unique value, a status flow, a full event) answers 409 with its message; the form shows it."""
    text = str(exc)
    unique = re.search(r"UNIQUE constraint failed: ([\w.]+(?:, [\w.]+)*)", text)
    if unique:
        column = unique.group(1).split(",")[-1].strip().split(".")[-1]
        text = column.replace("_", " ").strip().capitalize() + " already exists"
    return JSONResponse({"detail": text}, status_code=409)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


for _mod in pkgutil.iter_modules(api.__path__):
    _router = getattr(importlib.import_module(f"backend.api.{_mod.name}"), "router", None)
    if _router is not None:
        app.include_router(_router)


if os.environ.get("Q_SEED") == "1":  # an app that is started to be looked at opens with realistic data (see backend/seed.py); tests and builds never set this
    try:
        from backend.seed import seed

        seed()
    except Exception:
        pass


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
