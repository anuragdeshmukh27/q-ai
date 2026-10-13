"""Shared by the scenario tests and scripts/scenario_e2e.py: the scripted LLM, a fake clock and the reference fix applied to file contents (what the learner would type)."""
from __future__ import annotations

import subprocess
import tempfile
import threading
import time
from pathlib import Path

from app.llm import StructuredResult
from app.providers.base import ProviderError
from app.scenarios.autoplay import FIX_FILES as FIX_PATHS, REGRESSION_PATH as REGRESSION_FILE, reference_fix, regression_test
from app.scenarios.director import ChatReply
from app.scenarios.wording import VoiceOutput

from test_orchestrator import FakeLLM



class FakeClock:
    """A clock the test moves: `clock.advance(300)` is five quiet minutes."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class ScenarioLLM(FakeLLM):
    """The FakeLLM (every review is a PASS) that also answers the teammates of a scenario. `reply` is what a teammate says; `fail` makes the call raise like Ollama being down;
    `delay` makes it slow; `gate` holds it until the test opens it. `prompts` keeps every system prompt a teammate was given.
    The debrief's voice call (VoiceOutput: the judges' lines and the coach paragraph) is answered by `wording(system_prompt) -> VoiceOutput`, or fails like Ollama being down when there is none."""

    def __init__(self, reply: str = "It was my migration 0007: slot_time is slot_at now.", fail: bool = False, delay: float = 0.0, gate: threading.Event | None = None, wording=None):
        super().__init__()
        self.reply, self.fail, self.delay, self.gate, self.wording = reply, fail, delay, gate, wording
        self.prompts: list[str] = []
        self.chat_calls = 0
        self.wording_calls = 0

    def call(self, model_id, messages, schema_model, temperature=0.2):
        if schema_model is ChatReply:
            self.chat_calls += 1
            self.prompts.append(messages[0]["content"])
            if self.gate is not None:
                self.gate.wait(30)
            if self.delay:
                time.sleep(self.delay)
            if self.fail:
                raise ProviderError("Ollama is not running")
            return StructuredResult(ChatReply(reply=self.reply), model_id, 1, 10, 5, 0.01, "{}")
        if schema_model is VoiceOutput:
            self.wording_calls += 1
            if self.wording is None:
                raise ProviderError("Ollama is not running")
            return StructuredResult(self.wording(messages[0]["content"]), model_id, 1, 10, 5, 0.01, "{}")
        return super().call(model_id, messages, schema_model, temperature)


def apply_reference_fix(files: dict[str, str]) -> dict[str, str]:
    """The files of the reference fix: `files` are the current contents of the files the patch touches (path -> text); the result is what they must become."""
    return reference_fix(files)


FIX_FILES = FIX_PATHS

REGRESSION_PATH = REGRESSION_FILE
REGRESSION_TEST = regression_test()
