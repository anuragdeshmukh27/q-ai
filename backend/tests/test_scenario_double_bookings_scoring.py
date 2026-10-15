"""The rubric of "Double bookings": its rules over a strong and a weak session, the measure that tries the learner's migration on the production snapshot, and the report built from them."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.config import load_agents
from app.scenarios.loader import SCENARIOS_DIR, load_scenario
from app.scenarios.measures import double_bookings
from app.scenarios.reports import build_report
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import Facts, event_text, score

from scenario_fixtures import make_log
from scenario_fixtures_double import MEASURED_OK, NEW, M0006, REGRESSION, SNAPSHOT, STRONG, STRONG_FACTS, STRONG_SCORES, WEAK, WEAK_FACTS, WEAK_SCORES, facts

ID = "opd-double-bookings"
SCN = load_scenario(ID)
RUBRIC = load_rubric(SCN)
NAMES = {a.id: a.name for a in load_agents().values()}
SEED = SCN.seed_dir
NAIVE = Path(__file__).parent / "scenario_fixes" / "double-bookings"
REFERENCE = SCN.folder / "autoplay" / "0008_one_booking_per_slot.sql"


def scores(f: Facts) -> dict:
    return {r.id: r.score for r in score(RUBRIC, f)}


def finding(f: Facts, rule: str):
    return next(x for r in score(RUBRIC, f) for x in r.findings if x.rule == rule)


def test_the_rubric_has_the_same_five_criteria_with_rohan_judging_the_diagnosis():
    assert RUBRIC.id == SCN.rubric == "opd-double-bookings-v1" and RUBRIC.max_total == 100
    assert [(c.name, NAMES[c.judge]) for c in RUBRIC.criteria] == [("Communication", "Aarav"), ("Diagnosis", "Rohan"), ("Fix quality", "Vikram"), ("Testing", "Ananya"), ("Ownership", "Aarav")]
    assert [[r.id for r in c.rules] for c in RUBRIC.criteria][2] == ["no_row_deleted", "duplicates_resolved", "partial_index_present", "suite_green_on_main"]
    assert all(len(c.rules) == 4 and sorted(c.descriptors) == ["0", "1", "2", "3", "4"] for c in RUBRIC.criteria)


def test_a_strong_run_scores_every_point_and_the_log_has_no_scan_of_an_old_name():
    f = facts(STRONG, STRONG_FACTS)
    assert scores(f) == STRONG_SCORES and sum(scores(f).values()) * RUBRIC.weight == 100
    findings = [x for r in score(RUBRIC, f) for x in r.findings]
    assert len(findings) == 20 and all(x.kind == "strength" and x.advice == "" for x in findings)
    assert [e["check"] for e in f.log if e["kind"] == "debrief_check"] == ["rerun", "regression", "change", "counts", "rows_kept", "duplicates", "unique_index"]


def test_a_weak_run_scores_35_and_every_gap_cites_a_real_entry():
    f = facts(WEAK, WEAK_FACTS)
    assert scores(f) == WEAK_SCORES and sum(scores(f).values()) * RUBRIC.weight == 35
    log = {e["id"] for e in f.log}
    for r in score(RUBRIC, f):
        for x in r.findings:
            assert x.events and set(x.events) <= log
            assert (x.kind == "gap") == bool(x.advice)


def test_each_new_rule_cites_the_entry_that_proves_it():
    strong, weak = facts(STRONG, STRONG_FACTS), facts(WEAK, WEAK_FACTS)
    by = lambda f, kind, **m: next(e for e in f.log if e["kind"] == kind and all(e.get(k) == v for k, v in m.items()))  # noqa: E731
    assert finding(strong, "looked_at_the_data").events[0] == by(strong, "file_opened", path=SNAPSHOT)["id"]
    assert finding(strong, "found_the_missing_constraint").events[0] == by(strong, "file_opened", path=M0006)["id"]
    assert finding(strong, "no_row_deleted").events[0] == strong.check("rows_kept")["id"]
    assert finding(strong, "partial_index_present").events[0] == strong.check("unique_index")["id"]
    assert finding(strong, "regression_test_added").events[0] == by(strong, "file_saved", path=REGRESSION)["id"]
    assert finding(weak, "names_the_cause").kind == "strength" and finding(weak, "first_update").kind == "gap"
    assert finding(weak, "looked_at_the_data").text == "By your first edit at 00:40 you had not opened the production data."
    assert finding(weak, "no_pointer_needed").events[0] == by(weak, "hint_given", n=1)["id"]


def test_a_search_for_the_duplicates_counts_as_looking_at_the_data_and_the_constraint():
    steps = [s for s in STRONG if s[1] != "file_opened"] + [(36, "search", {"role": "database", "query": "duplicate", "matches": 2, "files": 1})]
    steps.sort(key=lambda s: s[0])
    f = facts(steps, STRONG_FACTS)
    assert finding(f, "looked_at_the_data").kind == "strength" and "searched the project for “duplicate”" in finding(f, "looked_at_the_data").text
    assert finding(f, "found_the_missing_constraint").kind == "strength"  # the earlier search for UNIQUE
    late = [(t + 200 if k == "file_opened" else t, k, v) for t, k, v in STRONG if k != "search"]
    late.sort(key=lambda s: s[0])
    assert finding(facts(late, STRONG_FACTS), "looked_at_the_data").kind == "gap"  # opened after the first save


def test_the_pointer_is_not_held_against_a_learner_who_had_opened_the_migration_first():
    steps = [*STRONG, (240, "hint_given", {"message": "C9", "from": "backend", "source": "scripted", "reason": "timeline", "question": "", "text": "Look at 0006.", "n": 1})]
    steps.sort(key=lambda s: s[0])
    assert finding(facts(steps, STRONG_FACTS), "no_pointer_needed").kind == "strength"  # 0006 was opened at 55 s
    weak_steps = sorted([*WEAK, (250, "file_opened", {"role": "database", "path": M0006})], key=lambda s: s[0])
    assert finding(facts(weak_steps, WEAK_FACTS), "no_pointer_needed").kind == "gap"  # opened after the pointer


# -- the measure: the learner's migration tried on the production snapshot -----------------------------------------

def project_with(tmp_path: Path, migration: Path | None) -> Path:
    root = tmp_path / "merged"
    shutil.copytree(SEED / "database" / "migrations", root / "database" / "migrations")
    if migration is not None:
        shutil.copyfile(migration, root / "database" / "migrations" / "0008_x.sql")
    return root


def measured(tmp_path, migration: Path | None) -> dict:
    return double_bookings(project_with(tmp_path, migration), SEED, {})


def test_the_reference_migration_passes_all_three_measures(tmp_path):
    m = measured(tmp_path, REFERENCE)
    assert {k: v["ok"] for k, v in m.items()} == {"rows_kept": True, "duplicates": True, "unique_index": True}
    assert m["rows_kept"]["text"] == "Debrief upgrade of the production snapshot: 30 of 30 appointments are still there"
    assert m["duplicates"]["text"] == "Debrief check of the 3 double-booked slots: 3 keep their earliest booking, 3 of 3 later bookings are cancelled, 3 of 3 say why"
    assert m["unique_index"]["partial"] and m["unique_index"]["refuses_second_booked"] and m["unique_index"]["allows_cancelled"]
    assert m["unique_index"]["text"] == MEASURED_OK["unique_index"]["text"]  # the fixtures say what the real measure says


NAIVE_RESULTS = [
    # name: (rows_kept ok, duplicates ok, index ok)
    ("naive_delete", (False, False, True)),
    ("naive_index_only", (False, False, False)),  # the upgrade fails on the data
    ("naive_full_unique", (False, False, False)),  # the upgrade fails on the cancelled twins
    ("naive_no_reason", (True, False, True)),
    ("naive_no_index", (True, True, False)),
]


@pytest.mark.parametrize("name,expected", NAIVE_RESULTS, ids=[n for n, _ in NAIVE_RESULTS])
def test_every_naive_migration_fails_the_measure_that_names_its_mistake(tmp_path, name, expected):
    m = measured(tmp_path, NAIVE / f"{name}.sql")
    assert (m["rows_kept"]["ok"], m["duplicates"]["ok"], m["unique_index"]["ok"]) == expected, {k: v["text"] for k, v in m.items()}


def test_the_measure_says_what_went_wrong_in_the_entry_a_point_quotes(tmp_path):
    deleted = measured(tmp_path, NAIVE / "naive_delete.sql")
    assert "(deleted: 19, 24, 27)" in deleted["rows_kept"]["text"] or "deleted:" in deleted["rows_kept"]["text"]
    assert deleted["rows_kept"]["lost"] and not deleted["rows_kept"]["error"]
    index_only = measured(tmp_path / "b", NAIVE / "naive_index_only.sql")
    assert "your migration failed (IntegrityError: UNIQUE constraint failed" in index_only["rows_kept"]["text"]
    plain = measured(tmp_path / "c", NAIVE / "naive_no_reason.sql")
    assert plain["duplicates"]["reasons"] == 0 and plain["duplicates"]["cancelled"] == 3 and "0 of 3 say why" in plain["duplicates"]["text"]
    no_index = measured(tmp_path / "d", NAIVE / "naive_no_index.sql")
    assert no_index["unique_index"]["text"] == "Debrief check of the index: there is no unique index over doctor_id, date and slot_at"
    seed = measured(tmp_path / "e", None)
    assert seed["duplicates"]["still_double"] and "a slot still holds two Booked appointments" in seed["duplicates"]["text"]


def test_a_learner_cannot_change_the_data_the_measure_runs_on(tmp_path):
    """Edits to migrations 0001 to 0007 or to the snapshot in the merged project are ignored: the measure builds the production database from the seed."""
    root = project_with(tmp_path, REFERENCE)
    (root / "database" / "migrations" / "0002_create_appointments.sql").write_text("-- emptied\n", encoding="utf-8")
    assert all(v["ok"] for v in double_bookings(root, SEED, {}).values())


def test_a_migration_that_is_missing_or_cannot_be_measured_is_a_gap_not_a_guess():
    f = Facts(make_log(STRONG), scan=None, rerun=None)  # no measurement at all
    for rule in ("no_row_deleted", "duplicates_resolved", "partial_index_present"):
        x = finding(f, rule)
        assert x.kind == "gap" and x.text == "Q could not try your migration on the production snapshot." and x.events


FIX_QUALITY = [
    ("naive_delete", 2),  # the index is there and the suite is green, but rows were deleted and the duplicates are not resolved
    ("naive_index_only", 1),  # the migration fails on the data: only the green re-run is left
    ("naive_no_reason", 3),
    ("naive_no_index", 3),
]


@pytest.mark.parametrize("name,points", FIX_QUALITY, ids=[n for n, _ in FIX_QUALITY])
def test_fix_quality_follows_the_measure(tmp_path, name, points):
    f = Facts(make_log(STRONG), scan=None, measured=measured(tmp_path, NAIVE / f"{name}.sql"), rerun={"ok": True, "passed": 111, "failed": 0}, regression=STRONG_FACTS["regression"])
    assert scores(f)["fix_quality"] == points


# -- the report ------------------------------------------------------------------------------------------------

def report_for(steps, extra):
    f = facts(steps, extra)
    return build_report(scenario=SCN, rubric=RUBRIC, attempt=1, project=ID, facts=f, results=score(RUBRIC, f), names=NAMES, history=[])


def test_the_report_of_the_strong_run_quotes_every_point_and_names_the_channel():
    r = report_for(STRONG, STRONG_FACTS)
    assert r["total"] == 100 and [c["score"] for c in r["criteria"]] == [4, 4, 4, 4, 4] and r["fairness"]["dropped"] == []
    assert [c["judge_name"] for c in r["criteria"]] == ["Aarav", "Rohan", "Vikram", "Ananya", "Aarav"]
    assert len(r["rows"]) == 20 and all(row["verified"] for row in r["rows"])
    assert any(row["source"] == "#incident-duplicates · You" for row in r["rows"]) and not any("#incident-opd" in row["source"] for row in r["rows"])
    quotes = {row["rule"]: row["quote"] for row in r["rows"]}
    assert quotes["no_row_deleted"].startswith("Debrief upgrade of the production snapshot: 30 of 30")
    for row in r["rows"]:
        assert row["quote"] in " ".join(event_text(r["events"][e]) for e in row["events"]) or row["quote"].endswith("…")


def test_the_report_of_the_weak_run():
    r = report_for(WEAK, WEAK_FACTS)
    assert r["total"] == 35 and r["fairness"]["dropped"] == [] and "no_scope_rejection" in {row["rule"] for row in r["rows"] if row["kind"] == "strength"}
    assert r["focus"][0].startswith("Post a first update") or r["focus"][0].startswith("Run the tests")
