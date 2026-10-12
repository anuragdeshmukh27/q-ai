"""The rubric of a scenario: `<scenario folder>/rubric.json`.

Five criteria, each scored 0 to 4 by four rules (see scoring.py). The file holds what a person may want to read or change without touching code: the criteria and their
judges, a written descriptor for every score, the log entries that count as evidence (`signals`), the rule list with its numbers, the advice for each rule and a line for
a criterion that was scored full marks. `load_rubric` checks the file the way `load_scenario` checks a scenario, so a mistake is found when it is loaded.
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError, model_validator

from ..config import load_agents
from .loader import Scenario, ScenarioError
from .scoring import RULES
from .sessionlog import KINDS

LEVELS = ("0", "1", "2", "3", "4")


class RuleRef(BaseModel):
    id: str
    label: str = Field(min_length=3)  # the rule in a few words ("a regression test added"): the criterion's summary lists the ones that held and the ones that did not
    params: dict = Field(default_factory=dict)
    advice: str = Field(min_length=10)  # what to do next time when this rule is a gap


class Criterion(BaseModel):
    id: str
    name: str
    judge: str  # the employee who gives this criterion's feedback in the debrief
    descriptors: dict[str, str]
    signals: list[str] = Field(min_length=1)  # session log kinds that count as evidence
    keep: str = Field(min_length=10)  # said instead of a tip when the criterion scored full marks
    rules: list[RuleRef]

    @model_validator(mode="after")
    def _complete(self):
        if set(self.descriptors) != set(LEVELS) or any(len(v) < 10 for v in self.descriptors.values()):
            raise ValueError(f"criterion {self.id}: give a descriptor of at least 10 characters for each score 0 to 4")
        bad = [s for s in self.signals if s not in KINDS]
        if bad:
            raise ValueError(f"criterion {self.id}: unknown signal {bad[0]!r}")
        unknown = [r.id for r in self.rules if r.id not in RULES]
        if unknown:
            raise ValueError(f"criterion {self.id}: unknown rule {unknown[0]!r}")
        if len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError(f"criterion {self.id}: a rule is listed twice")
        return self


class Rubric(BaseModel):
    id: str
    version: int = Field(ge=1)
    scenario: str
    title: str
    points_per_criterion: int = Field(default=4, ge=1)
    weight: int = Field(default=5, ge=1)  # marks per point: the total is the points times this, out of 100
    criteria: list[Criterion] = Field(min_length=1)

    @model_validator(mode="after")
    def _adds_up(self):
        for c in self.criteria:
            if len(c.rules) != self.points_per_criterion:
                raise ValueError(f"criterion {c.id}: it needs exactly {self.points_per_criterion} rules (one point each), not {len(c.rules)}")
        if len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError("a criterion id is used twice")
        if self.max_total != 100:
            raise ValueError(f"the criteria must add up to 100 marks, not {self.max_total}")
        return self

    @property
    def max_total(self) -> int:
        return len(self.criteria) * self.points_per_criterion * self.weight

    def criterion(self, cid: str) -> Criterion:
        return next(c for c in self.criteria if c.id == cid)

    def public(self) -> dict:
        return {"id": self.id, "version": self.version, "criteria": [{"id": c.id, "name": c.name, "judge": c.judge} for c in self.criteria]}


def load_rubric(scenario: Scenario) -> Rubric:
    """The scenario's rubric, validated, or a ScenarioError that says what is wrong."""
    path = scenario.folder / "rubric.json"
    if not path.is_file():
        raise ScenarioError(f"scenario {scenario.id}: rubric.json is missing")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        r = Rubric.model_validate(raw)
    except ValueError as e:
        if isinstance(e, ValidationError):
            first = "; ".join(f"{'.'.join(str(p) for p in x['loc'])}: {x['msg']}" for x in e.errors()[:3])
        else:
            first = f"not valid JSON ({e})"
        raise ScenarioError(f"rubric of {scenario.id}: {first}") from None
    problems: list[str] = []
    if r.id != scenario.rubric or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", r.id):
        problems.append(f"id {r.id!r} must equal the scenario's rubric {scenario.rubric!r}")
    if r.scenario != scenario.id:
        problems.append(f"it says it is for {r.scenario!r}")
    agents = load_agents()
    for c in r.criteria:
        if c.judge not in agents:
            problems.append(f"criterion {c.id}: judge {c.judge!r} is not an employee of the roster")
    if problems:
        raise ScenarioError(f"rubric of {scenario.id}: " + "; ".join(problems))
    return r
