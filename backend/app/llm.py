"""Structured LLM calls: JSON schema -> provider -> Pydantic validation, one retry, model fallback."""
from __future__ import annotations

import contextlib
import contextvars
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

_current_agent: contextvars.ContextVar[str | None] = contextvars.ContextVar("q_current_agent", default=None)


@contextlib.contextmanager
def agent_context(agent_id: str):
    """Names the employee making the LLM calls inside the block, so the scheduler can show who is waiting for the GPU."""
    token = _current_agent.set(agent_id)
    try:
        yield
    finally:
        _current_agent.reset(token)


def _dump_prompt(m: ModelConfig, msgs: list[dict], resp: LLMResponse) -> None:
    """Q_DUMP_PROMPTS=<folder>: write every model call (prompt and reply) there, to see what a model was actually given."""
    folder = os.environ.get("Q_DUMP_PROMPTS")
    if not folder:
        return
    try:
        import json
        import time
        os.makedirs(folder, exist_ok=True)
        n = len(os.listdir(folder))
        with open(os.path.join(folder, f"{n:04d}.json"), "w", encoding="utf-8") as f:
            json.dump({"model": m.id, "ts": time.time(), "messages": msgs, "reply": resp.text, "prompt_tokens": resp.prompt_tokens, "completion_tokens": resp.completion_tokens}, f)
    except OSError:
        pass


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
        observer: Callable[[dict], None] | None = None,
        scheduler=None,
    ):
        self.registry = registry
        self.scheduler = scheduler  # ModelScheduler: keeps local models inside the VRAM budget (None: call the provider directly)
        self.tokens_per_s = 0.0  # smoothed generation speed of the last responses, for the metrics gauge
        self.observer = observer  # called with every raw model response (the recorder uses it)
        self.env = os.environ if env is None else env
        self._factory = provider_factory or self._default_factory
        self._cache: dict[str, LLMProvider] = {}

    def _default_factory(self, m: ModelConfig) -> LLMProvider:
        if m.provider not in self._cache:
            if m.provider == "ollama":
                self._cache[m.provider] = OllamaProvider(ollama_host(), keep_alive=self.registry.keep_alive)
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
            with (self.scheduler.slot(m, _current_agent.get()) if self.scheduler else contextlib.nullcontext()):
                resp: LLMResponse = provider.chat(m, msgs, schema, temperature if attempt == 1 else min(0.9, temperature + 0.4))  # the retry must be free to differ: at a low temperature a 7B repeats the same invalid reply
            if resp.seconds > 0 and resp.completion_tokens > 8:
                rate = resp.completion_tokens / resp.seconds
                self.tokens_per_s = rate if self.tokens_per_s == 0 else 0.6 * self.tokens_per_s + 0.4 * rate
            pt, ct, secs = pt + resp.prompt_tokens, ct + resp.completion_tokens, secs + resp.seconds
            _dump_prompt(m, msgs, resp)
            if self.observer:
                try:
                    self.observer({"model": m.id, "name": m.name, "attempt": attempt, "text": resp.text, "prompt_tokens": resp.prompt_tokens,
                                   "completion_tokens": resp.completion_tokens, "seconds": round(resp.seconds, 2),
                                   "prompt_chars": sum(len(x.get("content", "")) for x in msgs)})
                except Exception:
                    pass
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
