"""The incident channel: the scripted timeline and the replies when the learner asks a teammate something.

`Director.tick()` is the whole script: given the session clock it posts what is due (a report at 3 s, a request for an update at 90 s, a nudge after 5 quiet minutes,
a pointer from Karan at 4 minutes unless he was asked). The clock is injected, so the tests play a 30-minute incident in milliseconds. A thread calls `tick()` once a
second in a real session. What the learner does (the session log) can trigger reactions (a failed submit, an accepted one).

When the learner @-mentions or addresses a teammate, `Replier` asks the local model for a reply in character, grounded only in that teammate's facts from the
scenario; if the model is not available, busy, slow or answers badly, the scripted fallback text is posted instead. Every reply to the learner is a hint: counted and logged.
"""
from __future__ import annotations

import fnmatch
import re
import threading
from typing import Callable

from pydantic import BaseModel

from ..config import AgentConfig
from .loader import Character, Scenario, TimelineItem
from .sessionlog import SessionLog

MAX_REPLY_CHARS = 320
MAX_ADDRESSED = 2  # one post never starts more replies than this
LIVE_TIMEOUT = 15.0  # seconds a live reply may take before the scripted one is posted


class ChatReply(BaseModel):
    reply: str


def _first_sentences(text: str, limit: int = MAX_REPLY_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > 60 else cut.rstrip(" ,;:") + "…"


_QUESTION_START = re.compile(r"^(how|what|where|why|which|who|when|can|could|would|do|does|did|is|are|should|any|tell|explain|show|help)\b", re.I)
_LEADING_NAME = re.compile(r"^@?\w+(?:[,:]\s+|\s+(?=(?:how|what|where|why|which|who|when|can|could|would|do|does|did|is|are|should)\b))", re.I)  # "Karan, what changed" and "Karan what changed"
_ASKS_FOR_HELP = re.compile(r"\b(help me|i('| a)m stuck|any idea|any hint|any advice|can you|could you|would you|do you know|i need (help|a hint|advice)|please (tell|explain|check|confirm|look|help|show))", re.I)


def is_question(text: str) -> bool:
    """The learner asks a teammate something or asks for help (a hint when they answer), as opposed to reporting what they found or did (a status update, which is only acknowledged)."""
    if "?" in text:
        return True
    if _ASKS_FOR_HELP.search(text):
        return True
    # a sentence that opens like a question and is short, without a colon ("What I found: ..." is a report)
    return any(_QUESTION_START.match(x) and ":" not in x and len(x.split()) <= 18 for x in (_LEADING_NAME.sub("", y.strip()) for y in re.split(r"(?<=[.!])\s+|\n", text)) if x)


def fallback_text(scenario: Scenario, cid: str, question: str, extra: dict[str, str] | None = None) -> str:
    """The scripted answer of a teammate: the first fallback with a word that appears in the question, else the default (the last)."""
    low = question.lower()
    chosen = next((f for f in scenario.characters[cid].fallbacks if f.match and any(w in low for w in f.match)), scenario.characters[cid].fallbacks[-1])
    return scenario.fill(chosen.text, extra)


class Replier:
    """Asks the model for a short in-character answer. `ask` never raises and never blocks longer than `timeout`: it returns (text, source, reason)
    with source "live" or "fallback" (and why: unavailable, busy, timeout, error, invalid)."""

    def __init__(self, llm=None, model_id: str = "qwen25-coder-7b", available: Callable[[], bool] | None = None, timeout: float = LIVE_TIMEOUT):
        self.llm, self.model_id, self.timeout = llm, model_id, timeout
        self._available = available or (lambda: True)
        self._busy = threading.Lock()  # one live reply at a time: a second question while the model is working gets the scripted answer

    def _prompt(self, scenario: Scenario, cid: str, agent: AgentConfig, question: str, recent: list[str]) -> list[dict]:
        c: Character = scenario.characters[cid]
        facts = "\n".join(f"- {scenario.fill(f)}" for f in c.facts)
        system = (f"You are {agent.name}, the {agent.role}, in the {scenario.channel.name} channel of a hospital software team during a production incident. {c.persona}\n"
                  "Answer the message in 1 or 2 short sentences (at most 40 words), in character, in plain words.\n"
                  "Use ONLY the facts below. If the message asks for something the facts do not cover, say you do not know and, if you can, who might. "
                  "Never write code, never give the fix itself, never invent file names, numbers or events.\n\nFacts:\n" + facts)
        if recent:
            system += "\n\nThe latest messages in the channel (oldest first):\n" + "\n".join(recent[-6:])
        return [{"role": "system", "content": system}, {"role": "user", "content": question}]

    def ask(self, scenario: Scenario, cid: str, agent: AgentConfig, question: str, recent: list[str]) -> tuple[str, str, str]:
        fallback = fallback_text(scenario, cid, question)
        if self.llm is None or not self._available():
            return fallback, "fallback", "unavailable"
        if not self._busy.acquire(blocking=False):
            return fallback, "fallback", "busy"
        box: dict = {}
        done = threading.Event()

        def work() -> None:
            try:
                from ..llm import agent_context
                with agent_context(cid):
                    box["text"] = self.llm.call(self.model_id, self._prompt(scenario, cid, agent, question, recent), ChatReply, temperature=0.3).parsed.reply  # type: ignore[attr-defined]
            except Exception as e:  # Ollama down, a provider error, invalid JSON twice: the scripted text answers
                box["error"] = type(e).__name__
            finally:
                self._busy.release()
                done.set()

        threading.Thread(target=work, name=f"reply-{cid}", daemon=True).start()
        if not done.wait(self.timeout):
            return fallback, "fallback", "timeout"
        if "error" in box:
            return fallback, "fallback", "error"
        text = _first_sentences(str(box.get("text", "")).strip())
        if len(text) < 3 or "```" in text:
            return fallback, "fallback", "invalid"
        return text, "live", ""


class Director:
    def __init__(self, scenario: Scenario, log: SessionLog, emit: Callable[..., object], roster: dict[str, AgentConfig], replier: Replier | None = None):
        self.scenario, self.log, self.emit, self.roster = scenario, log, emit, roster
        self.replier = replier or Replier()
        self.messages: list[dict] = []
        self.closed = False  # the incident is over (accepted) or the session stopped: no more nudges
        self.learner_posted = False
        self.asked: set[str] = set()  # teammates the learner asked a question
        self.posts: list[str] = []  # what the learner posted
        self.hints = 0
        self._fired: set[str] = set()
        self._nudges = 0
        self._last_post = 0.0  # session time of the last post by the learner, or of the last nudge
        self._pending: list[tuple[float, TimelineItem, dict]] = []  # reactions waiting for their delay
        self._lock = threading.RLock()
        self._threads: list[threading.Thread] = []
        self._halted = threading.Event()  # the session was stopped: nothing more is said
        self._ticking = False
        self._ack = 0
        self._ticker: threading.Thread | None = None

    # -- saying things ---------------------------------------------------------------
    def _say(self, sender: str, text: str, source: str, ref: str = "", log: bool = True, **extra) -> dict:
        with self._lock:
            n = len(self.messages) + 1
            msg = {"id": f"C{n:03d}", "channel": self.scenario.channel.id, "from": sender, "text": text, "source": source, "t": round(self.log.now(), 1), **({"ref": ref} if ref else {}), **extra}
            self.messages.append(msg)
        self.emit("channel_message", **msg)
        if sender != "human" and log:
            self.log.add("team_message", message=msg["id"], **{"from": sender}, text=text, source=source, ref=ref)
        return msg

    def announce(self, sender: str, text: str, **extra) -> dict:
        """A message of the debrief meeting: in the channel like any other, but not in the session log (the log is the evidence the debrief is scored from)."""
        return self._say(sender, text, "debrief", log=False, **extra)

    def _hint(self, msg: dict, source: str, reason: str, question: str) -> None:
        with self._lock:
            self.hints += 1
            n = self.hints
        self.log.add("hint_given", message=msg["id"], **{"from": msg["from"]}, source=source, reason=reason, question=question, text=msg["text"], n=n)

    # -- the timeline ----------------------------------------------------------------
    def _skipped(self, item: TimelineItem) -> bool:
        """Any condition of the item holds: the learner already did what the message is for (so it is neither said nor counted as a hint)."""
        for cond in item.conditions():
            if cond == "learner_posted" and self.learner_posted:
                return True
            if cond.startswith("asked:") and cond.split(":", 1)[1] in self.asked:
                return True
            if cond.startswith("opened:") and any(fnmatch.fnmatch(str(e.get("path", "")), cond[7:]) for e in self.log.events("file_opened") if not e.get("auto")):
                return True
            if cond.startswith("said:") and any(re.search(cond[5:], t, re.I) for t in self.posts):
                return True
        return False

    def _fire(self, item: TimelineItem, text: str, extra: dict | None = None) -> dict:
        msg = self._say(item.from_, self.scenario.fill(text, extra), "scripted", ref=item.id, **({"hint": True} if item.hint else {}))
        if item.hint:
            self._hint(msg, "scripted", "timeline", "")
        return msg

    def tick(self) -> list[dict]:
        """Post everything that is due now. Returns the messages posted (the clock decides, so a test calls this after moving the clock)."""
        posted: list[dict] = []
        with self._lock:
            if self._halted.is_set() or self._ticking:  # a post made while a tick is going out waits for the next tick
                return posted
            self._ticking = True
            try:
                now = self.log.now()
                for due, item, ctx in [p for p in self._pending if p[0] <= now]:
                    self._pending.remove((due, item, ctx))
                    posted.append(self._fire(item, item.all_texts()[0], ctx))
                if self.closed:
                    return posted
                for item in self.scenario.timeline:
                    if item.at is not None and item.id not in self._fired and now >= item.at:
                        self._fired.add(item.id)
                        if not self._skipped(item):
                            posted.append(self._fire(item, item.all_texts()[0]))
                    elif item.idle is not None and self._nudges < item.max and now - self._last_post >= item.idle:
                        texts = item.all_texts()
                        self._nudges += 1
                        self._last_post = now  # the next nudge comes after another quiet stretch
                        posted.append(self._fire(item, texts[min(self._nudges - 1, len(texts) - 1)]))
            finally:
                self._ticking = False
        return posted

    def on_log_event(self, event: dict) -> None:
        """What the learner did: a reaction may be due (after its delay, which the next tick posts)."""
        if event["kind"] == "submit_result" and event.get("ok"):
            with self._lock:
                self.closed = True  # solved: Aarav and Ananya say their thanks, nobody nudges any more
        extra = {"failed": ", ".join(x.split("::")[-1] for x in event.get("failed", [])[:3]) or "the suite", "summary": event.get("summary", "")}
        queued = False
        with self._lock:
            for item in self.scenario.timeline:
                if item.on != event["kind"] or any(event.get(k) != v for k, v in item.where.items()):
                    continue
                self._pending.append((self.log.now() + item.delay, item, extra))
                queued = True
        if queued:
            self.tick()  # reactions without a delay are posted now

    # -- the learner talks ----------------------------------------------------------------
    def _addressed(self, text: str, to: str | None) -> tuple[list[str], list[str]]:
        """(the teammates of this scenario the post is for, the other employees it names). `to` is the recipient picked in the UI; names and @ids in the text count too."""
        found: list[str] = [to] if to and to in self.scenario.characters else []
        others: list[str] = []
        hits: list[tuple[int, str]] = []
        for cid, a in self.roster.items():
            if cid == self.scenario.role:  # that is you
                continue
            m = re.search(rf"(?<![A-Za-z0-9]){re.escape(a.name)}(?![A-Za-z0-9])|@{re.escape(cid)}\b", text, re.I)
            if m:
                hits.append((m.start(), cid))
        for _, cid in sorted(hits):  # in the order they are named
            if cid not in self.scenario.characters:
                others.append(self.roster[cid].name)
            elif cid not in found:
                found.append(cid)
        return found[:MAX_ADDRESSED], others

    def post(self, text: str, to: str | None = None) -> dict:
        """The learner posts in the channel. Returns at once with {message, to, pending}; the replies arrive as `channel_message` events."""
        text = text.strip()
        if not text:
            raise ValueError("write a message")
        addressed, others = self._addressed(text, to)
        question = is_question(text)
        with self._lock:
            if self._halted.is_set():
                raise ValueError("The incident channel is closed.")
            self.learner_posted = True
            self._last_post = self.log.now()
            self.posts.append(text)
            if question:
                self.asked.update(addressed)
        msg = self._say("human", text, "learner", to=addressed)
        self.log.add("message_posted", message=msg["id"], text=text, to=addressed)
        pending: list[str] = []
        if not question:  # a status update or a remark: one scripted acknowledgement (the lead's, or from the one teammate it is addressed to), never a live reply and never a hint
            with self._lock:
                ack = self.scenario.acks[self._ack % len(self.scenario.acks)]
                self._ack += 1
            self._answer_scripted(addressed[0] if addressed else "architect", ack, msg)
            return {"message": msg, "to": addressed, "pending": []}
        if not addressed:
            if others:  # a colleague who is not part of this incident
                self._answer_scripted("architect", f"{', '.join(others)} is not on this incident. Ask Ananya, Karan or me.", msg)
            else:
                with self._lock:
                    ack = self.scenario.acks[self._ack % len(self.scenario.acks)]
                    self._ack += 1
                self._answer_scripted("architect", ack, msg)
        for cid in addressed:
            pending.append(cid)
            th = threading.Thread(target=self._reply, args=(cid, text, msg["id"]), name=f"channel-{cid}", daemon=True)
            self._threads.append(th)
            th.start()
        return {"message": msg, "to": addressed, "pending": pending}

    def _answer_scripted(self, cid: str, text: str, to_msg: dict) -> None:
        self._say(cid, text, "scripted", ref=to_msg["id"], reply_to=to_msg["id"])

    def _reply(self, cid: str, question: str, to_id: str) -> None:
        recent = [f"{self.roster[m['from']].name if m['from'] in self.roster else 'You'}: {m['text']}" for m in list(self.messages)[-7:-1]]
        text, source, reason = self.replier.ask(self.scenario, cid, self.roster[cid], question, recent)
        msg = self._say(cid, text, source, ref=to_id, reply_to=to_id, hint=True)
        self._hint(msg, source, reason, question)

    def join(self, timeout: float = 30.0) -> None:
        """Wait for the replies that are on their way (tests)."""
        for th in list(self._threads):
            th.join(timeout)

    # -- the clock thread ---------------------------------------------------------------------
    def start(self, interval: float = 1.0) -> None:
        def loop() -> None:
            while not self._halted.wait(interval):
                try:
                    self.tick()
                except Exception:  # the script must never take the session down
                    pass
                if self.closed and not self._pending:  # solved, and everyone has said their thanks
                    break

        self._ticker = threading.Thread(target=loop, name="incident-clock", daemon=True)
        self._ticker.start()

    def stop(self) -> None:
        self._halted.set()
        self.closed = True
