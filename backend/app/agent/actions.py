"""The JSON action an agent emits each step.

The schema is deliberately flat (no unions): small local models follow a flat
grammar-constrained schema far more reliably than a discriminated union.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

ActionName = Literal[
    "list_dir", "read_file", "write_file", "search", "run", "run_tests", "send_message", "ask_human", "finish"
]

REQUIRED: dict[str, tuple[str, ...]] = {
    "list_dir": (),
    "read_file": ("path",),
    "write_file": ("path", "content"),
    "search": ("pattern",),
    "run": ("command",),
    "run_tests": (),
    "send_message": ("to", "text"),
    "ask_human": ("question",),
    "finish": ("summary",),
}


class Action(BaseModel):
    thought: str
    action: ActionName
    path: str | None = None
    content: str | None = None
    command: str | None = None
    pattern: str | None = None
    to: str | None = None
    text: str | None = None
    question: str | None = None
    summary: str | None = None

    @model_validator(mode="after")
    def _has_required_args(self) -> "Action":
        missing = [f for f in REQUIRED[self.action] if getattr(self, f) is None]
        if missing:
            raise ValueError(f"action '{self.action}' requires: {', '.join(missing)}")
        return self

    def args(self) -> dict[str, str]:
        return {k: v for k, v in self.model_dump(exclude={"thought", "action"}).items() if v is not None}

    def fingerprint(self) -> str:
        """Identity of an action for repeat detection (the thought is ignored)."""
        return self.action + "|" + "|".join(f"{k}={v}" for k, v in sorted(self.args().items()))
