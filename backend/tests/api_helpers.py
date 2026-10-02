"""Shared helpers for the API tests: a scripted fake team behind the real SessionManager, and a recording of a fake build."""
from __future__ import annotations

import threading
import time

from app.main import create_app
from app.registry import ModelRegistry
from app.schemas import PlannerOutput  # noqa: F401
from app.session import AskReply, SessionManager, Settings

from test_orchestrator import API_POST, FakeLLM, act
from app.llm import StructuredResult


class ObservedFake(FakeLLM):
    """FakeLLM that reports every response to the recorder's observer, answers Ask-employee, and can be gated to stay 'busy'."""

    def __init__(self, observer=None, gate: threading.Event | None = None):
        super().__init__()
        self.observer, self.gate = observer, gate

    def call(self, model_id, messages, schema_model, temperature=0.2):
        if self.gate is not None:
            self.gate.wait(30)
        if schema_model is AskReply:
            res = StructuredResult(AskReply(reply="I am working on the API."), model_id, 1, 5, 5, 0.01, "{}")
        else:
            res = super().call(model_id, messages, schema_model, temperature)
        if self.observer:
            self.observer({"model": model_id, "name": model_id, "text": "{}", "prompt_tokens": 1, "completion_tokens": 1, "seconds": 0.0})
        return res


def make_settings(tmp_path) -> Settings:
    return Settings(workspace=tmp_path / "ws", recordings=tmp_path / "rec", leaderboard_db=tmp_path / "q.db", approval_timeout=5.0, max_gap=0.0)


def make_manager(tmp_path, gate=None, llm_holder: list | None = None):
    settings = make_settings(tmp_path)

    def factory(registry, observer):
        llm = ObservedFake(observer, gate)
        if llm_holder is not None:
            llm_holder.append(llm)
        return llm

    return settings, SessionManager(settings, ModelRegistry.load(env={}), llm_factory=factory)


def make_client(tmp_path, **kw):
    from fastapi.testclient import TestClient
    settings, mgr = make_manager(tmp_path, **kw)
    return TestClient(create_app(settings, mgr)), settings, mgr


def wait_for(fn, timeout=90.0, what="condition"):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


def fault_build_llm(holder: list) -> None:
    """After the injected bug is found, the backend engineer fixes it (same script as the P3 test)."""
    holder[0].scripts["Rohan"] += [act("implement", path="backend/api/calculator.py", function="handle_post_calculate", content=API_POST),
                                   act("run_tests"), act("finish", summary="fixed the operator")]


def record_fake_build(tmp_path, name="demo-fault"):
    """Run a full fault-injected build with the scripted team through the real session layer, recording it. Returns (settings, project status)."""
    holder: list = []
    settings, mgr = make_manager(tmp_path, llm_holder=holder)
    from app.session import CreateRequest
    # the factory builds the LLM inside create(); script the extra fix before the QA phase needs it
    orig = mgr._llm_factory

    def factory(registry, observer):
        llm = orig(registry, observer)
        fault_build_llm([llm] if not isinstance(llm, list) else llm)
        return llm

    mgr._llm_factory = factory
    s = mgr.create(CreateRequest(goal="Build a calculator with history", mode="autonomous", record_as=name, inject_fault=True))
    wait_for(lambda: s.state in ("done", "failed"), 120, "the fake build")
    wait_for(lambda: (settings.recordings / name / "meta.json").exists(), 30, "the recording")
    status = s.status()
    mgr.shutdown()
    return settings, status
