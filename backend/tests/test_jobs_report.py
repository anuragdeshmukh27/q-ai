"""A report of a session started from a job description: the extra Role fit block, in JSON and markdown, and the proof that the standard score and every row are exactly what they were."""
import copy

import pytest

from app.scenarios import progress
from app.scenarios.jobs.adapt import build_context
from app.scenarios.jobs.extract import extract_keywords, prepare
from app.scenarios.jobs.report import attach_job, job_markdown
from app.scenarios.jobs.samples import sample_text
from app.scenarios.reports import History, render_markdown
from app.scenarios.rubric import load_rubric

from test_jobs_adapt import CRIT_NAMES, NAMES, REPORTS, SAMPLE, SCN, ctx_for, scores_of

IDS = list(SAMPLE)


def stripped(report: dict) -> dict:
    """The report without the job block and without the two fields the job adds to the last attempt record: what has to be identical to a report built without a job."""
    r = copy.deepcopy(report)
    r.pop("job", None)
    r["attempts"][-1].pop("role_fit", None)
    r["attempts"][-1].pop("job_role", None)
    return r


@pytest.mark.parametrize("sid", IDS)
@pytest.mark.parametrize("variant", ["strong", "weak"])
def test_the_standard_score_and_every_row_are_the_same_with_and_without_a_job(sid, variant):
    plain = REPORTS[(sid, variant)]
    before = copy.deepcopy(plain)
    ctx, _ = ctx_for(sid)
    with_job = attach_job(copy.deepcopy(plain), ctx)
    assert plain == before  # attaching worked on a copy
    assert stripped(with_job) == plain
    assert with_job["total"] == plain["total"] and [c["score"] for c in with_job["criteria"]] == [c["score"] for c in plain["criteria"]]
    assert with_job["rows"] == plain["rows"] and with_job["fairness"] == plain["fairness"] and with_job["focus"] == plain["focus"]


@pytest.mark.parametrize("sid", IDS)
def test_the_job_block_holds_what_was_asked_for(sid):
    ctx, _ = ctx_for(sid)
    r = attach_job(copy.deepcopy(REPORTS[(sid, "weak")]), ctx)
    j = r["job"]
    assert j["source"] == "sample" and j["sample_id"] == SAMPLE[sid] and j["text"] == prepare(sample_text(SAMPLE[sid]))[0]
    assert j["extraction"]["source"] == "keywords" and j["extraction"]["role_family"] == SCN[sid].role
    assert j["weights"] == ctx.weights and set(j["weight_reasons"]) == set(CRIT_NAMES) and j["key_skills"] == ctx.key_skills
    assert j["match"]["scenario"] == sid and j["match"]["rank"] == 1 and len(j["ranking"]) == 3
    assert j["standard_total"] == r["total"] and 0 <= j["role_fit"] <= 100 and j["briefing"]["source"] == "template"
    assert [c["weight"] for c in j["criteria"]] == [ctx.weights[c["id"]] for c in r["criteria"]]
    assert r["attempts"][-1]["role_fit"] == j["role_fit"] and r["attempts"][-1]["job_role"] == ctx.extraction.role


def test_role_fit_is_computed_from_the_stored_weights_and_scores():
    ctx, _ = ctx_for("opd-bookings-down")
    r = attach_job(copy.deepcopy(REPORTS[("opd-bookings-down", "weak")]), ctx)
    s = scores_of(r)
    expected = int(100 * sum(ctx.weights[c] * s[c] for c in s) / (4 * sum(ctx.weights[c] for c in s)) + 0.5)
    assert r["job"]["role_fit"] == expected
    assert attach_job(copy.deepcopy(REPORTS[("opd-bookings-down", "strong")]), ctx)["job"]["role_fit"] == 100


def test_the_markdown_has_a_role_fit_section_only_when_a_job_was_used():
    plain = REPORTS[("opd-bookings-down", "weak")]
    assert "Role fit" not in render_markdown(plain, NAMES) and job_markdown(plain) == []
    ctx, _ = ctx_for("opd-bookings-down")
    md = render_markdown(attach_job(copy.deepcopy(plain), ctx), NAMES)
    j = ctx.weights
    assert "## Role fit for this job" in md and f"**Role fit: " in md and f"your standard score, {plain['total']}/100, is the one that counts" in md
    assert "the bundled sample “backend-engineer”" in md and "Read by: keyword reader" in md and "Why this scenario:" in md
    for cid, name in CRIT_NAMES.items():
        assert f"| {name} | " in md and f"{j[cid]:.2f}" in md
    # everything of the plain markdown is still there, in the same order
    plain_md = render_markdown(plain, NAMES)
    head, tail = plain_md.split("## Fairness checks")
    assert md.startswith(head) and md.endswith("## Fairness checks" + tail)


def test_a_pasted_posting_is_described_as_pasted_with_its_length():
    s = SCN["opd-bookings-down"]
    text, _ = prepare(sample_text("backend-engineer"))
    ctx = build_context(scenario=s, rubric=load_rubric(s), extraction=extract_keywords(text), text=text, clipped=True, source="paste")
    md = "\n".join(job_markdown(attach_job(copy.deepcopy(REPORTS[("opd-bookings-down", "strong")]), ctx)))
    assert f"a pasted text ({len(text)} characters, cut at 5,000)" in md


def test_the_history_record_carries_role_fit_and_my_progress_shows_it_as_extra(tmp_path):
    ctx, _ = ctx_for("opd-bookings-down")
    r = attach_job(copy.deepcopy(REPORTS[("opd-bookings-down", "weak")]), ctx)
    History(tmp_path, "opd-bookings-down").add(r["attempts"][-1])
    History(tmp_path, "opd-double-bookings").add({**REPORTS[("opd-double-bookings", "weak")]["attempts"][-1]})
    p = progress.build_progress(tmp_path)
    one = next(s for s in p["scenarios"] if s["id"] == "opd-bookings-down")["attempts"][0]
    two = next(s for s in p["scenarios"] if s["id"] == "opd-double-bookings")["attempts"][0]
    assert one["total"] == 20 and one["role_fit"] == r["job"]["role_fit"] and one["job_role"] == ctx.extraction.role  # the score stays the main number
    assert "role_fit" not in two
    md = progress.render_markdown(p)
    assert f"20/100 (role fit {one['role_fit']} for {ctx.extraction.role})" in md and "30/100 |" in md
    assert next(s for s in p["scenarios"] if s["id"] == "opd-bookings-down")["best_score"] == 20
