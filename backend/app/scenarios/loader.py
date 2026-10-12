"""Scenarios: a ready-made situation for Simulation mode (a finished app with a planted problem, a role, a scripted team and a guide).

A scenario is a folder `backend/app/scenarios/<id>/` with `scenario.json` and the files it points at (`seed/` is the finished app). `load_scenario` checks the whole
file against the seed and the roster, so a mistake in a scenario is found when it is loaded (and by the tests), never in the middle of a session.
"""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from ..config import load_agents

SCENARIOS_DIR = Path(__file__).resolve().parent
ROLES = ("database", "backend", "frontend")
EVENT_KINDS = ("file_opened", "file_saved", "test_run", "test_result", "message_posted", "hint_given", "submit", "submit_result")
REACT_ON = ("submit_result", "test_result")
BUILTIN_PLACEHOLDERS = ("failed", "summary")  # filled in when a reaction is posted
ROUTE_PARAMS = ("id", "doctor_id", "appointment_id")  # `{id}` in a text is a route template, not a placeholder
_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
_BRACES = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ScenarioError(ValueError):
    """The scenario is invalid or does not exist. The message names the scenario and the problem."""


class SeedInfo(BaseModel):
    dir: str = "seed"
    preset: str = "fastapi-vanilla"


class TaskInfo(BaseModel):
    title: str = Field(min_length=3)
    files: list[str] = Field(min_length=1)
    acceptance_tests: list[str] = Field(min_length=1)


class ChannelInfo(BaseModel):
    id: str
    name: str


class Fallback(BaseModel):
    match: list[str] = Field(default_factory=list)  # words in the question; an empty list matches every question (the last one is the default)
    text: str = Field(min_length=1)


class Character(BaseModel):
    persona: str = Field(min_length=10)
    facts: list[str] = Field(min_length=1)
    fallbacks: list[Fallback] = Field(min_length=1)

    @model_validator(mode="after")
    def _has_default(self):
        if self.fallbacks[-1].match:
            raise ValueError("the last fallback must have an empty `match` so there is always an answer")
        return self


class TimelineItem(BaseModel):
    id: str
    from_: str = Field(alias="from")
    text: str | None = None
    texts: list[str] | None = None
    at: float | None = Field(default=None, ge=0)  # seconds after the session starts
    idle: float | None = Field(default=None, gt=0)  # seconds without a post from the learner (nudges)
    on: str | None = None  # a reaction to an event of the learner's
    where: dict[str, object] = Field(default_factory=dict)
    max: int = Field(default=1, ge=1)
    delay: float = Field(default=0, ge=0)
    hint: bool = False
    skip_if: str | None = None  # "learner_posted" | "asked:<character>"

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _one_trigger(self):
        if sum(x is not None for x in (self.at, self.idle, self.on)) != 1:
            raise ValueError(f"timeline item {self.id}: give exactly one of `at`, `idle`, `on`")
        if (self.text is None) == (self.texts is None):
            raise ValueError(f"timeline item {self.id}: give exactly one of `text`, `texts`")
        if self.on is not None and self.on not in REACT_ON:
            raise ValueError(f"timeline item {self.id}: `on` must be one of {', '.join(REACT_ON)}")
        if self.skip_if is not None and not (self.skip_if == "learner_posted" or re.fullmatch(r"asked:[a-z]+", self.skip_if)):
            raise ValueError(f"timeline item {self.id}: skip_if must be learner_posted or asked:<character>")
        return self

    def all_texts(self) -> list[str]:
        return [self.text] if self.text is not None else list(self.texts or [])


class Advance(BaseModel):
    kind: Literal["file_opened", "file_saved", "test_run", "test_result", "message_posted", "hint_given", "submit", "submit_result"]
    path: str | None = None  # a glob for file events
    ok: bool | None = None


class GuideStep(BaseModel):
    id: str
    title: str
    text: str
    advance_on: Advance


class Scenario(BaseModel):
    id: str
    title: str = Field(min_length=3)
    summary: str = Field(min_length=10)
    role: str
    minutes: int = Field(gt=0)
    level: str = ""
    rubric: str
    goal: str = Field(min_length=3, max_length=1000)
    brief: str = Field(min_length=20)
    seed: SeedInfo
    task: TaskInfo
    channel: ChannelInfo
    evidence: dict[str, str] = Field(default_factory=dict)
    characters: dict[str, Character]
    timeline: list[TimelineItem]
    guide: list[GuideStep] = Field(min_length=1)
    root: Path = Field(default=SCENARIOS_DIR, exclude=True)

    @property
    def folder(self) -> Path:
        return self.root / self.id

    @property
    def seed_dir(self) -> Path:
        return self.folder / self.seed.dir

    def public(self) -> dict:
        """What the picker needs. The script, the facts and the guide stay on the server."""
        return {"id": self.id, "title": self.title, "summary": self.summary, "role": self.role, "minutes": self.minutes, "level": self.level,
                "channel": self.channel.name, "tests": len(self.task.acceptance_tests)}

    def fill(self, text: str, extra: dict[str, str] | None = None) -> str:
        """The text with `{booking_error}`-style placeholders replaced (route templates such as `{id}` are left alone)."""
        values = {**self.evidence, **(extra or {})}
        return _BRACES.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def _check(s: Scenario, folder: Path) -> list[str]:
    """Everything that cannot be said in the schema: the files, the roster, the placeholders, the references between parts."""
    problems: list[str] = []
    if not _ID.fullmatch(s.id) or s.id != folder.name:
        problems.append(f"id {s.id!r} must be lowercase words with dashes and equal the folder name {folder.name!r}")
    if not _ID.fullmatch(s.rubric):
        problems.append(f"rubric {s.rubric!r} must be an id (lowercase, digits, dashes)")
    if s.role not in ROLES:
        problems.append(f"role must be one of {', '.join(ROLES)}")
    if not _ID.fullmatch(s.channel.id):
        problems.append("channel id must be lowercase words with dashes")
    agents = load_agents()
    for cid in s.characters:
        if cid not in agents:
            problems.append(f"character {cid!r} is not an employee of the roster")
        elif cid == s.role:
            problems.append(f"character {cid!r} is the role you play: you are that employee")
    seed = folder / s.seed.dir
    if not seed.is_dir():
        problems.append(f"seed folder {s.seed.dir!r} does not exist")
        return problems
    for needed in ("pytest.ini", "tests"):
        if not (seed / needed).exists():
            problems.append(f"the seed has no {needed}")
    for f in s.task.files:
        if not (seed / f).is_file():
            problems.append(f"task file {f!r} is not in the seed")
    for t in s.task.acceptance_tests:
        path, _, name = t.partition("::")
        file = seed / path
        if not name or not file.is_file():
            problems.append(f"acceptance test {t!r} must be <test file>::<test name> of a file in the seed")
        elif not re.search(rf"^def {re.escape(name)}\(", file.read_text(encoding="utf-8"), re.M):
            problems.append(f"acceptance test {t!r}: there is no function {name} in {path}")
    ids: set[str] = set()
    known = set(s.evidence) | set(BUILTIN_PLACEHOLDERS)
    texts = [(f"timeline {i.id}", x) for i in s.timeline for x in i.all_texts()]
    for cid, c in s.characters.items():
        texts += [(f"{cid} fact", x) for x in c.facts] + [(f"{cid} fallback", f.text) for f in c.fallbacks]
    for item in s.timeline:
        if item.id in ids:
            problems.append(f"timeline id {item.id!r} is used twice")
        ids.add(item.id)
        if item.from_ not in s.characters:
            problems.append(f"timeline {item.id}: `from` {item.from_!r} is not one of the characters")
        if item.hint and item.from_ not in s.characters:
            problems.append(f"timeline {item.id}: a hint needs a character")
        if item.skip_if and item.skip_if.startswith("asked:") and item.skip_if.split(":", 1)[1] not in s.characters:
            problems.append(f"timeline {item.id}: skip_if names a character that does not exist")
    for where, text in texts:
        for name in _BRACES.findall(text):
            if name not in known and name not in ROUTE_PARAMS:
                problems.append(f"{where}: unknown placeholder {{{name}}}")
    gids: set[str] = set()
    for g in s.guide:
        if g.id in gids:
            problems.append(f"guide step id {g.id!r} is used twice")
        gids.add(g.id)
        a = g.advance_on
        if a.kind not in EVENT_KINDS:
            problems.append(f"guide step {g.id}: unknown event kind {a.kind!r}")
        if a.path is not None and not a.kind.startswith("file_"):
            problems.append(f"guide step {g.id}: `path` only belongs to file events")
        if a.path is not None and not any(fnmatch.fnmatch(p.relative_to(seed).as_posix(), a.path) for p in seed.rglob("*") if p.is_file()):
            problems.append(f"guide step {g.id}: no file of the seed matches {a.path!r}")
    return problems


def load_scenario(scenario_id: str, root: Path = SCENARIOS_DIR) -> Scenario:
    """The validated scenario, or a ScenarioError that says what is wrong."""
    if not _ID.fullmatch(scenario_id or ""):
        raise ScenarioError(f"unknown scenario {scenario_id!r}")
    folder = root / scenario_id
    path = folder / "scenario.json"
    if not path.is_file():
        raise ScenarioError(f"unknown scenario {scenario_id!r}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ScenarioError(f"scenario {scenario_id}: scenario.json is not valid JSON ({e})") from None
    try:
        s = Scenario.model_validate({**raw, "root": root})
    except ValidationError as e:
        first = "; ".join(f"{'.'.join(str(p) for p in x['loc'])}: {x['msg']}" for x in e.errors()[:4])
        raise ScenarioError(f"scenario {scenario_id}: {first}") from None
    problems = _check(s, folder)
    if problems:
        raise ScenarioError(f"scenario {scenario_id}: " + "; ".join(problems))
    return s


def list_scenarios(root: Path = SCENARIOS_DIR) -> list[Scenario]:
    """Every valid scenario under `root`, in folder order. A broken one raises: the picker never shows a half scenario."""
    return [load_scenario(p.parent.name, root) for p in sorted(root.glob("*/scenario.json"))]
