from __future__ import annotations

import time

import httpx

from ..registry import ModelConfig
from .base import LLMResponse, ProviderError

BASE = "https://generativelanguage.googleapis.com"


class GeminiProvider:
    def __init__(self, api_key: str, base_url: str = BASE, client: httpx.Client | None = None):
        self.key = api_key
        self.base = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=httpx.Timeout(120, connect=10))

    def _scrub(self, text: str) -> str:
        return text.replace(self.key, "***") if self.key else text

    def chat(self, model: ModelConfig, messages: list[dict], schema: dict | None = None, temperature: float = 0.2) -> LLMResponse:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in messages
            if m["role"] != "system"
        ]
        gen = {"temperature": temperature}
        if schema:
            gen.update(responseMimeType="application/json", responseJsonSchema=schema)
        body: dict = {"contents": contents, "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        t0 = time.time()
        try:
            r = self.client.post(
                f"{self.base}/v1beta/models/{model.name}:generateContent",
                json=body,
                headers={"x-goog-api-key": self.key},
            )
        except httpx.TimeoutException:
            raise ProviderError("Gemini timed out") from None
        except httpx.HTTPError:
            raise ProviderError("Gemini is unreachable (offline?)") from None
        if r.status_code >= 400:
            try:
                msg = r.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                msg = r.text
            raise ProviderError(self._scrub(f"Gemini error {r.status_code} for {model.name}: {msg[:200]}"))
        try:
            d = r.json()
            parts = d["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("Gemini returned no usable answer (blocked or empty)") from None
        u = d.get("usageMetadata", {})
        return LLMResponse(text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0), time.time() - t0)
