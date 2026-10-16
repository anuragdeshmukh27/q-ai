"""Adapting a scenario to a job description: the emphasis (weights and the role-fit score), the key skills, and the briefing paragraph.

Nothing here touches the standard score. The weights come from what the posting asks for (the phrases of `vocab.SIGNALS` found in its text, so the same posting always gives the same
weights, whichever reader read it) and each stays within 0.5 to 2.0 with a mean of 1.0. Role fit is the same five criterion scores averaged with those weights. The briefing is a
template built from the reading and the scenario; the 7b may reword it, and its text is used only if `verify_briefing` finds nothing in it that is not in the reading or the scenario.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..loader import Scenario
from ..rubric import Rubric
from ..wording import _GENERIC, _NUMBER, _QUOTED, _ROLE_ID, _TIME, _norm, praise_of_names
from .modelcall import BRIEF_GATE, BRIEF_TIMEOUT, ModelGate
from .match import candidate_of, candidates, rank
from .schema import Briefing, JobContext, JobExtraction, Match
from .vocab import FAMILY_NAME, find_skills, signal_hits

MIN_WEIGHT, MAX_WEIGHT = 0.5, 2.0
STEP = 0.5  # one phrase of the posting adds this much to a criterion's raw weight...
MAX_HITS = 3  # ...up to this many phrases
KEY_SKILLS = 5
BRIEF_CHARS = (120, 700)


class JobError(ValueError):
    """The scenario cannot be adapted to this job (it declares no `fit`)."""


# -- the emphasis ------------------------------------------------------------------------------------------------

def normalise(raw: dict[str, float], lo: float = MIN_WEIGHT, hi: float = MAX_WEIGHT) -> dict[str, float]:
    """Weights within [lo, hi] whose mean is 1.0: scale the free ones to the target, pin any that leave the bounds at the bound they crossed, scale the rest again.
    Needs n x lo <= n <= n x hi, which holds for any n with lo <= 1 <= hi."""
    n = len(raw)
    if n == 0:
        return {}
    fixed: dict[str, float] = {}
    for _ in range(n + 1):
        free = [k for k in raw if k not in fixed]
        if not free:
            break
        base = sum(max(raw[k], 1e-9) for k in free)
        scale = (n - sum(fixed.values())) / base
        got = {k: max(raw[k], 1e-9) * scale for k in free}
        over = {k: v for k, v in got.items() if v > hi + 1e-9}
        under = {k: v for k, v in got.items() if v < lo - 1e-9}
        if not over and not under:
            fixed.update(got)
            break
        side, bound = (over, hi) if sum(v - hi for v in over.values()) >= sum(lo - v for v in under.values()) else (under, lo)
        fixed.update({k: bound for k in side})
    return {k: round(min(hi, max(lo, fixed.get(k, 1.0))), 2) for k in raw}


def weights_for(text: str, criterion_ids: list[str]) -> tuple[dict[str, float], dict[str, list[str]]]:
    """(criterion id -> weight, criterion id -> the phrases of the posting behind it). A posting that asks for nothing in particular gives every criterion 1.0."""
    hits = signal_hits(text)
    raw = {cid: 1.0 + STEP * min(len(hits.get(cid, [])), MAX_HITS) for cid in criterion_ids}
    reasons = {cid: hits.get(cid, []) for cid in criterion_ids}
    if len({round(v, 6) for v in raw.values()}) == 1:
        return {cid: 1.0 for cid in criterion_ids}, reasons
    return normalise(raw), reasons


def role_fit(scores: dict[str, int], max_points: int, weights: dict[str, float]) -> int:
    """The same criterion scores, averaged with the posting's weights, out of 100. Equal weights give the standard score."""
    total = sum(weights.get(cid, 1.0) for cid in scores)
    if not scores or total <= 0 or max_points <= 0:
        return 0
    return int(100 * sum(weights.get(cid, 1.0) * s for cid, s in scores.items()) / (max_points * total) + 0.5)


def emphasised(weights: dict[str, float], names: dict[str, str], at: float = 1.1) -> list[str]:
    """The names of the criteria the posting weighs more, heaviest first."""
    return [names[c] for c, w in sorted(weights.items(), key=lambda kv: -kv[1]) if w >= at and c in names]


# -- the key skills and the briefing ---------------------------------------------------------------------------------

def key_skills(e: JobExtraction, scenario_skills: list[str]) -> list[str]:
    """Up to five skills of the posting: the ones this incident exercises first, then the rest, in the order the posting names them."""
    shared = [s for s in e.skills if s in scenario_skills]
    return (shared + [s for s in e.skills if s not in shared])[:KEY_SKILLS]


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def template_briefing(e: JobExtraction, scenario: Scenario, m: Match, weights: dict[str, float], names: dict[str, str], key: list[str]) -> str:
    seat = FAMILY_NAME[scenario.role]
    if not e.software_job:
        return (f"The posting ({e.role}) does not look like a software engineering job, so no scenario really fits it. This is the closest one: it puts you in the {seat} seat for "
                f"{scenario.minutes} minutes on “{scenario.title}”. Your role-fit score will equal your standard score.")
    parts = [f"This incident fits the {e.role} job: it puts you in the {seat} seat for {scenario.minutes} minutes on “{scenario.title}”."]
    if key:
        parts.append(f"The posting asks for {_join(key)}" + (f"; the incident exercises {_join(m.shared_skills[:4])}." if m.shared_skills else "."))
    top = emphasised(weights, names)
    parts.append(f"Your role-fit score will count {_join(top[:3])} most, given what the posting stresses." if top else "The posting does not stress one skill over another, so your role-fit score will equal your standard score.")
    return " ".join(parts)


class BriefOutput(BaseModel):
    paragraph: str = Field(min_length=20, max_length=1200)


def _facts_blob(e: JobExtraction, scenario: Scenario, names: dict[str, str]) -> str:
    fit = scenario.fit.skills if scenario.fit else []
    return _norm(" ".join([e.role, e.domain, e.seniority, *e.skills, *e.soft_skills, scenario.title, scenario.summary, scenario.level, str(scenario.minutes), FAMILY_NAME[scenario.role], *fit, *names.values()]))


def verify_briefing(text: str, e: JobExtraction, scenario: Scenario, names: dict[str, str]) -> str | None:
    """None when the paragraph only says what the reading and the scenario say, else why not (the template is used then)."""
    text = " ".join(text.split())
    lo, hi = BRIEF_CHARS
    if not lo <= len(text) <= hi:
        return f"the text is {len(text)} characters, it must be {lo} to {hi}"
    if _ROLE_ID.search(text):
        return "it uses a role id instead of a name"
    if g := _GENERIC.search(text):
        return f"it uses generic praise (“{g.group(0)}”)"
    if p := praise_of_names(text, {"criteria": [{"name": n} for n in names.values()]}):
        return p
    if _TIME.search(text):
        return "it states a time, which no fact has"
    blob = _facts_blob(e, scenario, names)
    allowed = set(e.skills) | set(scenario.fit.skills if scenario.fit else [])
    for s in find_skills(text):
        if s not in allowed:
            return f"it names the skill {s}, which is neither in the posting nor in the scenario"
    for token in re.findall(r"\b(?:[A-Za-z]+[A-Z][A-Za-z]*|[A-Z]{2,}|[A-Za-z]+\.js)\b", text):
        if _norm(token) not in blob:
            return f"“{token}” is not in the posting or the scenario"
    for q in _QUOTED.findall(text):
        if _norm(q) not in blob:
            return f"the quoted words “{q}” are not in the posting or the scenario"
    for n in _NUMBER.findall(text):
        if n not in set(_NUMBER.findall(blob)):
            return f"the number {n} is not in the posting or the scenario"
    if FAMILY_NAME[scenario.role].split()[0].lower() not in text.lower():
        return "it does not say which seat the scenario puts you in"
    return None


def _brief_prompt(e: JobExtraction, scenario: Scenario, m: Match, top: list[str], key: list[str]) -> list[dict]:
    facts = [f"- job: {e.role} ({e.seniority}), domain {e.domain}", f"- skills the posting asks for: {', '.join(key) or 'none named'}",
             f"- soft skills it asks for: {', '.join(e.soft_skills) or 'none named'}", f"- scenario: “{scenario.title}”, you play the {FAMILY_NAME[scenario.role]}, {scenario.minutes} minutes, level {scenario.level or 'any'}",
             f"- skills of the posting that the scenario exercises: {', '.join(m.shared_skills) or 'none'}", f"- the role-fit score will count most: {', '.join(top) or 'nothing in particular'}"]
    system = ("You write the short briefing a candidate reads before a practice incident, explaining why it fits the job they are applying for. Use only the facts below: "
              "no other skill, tool, number, time or company, no praise, no scores. Two or three sentences, plain words, speak to the candidate (\"you\"). "
              "Say which seat they play and which of their job's skills the incident exercises.\nFacts:\n" + "\n".join(facts) + "\nReply with JSON: {\"paragraph\": \"...\"}")
    return [{"role": "system", "content": system}, {"role": "user", "content": "Write the briefing."}]


def word_briefing(ctx: JobContext, scenario: Scenario, names: dict[str, str], llm, available=None, timeout: float = BRIEF_TIMEOUT, gate: ModelGate = BRIEF_GATE) -> tuple[Briefing | None, str]:
    """The 7b's wording of the briefing if it passes `verify_briefing`: (the briefing, "") or (None, why the template stays)."""
    out, why = gate.ask(llm, _brief_prompt(ctx.extraction, scenario, ctx.match, emphasised(ctx.weights, names), ctx.key_skills), BriefOutput, available=available, timeout=timeout, temperature=0.3)
    if out is None:
        return None, why
    problem = verify_briefing(out.paragraph, ctx.extraction, scenario, names)
    return (None, problem) if problem else (Briefing(text=" ".join(out.paragraph.split()), source="model"), "")


# -- putting it together --------------------------------------------------------------------------------------------

def build_context(*, scenario: Scenario, rubric: Rubric, extraction: JobExtraction, text: str, clipped: bool, source: str, sample_id: str = "") -> JobContext:
    """Everything a session started from a job description carries. Raises JobError for a scenario that declares no `fit`."""
    own = candidate_of(scenario)
    if own is None:
        raise JobError("That scenario cannot be matched to a job description.")
    ranking = rank(extraction, candidates(extraction))
    match = next((m for m in ranking if m.scenario == scenario.id), None) or rank(extraction, [own])[0]
    names = {c.id: c.name for c in rubric.criteria}
    weights, reasons = weights_for(text, [c.id for c in rubric.criteria])
    if not extraction.software_job:  # nothing in a non-software posting says what to stress in an incident: the role fit equals the standard score
        weights, reasons = {c.id: 1.0 for c in rubric.criteria}, {c.id: [] for c in rubric.criteria}
    key = key_skills(extraction, own.skills)
    return JobContext(source=source, sample_id=sample_id, text=text, clipped=clipped, extraction=extraction, match=match, ranking=ranking, weights=weights, weight_reasons=reasons,
                      key_skills=key, briefing=Briefing(text=template_briefing(extraction, scenario, match, weights, names, key), source="template"))


__all__ = ["BriefOutput", "JobError", "build_context", "emphasised", "key_skills", "normalise", "role_fit", "template_briefing", "verify_briefing", "weights_for", "word_briefing"]
