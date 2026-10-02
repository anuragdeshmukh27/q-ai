from __future__ import annotations

import time

import httpx

from ..registry import ModelConfig
from .base import LLMResponse, ProviderError


class OllamaProvider:
    def __init__(self, host: str, client: httpx.Client | None = None, keep_alive: str = "10m"):
        self.host = host.rstrip("/")
        self.client = client or httpx.Client(timeout=httpx.Timeout(300, connect=5))
        self.keep_alive = keep_alive

    def chat(self, model: ModelConfig, messages: list[dict], schema: dict | None = None, temperature: float = 0.2) -> LLMResponse:
        body = {
            "model": model.name,
            "messages": messages,
            "stream": False,
            "think": False,  # qwen3 is ~4x slower with thinking on; harmless for other models
            "keep_alive": self.keep_alive,
            "options": {"num_ctx": model.num_ctx, "temperature": temperature},
        }
        if schema:
            body["format"] = schema
        t0 = time.time()
        try:
            r = self.client.post(f"{self.host}/api/chat", json=body)
        except httpx.ConnectError:
            raise ProviderError(f"Ollama is not reachable at {self.host}. Is it running?") from None
        except httpx.TimeoutException:
            raise ProviderError(f"Ollama timed out answering {model.name}") from None
        except httpx.HTTPError as e:
            raise ProviderError(f"Ollama request failed: {type(e).__name__}") from None
        if r.status_code >= 400:
            raise ProviderError(f"Ollama error {r.status_code} for {model.name}: {r.text[:200]}")
        try:
            d = r.json()
            return LLMResponse(
                text=d["message"]["content"],
                prompt_tokens=d.get("prompt_eval_count", 0),
                completion_tokens=d.get("eval_count", 0),
                seconds=time.time() - t0,
            )
        except (ValueError, KeyError):
            raise ProviderError("Ollama returned an unexpected response") from None
