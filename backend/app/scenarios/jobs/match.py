"""Which scenario fits a job description: fixed rules, each point explainable.

    role    50  the posting's role family is the scenario's seat (30 when the posting is full-stack and the seat is backend or frontend, 0 otherwise)
    skills  35  35 x min(shared skills, 4) / 4: the skills the posting names that the incident exercises (`fit.skills` of the scenario)
    domain  15  the posting's domain is the scenario's domain

The reason shown for a scenario is built from those numbers and names, never written by a model. Ties keep the catalog's order.

Part B plugs in here: `candidates()` returns the shipped scenarios plus whatever the functions in `EXTRA_PROVIDERS` offer for this posting (a generated scenario that passed its
proof gates is a `Candidate` with kind "generated"); `rank()` treats them all alike.
"""
from __future__ import annotations

from typing import Callable

from ..loader import Scenario, list_scenarios
from .schema import Candidate, JobExtraction, Match
from .vocab import FAMILY_NAME, normalise_domain

ROLE_POINTS, FULLSTACK_POINTS, SKILL_POINTS, SKILL_CAP, DOMAIN_POINTS = 50, 30, 35, 4, 15

# Part B appends a function here: it gets the reading of the posting and returns the generated scenarios it can offer for it (none when its proof gates did not pass).
EXTRA_PROVIDERS: list[Callable[[JobExtraction], list[Candidate]]] = []


def candidate_of(s: Scenario) -> Candidate | None:
    """A shipped scenario as a candidate; None when it declares no `fit` (it is then not offered for a job description)."""
    if s.fit is None or s.role not in ("backend", "frontend", "database"):
        return None
    return Candidate(id=s.id, title=s.title, role_family=s.role, domain=normalise_domain(s.fit.domain), skills=list(s.fit.skills))  # type: ignore[arg-type]


def candidates(extraction: JobExtraction | None = None, scenarios: list[Scenario] | None = None) -> list[Candidate]:
    out = [c for s in (list_scenarios() if scenarios is None else scenarios) if (c := candidate_of(s))]
    if extraction is not None:
        for provider in EXTRA_PROVIDERS:
            out += [c for c in provider(extraction) if c.id not in {x.id for x in out}]
    return out


def score_one(e: JobExtraction, c: Candidate) -> Match:
    seat = FAMILY_NAME[c.role_family]
    if not e.software_job:
        role, why_role = 0, f"the posting ({e.role}) is not a software engineering job, so no seat fits it"
    elif e.role_family == c.role_family:
        role, why_role = ROLE_POINTS, f"the posting's role ({e.role}) matches the {seat} seat"
    elif e.role_family == "fullstack" and c.role_family in ("backend", "frontend"):
        role, why_role = FULLSTACK_POINTS, f"a full-stack posting partly fits the {seat} seat"
    else:
        role, why_role = 0, f"the posting is for a {FAMILY_NAME[e.role_family].lower()}, this is the {seat} seat"
    shared = [s for s in e.skills if s in c.skills]
    skills = round(SKILL_POINTS * min(len(shared), SKILL_CAP) / SKILL_CAP)
    why_skills = f"shares {', '.join(shared)} ({len(shared)} of the incident's {len(c.skills)} skills)" if shared else "no skill in common"
    domain_of_job = normalise_domain(e.domain)
    domain = DOMAIN_POINTS if domain_of_job == c.domain else 0
    why_domain = f"same domain ({c.domain})" if domain else f"domain {domain_of_job} differs from {c.domain}"
    return Match(scenario=c.id, title=c.title, kind=c.kind, score=role + skills + domain, parts={"role": role, "skills": skills, "domain": domain}, shared_skills=shared,
                 reason="; ".join((why_role[0].upper() + why_role[1:], why_skills, why_domain)) + ".")


def rank(e: JobExtraction, cands: list[Candidate]) -> list[Match]:
    """Every candidate scored, best first (ties in the order the candidates came in), numbered from 1."""
    scored = [score_one(e, c) for c in cands]
    order = sorted(range(len(scored)), key=lambda i: (-scored[i].score, i))
    return [scored[i].model_copy(update={"rank": n}) for n, i in enumerate(order, 1)]
