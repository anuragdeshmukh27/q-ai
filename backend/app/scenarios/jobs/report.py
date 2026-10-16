"""The job description in a report: the extra "Role fit" block saved with an attempt (JSON and markdown). The standard score, the criteria and every row of the report are never touched:
role fit is the same criterion scores averaged with the weights of the posting, shown next to the standard score and labelled as extra."""
from __future__ import annotations

from .adapt import role_fit
from .schema import JobContext


def attach_job(report: dict, job: JobContext) -> dict:
    """Add `report["job"]` (and the attempt record's `role_fit`) for a session that was started from a job description. Returns the report."""
    crit = report["criteria"]
    top = crit[0]["max"] if crit else 4
    fit = role_fit({c["id"]: c["score"] for c in crit}, top, job.weights)
    e = job.extraction
    report["job"] = {
        "source": job.source, "sample_id": job.sample_id, "text": job.text, "clipped": job.clipped,
        "extraction": e.model_dump(), "match": job.match.model_dump(), "ranking": [{"scenario": m.scenario, "title": m.title, "score": m.score, "rank": m.rank} for m in job.ranking],
        "weights": job.weights, "weight_reasons": job.weight_reasons, "key_skills": job.key_skills, "briefing": job.briefing.model_dump(),
        "role_fit": fit, "standard_total": report["total"],
        "criteria": [{"id": c["id"], "name": c["name"], "score": c["score"], "max": c["max"], "weight": job.weights.get(c["id"], 1.0)} for c in crit],
    }
    if report.get("attempts"):
        report["attempts"][-1]["role_fit"] = fit
        report["attempts"][-1]["job_role"] = e.role
    return report


def reader_label(extraction: dict) -> str:
    return "AI (qwen2.5-coder:7b)" if extraction.get("source") == "model" else "keyword reader" + (f" ({extraction['reason']})" if extraction.get("reason") else "")


def job_markdown(report: dict) -> list[str]:
    """The lines of the "Role fit" section, or none for a report of a session that did not start from a job description."""
    j = report.get("job")
    if not j:
        return []
    e = j["extraction"]
    where = f"the bundled sample “{j['sample_id']}”" if j["source"] == "sample" else f"a pasted text ({len(j['text'])} characters{', cut at 5,000' if j.get('clipped') else ''})"
    lines = ["## Role fit for this job", "",
             f"**Role fit: {j['role_fit']}/{report['max']}**. This is an extra score: your standard score, {j['standard_total']}/{report['max']}, is the one that counts and is not changed by it. "
             "Role fit averages the same five criterion scores with the weights below, which come from what the job description asks for.", "",
             f"- Job description: {where}", f"- Read by: {reader_label(e)}", f"- Role: {e['role']} ({e['seniority']}), domain {e['domain']}",
             f"- Skills asked for: {', '.join(e['skills']) or 'none named'}", f"- Soft skills asked for: {', '.join(e['soft_skills']) or 'none named'}",
             f"- Why this scenario: {j['match']['reason']} ({j['match']['score']}/100, rank {j['match']['rank']} of {len(j['ranking'])})", "",
             "| Criterion | Score | Weight | Phrases of the job description |", "| --- | --- | --- | --- |"]
    for c in j["criteria"]:
        why = ", ".join(f"“{p}”" for p in j["weight_reasons"].get(c["id"], [])) or "none"
        lines.append(f"| {c['name']} | {c['score']}/{c['max']} | {c['weight']:.2f} | {why} |")
    return [*lines, ""]
