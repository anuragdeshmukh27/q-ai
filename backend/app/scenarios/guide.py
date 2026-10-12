"""Priya's guide: the steps of a scenario, written to `.q/guides/<task>.md` and advanced by what the learner does (never by a timer).

A step is done once an event that matches its `advance_on` is in the session log; the current step is the first one that is not done. Because the whole log counts,
a learner who opens the migration before the guide asks for it still gets the tick when the guide reaches that step.
"""
from __future__ import annotations

import fnmatch
from typing import Callable

from .loader import GuideStep, Scenario


def matches(step: GuideStep, event: dict) -> bool:
    a = step.advance_on
    if event.get("kind") != a.kind or event.get("auto"):
        return False
    if a.path is not None and not fnmatch.fnmatch(str(event.get("path", "")), a.path):
        return False
    return a.ok is None or bool(event.get("ok")) == a.ok


def guide_markdown(scenario: Scenario, task_id: str, task_title: str) -> str:
    lines = [f"# Priya's guide: {task_id} {task_title}", "",
             f"This is the incident in {scenario.channel.name}. I will not tell you the answer; I will tell you what to do next. The current step changes by itself "
             "when you run the tests, open a file, post in the channel or submit.", ""]
    for i, g in enumerate(scenario.guide, 1):
        lines += [f"{i}. **{g.title}**: {g.text}"]
    return "\n".join(lines) + "\n"


class GuideTracker:
    def __init__(self, scenario: Scenario, emit: Callable[..., object], events: Callable[[], list[dict]]):
        self.steps = scenario.guide
        self.emit = emit
        self._events = events
        self.task = ""  # set when the learner's task is handed over: the guide starts then
        self._done: tuple[str, ...] = ()

    def done(self) -> tuple[str, ...]:
        log = self._events()
        return tuple(g.id for g in self.steps if any(matches(g, e) for e in log))

    def state(self) -> dict:
        done = set(self.done())
        current = next((g.id for g in self.steps if g.id not in done), None)
        return {"task": self.task, "current": current, "done": len(done),
                "steps": [{"id": g.id, "title": g.title, "text": g.text, "state": "done" if g.id in done else "current" if g.id == current else "todo"} for g in self.steps]}

    def start(self, task: str) -> None:
        self.task = task
        self._done = self.done()
        self.emit("guide_progress", **self.state())

    def on_event(self, _event: dict) -> None:
        if not self.task:
            return
        done = self.done()
        if done != self._done:
            self._done = done
            self.emit("guide_progress", **self.state())
