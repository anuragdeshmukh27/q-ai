"""The job descriptions that ship with Q: one per seat, so the feature can be tried without a posting at hand."""
from __future__ import annotations

from pathlib import Path

FOLDER = Path(__file__).resolve().parent / "samples"
SAMPLES = (("backend-engineer", "Backend engineer"), ("database-engineer", "Database / data engineer"), ("frontend-engineer", "Frontend engineer"))


def list_samples() -> list[dict]:
    return [{"id": sid, "title": title, "text": (FOLDER / f"{sid}.txt").read_text(encoding="utf-8")} for sid, title in SAMPLES]


def sample_text(sample_id: str) -> str | None:
    """The text of a bundled sample, or None for an id that is not one."""
    if sample_id not in dict(SAMPLES):
        return None
    return (FOLDER / f"{sample_id}.txt").read_text(encoding="utf-8")
