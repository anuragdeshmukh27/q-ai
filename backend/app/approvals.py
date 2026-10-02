"""Human approvals: a blocking queue the UI resolves over HTTP, plus the one helper every approval site goes through."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Approval:
    id: str
    agent: str
    kind: str
    summary: str
    details: dict
    created: float = field(default_factory=time.time)
    approve: bool | None = None
    by: str = ""
    event: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self) -> dict:
        return {"id": self.id, "agent": self.agent, "kind": self.kind, "summary": self.summary, "details": self.details,
                "created": self.created, "approve": self.approve, "by": self.by}


class UnknownApproval(KeyError):
    pass


class ApprovalQueue:
    """Callable approver: the asking agent thread blocks until a human decides (or the timeout denies, so nothing hangs forever)."""

    def __init__(self, emit: Callable[..., object], timeout: float = 600.0):
        self.emit, self.timeout = emit, timeout
        self._lock = threading.Lock()
        self._items: dict[str, Approval] = {}

    def announce(self, agent: str, kind: str, summary: str, details: dict) -> bool:
        a = Approval(uuid.uuid4().hex[:8], agent, kind, summary, details)
        with self._lock:
            self._items[a.id] = a
        self.emit("approval_needed", id=a.id, agent=agent, kind=kind, summary=summary, details=details)
        self.emit("agent_state", agent=agent, state="waiting_human")
        if not a.event.wait(self.timeout):
            self._decide(a, False, "timeout")
        return bool(a.approve)

    __call__ = announce

    def _decide(self, a: Approval, approve: bool, by: str) -> bool:
        with self._lock:
            if a.approve is not None:
                return False
            a.approve, a.by = approve, by
        self.emit("approval_resolved", id=a.id, agent=a.agent, kind=a.kind, approve=approve, by=by)
        a.event.set()
        return True

    def resolve(self, approval_id: str, approve: bool, by: str = "human") -> bool:
        """True if this call decided it, False if it was already decided. Raises UnknownApproval for a bad id."""
        with self._lock:
            a = self._items.get(approval_id)
        if a is None:
            raise UnknownApproval(approval_id)
        return self._decide(a, approve, by)

    def release_all(self, approve: bool, by: str) -> int:
        n = 0
        for a in self.pending():
            n += self._decide(self._items[a["id"]], approve, by)
        return n

    def pending(self) -> list[dict]:
        with self._lock:
            return [a.public() for a in self._items.values() if a.approve is None]

    def all(self) -> list[dict]:
        with self._lock:
            return [a.public() for a in self._items.values()]


def request_approval(emit: Callable[..., object], approver, agent: str, kind: str, summary: str, details: dict) -> bool:
    """Ask for approval. A queue announces (and emits) it itself with an id; any other approver is announced here."""
    if approver is None:
        emit("approval_needed", agent=agent, kind=kind, summary=summary, details=details)
        return False
    try:
        if hasattr(approver, "announce"):
            return bool(approver.announce(agent, kind, summary, details))
        emit("approval_needed", agent=agent, kind=kind, summary=summary, details=details)
        return bool(approver(agent, kind, summary, details))
    except Exception:
        return False
