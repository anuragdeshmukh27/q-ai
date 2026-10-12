"""The voice of the debrief: the only job of the model.

The scores and every point of the report (its quote and its sentence) come from the rules, and are final before the model is asked anything. The 7b writes two things from the
verified points: each judge's spoken line in the meeting room (one or two sentences, with the score, the moment and the tip) and a short coaching paragraph for the Debrief tab.
`verify_voice` is `drop_unfounded` for them: every time, quoted text, file, number and test count in what the model wrote must be one of the point's own (or the score), no role
id may leak, and the line must say the score of its criterion; a line that fails is dropped, the drop is recorded with its reason, and the template line is used instead.
If the model is not installed, is busy, is slow or answers badly, every line is the template's. A score never depends on any of this.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel

from .scoring import _FILE, _TIME, clock, event_text

VOICE_TIMEOUT = 40.0  # seconds for the one call: five lines and a paragraph
JUDGE_CHARS = (20, 300)
COACH_CHARS = (60, 800)
_ROLE_ID = re.compile(r"\b(architect|planner|reviewer|integrator|qa)\b")
_QUOTED = re.compile(r"[“\"]([^”\"]{4,})[”\"]")
_NUMBER = re.compile(r"\d+")


class VoiceLine(BaseModel):
    criterion: str
    line: str


class VoiceOutput(BaseModel):
    lines: list[VoiceLine]
    coach: str


@dataclass
class Dropped:
    finding: str  # the criterion (or "coach") whose text was dropped; for a point, its finding id
    text: str
    reason: str

    def as_dict(self) -> dict:
        return {"finding": self.finding, "text": self.text, "reason": self.reason}


def _norm(s: str) -> str:
    return " ".join(s.replace("…", " ").replace("...", " ").replace("“", '"').replace("”", '"').replace("’", "'").split()).strip(" \"'").casefold()


MIN_QUOTE = 8  # characters; a shorter quote must be the whole text of the entry


def quote_matches(quote: str, event: dict) -> bool:
    """The quote is a stretch of the entry's own words (case and spacing aside, a trailing ellipsis allowed)."""
    q, text = _norm(quote), _norm(event_text(event))
    if not q or q not in text:
        return False
    return len(q) >= MIN_QUOTE or q == text


def _facts_of(report: dict, criterion: str | None) -> dict:
    """What a text about `criterion` (or about everything) may mention: the times, the texts, the numbers of its points, and the scores."""
    rows = [r for r in report["rows"] if criterion is None or r["criterion"] == criterion]
    events = report["events"]
    texts = [x for r in rows for x in (r["quote"], r["note"], r["advice"], event_text(events[r["event"]]) if r["event"] in events else "")]
    crit = [c for c in report["criteria"] if criterion is None or c["id"] == criterion]
    texts += [c["summary"] for c in crit] + ([x for x in report["focus"]] if criterion is None else [])
    times = {clock(r["t"]) for r in rows} | {clock(events[e]["t"]) for r in rows for e in r["events"] if e in events}
    for t in list(texts):
        times |= set(_TIME.findall(t))
    numbers = {str(c["score"]) for c in crit} | {str(c["max"]) for c in crit} | {str(report["max"]), str(report["total"]), str(report["attempt"])}
    for t in texts:
        numbers |= set(_NUMBER.findall(_FILE.sub(" ", _TIME.sub(" ", t))))
    return {"times": times, "texts": texts, "numbers": numbers, "blob": _norm(" ".join(texts))}


def verify_voice(text: str, report: dict, criterion: str | None, kind: str) -> str | None:
    """None when `text` (a judge's line, kind "judge", or the coach paragraph, kind "coach") only says what the report's own points say, else why not."""
    lo, hi = JUDGE_CHARS if kind == "judge" else COACH_CHARS
    if not lo <= len(text.strip()) <= hi:
        return f"the text is {len(text.strip())} characters, it must be {lo} to {hi}"
    if _ROLE_ID.search(text):
        return "it uses a role id instead of a name"
    if kind == "judge":
        c = next((c for c in report["criteria"] if c["id"] == criterion), None)
        if c is None or f"{c['score']}/{c['max']}" not in text:
            return "it does not say the score of its criterion"
    f = _facts_of(report, criterion)
    for t in _TIME.findall(text):
        if t not in f["times"]:
            return f"the time {t} is not the time of any point"
    for q in _QUOTED.findall(text):
        if _norm(q) not in f["blob"]:
            return f"the quoted words “{q}” are not in any point"
    for name in _FILE.findall(text):
        if name.strip(".") not in " ".join(f["texts"]):
            return f"the file {name} is not in any point"
    plain = _FILE.sub(" ", _TIME.sub(" ", text))
    for n in _NUMBER.findall(plain):
        if n not in f["numbers"]:
            return f"the number {n} is not in any point"
    return None


class Wordsmith:
    """Asks the local model for the judges' lines and the coach paragraph. `speak` never raises and never blocks longer than `timeout`:
    it returns (output or None, reason) where reason is "" when the model answered and else unavailable, busy, timeout, error or invalid."""

    def __init__(self, llm=None, model_id: str = "qwen25-coder-7b", available: Callable[[], bool] | None = None, timeout: float = VOICE_TIMEOUT):
        self.llm, self.model_id, self.timeout = llm, model_id, timeout
        self._available = available or (lambda: True)
        self._busy = threading.Lock()

    @staticmethod
    def _prompt(report: dict, moments: dict[str, dict]) -> list[dict]:
        lines = []
        for c in report["criteria"]:
            m = moments.get(c["id"])
            at = f' at {clock(m["t"])}: "{m["quote"]}" ({m["note"]})' if m else ""
            lines.append(f'- criterion "{c["id"]}": {c["name"]}, judge {c["judge_name"]}, score {c["score"]}/{c["max"]}. Moment{at}. Tip: {m["tip"] if m else c["keep"]}')
        system = ("You write what the judges of a simulated engineering team say to a junior engineer in the debrief meeting after a production incident, and a short coaching paragraph. "
                  "The scores and the moments below are final: you only put them into words. For each criterion write `line`: what its judge says, in first person, one or two short "
                  "sentences (at most 40 words), that says the score exactly as written (for example 3/4), mentions the moment by its time exactly as written (mm:ss) and ends with the tip in your "
                  "own words. Then write `coach`: three or four sentences to the learner (\"you\") about the whole attempt, using only what is below. "
                  f"The total score is {report['total']}/{report['max']}. Never invent a time, a number, a file name, a quote or an event; use only the ones below. Use names, not roles.\n"
                  "Reply with JSON: {\"lines\": [{\"criterion\": \"communication\", \"line\": \"...\"}], \"coach\": \"...\"} with one line per criterion.\n\nCriteria:\n" + "\n".join(lines)
                  + "\n\nFocus for the next attempt: " + " | ".join(report["focus"]))
        return [{"role": "system", "content": system}, {"role": "user", "content": "Write the lines and the paragraph."}]

    def speak(self, report: dict, moments: dict[str, dict]) -> tuple[VoiceOutput | None, str]:
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
                    box["out"] = self.llm.call(self.model_id, self._prompt(report, moments), VoiceOutput, temperature=0.3).parsed  # type: ignore[attr-defined]
            except Exception as e:  # Ollama down, a provider error, invalid JSON twice: the template lines are used
                box["error"] = type(e).__name__
            finally:
                self._busy.release()
                done.set()

        threading.Thread(target=work, name="debrief-voice", daemon=True).start()
        if not done.wait(self.timeout):
            return None, "timeout"
        if "error" in box:
            return None, "error"
        out = box.get("out")
        if not isinstance(out, VoiceOutput) or not out.lines:
            return None, "invalid"
        return out, ""


def build_voices(report: dict, wordsmith: Wordsmith, moments: dict[str, dict], template_line: Callable[[dict], tuple[str, str]]) -> tuple[dict[str, dict], dict, list[Dropped], str]:
    """(each judge's line {text, bubble, source}, the coach {text, source}, what the verifier dropped, why the model was not used (or "")).
    A line or paragraph the model wrote and that passes `verify_voice` is used as it is; every other is the template's."""
    out, reason = wordsmith.speak(report, moments)
    said = {x.criterion: " ".join(x.line.split()) for x in out.lines} if out else {}
    dropped: list[Dropped] = []
    lines: dict[str, dict] = {}
    for c in report["criteria"]:
        text, bubble = template_line(c)
        source = "template"
        if out is not None:
            mine = said.get(c["id"], "")
            problem = verify_voice(mine, report, c["id"], "judge") if mine else "the model wrote no line for this criterion"
            if problem:
                dropped.append(Dropped(c["id"], mine or "(nothing)", problem))
            else:
                text, bubble, source = mine, (mine if len(mine) <= 78 else mine[:77].rstrip(" ,;:.") + "…"), "model"
        lines[c["id"]] = {"text": text, "bubble": bubble, "source": source}
    coach = {"text": report["coach"]["text"], "source": "template"}
    if out is not None:
        mine = " ".join(out.coach.split())
        problem = verify_voice(mine, report, None, "coach")
        if problem:
            dropped.append(Dropped("coach", mine[:300] or "(nothing)", problem))
        else:
            coach = {"text": mine, "source": "model"}
    return lines, coach, dropped, reason
