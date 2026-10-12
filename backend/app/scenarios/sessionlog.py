"""The session log: everything the learner does and everything the team says, with a session-relative time and an id that step 5 (the debrief) can quote.

An entry is `{id: "E007", t: 63.2, kind, ...}`. `t` is seconds since the session started (the clock is injected, so tests run a whole incident without waiting).
Kinds and their fields:

    session_started   scenario, role
    file_opened       path, auto (true when the IDE opened its first file by itself)
    file_saved        path, added, removed, size            (lines added and removed compared with what was on disk)
    test_run          task, trigger ("ide" | "submit")
    test_result       task, ok, passed, failed (ids), summary, trigger
    message_posted    message (the channel message id), text, to (the teammates addressed)
    team_message      message, from, text, source ("scripted" | "live" | "fallback"), ref (the timeline item, or the learner's message)
    hint_given        message, from, source, reason, question, n (this is hint number n)
    submit            task
    submit_result     task, ok, stage ("tests" | "scope" | "review" | "accepted"), summary, failed, review_items
    session_finished  ok

Entries are appended to `.q/session/log.jsonl` of the project and published as `session_event`, so a reload shows the same log.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

KINDS = ("session_started", "file_opened", "file_saved", "test_run", "test_result", "message_posted", "team_message", "hint_given", "submit", "submit_result", "session_finished")


class SessionLog:
    def __init__(self, clock: Callable[[], float] = time.monotonic, emit: Callable[..., object] | None = None):
        self.clock = clock
        self.t0 = clock()
        self.started_at = time.time()  # wall clock of the start, for display
        self.emit = emit
        self._events: list[dict] = []
        self._lock = threading.RLock()
        self._listeners: list[Callable[[dict], None]] = []
        self._file: Path | None = None

    # -- time -------------------------------------------------------------------
    def now(self) -> float:
        """Seconds since the session started."""
        return self.clock() - self.t0

    # -- writing ----------------------------------------------------------------
    def subscribe(self, fn: Callable[[dict], None]) -> None:
        self._listeners.append(fn)

    def attach(self, folder: Path) -> None:
        """Keep the log in `folder/log.jsonl` from now on (what happened before is written first)."""
        with self._lock:
            folder.mkdir(parents=True, exist_ok=True)
            self._file = folder / "log.jsonl"
            self._file.write_text("".join(json.dumps(e) + "\n" for e in self._events), encoding="utf-8", newline="\n")

    def add(self, kind: str, **data) -> dict:
        if kind not in KINDS:
            raise ValueError(f"unknown session event kind {kind!r}")
        with self._lock:
            n = len(self._events) + 1
            event = {"id": f"E{n:03d}", "t": round(self.now(), 1), "kind": kind, **data}
            self._events.append(event)
            if self._file is not None:
                try:
                    with self._file.open("a", encoding="utf-8", newline="\n") as f:
                        f.write(json.dumps(event) + "\n")
                except OSError:
                    pass  # a full disk must not stop the session
            listeners = list(self._listeners)
        if self.emit:
            self.emit("session_event", **event)
        for fn in listeners:
            try:
                fn(event)
            except Exception:  # a broken listener must never break the learner's action
                pass
        return event

    # -- reading ----------------------------------------------------------------
    def events(self, kind: str | None = None) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._events if kind is None or e["kind"] == kind]

    def get(self, event_id: str) -> dict | None:
        with self._lock:
            return next((dict(e) for e in self._events if e["id"] == event_id), None)

    def first_accepted(self) -> dict | None:
        """The submit_result that accepted the fix, if there is one."""
        return next((e for e in self.events("submit_result") if e.get("ok")), None)

    def summary(self) -> dict:
        """The counts the debrief starts from."""
        with self._lock:
            by = {k: sum(1 for e in self._events if e["kind"] == k) for k in KINDS}
            return {"events": len(self._events), "hints": by["hint_given"], "test_runs": by["test_run"], "saves": by["file_saved"], "opened": by["file_opened"],
                    "messages": by["message_posted"], "submits": by["submit"]}
