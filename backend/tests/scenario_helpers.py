"""Shared by the scenario tests and scripts/scenario_e2e.py: the scripted LLM, a fake clock and the reference fix applied to file contents (what the learner would type)."""
from __future__ import annotations

import subprocess
import tempfile
import threading
import time
from pathlib import Path

from app.llm import StructuredResult
from app.providers.base import ProviderError
from app.scenarios.director import ChatReply

from test_orchestrator import FakeLLM

PATCH = Path(__file__).parent / "scenario_fixes" / "opd-bookings-down.patch"


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
    `delay` makes it slow; `gate` holds it until the test opens it. `prompts` keeps every system prompt a teammate was given."""

    def __init__(self, reply: str = "It was my migration 0007: slot_time is slot_at now.", fail: bool = False, delay: float = 0.0, gate: threading.Event | None = None):
        super().__init__()
        self.reply, self.fail, self.delay, self.gate = reply, fail, delay, gate
        self.prompts: list[str] = []
        self.chat_calls = 0

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
        return super().call(model_id, messages, schema_model, temperature)


def apply_reference_fix(files: dict[str, str]) -> dict[str, str]:
    """The files of the reference fix: `files` are the current contents of the files the patch touches (path -> text); the result is what they must become."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
        r = subprocess.run(["git", "apply", str(PATCH)], cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError(f"the reference fix does not apply: {r.stderr}")
        return {rel: (root / rel).read_text(encoding="utf-8") for rel in files}


FIX_FILES = ("backend/api/appointments.py", "backend/api/doctors.py")

REGRESSION_PATH = "tests/regression/test_regression_slot_at.py"
REGRESSION_TEST = '''"""The booking route must write the appointment's time with the column's new name."""
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_booking_an_appointment_still_works_after_the_column_rename():
    doctor = client.post("/api/doctors", json={"name": "Dr. Test", "department": "General Medicine", "phone": "9876500001", "room": "OPD 1", "consultation_fee": 300,
                                               "availability": "Available", "email": "regression@example.com"})
    assert doctor.status_code == 201, doctor.text
    booked = client.post(f"/api/doctors/{doctor.json()['id']}/appointments", json={"patient_name": "A", "patient_phone": "9876511112", "date": "2026-10-12", "time": "09:15",
                                                                                   "reason": "Check", "status": "Booked"})
    assert booked.status_code == 201, booked.text
'''
