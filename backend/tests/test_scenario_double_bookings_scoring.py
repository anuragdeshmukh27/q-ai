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


def test_a_weak_run_scores_30_and_every_gap_cites_a_real_entry():
    f = facts(WEAK, WEAK_FACTS)
    assert scores(f) == WEAK_SCORES and sum(scores(f).values()) * RUBRIC.weight == 30
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
    assert finding(weak, "names_the_cause").kind == "gap" and finding(weak, "first_update").kind == "gap"
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
    assert r["total"] == 30 and r["fairness"]["dropped"] == [] and "no_scope_rejection" in {row["rule"] for row in r["rows"] if row["kind"] == "strength"}
    assert r["focus"][0].startswith("Post a first update") or r["focus"][0].startswith("Run the tests")


# -- hand-test fixes: the cause named in the channel, and a run started before the first edit ---------------------

def post_only(text: str) -> Facts:
    """The strong run with its one update replaced by `text` (the other post, 'Fix is ready', never names a cause)."""
    steps = [(t, k, {**v, "text": text} if v.get("message") == "C003" else v) for t, k, v in STRONG]
    return facts(steps, STRONG_FACTS)


@pytest.mark.parametrize("text", [
    "Update: nothing in the database stops a second Booked row: migration 0006 only made a plain index. Three slots already hold duplicates.",
    "Update: three slots hold two Booked appointments each, and migration 0006 only made a plain index, so nothing stops a second booking.",
    "The database has no unique constraint on the slot, so the same slot can be booked twice.",
    "There is no unique index for doctor, date and slot.",
    "Migration 0006 made a plain, non-unique index.",
    "Without a unique index the database accepts a second booking.",
    "The index on the slot is not unique, so nothing refuses a second booking.",
])
def test_the_cause_is_named_when_a_post_says_the_database_has_no_unique_constraint_or_index(text):
    assert finding(post_only(text), "names_the_cause").kind == "strength"


@pytest.mark.parametrize("text", [
    "Sorry, still working on it. I think I need to remove the duplicate rows.",
    "There are duplicate rows: two patients booked the same slot twice.",
    "Rohan, can you help? I do not know what else the database needs.",
    "Still looking at the index.",
    "Fix is ready: migration 0008 cancels the later duplicates and adds the partial unique index.",
    "On it. I am running the tests first, then I will look at the data.",
])
def test_the_duplicate_rows_alone_or_a_fix_do_not_name_the_cause(text):
    x = finding(post_only(text), "names_the_cause")
    assert x.kind == "gap" and "does not say what was broken" in x.text and "the database has no unique constraint or index" in x.advice


def test_the_weak_run_no_longer_gets_the_point_for_wanting_to_remove_the_duplicate_rows():
    f = facts(WEAK, WEAK_FACTS)
    x = finding(f, "names_the_cause")
    assert x.kind == "gap" and x.text == "Your last post, at 05:30, does not say what was broken."
    assert scores(f)["communication"] == 0 and sum(scores(f).values()) * RUBRIC.weight == 30


def test_the_first_scenario_names_the_cause_by_its_own_rule_and_its_scores_do_not_move():
    from app.scenarios.rubric import load_rubric as load
    import scenario_fixtures as one
    first = load(load_scenario("opd-bookings-down"))
    pattern = next(r.params["pattern"] for c in first.criteria for r in c.rules if r.id == "names_the_cause")
    assert pattern == "slot_at|slot_time|migration|0007|renam"
    f = one.facts(one.WEAK, one.WEAK_FACTS)
    assert {r.id: r.score for r in score(first, f)} == one.WEAK_SCORES and sum(r.score for r in score(first, f)) * first.weight == sum(one.WEAK_SCORES.values()) * first.weight
    f = one.facts(one.STRONG, one.STRONG_FACTS)
    assert sum(r.score for r in score(first, f)) * first.weight == 100


def test_a_run_started_before_the_first_edit_counts_even_when_its_result_came_in_after_the_edit():
    steps = sorted([(101 if (t, k) == (26, "test_result") else t, k, v) for t, k, v in STRONG], key=lambda s: s[0])  # the first edit is at 100 s: the suite was still going
    f = facts(steps, STRONG_FACTS)
    x = finding(f, "reproduced_first")
    assert x.kind == "strength" and x.text == "You started the tests at 00:20, before the first edit."
    assert f.log[[e["id"] for e in f.log].index(x.events[0])]["kind"] == "test_run"  # the point quotes the click, not the late result
    assert scores(f)["diagnosis"] == 4


def test_a_run_that_finished_before_the_first_edit_still_quotes_its_result():
    x = finding(facts(STRONG, STRONG_FACTS), "reproduced_first")
    assert x.kind == "strength" and x.text == "Your first test run finished at 00:26 (5 failed, 105 passed in 6.1s), before the first edit."


def test_a_run_after_the_first_edit_does_not_count():
    steps = [(t, k, v) for t, k, v in STRONG if k not in ("test_run", "test_result") or t > 100]
    x = finding(facts(steps, STRONG_FACTS), "reproduced_first")
    assert x.kind == "gap" and x.text == "By your first edit at 01:40 you had not run the tests."


REAL_FACTS = {
    "scan": None, "rerun": {"ok": True, "passed": 111, "failed": 0, "summary": "111 passed"},
    "regression": {"path": REGRESSION, "fails_on_seed": True, "passes_on_main": True, "seed_summary": "1 failed in 0.39s", "main_summary": "1 passed"},
    "measured": MEASURED_OK,
}


def test_the_hand_testers_first_attempt_is_scored_again_and_the_log_has_no_run_before_the_first_edit():
    """Attempt 1 of the hand-test (95/100): the log, as the session wrote it. It holds no test run before the first save (00:58); the run of 5 failures that the hand-tester remembers
    belongs to the session before it (opd-double-bookings-3, abandoned and never submitted). The backend's own event history of the attempt has the same three runs as the log."""
    import json
    log = [json.loads(x) for x in (Path(__file__).parent / "fixtures_real_double_attempt1.jsonl").read_text(encoding="utf-8").splitlines()]
    first_edit = next(e for e in log if e["kind"] == "file_saved")
    assert (first_edit["id"], first_edit["t"]) == ("E008", 58.9) and first_edit["path"] == REGRESSION and first_edit["added"] == 0  # the empty file made with "+"
    assert [(e["id"], e["t"], e["trigger"]) for e in log if e["kind"] == "test_run"] == [("E011", 73.1, "ide"), ("E016", 96.0, "ide"), ("E021", 115.9, "submit")]
    assert [e["t"] for e in log if e["kind"] == "test_run" and e["t"] < first_edit["t"]] == []
    f = Facts(log, minutes=30, **REAL_FACTS)
    assert scores(f) == {"communication": 4, "diagnosis": 3, "fix_quality": 4, "testing": 4, "ownership": 4} and sum(scores(f).values()) * RUBRIC.weight == 95
    x = finding(f, "reproduced_first")
    assert x.kind == "gap" and x.text == "By your first edit at 00:58 you had not run the tests." and x.events[0] == "E008"
    assert finding(f, "names_the_cause").kind == "strength"  # "migration 0006 only made a plain index, so nothing stops a second booking"
