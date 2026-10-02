"""Any OpenAI-compatible chat API (Groq, OpenRouter, ...)."""
from __future__ import annotations

import json
import time

import httpx

from ..registry import ModelConfig
from .base import LLMResponse, ProviderError


class OpenAICompatProvider:
    def __init__(self, base_url: str, api_key: str, client: httpx.Client | None = None):
        self.base = base_url.rstrip("/")
        self.key = api_key
        self.client = client or httpx.Client(timeout=httpx.Timeout(120, connect=10))

    def chat(self, model: ModelConfig, messages: list[dict], schema: dict | None = None, temperature: float = 0.2) -> LLMResponse:
        msgs = [dict(m) for m in messages]
        body: dict = {"model": model.name, "messages": msgs, "temperature": temperature}
        if schema:
            # json_object mode is the portable subset; the schema goes into the prompt.
            note = "Respond with JSON matching this schema: " + json.dumps(schema)
            if msgs and msgs[0]["role"] == "system":
                msgs[0]["content"] += "\n\n" + note
            else:
                msgs.insert(0, {"role": "system", "content": note})
            body["response_format"] = {"type": "json_object"}
        t0 = time.time()
        try:
            r = self.client.post(f"{self.base}/chat/completions", json=body, headers={"Authorization": f"Bearer {self.key}"})
        except httpx.TimeoutException:
            raise ProviderError("The API timed out") from None
        except httpx.HTTPError:
            raise ProviderError("The API is unreachable (offline?)") from None
        if r.status_code >= 400:
            raise ProviderError(f"API error {r.status_code} for {model.name}: {r.text[:200].replace(self.key, '***')}")
        try:
            d = r.json()
            text = d["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("The API returned an unexpected response") from None
        u = d.get("usage", {})
        return LLMResponse(text, u.get("prompt_tokens", 0), u.get("completion_tokens", 0), time.time() - t0)
