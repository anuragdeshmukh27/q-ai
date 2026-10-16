"""My progress: the learner's real attempts added up across scenarios (demo runs never count), the weakest skill with the gap quoted from a saved report, the suggested next step,
the exports and the reset, and the endpoints that serve them."""
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import load_agents
from app.scenarios.build import ScenarioBuild
from app.scenarios.loader import load_scenario
from app.scenarios.progress import build_progress, catalog, read_report, render_markdown, report_path
from app.scenarios.reports import History, build_report, write_report
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import score

from api_helpers import make_client
from scenario_fixtures import WEAK, WEAK_FACTS, facts

CRITERIA = [("communication", "Communication"), ("diagnosis", "Diagnosis"), ("fix_quality", "Fix quality"), ("testing", "Testing"), ("ownership", "Ownership")]
KEYS = [c for c, _ in CRITERIA]


def scn(sid, title, minutes=25):
    return {"id": sid, "title": title, "minutes": minutes, "max": 100, "per": 4, "criteria": [{"id": c, "name": n} for c, n in CRITERIA]}


A, B, C = scn("alpha", "Alpha incident", 25), scn("beta", "Beta incident", 30), scn("gamma", "Gamma incident", 25)


def rec(n, scores, date, elapsed, project=None, **extra):
    return {"attempt": n, "total": sum(scores) * 5, "scores": dict(zip(KEYS, scores)), "project": project or f"p-{n}", "finished_at": date, "elapsed": elapsed, **extra}


def write_history(ws: Path, sid: str, records: list, demo: bool = False):
    folder = ws / ".q-attempts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{sid}{'-demo' if demo else ''}.json").write_text(json.dumps(records), encoding="utf-8")


def write_saved_report(ws: Path, project: str, attempt: int, scenario: str, rows: list, kind: str = "learner"):
    folder = ws / project / ".q" / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"attempt-{attempt}.json").write_text(json.dumps({"scenario": scenario, "attempt": attempt, "kind": kind, "rows": rows}), encoding="utf-8")


def gap_row(rid, criterion, t, quote, note="A gap.", advice="Do better.", source="#incident"):
    return {"id": rid, "criterion": criterion, "kind": "gap", "t": t, "quote": quote, "note": note, "advice": advice, "source": source, "event": "E001"}


# alpha: 3 attempts; beta: 1 attempt, later; gamma: none
ALPHA = [rec(1, [2, 2, 3, 1, 2], "2026-10-12T20:00:00", 900), rec(2, [3, 3, 4, 3, 3], "2026-10-12T21:00:00", 400), rec(3, [4, 3, 4, 4, 4], "2026-10-12T22:00:00", 300)]
BETA = [rec(1, [1, 3, 3, 2, 2], "2026-10-13T09:00:00", 600, project="beta-1")]


@pytest.fixture
def ws(tmp_path):
    p = tmp_path / "ws"
    write_history(p, "alpha", ALPHA)
    write_history(p, "beta", BETA)
    return p


def skill(p, sid):
    return next(k for k in p["skills"] if k["id"] == sid)


# -- aggregation ---------------------------------------------------------------------------------------------------

def test_scenarios_list_attempts_with_best_score_and_best_time(ws):
    p = build_progress(ws, [A, B, C])
    assert [s["id"] for s in p["scenarios"]] == ["alpha", "beta", "gamma"]
    a, b, c = p["scenarios"]
    assert [x["attempt"] for x in a["attempts"]] == [1, 2, 3]
    assert [x["total"] for x in a["attempts"]] == [50, 80, 95]
    assert a["attempts"][0] == {"attempt": 1, "total": 50, "max": 100, "scores": dict(zip(KEYS, [2, 2, 3, 1, 2])), "date": "2026-10-12T20:00:00", "elapsed": 900.0, "project": "p-1"}
    assert (a["count"], a["best_score"], a["best_time"], a["last_total"]) == (3, 95, 300.0, 95)
    assert (b["count"], b["best_score"], b["best_time"]) == (1, 55, 600.0)
    assert (c["count"], c["best_score"], c["best_time"], c["last_total"], c["attempts"]) == (0, None, None, None, [])
    assert p["attempts_total"] == 4 and p["empty"] is False


def test_best_time_is_not_the_time_of_the_best_score(ws):
    a = build_progress(ws, [A])["scenarios"][0]
    assert a["best_score"] == 95 and a["best_time"] == 300.0
    write_history(ws, "alpha", ALPHA + [rec(4, [4, 4, 4, 4, 4], "2026-10-14T10:00:00", 1200)])
    a = build_progress(ws, [A])["scenarios"][0]
    assert a["best_score"] == 100 and a["best_time"] == 300.0  # the fastest attempt is still attempt 3


def test_skills_across_scenarios_latest_average_and_trend(ws):
    p = build_progress(ws, [A, B, C])
    assert [k["id"] for k in p["skills"]] == KEYS and [k["name"] for k in p["skills"]][0] == "Communication"
    comm = skill(p, "communication")  # alpha 2, 3, 4 then beta 1 (the newest attempt is beta's)
    assert (comm["latest"], comm["average"], comm["count"], comm["trend"]) == (1, 2.5, 4, "down")
    diag = skill(p, "diagnosis")  # 2, 3, 3, 3: the latest is 0.33 above the average of the earlier ones
    assert (diag["latest"], diag["average"], diag["trend"]) == (3, 2.75, "steady")
    assert skill(p, "fix_quality")["average"] == 3.5


def test_trend_up_down_steady_and_new(tmp_path):
    def trend(scores):
        write_history(tmp_path, "alpha", [rec(i + 1, [s] * 5, f"2026-10-{10 + i}T10:00:00", 100) for i, s in enumerate(scores)])
        return skill(build_progress(tmp_path, [A]), "testing")["trend"]
    assert trend([2]) == "new"
    assert trend([2, 2, 3]) == "up"  # 3 against 2.0
    assert trend([2, 3]) == "up"
    assert trend([2, 3, 3]) == "up"  # 3 against 2.5: exactly half a point counts as a move
    assert trend([3, 4, 3]) == "down"  # 3 against 3.5
    assert trend([3, 3, 1]) == "down"
    assert trend([3, 3, 3]) == "steady"
    assert trend([2, 2, 3, 2]) == "steady"  # 2 against 2.33


def test_latest_follows_the_clock_not_the_scenario_order(tmp_path):
    write_history(tmp_path, "alpha", [rec(1, [1, 1, 1, 1, 1], "2026-10-20T10:00:00", 1)])  # the later one, in the first scenario
    write_history(tmp_path, "beta", [rec(1, [4, 4, 4, 4, 4], "2026-10-10T10:00:00", 1)])
    k = skill(build_progress(tmp_path, [A, B]), "testing")
    assert k["latest"] == 1 and k["trend"] == "down"


# -- demos and bad files never count ------------------------------------------------------------------------------

def test_demo_attempts_are_excluded(ws):
    write_history(ws, "alpha", [dict(r, kind="demo", variant="strong") if r["attempt"] == 3 else r for r in ALPHA])  # a demo record in the learner's file
    write_history(ws, "alpha", [rec(1, [4] * 5, "2026-10-30T10:00:00", 50, kind="demo", variant="strong")], demo=True)  # the demo history file
    write_history(ws, "gamma", [rec(1, [4] * 5, "2026-10-30T10:00:00", 50, kind="demo", variant="strong")], demo=True)
    p = build_progress(ws, [A, B, C])
    assert [x["attempt"] for x in p["scenarios"][0]["attempts"]] == [1, 2]
    assert p["scenarios"][2]["count"] == 0 and p["attempts_total"] == 3
    assert skill(p, "testing")["latest"] == 2  # beta's is the newest real one


def test_only_demo_history_is_an_empty_progress(tmp_path):
    write_history(tmp_path, "alpha", [rec(1, [4] * 5, "2026-10-30T10:00:00", 50, kind="demo")], demo=True)
    p = build_progress(tmp_path, [A, B])
    assert p["empty"] is True and p["attempts_total"] == 0 and p["weakest"] is None and p["next_step"] is None


def test_empty_history(tmp_path):
    p = build_progress(tmp_path / "nothing", [A, B, C])
    assert p["empty"] and p["attempts_total"] == 0
    assert [(s["count"], s["best_score"], s["best_time"]) for s in p["scenarios"]] == [(0, None, None)] * 3
    assert all(k["latest"] is None and k["average"] is None and k["trend"] == "none" for k in p["skills"]) and len(p["skills"]) == 5
    assert "No real attempts yet" in render_markdown(p)


def test_damaged_and_odd_records_are_skipped(tmp_path):
    (tmp_path / ".q-attempts").mkdir(parents=True)
    (tmp_path / ".q-attempts" / "alpha.json").write_text("{not json", encoding="utf-8")
    assert build_progress(tmp_path, [A])["empty"]
    write_history(tmp_path, "alpha", [{"attempt": 1, "total": "x", "scores": {}}, {"attempt": 2, "total": 50}, "junk", rec(3, [2] * 5, "2026-10-10T10:00:00", 5)])
    p = build_progress(tmp_path, [A])
    assert [x["attempt"] for x in p["scenarios"][0]["attempts"]] == [3]


# -- the weakest skill and its quote -------------------------------------------------------------------------------

def test_weakest_is_the_lowest_average_and_a_tie_goes_to_the_lower_latest_score(ws):
    p = build_progress(ws, [A, B, C])
    # communication and testing both average 2.5; communication's latest score (1) is lower than testing's (2)
    assert (skill(p, "communication")["average"], skill(p, "testing")["average"]) == (2.5, 2.5)
    w = p["weakest"]
    assert (w["skill"], w["name"], w["average"], w["latest"], w["max"]) == ("communication", "Communication", 2.5, 1, 4)


def test_a_full_tie_goes_to_the_rubric_order(tmp_path):
    write_history(tmp_path, "alpha", [rec(1, [3] * 5, "2026-10-10T10:00:00", 10)])
    assert build_progress(tmp_path, [A])["weakest"]["skill"] == "communication"


def test_nothing_is_weak_when_every_attempt_has_full_marks(tmp_path):
    write_history(tmp_path, "alpha", [rec(1, [4] * 5, "2026-10-10T10:00:00", 10), rec(2, [4] * 5, "2026-10-11T10:00:00", 9)])
    p = build_progress(tmp_path, [A])
    assert p["weakest"] is None
    assert "None: every skill is at full marks." in render_markdown(p)


def test_the_gap_is_quoted_from_the_newest_real_report_exactly_as_saved(ws):
    quote = 'Update: "call()" only throws when there is no JSON body… & more'
    write_saved_report(ws, "p-3", 3, "alpha", [gap_row("R01", "communication", 130.0, "old quote")])  # alpha attempt 3 (older)
    write_saved_report(ws, "beta-1", 1, "beta", [gap_row("R07", "testing", 50, "wrong criterion"), gap_row("R02", "communication", 315.9, quote, "Your first update came at 05:15.", "Post sooner.", "#incident-beta · You"),
                                              gap_row("R03", "communication", 400, "a later gap of the same skill")])
    g = build_progress(ws, [A, B, C])["weakest"]["gap"]
    assert g == {"scenario": "beta", "title": "Beta incident", "attempt": 1, "row": "R02", "t": 315.9, "clock": "05:15", "source": "#incident-beta · You", "quote": quote,
                 "note": "Your first update came at 05:15.", "advice": "Post sooner."}  # beta's report is the newest; its first gap of the skill, character for character


def test_a_missing_or_gapless_newest_report_falls_back_to_the_one_before(ws):
    write_saved_report(ws, "beta-1", 1, "beta", [{"id": "R01", "criterion": "communication", "kind": "strength", "t": 1, "quote": "fine"}])  # newest: no gap for the skill
    write_saved_report(ws, "p-2", 2, "alpha", [gap_row("R04", "communication", 70, "the older gap")])
    g = build_progress(ws, [A, B, C])["weakest"]["gap"]
    assert (g["scenario"], g["attempt"], g["quote"]) == ("alpha", 2, "the older gap")


def test_no_report_on_disk_says_why_instead_of_inventing_a_quote(ws):
    w = build_progress(ws, [A, B, C])["weakest"]
    assert w["gap"] is None and "Communication" in w["reason"] and "deleted" in w["reason"]
    assert w["reason"] in render_markdown(build_progress(ws, [A, B, C]))


def test_a_demo_report_is_never_quoted(ws):
    write_saved_report(ws, "beta-1", 1, "beta", [gap_row("R01", "communication", 9, "a demo's gap")], kind="demo")
    assert build_progress(ws, [A, B, C])["weakest"]["gap"] is None


def test_a_report_of_another_attempt_or_scenario_is_not_used(ws):
    write_saved_report(ws, "beta-1", 1, "alpha", [gap_row("R01", "communication", 9, "not beta's")])  # the file says alpha, the history says beta
    assert build_progress(ws, [A, B, C])["weakest"]["gap"] is None


@pytest.mark.parametrize("project", ["../outside", "..", ".", "a/b", "a\\b", "/abs", "", "C:\\x", ".hidden/../x"])
def test_a_project_name_cannot_leave_the_workspace(tmp_path, project):
    ws = tmp_path / "ws"
    write_history(ws, "alpha", [rec(1, [1, 4, 4, 4, 4], "2026-10-10T10:00:00", 5, project=project)])
    (tmp_path / "outside" / ".q" / "reports").mkdir(parents=True)
    (tmp_path / "outside" / ".q" / "reports" / "attempt-1.json").write_text(json.dumps({"scenario": "alpha", "attempt": 1, "rows": [gap_row("R01", "communication", 1, "outside!")]}), encoding="utf-8")
    assert report_path(ws, project, 1) is None
    assert build_progress(ws, [A])["weakest"]["gap"] is None


# -- the suggested next step ---------------------------------------------------------------------------------------

def test_retry_the_scenario_whose_last_attempt_was_weakest_on_the_skill(ws):
    n = build_progress(ws, [A, B, C])["next_step"]
    assert (n["kind"], n["scenario"], n["skill"]) == ("retry", "beta", "communication")  # alpha's last communication was 4, beta's was 1
    assert n["reason"] == "Retry Beta incident: your last attempt there scored 1/4 on Communication, the lowest of your latest attempts, and Communication is your weakest skill (average 2.5/4)."


def test_try_a_new_scenario_when_no_last_attempt_is_weak(tmp_path):
    write_history(tmp_path, "alpha", ALPHA)  # last attempt 4, 3, 4, 4, 4: diagnosis is weakest (average 2.7) and its last score is 3
    n = build_progress(tmp_path, [A, B, C])["next_step"]
    assert (n["kind"], n["scenario"], n["skill"]) == ("new", "beta", "diagnosis")
    assert n["reason"] == "Try Beta incident: you have not attempted it yet, and Diagnosis is your weakest skill (average 2.7/4)."


def test_a_weak_last_score_beats_an_unattempted_scenario(tmp_path):
    write_history(tmp_path, "alpha", [rec(1, [4, 4, 4, 2, 4], "2026-10-10T10:00:00", 100)])
    n = build_progress(tmp_path, [A, B])["next_step"]
    assert (n["kind"], n["scenario"]) == ("retry", "alpha") and "scored 2/4 on Testing" in n["reason"]


def test_retry_when_everything_is_attempted_and_the_last_score_is_not_full(tmp_path):
    write_history(tmp_path, "alpha", [rec(1, [3] * 5, "2026-10-10T10:00:00", 100)])
    write_history(tmp_path, "beta", [rec(1, [3, 3, 3, 3, 4], "2026-10-11T10:00:00", 100)])
    n = build_progress(tmp_path, [A, B])["next_step"]
    assert n["kind"] == "retry" and n["scenario"] == "alpha"  # communication is weakest; both last scores are 3; alpha has the lower total


def test_the_lowest_last_score_wins_among_scenarios(tmp_path):
    write_history(tmp_path, "alpha", [rec(1, [4, 4, 4, 1, 4], "2026-10-10T10:00:00", 100)])
    write_history(tmp_path, "beta", [rec(1, [4, 4, 4, 0, 4], "2026-10-11T10:00:00", 100)])
    assert build_progress(tmp_path, [A, B, C])["next_step"]["scenario"] == "beta"


def test_full_marks_everywhere_suggests_beating_the_best_time(tmp_path):
    write_history(tmp_path, "alpha", [rec(1, [4] * 5, "2026-10-10T10:00:00", 300)])  # 300 s of 25 min
    write_history(tmp_path, "beta", [rec(1, [4] * 5, "2026-10-11T10:00:00", 900)])  # 900 s of 30 min: closer to its time box
    n = build_progress(tmp_path, [A, B])["next_step"]
    assert (n["kind"], n["scenario"]) == ("beat", "beta")
    assert n["reason"] == "Every skill is at full marks; beat your best time of 15:00 on Beta incident."


def test_full_marks_with_a_scenario_still_to_try(tmp_path):
    write_history(tmp_path, "alpha", [rec(1, [4] * 5, "2026-10-10T10:00:00", 300)])
    n = build_progress(tmp_path, [A, B])["next_step"]
    assert (n["kind"], n["scenario"]) == ("new", "beta") and "every skill is at full marks so far" in n["reason"]


# -- export ---------------------------------------------------------------------------------------------------------

def test_markdown_has_the_same_numbers_as_the_data(ws):
    write_saved_report(ws, "beta-1", 1, "beta", [gap_row("R02", "communication", 315.9, "Update: call() is wrong", "Your first update came at 05:15.", "Post sooner.")])
    p = build_progress(ws, [A, B, C])
    md = render_markdown(p)
    assert "# My progress" in md and "4 real attempts" in md
    for s in p["scenarios"]:
        assert f"### {s['title']}" in md
    assert "Not attempted yet." in md  # gamma
    assert "| 3 | 95/100 | 2026-10-12 22:00:00 | 05:00 |" in md  # an attempt row: score, date, time
    assert "Best score 95/100 · best time 05:00" in md
    assert "| Communication | 1/4 | 2.5/4 | down |" in md
    assert "**Communication** (average 2.5/4, latest 1/4)" in md
    assert "Beta incident attempt 1 at 05:15: “Update: call() is wrong”" in md
    assert p["next_step"]["reason"] in md


# -- the real report shape ------------------------------------------------------------------------------------------

def test_the_quote_of_a_real_saved_report_is_returned_as_the_report_has_it(tmp_path):
    """A report written by the debrief's own code (a weak session) is read back: the weakest skill's gap is that report's own row."""
    sc = load_scenario("opd-bookings-down")
    rubric = load_rubric(sc)
    names = {a.id: a.name for a in load_agents().values()}
    f = facts(WEAK, WEAK_FACTS)
    rep = build_report(scenario=sc, rubric=rubric, attempt=1, project="opd-bookings-down-9", facts=f, results=score(rubric, f), names=names, finished_at=1_760_000_000)
    ws = tmp_path / "ws"
    write_report(ws / "opd-bookings-down-9", rep, names)
    History(ws, sc.id).add(rep["attempts"][-1])
    p = build_progress(ws)
    mine = next(s for s in p["scenarios"] if s["id"] == sc.id)
    assert p["attempts_total"] == 1 and mine["attempts"][0]["total"] == rep["total"]
    worst = min(rep["criteria"], key=lambda c: (c["score"], [x["id"] for x in rep["criteria"]].index(c["id"])))
    w = p["weakest"]
    assert w["skill"] == worst["id"] and w["average"] == worst["score"]
    row = next(r for r in rep["rows"] if r["criterion"] == worst["id"] and r["kind"] == "gap")
    assert (w["gap"]["quote"], w["gap"]["note"], w["gap"]["advice"], w["gap"]["t"], w["gap"]["row"]) == (row["quote"], row["note"], row["advice"], row["t"], row["id"])
    assert re.fullmatch(r"\d{2}:\d{2}", w["gap"]["clock"])
    assert read_report(ws, "opd-bookings-down-9", 1, sc.id)["total"] == rep["total"]


def test_the_catalog_has_the_shipped_scenarios_with_the_same_five_skills():
    cat = catalog()
    assert len(cat) >= 3
    assert all([c["id"] for c in s["criteria"]] == KEYS for s in cat)


# -- the endpoints --------------------------------------------------------------------------------------------------

REAL = ["opd-bookings-down", "opd-double-bookings", "opd-form-says-saved"]


@pytest.fixture
def api(tmp_path):
    client, settings, mgr = make_client(tmp_path)
    ws = settings.workspace
    write_history(ws, REAL[0], [rec(1, [2, 2, 3, 1, 2], "2026-10-12T20:00:00", 900, project="opd-bookings-down-2"), rec(2, [4, 3, 4, 4, 4], "2026-10-12T22:00:00", 300, project="opd-bookings-down-3")])
    write_history(ws, REAL[1], [rec(1, [1, 3, 3, 2, 2], "2026-10-13T09:00:00", 600, project="opd-double-bookings-2")])
    write_history(ws, REAL[0], [rec(1, [4] * 5, "2026-10-30T10:00:00", 50, kind="demo", variant="strong")], demo=True)
    write_history(ws, REAL[2], [rec(1, [4] * 5, "2026-10-30T10:00:00", 50, kind="demo", variant="weak")], demo=True)
    return client, settings, mgr


def test_endpoint_returns_everything_the_page_shows(api):
    client, _, _ = api
    r = client.get("/api/progress")
    assert r.status_code == 200
    p = r.json()
    assert set(p) == {"version", "generated_at", "empty", "attempts_total", "scenarios", "skills", "weakest", "next_step"}
    assert p["attempts_total"] == 3 and [s["id"] for s in p["scenarios"]] == REAL and p["scenarios"][2]["count"] == 0  # the demos did not count
    assert [k["id"] for k in p["skills"]] == KEYS
    assert p["weakest"]["skill"] == "communication" and p["next_step"]["kind"] == "retry"


def test_endpoint_with_no_history_is_the_empty_state(tmp_path):
    client, _, _ = make_client(tmp_path)
    p = client.get("/api/progress").json()
    assert p["empty"] is True and p["attempts_total"] == 0 and len(p["scenarios"]) >= 3 and p["weakest"] is None


def test_export_downloads_the_same_data_as_markdown_and_json(api):
    client, _, _ = api
    data = client.get("/api/progress").json()
    js = client.get("/api/progress/export", params={"format": "json"})
    assert js.status_code == 200 and 'attachment; filename="q-progress.json"' in js.headers["content-disposition"]
    got = json.loads(js.text)
    assert {k: v for k, v in got.items() if k != "generated_at"} == {k: v for k, v in data.items() if k != "generated_at"}
    md = client.get("/api/progress/export", params={"format": "md"})
    assert md.status_code == 200 and 'attachment; filename="q-progress.md"' in md.headers["content-disposition"] and md.headers["content-type"].startswith("text/markdown")
    assert md.text.splitlines()[0] == "# My progress" and data["next_step"]["reason"] in md.text
    assert client.get("/api/progress/export", params={"format": "pdf"}).status_code == 400


def test_report_endpoint_serves_a_real_attempts_saved_report(api):
    client, settings, _ = api
    write_saved_report(settings.workspace, "opd-bookings-down-3", 2, REAL[0], [gap_row("R01", "testing", 3, "q")])
    folder = settings.workspace / "opd-bookings-down-3" / ".q" / "reports"
    (folder / "attempt-2.md").write_text("# Debrief: saved", encoding="utf-8")
    r = client.get(f"/api/progress/report/{REAL[0]}/2")
    assert r.status_code == 200 and r.json()["rows"][0]["quote"] == "q"
    assert client.get(f"/api/progress/report/{REAL[0]}/2", params={"format": "md"}).text == "# Debrief: saved"
    assert client.get(f"/api/progress/report/{REAL[0]}/2", params={"format": "x"}).status_code == 400


def test_report_endpoint_refuses_what_is_not_a_real_attempt(api):
    client, settings, _ = api
    assert client.get(f"/api/progress/report/{REAL[0]}/7").status_code == 404  # no such attempt
    assert client.get(f"/api/progress/report/{REAL[0]}/1").status_code == 404  # in the history, but its folder is gone
    assert client.get("/api/progress/report/nope/1").status_code == 404
    write_saved_report(settings.workspace, "opd-bookings-down-2", 1, REAL[0], [], kind="demo")
    assert client.get(f"/api/progress/report/{REAL[0]}/1").status_code == 404  # a demo's report is never served
    write_history(settings.workspace, REAL[2], [rec(1, [4] * 5, "2026-10-30T10:00:00", 50, project="x-demo", kind="demo")], demo=True)
    write_saved_report(settings.workspace, "x-demo", 1, REAL[2], [])
    assert client.get(f"/api/progress/report/{REAL[2]}/1").status_code == 404  # only in the demo history


# -- reset ------------------------------------------------------------------------------------------------------------

def test_reset_clears_the_learners_history_and_nothing_else(api):
    client, settings, _ = api
    ws = settings.workspace
    write_saved_report(ws, "opd-bookings-down-3", 2, REAL[0], [gap_row("R01", "testing", 3, "q")])
    recording = settings.recordings / "simulation-bookings-down-strong"
    recording.mkdir(parents=True)
    (recording / "meta.json").write_text("{}", encoding="utf-8")
    before_demo = {p.name: p.read_text(encoding="utf-8") for p in (ws / ".q-attempts").glob("*-demo.json")}
    assert len(before_demo) == 2
    r = client.delete("/api/progress")
    assert r.status_code == 200 and r.json() == {"cleared": 2}
    assert sorted(p.name for p in (ws / ".q-attempts").glob("*.json")) == sorted(before_demo)  # the demo history files stay
    assert {p.name: p.read_text(encoding="utf-8") for p in (ws / ".q-attempts").glob("*-demo.json")} == before_demo
    assert (ws / "opd-bookings-down-3" / ".q" / "reports" / "attempt-2.json").is_file()  # saved reports stay
    assert (recording / "meta.json").is_file()  # recordings stay
    assert client.get("/api/progress").json()["empty"] is True
    assert History(ws, REAL[0], "demo").attempts() != [] and History(ws, REAL[0]).next_number() == 1  # numbering starts again; demos are as they were
    assert client.delete("/api/progress").json() == {"cleared": 0}  # twice is fine


def test_reset_on_a_fresh_workspace(tmp_path):
    client, _, _ = make_client(tmp_path)
    assert client.delete("/api/progress").json() == {"cleared": 0}


def test_reset_waits_for_a_debrief_that_is_still_writing_the_history(api):
    client, settings, mgr = api
    release = threading.Event()
    thread = threading.Thread(target=release.wait, daemon=True)
    thread.start()
    orch = object.__new__(ScenarioBuild)
    orch.debrief = SimpleNamespace(_thread=thread)
    mgr.sessions["fake"] = SimpleNamespace(orch=orch)
    try:
        r = client.delete("/api/progress")
        assert r.status_code == 409 and "debrief" in r.json()["detail"]
        assert (settings.workspace / ".q-attempts" / f"{REAL[0]}.json").is_file()  # nothing was removed
    finally:
        release.set()
        thread.join(5)
    assert client.delete("/api/progress").json()["cleared"] == 2


def test_clear_learner_leaves_unrelated_files_alone(tmp_path):
    (tmp_path / ".q-attempts").mkdir()
    for name in ("alpha.json", "alpha-demo.json", "notes.txt"):
        (tmp_path / ".q-attempts" / name).write_text("[]", encoding="utf-8")
    assert History.clear_learner(tmp_path) == 1
    assert sorted(p.name for p in (tmp_path / ".q-attempts").iterdir()) == ["alpha-demo.json", "notes.txt"]
    assert History.clear_learner(tmp_path / "missing") == 0
