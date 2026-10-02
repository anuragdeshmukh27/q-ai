"""Thread-safe event bus. Every agent step emits events (CLAUDE.md section 9)."""
from __future__ import annotations

import threading
import time
from typing import Callable


class EventBus:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._sinks: list[Callable[[dict], None]] = []
        self.history: list[dict] = []

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        with self._cond:
            self._sinks.append(fn)

    def emit(self, type: str, **data) -> dict:
        with self._cond:
            event = {"seq": len(self.history), "ts": time.time(), "type": type, **data}
            self.history.append(event)
            sinks = list(self._sinks)
            self._cond.notify_all()
        for fn in sinks:
            try:
                fn(event)
            except Exception:  # a broken sink must never break an agent
                pass
        return event

    def wait_for(self, after: int, timeout: float = 1.0) -> list[dict]:
        """Events with seq >= `after`; blocks up to `timeout` seconds when there are none yet (used by the WebSocket stream)."""
        with self._cond:
            if len(self.history) <= after:
                self._cond.wait(timeout)
            return self.history[after:]
