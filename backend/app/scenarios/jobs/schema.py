"""The data that moves between the parts of the job-description feature: what was read, who it was matched with, and what is saved with an attempt.

Part B (generated scenarios) plugs in through `Candidate`: anything that has an id, a role, a domain and skills can be ranked, whether it is a shipped scenario or one Q generated.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MAX_JD_CHARS = 5000
MAX_SKILLS = 12


class JobExtraction(BaseModel):
    role: str = Field(min_length=2, max_length=120)  # the title as the posting words it ("Senior Backend Engineer")
    role_family: Literal["backend", "frontend", "database", "fullstack", "devops", "other"]
    seniority: Literal["intern", "junior", "mid", "senior", "lead"]
    domain: str = Field(min_length=2, max_length=60)
    skills: list[str] = Field(default_factory=list, max_length=MAX_SKILLS)  # canonical names (vocab.SKILLS)
    soft_skills: list[str] = Field(default_factory=list, max_length=6)  # labels of vocab.SIGNALS
    app_idea: str = Field(min_length=5, max_length=200)  # one line: the app Q would build for this domain (Part B)
    source: Literal["model", "keywords"] = "keywords"
    reason: str = ""  # why the keyword reader was used, "" for the model


class Candidate(BaseModel):
    """One scenario that can be offered for a job: a shipped one, or (Part B) one Q generated that passed its proof gates."""
    id: str
    title: str
    role_family: Literal["backend", "frontend", "database"]
    domain: str
    skills: list[str]
    kind: Literal["existing", "generated"] = "existing"


class Match(BaseModel):
    scenario: str
    title: str
    kind: str
    score: int  # 0 to 100: role 50 + skills 35 + domain 15
    parts: dict[str, int]
    shared_skills: list[str]
    reason: str  # one line, built from the numbers
    rank: int = 0


class Briefing(BaseModel):
    text: str
    source: Literal["template", "model"] = "template"
    reason: str = ""  # why the template stayed (the model was missing, slow, or its wording failed the check)


class JobContext(BaseModel):
    """What a session started from a job description carries, and what the report saves: the posting, how it was read, why this scenario, the emphasis and the briefing."""
    source: Literal["paste", "sample"]
    sample_id: str = ""
    text: str
    clipped: bool = False
    extraction: JobExtraction
    match: Match
    ranking: list[Match] = Field(default_factory=list)
    weights: dict[str, float]  # criterion id -> weight (0.5 to 2.0, mean 1.0)
    weight_reasons: dict[str, list[str]]  # criterion id -> the phrases of the posting behind its weight
    key_skills: list[str]  # three to five
    briefing: Briefing
