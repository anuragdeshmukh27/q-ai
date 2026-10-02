"""Structured LLM calls: JSON schema -> provider -> Pydantic validation, one retry, model fallback."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Mapping, TypeVar

from pydantic import BaseModel, ValidationError

from .config import ollama_host
from .providers.base import LLMProvider, LLMResponse, ProviderError
from .providers.gemini import GeminiProvider
from .providers.ollama import OllamaProvider
from .providers.openai_compat import OpenAICompatProvider
from .registry import ModelConfig, ModelRegistry

T = TypeVar("T", bound=BaseModel)


class InvalidOutputError(Exception):
    """The model returned invalid output twice (original + one retry)."""


@dataclass
class StructuredResult:
    parsed: BaseModel
    model_id: str
    attempts: int
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    raw: str


def extract_json(text: str) -> str:
    t = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL)
    if fence:
        return fence.group(1)
    if not t.startswith("{") and "{" in t and "}" in t:
        return t[t.index("{") : t.rindex("}") + 1]
    return t


def _error_summary(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(map(str, x['loc'])) or 'output'}: {x['msg']}" for x in e.errors())[:400]
    return str(e)[:400]


class LLMClient:
    def __init__(
        self,
        registry: ModelRegistry,
        provider_factory: Callable[[ModelConfig], LLMProvider] | None = None,
        env: Mapping[str, str] | None = None,
    ):
        self.registry = registry
        self.env = os.environ if env is None else env
        self._factory = provider_factory or self._default_factory
        self._cache: dict[str, LLMProvider] = {}

    def _default_factory(self, m: ModelConfig) -> LLMProvider:
        if m.provider not in self._cache:
            if m.provider == "ollama":
                self._cache[m.provider] = OllamaProvider(ollama_host())
            elif m.provider == "gemini":
                self._cache[m.provider] = GeminiProvider(self.env["GEMINI_API_KEY"])
            elif m.provider == "openai_compat":
                base = self.env.get("OPENAI_COMPAT_BASE_URL") or "https://api.groq.com/openai/v1"
                self._cache[m.provider] = OpenAICompatProvider(base, self.env["OPENAI_COMPAT_API_KEY"])
            else:
                raise ProviderError(f"unknown provider: {m.provider}")
        return self._cache[m.provider]

    def call(self, model_id: str, messages: list[dict], schema_model: type[T], temperature: float = 0.2) -> StructuredResult:
        chain = self.registry.chain(model_id)
        if not chain:
            raise ProviderError(f"model '{model_id}' is not available (disabled or missing API key)")
        schema = schema_model.model_json_schema()
        last: ProviderError | None = None
        for m in chain:
            try:
                return self._attempt(m, messages, schema, schema_model, temperature)
            except ProviderError as e:
                last = e
        assert last is not None
        raise last

    def _attempt(self, m: ModelConfig, messages: list[dict], schema: dict, schema_model: type[T], temperature: float) -> StructuredResult:
        provider = self._factory(m)
        msgs = list(messages)
        pt = ct = 0
        secs = 0.0
        err: Exception | None = None
        for attempt in (1, 2):
            resp: LLMResponse = provider.chat(m, msgs, schema, temperature)
            pt, ct, secs = pt + resp.prompt_tokens, ct + resp.completion_tokens, secs + resp.seconds
            try:
                parsed = schema_model.model_validate_json(extract_json(resp.text))
                return StructuredResult(parsed, m.id, attempt, pt, ct, secs, resp.text)
            except (ValidationError, ValueError) as e:
                err = e
                msgs = msgs + [
                    {"role": "assistant", "content": resp.text},
                    {"role": "user", "content": f"Your previous reply was invalid: {_error_summary(e)}. Reply again with only valid JSON matching the schema."},
                ]
        raise InvalidOutputError(_error_summary(err) if err else "invalid output")
