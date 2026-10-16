"""One guarded call to the local model, for the two places the job-description feature may use it (reading the posting, wording the briefing).

`ModelGate.ask` never raises and never blocks longer than `timeout`: it returns (the parsed answer or None, why not). One call at a time per gate: a second caller is told "busy"
instead of queueing behind a slow model. The reasons are the ones the report shows: unavailable, busy, timeout, invalid (invalid JSON after the client's own retry), error.
"""
from __future__ import annotations

import threading
from typing import Callable, TypeVar

from pydantic import BaseModel

from ...llm import InvalidOutputError

T = TypeVar("T", bound=BaseModel)

MODEL_ID = "qwen25-coder-7b"
EXTRACT_TIMEOUT = 20.0  # seconds to read a posting before the keyword reader is used
BRIEF_TIMEOUT = 25.0


class ModelGate:
    def __init__(self) -> None:
        self._busy = threading.Lock()

    def ask(self, llm, messages: list[dict], schema: type[T], *, model_id: str = MODEL_ID, available: Callable[[], bool] | None = None, timeout: float = EXTRACT_TIMEOUT,
            temperature: float = 0.1) -> tuple[T | None, str]:
        if llm is None or not (available or (lambda: True))():
            return None, "the model is not installed or not running"
        if not self._busy.acquire(blocking=False):
            return None, "the model is busy"
        box: dict = {}
        done = threading.Event()

        def work() -> None:
            try:
                from ...llm import agent_context

                with agent_context("reviewer"):
                    box["out"] = llm.call(model_id, messages, schema, temperature=temperature).parsed
            except InvalidOutputError:
                box["error"] = "the model did not return valid JSON"
            except Exception as e:  # Ollama down, a provider error
                box["error"] = f"the model failed ({type(e).__name__})"
            finally:
                self._busy.release()
                done.set()

        threading.Thread(target=work, name="jd-model", daemon=True).start()
        if not done.wait(timeout):
            return None, f"the model took more than {timeout:g} s"
        if "error" in box:
            return None, box["error"]
        out = box.get("out")
        return (out, "") if isinstance(out, schema) else (None, "the model's answer did not fit the schema")


READ_GATE = ModelGate()
BRIEF_GATE = ModelGate()
