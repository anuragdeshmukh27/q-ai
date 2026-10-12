"""The wording of the debrief: the only job of the model.

The scores and the points (which rule passed or failed, and which log entries prove it) are fixed before the model is asked anything. The 7b writes, for each point, one
sentence about what happened and one sentence of advice for the next attempt, and it must name the log entry its sentence rests on and quote that entry word for word.
`verify_points` is `drop_unfounded` for the debrief: a point whose entry does not exist, is not evidence for that finding, or whose quote is not in the entry's text is
dropped and the drop is recorded; the finding then reads with the template wording (rule result and the rubric's advice), so the report always has every point.
If the model is not installed, is busy, is slow or answers badly, every point reads with the template wording. A score never depends on any of this.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel

from .scoring import Finding, clock, event_text

MIN_QUOTE = 8  # characters; a shorter quote must be the whole text of the entry
WORDING_TIMEOUT = 40.0  # seconds for the one call; the 7b writes about 20 points
_ID = re.compile(r"\bE\d{3,}\b")


class PointWording(BaseModel):
    finding: str
    event: str
    quote: str
    note: str
    advice: str = ""


class WordingOutput(BaseModel):
    points: list[PointWording]


@dataclass
class Dropped:
    finding: str
    text: str
    reason: str

    def as_dict(self) -> dict:
        return {"finding": self.finding, "text": self.text, "reason": self.reason}


def _norm(s: str) -> str:
    return " ".join(s.replace("…", " ").replace("...", " ").replace("“", '"').replace("”", '"').replace("’", "'").split()).strip(" \"'").casefold()


def quote_matches(quote: str, event: dict) -> bool:
    """The quote is a stretch of the entry's own words (case and spacing aside, a trailing ellipsis allowed)."""
    q, text = _norm(quote), _norm(event_text(event))
    if not q or q not in text:
        return False
    return len(q) >= MIN_QUOTE or q == text


def verify_points(points: list[PointWording], findings: list[Finding], events: list[dict]) -> tuple[dict[str, PointWording], list[Dropped]]:
    """(the points that hold, keyed by finding id; what was dropped and why)."""
    by_id = {f.id: f for f in findings}
    log = {e["id"]: e for e in events}
    kept: dict[str, PointWording] = {}
    dropped: list[Dropped] = []

    def drop(p: PointWording, reason: str) -> None:
        dropped.append(Dropped(p.finding if p.finding in by_id else "", (p.note or p.quote).strip()[:200], reason))

    for p in points:
        f = by_id.get(p.finding)
        if f is None:
            drop(p, f"there is no finding {p.finding or '(none)'}")
        elif p.finding in kept:
            drop(p, "a second sentence for the same point")
        elif p.event not in log:
            drop(p, f"event {p.event or '(none)'} is not in the session log")
        elif p.event not in f.events:
            drop(p, f"{p.event} is not evidence for this point")
        elif not quote_matches(p.quote, log[p.event]):
            drop(p, f"the quote is not in {p.event} at {clock(log[p.event]['t'])}")
        elif not p.note.strip():
            drop(p, "the point has no sentence")
        elif any(i not in log for i in _ID.findall(p.note + " " + p.advice)):
            drop(p, "the sentence cites an event that does not exist")
        else:
            kept[p.finding] = PointWording(finding=p.finding, event=p.event, quote=p.quote.strip(), note=" ".join(p.note.split()), advice=" ".join(p.advice.split()))
    return kept, dropped


class Wordsmith:
    """Asks the local model to word the points. `word` never raises and never blocks longer than `timeout`:
    it returns (points or None, reason) where reason is "" when the model answered and else unavailable, busy, timeout, error or invalid."""

    def __init__(self, llm=None, model_id: str = "qwen25-coder-7b", available: Callable[[], bool] | None = None, timeout: float = WORDING_TIMEOUT):
        self.llm, self.model_id, self.timeout = llm, model_id, timeout
        self._available = available or (lambda: True)
        self._busy = threading.Lock()

    @staticmethod
    def _prompt(findings: list[Finding], events: list[dict]) -> list[dict]:
        log = {e["id"]: e for e in events}
        lines = []
        for f in findings:
            proof = "; ".join(f'{i} at {clock(log[i]["t"])}: "{event_text(log[i])[:160]}"' for i in f.events if i in log)
            lines.append(f"{f.id} [{f.kind.upper()}] fact: {f.text}\n   evidence: {proof}" + (f"\n   advice to reword: {f.advice}" if f.advice else ""))
        system = ("You write feedback for a junior engineer who just handled a production incident in a simulated team. Below are the points of the scoring: every point is already "
                  "decided, you only word it. Speak to the learner (\"you\") in your own words: never copy the fact or the advice word for word. For each point write `note`: one plain sentence (at most 25 words) about what the learner did or did not do, using only the facts and "
                  "evidence given; and `advice`: for a GAP, one imperative sentence (at most 25 words) for the next attempt, based on the advice given; for a STRENGTH leave it empty. "
                  "Also give `event`: the id of one evidence entry the sentence rests on, and `quote`: 3 to 12 words copied WORD FOR WORD from that entry's quoted text. "
                  "Never invent an event id, a time, a file name or a number. Reply with JSON: {\"points\": [{\"finding\": \"F01\", \"event\": \"E004\", \"quote\": \"...\", "
                  "\"note\": \"...\", \"advice\": \"...\"}]} with one object per point.\n\nPoints:\n" + "\n".join(lines))
        return [{"role": "system", "content": system}, {"role": "user", "content": "Word every point."}]

    def word(self, findings: list[Finding], events: list[dict]) -> tuple[list[PointWording] | None, str]:
        if self.llm is None or not self._available():
            return None, "unavailable"
        if not self._busy.acquire(blocking=False):
            return None, "busy"
        box: dict = {}
        done = threading.Event()

        def work() -> None:
            try:
                from ..llm import agent_context
                with agent_context("reviewer"):
                    box["out"] = self.llm.call(self.model_id, self._prompt(findings, events), WordingOutput, temperature=0.2).parsed  # type: ignore[attr-defined]
            except Exception as e:  # Ollama down, a provider error, invalid JSON twice: the template wording is used
                box["error"] = type(e).__name__
            finally:
                self._busy.release()
                done.set()

        threading.Thread(target=work, name="debrief-wording", daemon=True).start()
        if not done.wait(self.timeout):
            return None, "timeout"
        if "error" in box:
            return None, "error"
        out = box.get("out")
        if not isinstance(out, WordingOutput) or not out.points:
            return None, "invalid"
        return out.points, ""
