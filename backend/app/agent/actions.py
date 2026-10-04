"""The JSON action an agent emits each step.

The schema is deliberately flat (no unions): small local models follow a flat
grammar-constrained schema far more reliably than a discriminated union.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

ActionName = Literal[
    "list_dir", "read_file", "write_file", "implement", "replace", "search", "run", "run_tests", "send_message", "ask_human", "finish"
]

REQUIRED: dict[str, tuple[str, ...]] = {
    "list_dir": (),
    "read_file": ("path",),
    "write_file": ("path", "content"),
    "implement": ("path", "function", "content"),
    "replace": ("path", "pattern", "content"),
    "search": ("pattern",),
    "run": ("command",),
    "run_tests": (),
    "send_message": ("to", "text"),
    "ask_human": ("question",),
    "finish": ("summary",),
}


HINTS = {
    "implement": "implement needs three fields in the same reply: path, function and content, and content is the lines inside the function (never leave it out; to look at a file use read_file)",
    "replace": "replace needs path, pattern (a short text that occurs once in the file) and content (the text that takes its place)",
    "write_file": "write_file needs path and content (the whole file)",
}


class Action(BaseModel):
    thought: str
    action: ActionName
    path: str | None = None
    content: str | None = None
    function: str | None = None
    command: str | None = None
    pattern: str | None = None
    to: str | None = None
    text: str | None = None
    question: str | None = None
    summary: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _misfiled_code(cls, data):
        """Small models sometimes put the code of write_file/implement into the wrong text field; accept it."""
        if isinstance(data, dict) and data.get("action") in ("implement", "write_file", "replace") and data.get("content") is None:
            for alt in ("body", "code", "text", "command", "summary"):
                if isinstance(data.get(alt), str) and data[alt].strip():
                    data = {**data, "content": data[alt], alt: None}
                    break
        return data

    @model_validator(mode="after")
    def _has_required_args(self) -> "Action":
        missing = [f for f in REQUIRED[self.action] if getattr(self, f) is None]
        if missing:
            hint = HINTS.get(self.action, "")
            raise ValueError(f"action '{self.action}' requires: {', '.join(missing)}" + (f". {hint}" if hint else ""))
        return self

    def args(self) -> dict[str, str]:
        return {k: v for k, v in self.model_dump(exclude={"thought", "action"}).items() if v is not None}

    def fingerprint(self) -> str:
        """Identity of an action for repeat detection (the thought is ignored)."""
        return self.action + "|" + "|".join(f"{k}={v}" for k, v in sorted(self.args().items()))
