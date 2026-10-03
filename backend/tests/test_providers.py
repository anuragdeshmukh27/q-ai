"""Providers against httpx mock transports, plus the structured-output retry wrapper."""
import json

import httpx
import pytest
from pydantic import BaseModel

from app.llm import InvalidOutputError, LLMClient
from app.providers.base import LLMResponse, ProviderError
from app.providers.gemini import GeminiProvider
from app.providers.ollama import OllamaProvider
from app.providers.openai_compat import OpenAICompatProvider
from app.registry import ModelConfig, ModelRegistry

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}, {"role": "assistant", "content": "prev"}, {"role": "user", "content": "more"}]


def model(**kw):
    base = dict(id="m", provider="ollama", name="qwen2.5-coder:7b", capabilities=["coding"], num_ctx=8192, vram_gb=4.7, enabled=True)
    base.update(kw)
    return ModelConfig(**base)


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ollama_request_shape_and_parsing():
    seen = {}

    def handler(req):
        seen["url"], seen["body"] = str(req.url), json.loads(req.content)
        return httpx.Response(200, json={"message": {"content": '{"x": 1}'}, "prompt_eval_count": 11, "eval_count": 7, "eval_duration": 1_000_000_000})

    r = OllamaProvider("http://localhost:11434", client(handler)).chat(model(), MSGS, SCHEMA, temperature=0.1)
    b = seen["body"]
    assert seen["url"] == "http://localhost:11434/api/chat"
    assert b["model"] == "qwen2.5-coder:7b" and b["stream"] is False and b["format"] == SCHEMA
    assert b["options"]["num_ctx"] == 8192 and b["options"]["temperature"] == 0.1 and b["options"]["num_predict"] == 4096  # a looping model cannot run for minutes
    assert b["think"] is False and b["keep_alive"]
    assert b["messages"] == MSGS
    assert r.text == '{"x": 1}' and r.prompt_tokens == 11 and r.completion_tokens == 7


def test_ollama_connection_error_is_friendly():
    def handler(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderError, match="Ollama"):
        OllamaProvider("http://localhost:11434", client(handler)).chat(model(), MSGS, SCHEMA)


def test_ollama_http_error():
    with pytest.raises(ProviderError):
        OllamaProvider("http://x", client(lambda r: httpx.Response(500, text="boom"))).chat(model(), MSGS, SCHEMA)


def test_gemini_request_shape_key_in_header_not_url():
    seen = {}

    def handler(req):
        seen["url"], seen["headers"], seen["body"] = str(req.url), req.headers, json.loads(req.content)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": '{"x": 2}'}]}}],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3},
        })

    m = model(provider="gemini", name="gemini-3.8-flash")
    r = GeminiProvider("SECRET-KEY", client=client(handler)).chat(m, MSGS, SCHEMA, temperature=0.3)
    assert "SECRET-KEY" not in seen["url"] and seen["headers"]["x-goog-api-key"] == "SECRET-KEY"
    assert seen["url"].endswith("/v1beta/models/gemini-3.8-flash:generateContent")
    b = seen["body"]
    assert b["systemInstruction"]["parts"][0]["text"] == "sys"
    assert [c["role"] for c in b["contents"]] == ["user", "model", "user"]
    assert b["generationConfig"]["responseMimeType"] == "application/json"
    assert b["generationConfig"]["responseJsonSchema"] == SCHEMA
    assert r.text == '{"x": 2}' and r.prompt_tokens == 5 and r.completion_tokens == 3


def test_gemini_error_does_not_leak_key():
    def handler(req):
        return httpx.Response(404, json={"error": {"message": "model not found"}})

    with pytest.raises(ProviderError) as e:
        GeminiProvider("SECRET-KEY", client=client(handler)).chat(model(provider="gemini", name="x"), MSGS, SCHEMA)
    assert "SECRET-KEY" not in str(e.value) and "404" in str(e.value)


def test_gemini_blocked_or_empty_response():
    with pytest.raises(ProviderError):
        GeminiProvider("k", client=client(lambda r: httpx.Response(200, json={"candidates": []}))).chat(model(provider="gemini"), MSGS, SCHEMA)


def test_openai_compat_request_shape():
    seen = {}

    def handler(req):
        seen["url"], seen["headers"], seen["body"] = str(req.url), req.headers, json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 3}'}}], "usage": {"prompt_tokens": 4, "completion_tokens": 2}})

    p = OpenAICompatProvider("https://api.groq.com/openai/v1/", "K", client=client(handler))
    r = p.chat(model(provider="openai_compat", name="llama-3.3-70b-versatile"), MSGS, SCHEMA)
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer K"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert "x" in seen["body"]["messages"][0]["content"]  # schema is described in the system prompt
    assert r.text == '{"x": 3}' and r.completion_tokens == 2


# --- structured output wrapper ---------------------------------------------------------
class Out(BaseModel):
    x: int


class FakeProvider:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def chat(self, model, messages, schema=None, temperature=0.2):
        self.calls.append((model.id, [dict(m) for m in messages]))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return LLMResponse(text=r, prompt_tokens=1, completion_tokens=1, seconds=0.1)


def llm_with(providers, models=None):
    reg = ModelRegistry(models or [model(id="m")], env={})
    return LLMClient(reg, provider_factory=lambda m: providers[m.id])


def test_structured_valid():
    res = llm_with({"m": FakeProvider(['{"x": 5}'])}).call("m", MSGS, Out)
    assert res.parsed.x == 5 and res.attempts == 1 and res.model_id == "m"


def test_structured_retries_once_with_the_error_then_succeeds():
    fp = FakeProvider(['{"x": "nope"}', '{"x": 6}'])
    res = llm_with({"m": fp}).call("m", MSGS, Out)
    assert res.parsed.x == 6 and res.attempts == 2
    retry_msgs = fp.calls[1][1]
    assert retry_msgs[-2]["role"] == "assistant" and retry_msgs[-2]["content"] == '{"x": "nope"}'
    assert retry_msgs[-1]["role"] == "user" and "invalid" in retry_msgs[-1]["content"].lower()
    assert res.prompt_tokens == 2  # usage is summed over both attempts


def test_structured_invalid_twice_raises():
    with pytest.raises(InvalidOutputError):
        llm_with({"m": FakeProvider(["not json", "still not"])}).call("m", MSGS, Out)


def test_structured_extracts_json_from_code_fence():
    assert llm_with({"m": FakeProvider(['```json\n{"x": 7}\n```'])}).call("m", MSGS, Out).parsed.x == 7


def test_provider_failure_uses_fallback_model():
    models = [model(id="a", fallback="b"), model(id="b")]
    res = llm_with({"a": FakeProvider([ProviderError("down")]), "b": FakeProvider(['{"x": 8}'])}, models).call("a", MSGS, Out)
    assert res.parsed.x == 8 and res.model_id == "b"


def test_all_providers_failing_raises_provider_error():
    models = [model(id="a", fallback="b"), model(id="b")]
    with pytest.raises(ProviderError):
        llm_with({"a": FakeProvider([ProviderError("down")]), "b": FakeProvider([ProviderError("down")])}, models).call("a", MSGS, Out)
