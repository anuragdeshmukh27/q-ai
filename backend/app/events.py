"""Thread-safe event bus. Every agent step emits events (CLAUDE.md section 9)."""
from __future__ import annotations

import threading
import time
from typing import Callable


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sinks: list[Callable[[dict], None]] = []
        self.history: list[dict] = []

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        with self._lock:
            self._sinks.append(fn)

    def emit(self, type: str, **data) -> dict:
        with self._lock:
            event = {"seq": len(self.history), "ts": time.time(), "type": type, **data}
            self.history.append(event)
            sinks = list(self._sinks)
        for fn in sinks:
            try:
                fn(event)
            except Exception:  # a broken sink must never break an agent
                pass
        return event
