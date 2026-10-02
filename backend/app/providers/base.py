from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..registry import ModelConfig


class ProviderError(Exception):
    """A provider could not answer. The message is safe to show in the UI (no keys, no traces)."""


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0


class LLMProvider(Protocol):
    def chat(self, model: ModelConfig, messages: list[dict], schema: dict | None = None, temperature: float = 0.2) -> LLMResponse: ...
