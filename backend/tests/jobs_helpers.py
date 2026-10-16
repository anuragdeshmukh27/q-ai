"""Shared by the job-description tests: a scripted model for the reader and the briefing, and the three samples."""
from __future__ import annotations

import threading
import time

from app.llm import InvalidOutputError, StructuredResult
from app.providers.base import ProviderError
from app.scenarios.jobs.samples import list_samples, sample_text


class JobLLM:
    """Answers the reader (`ModelReading`) and the briefing (`BriefOutput`) like Ollama would. `reading` / `brief` are the objects returned (or a callable of the prompt);
    `fail` raises ProviderError, `invalid` raises InvalidOutputError, `delay` is slow, `gate` holds the call until the test opens it."""

    def __init__(self, reading=None, brief=None, fail: bool = False, invalid: bool = False, delay: float = 0.0, gate: threading.Event | None = None):
        self.reading, self.brief, self.fail, self.invalid, self.delay, self.gate = reading, brief, fail, invalid, delay, gate
        self.calls: list[tuple[str, str]] = []

    def call(self, model_id, messages, schema_model, temperature=0.2):
        self.calls.append((schema_model.__name__, messages[0]["content"]))
        if self.gate is not None:
            self.gate.wait(30)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise ProviderError("Ollama is not running")
        if self.invalid:
            raise InvalidOutputError("not json")
        out = {"ModelReading": self.reading, "BriefOutput": self.brief}.get(schema_model.__name__)
        out = out(messages[0]["content"]) if callable(out) else out
        if out is None:
            raise ProviderError("no scripted answer")
        return StructuredResult(out, model_id, 1, 10, 5, 0.01, "{}")


SAMPLE_IDS = [s["id"] for s in list_samples()]
