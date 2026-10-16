"""What the API needs from the job-description feature: read a posting and rank the scenarios (`analyze`), and turn the job a client sends with a start request into the context
a session carries (`resolve`). Errors are `JobRequestError`s whose message is for the person."""
from __future__ import annotations

from pydantic import BaseModel

from ..loader import Scenario
from ..rubric import Rubric
from .adapt import JobError, build_context
from .extract import JobTextError, extract_keywords, prepare, read_job, revalidate
from .match import candidates, rank
from .samples import sample_text
from .schema import JobContext, JobExtraction


class JobRequestError(ValueError):
    """The request cannot be served (empty, both a text and a sample, an unknown sample, a scenario that cannot be matched)."""


class JobBody(BaseModel):
    """A job description in a request: a bundled sample's id, or pasted text. At a start request the reading the person was shown may come back with it (it is checked, not trusted)."""
    sample_id: str | None = None
    text: str | None = None
    extraction: dict | None = None


def posting(body: JobBody) -> tuple[str, str, str]:
    """(source, sample id, text) of a request, or a JobRequestError."""
    if body.sample_id and body.text and body.text.strip():
        raise JobRequestError("Give either pasted text or a sample, not both.")
    if body.sample_id:
        text = sample_text(body.sample_id)
        if text is None:
            raise JobRequestError("That sample job description does not exist.")
        return "sample", body.sample_id, text
    return "paste", "", body.text or ""


def analyze(body: JobBody, llm=None, available=None) -> dict:
    """Read the posting (the model when it can, else the keywords) and rank every candidate scenario against it."""
    source, sample_id, text = posting(body)
    try:
        clean, clipped, extraction = read_job(text, llm, available)
    except JobTextError as e:
        raise JobRequestError(str(e)) from None
    ranking = rank(extraction, candidates(extraction))
    return {"job": {"source": source, "sample_id": sample_id, "chars": len(clean), "clipped": clipped}, "extraction": extraction.model_dump(),
            "ranking": [m.model_dump() for m in ranking], "recommended": ranking[0].scenario if ranking else None}


def resolve(body: JobBody, scenario: Scenario, rubric: Rubric) -> JobContext:
    """The context for a session of `scenario` started from this job. The reading that came back is checked against the posting; without one the keywords read it."""
    source, sample_id, text = posting(body)
    try:
        clean, clipped = prepare(text)
    except JobTextError as e:
        raise JobRequestError(str(e)) from None
    extraction: JobExtraction = revalidate(body.extraction, clean) if body.extraction else extract_keywords(clean, reason="read when the scenario started")
    try:
        return build_context(scenario=scenario, rubric=rubric, extraction=extraction, text=clean, clipped=clipped, source=source, sample_id=sample_id)  # type: ignore[arg-type]
    except JobError as e:
        raise JobRequestError(str(e)) from None
