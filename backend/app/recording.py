"""Record and replay (CLAUDE.md section 9).

A recording is a folder under `recordings/<name>/`:
  meta.json         goal, outcome, durations, models
  events.jsonl      the full event stream (what the UI replays)
  llm.jsonl         every raw model response of the run
  snapshot.bundle   `git bundle` of the finished project (all branches), so the built app can be restored and opened

It is written to a hidden temp folder and renamed on `finalize`, so a crashed run never leaves a half recording that looks valid.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}$")


class RecordingError(Exception):
    """Safe to show in the UI."""


def check_name(name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise RecordingError("a recording name uses lowercase letters, digits and dashes (max 49 characters)")
    return name


def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RecordingError(f"git {args[0]} failed: {(r.stderr or r.stdout).strip()[:200]}")


class Recorder:
    def __init__(self, base: Path, name: str, goal: str, overwrite: bool = False):
        self.base, self.name, self.goal = Path(base), check_name(name), goal
        self.final = self.base / name
        if self.final.exists() and not overwrite:
            raise RecordingError(f"a recording named '{name}' already exists")
        self.tmp = self.base / f".tmp-{name}"
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self._events = open(self.tmp / "events.jsonl", "w", encoding="utf-8", newline="\n")
        self._llm = open(self.tmp / "llm.jsonl", "w", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()
        self.n_events = self.n_llm = 0
        self.started = time.time()
        self.preset = ""
        self.models: set[str] = set()

    def on_event(self, e: dict) -> None:
        if e["type"] == "project_created":
            self.preset = e.get("preset", "")
        with self._lock:
            self._events.write(json.dumps(e, default=str) + "\n")
            self._events.flush()
            self.n_events += 1

    def on_llm(self, d: dict) -> None:
        with self._lock:
            self._llm.write(json.dumps({"ts": time.time(), **d}) + "\n")
            self._llm.flush()
            self.n_llm += 1
            self.models.add(d.get("name", ""))

    def finalize(self, project_root: Path | None, ok: bool, problems: list[str] | None = None, info: dict | None = None) -> Path:
        with self._lock:
            self._events.close()
            self._llm.close()
        snapshot = False
        if project_root and (Path(project_root) / ".git").exists():
            _git(Path(project_root), "bundle", "create", str(self.tmp / "snapshot.bundle"), "--all")
            snapshot = True
        meta = {"name": self.name, "goal": self.goal, "ok": ok, "problems": problems or [], "preset": self.preset,
                "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(time.time() - self.started),
                "events": self.n_events, "llm_calls": self.n_llm, "models": sorted(m for m in self.models if m), "snapshot": snapshot,
                **{k: str(v)[:120] for k, v in (info or {}).items() if k in ("title", "app", "feature")}}
        if project_root:
            from .buildstats import project_stats

            stats = project_stats(project_root)
            if stats:
                meta["stats"] = stats  # shown on the demo card: tables, endpoints, pages, functions, lines, how much the agents wrote
        (self.tmp / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        shutil.rmtree(self.final, ignore_errors=True)
        self.tmp.rename(self.final)
        return self.final

    def abort(self) -> None:
        for f in (self._events, self._llm):
            try:
                f.close()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)


@dataclass
class Recording:
    name: str
    path: Path
    meta: dict

    def events(self) -> list[dict]:
        out = []
        for line in (self.path / "events.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    @property
    def bundle(self) -> Path | None:
        b = self.path / "snapshot.bundle"
        return b if b.is_file() else None


def list_recordings(base: Path) -> list[dict]:
    """Valid recordings (those with a meta.json), newest first."""
    out = []
    for d in Path(base).glob("*"):
        meta = d / "meta.json"
        if d.name.startswith(".") or not meta.is_file():
            continue
        try:
            out.append(json.loads(meta.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return sorted(out, key=lambda m: m.get("recorded_at", ""), reverse=True)


def load_recording(base: Path, name: str | None = None) -> Recording:
    """Load by name, or the newest successful recording when no name is given."""
    base = Path(base)
    if name is None:
        good = [m for m in list_recordings(base) if m.get("ok")]
        if not good:
            raise RecordingError("there is no recording to play yet; record a build first (see scripts/record.py)")
        name = good[0]["name"]
    check_name(name)
    path = base / name
    try:
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        rec = Recording(name, path, meta)
        events = rec.events()
    except (OSError, ValueError):
        raise RecordingError(f"recording '{name}' was not found or is damaged") from None
    if not events or events[-1]["type"] != "project_done":
        raise RecordingError(f"recording '{name}' is incomplete")
    return rec


def restore_snapshot(bundle: Path, dest: Path) -> Path:
    """Rebuild the finished project (files + every branch) from a bundle into `dest`."""
    dest = Path(dest)
    shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(dest.parent, "clone", "--quiet", str(bundle), str(dest))
    refs = subprocess.run(["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"], cwd=dest, capture_output=True,
                          text=True, encoding="utf-8").stdout.split()
    for ref in refs:
        branch = ref.removeprefix("origin/")
        if branch not in ("HEAD", "main"):
            _git(dest, "branch", branch, ref)
    _git(dest, "remote", "remove", "origin")
    _git(dest, "config", "user.name", "Q")
    _git(dest, "config", "user.email", "q@localhost")
    return dest
