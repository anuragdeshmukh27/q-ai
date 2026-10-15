"""The scenario "Double bookings" (the database engineer): its loader, its seed (red as it is, green with the reference migration, red in a named way with every naive fix), the
planted data and what the team says about it."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from app.scenarios.loader import SCENARIOS_DIR, ScenarioError, list_scenarios, load_scenario
from app.scenarios.rubric import load_rubric

from test_scenarios import copy_scenario, edit, run_suite

ID = "opd-double-bookings"
FOLDER = SCENARIOS_DIR / ID
PATCH = FOLDER / "autoplay" / "fix.patch"
NAIVE = Path(__file__).parent / "scenario_fixes" / "double-bookings"
MIGRATION = "database/migrations/0008_one_booking_per_slot.sql"
DB, API = "tests/db/test_double_bookings.py", "tests/api/test_double_booking_api.py"
A, B, C = f"{DB}::test_duplicate_bookings_are_cancelled_not_deleted", f"{DB}::test_a_cancelled_duplicate_records_why", f"{DB}::test_the_database_refuses_a_second_booked_row_for_a_slot"
D, E = f"{API}::test_booking_the_same_slot_twice_returns_409_slot_already_booked", f"{API}::test_moving_an_appointment_onto_a_taken_slot_returns_409"
GUARD = f"{API}::test_a_cancelled_slot_can_be_booked_again"


# -- the loader ----------------------------------------------------------------------------------------

def test_the_scenario_loads_with_a_database_engineer_and_rohan_as_a_teammate():
    s = load_scenario(ID)
    assert s.title == "Double bookings" and s.role == "database" and s.rubric == "opd-double-bookings-v1" and s.level == "Advanced" and s.minutes == 30
    assert s.channel.name == "#incident-duplicates" and s.seed_dir.joinpath("pytest.ini").is_file()
    assert set(s.characters) == {"qa", "architect", "backend", "planner"} and s.role not in s.characters
    assert s.task.new_files == [MIGRATION] and s.task.all_files == [MIGRATION] and len(s.task.acceptance_tests) == 5 and len(s.guide) == 8
    assert [i.id for i in s.timeline][:3] == ["qa-report", "lead-update", "lead-nudge"]  # the ids the rules read
    assert [x.id for x in list_scenarios()] == ["opd-bookings-down", ID]


def test_the_picker_cards_carry_the_same_fields_for_both_scenarios():
    a, b = (load_scenario(i).public() for i in ("opd-bookings-down", ID))
    assert set(a) == set(b) == {"id", "title", "summary", "role", "minutes", "level", "channel", "tests", "teammates"}
    assert (b["role"], b["level"], b["minutes"], b["tests"], b["teammates"]) == ("database", "Advanced", 30, 5, ["qa", "architect", "backend", "planner"])
    assert "0008" not in json.dumps(b) and "Rohan" not in json.dumps(b)  # the script stays on the server


def test_the_judges_are_not_the_person_who_plays():
    s = load_scenario(ID)
    r = load_rubric(s)
    assert [(c.id, c.judge) for c in r.criteria] == [("communication", "architect"), ("diagnosis", "backend"), ("fix_quality", "reviewer"), ("testing", "qa"), ("ownership", "architect")]
    assert all(c.judge != s.role for c in r.criteria) and r.max_total == 100 and r.measures == ["double_bookings"]


def test_the_learner_owns_the_database_folder_and_the_regression_tests_only():
    from app.config import load_agents
    from app.orchestrator import LOCKED
    from app.scenarios.build import REGRESSION_TESTS
    from app.orchestrator import TEST_GLOBS
    base = load_agents()["database"].owned_paths
    assert base == ["database/**"] and TEST_GLOBS["database"] == "tests/test_db*.py"  # the generic grant that a scenario build leaves out
    assert REGRESSION_TESTS == "tests/regression/**" and "database/connection.py" in LOCKED and "backend/main.py" in LOCKED


NEW_FILE_BREAKS = [
    ("a new file that is already in the seed", lambda r: r["task"]["new_files"].append("database/migrations/0007_rename_slot_time_to_slot_at.sql"), "already in the seed"),
    ("a new file in a folder the seed lacks", lambda r: r["task"]["new_files"].append("nowhere/0009_x.sql"), "its folder is not in the seed"),
    ("a task with no files at all", lambda r: r["task"].update(new_files=[], files=[]), "needs `files` or `new_files`"),
    ("the role you play as a character", lambda r: r["characters"].update(database=r["characters"]["qa"]), "the role you play"),
]


@pytest.mark.parametrize("what,change,message", NEW_FILE_BREAKS, ids=[b[0] for b in NEW_FILE_BREAKS])
def test_a_broken_double_bookings_scenario_is_refused(tmp_path, what, change, message):
    root = copy_scenario(tmp_path, ID)
    edit(root, change, ID)
    with pytest.raises(ScenarioError, match=re.escape(message)):
        load_scenario(ID, root)


# -- the planted data ----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def snapshot(tmp_path_factory):
    """The production snapshot built the way the tests build it: migrations 0001 to 0007, then fixtures/prod_snapshot.sql."""
    seed = FOLDER / "seed"
    conn = sqlite3.connect(tmp_path_factory.mktemp("snap") / "prod.db")
    conn.row_factory = sqlite3.Row
    for sql in sorted((seed / "database" / "migrations").glob("000[1-7]_*.sql")):
        conn.executescript(sql.read_text(encoding="utf-8"))
    conn.executescript((seed / "fixtures" / "prod_snapshot.sql").read_text(encoding="utf-8"))
    yield conn
    conn.close()


def test_the_snapshot_holds_exactly_three_double_booked_slots_and_the_decoys(snapshot):
    pairs = snapshot.execute("SELECT doctor_id, date, slot_at, group_concat(id) AS ids FROM appointments WHERE status = 'Booked' GROUP BY doctor_id, date, slot_at HAVING COUNT(*) > 1").fetchall()
    assert len(pairs) == 3 and all(len(p["ids"].split(",")) == 2 for p in pairs)
    twins = snapshot.execute("SELECT COUNT(*) FROM (SELECT 1 FROM appointments WHERE status != 'Booked' GROUP BY doctor_id, date, slot_at HAVING COUNT(*) > 1)").fetchone()[0]
    mixed = snapshot.execute("SELECT COUNT(*) FROM (SELECT 1 FROM appointments GROUP BY doctor_id, date, slot_at HAVING SUM(status = 'Booked') = 1 AND COUNT(*) > 1)").fetchone()[0]
    assert twins >= 1 and mixed >= 1  # cancelled twins and a cancelled row beside a Booked one: a plain unique index cannot be built over them
    first = snapshot.execute("SELECT id, created_at FROM appointments WHERE status = 'Booked' AND id IN (7, 19)").fetchall()
    assert [r["id"] for r in sorted(first, key=lambda r: r["created_at"])] == [7, 19]  # the earliest by id is the earliest by time


def test_the_rows_ananya_quotes_are_the_rows_of_the_snapshot(snapshot):
    s = load_scenario(ID)
    for key, text in s.evidence.items():
        ids = [int(x) for x in re.findall(r"appointment (\d+)", text)]
        assert len(ids) == 2, key
        rows = snapshot.execute(f"SELECT a.*, d.name AS doctor FROM appointments a JOIN doctors d ON d.id = a.doctor_id WHERE a.id IN ({','.join('?' * 2)})", ids).fetchall()
        assert len(rows) == 2 and {r["status"] for r in rows} == {"Booked"}
        assert len({(r["doctor_id"], r["date"], r["slot_at"]) for r in rows}) == 1, key
        assert all(r["doctor"] in text and r["patient_name"] in text and r["slot_at"] in text for r in rows), key
    assert "{dup_1}" not in s.fill("{dup_1}") and s.evidence["dup_1"] in s.fill(s.timeline[0].text)


def test_the_planted_data_is_not_in_the_apps_own_seed_data():
    """seed.json is what the app opens with (Q_SEED=1); a duplicate in it would make the seeding fail once the index exists."""
    assert "7" not in {str(r.get("id")) for r in json.loads((FOLDER / "seed" / "seed.json").read_text(encoding="utf-8"))["appointments"]}


# -- the seed: red as it is, green with the reference migration, red in a named way with each naive one --------

def make_copy(base: Path, name: str, migration: Path | None = None, patch: bool = False) -> Path:
    dest = base / name
    shutil.copytree(FOLDER / "seed", dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    if migration is not None:
        shutil.copyfile(migration, dest / "database" / "migrations" / "0008_naive.sql")
    if patch:
        import subprocess
        r = subprocess.run(["git", "apply", str(PATCH)], cwd=dest, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    return dest


@pytest.fixture(scope="module")
def copies(tmp_path_factory):
    return tmp_path_factory.mktemp("double")


def test_the_seed_fails_exactly_the_five_acceptance_tests(copies):
    rc, failed, out = run_suite(make_copy(copies, "red"))
    assert rc != 0
    assert failed == set(load_scenario(ID).task.acceptance_tests), out[-1500:]  # everything else in the suite passes on the seed


def test_the_reference_migration_makes_the_whole_suite_green(copies):
    rc, failed, out = run_suite(make_copy(copies, "green", patch=True))
    assert rc == 0 and not failed, out[-1500:]
    assert re.search(r"\d+ passed", out)


def test_the_reference_fix_adds_one_migration_and_nothing_else():
    assert re.findall(r"^\+\+\+ b/(\S+)$", PATCH.read_text(encoding="utf-8"), re.M) == [MIGRATION]
    assert [l[1:] for l in PATCH.read_text(encoding="utf-8").splitlines() if l.startswith("+") and not l.startswith("+++")] == (FOLDER / "autoplay" / "0008_one_booking_per_slot.sql").read_text(encoding="utf-8").splitlines()


NAIVE_FIXES = [
    ("naive_delete", {A, B}),  # the later duplicates are gone: nothing to cancel, nothing that says why
    ("naive_index_only", {A, B, C}),  # the index cannot be built over rows that already collide: the upgrade fails on the production data
    ("naive_full_unique", {A, B, C, GUARD}),  # not partial: it cannot be built over cancelled twins, and a cancelled slot could never be booked again
    ("naive_no_reason", {B}),
    ("naive_no_index", {C, D, E}),
]


@pytest.mark.parametrize("name,expected", NAIVE_FIXES, ids=[n for n, _ in NAIVE_FIXES])
def test_each_naive_fix_fails_the_tests_that_name_its_mistake(copies, name, expected):
    rc, failed, out = run_suite(make_copy(copies, name, NAIVE / f"{name}.sql"))
    assert failed == expected, out[-2000:]


# -- the engine pieces that used to know only the first scenario ---------------------------------------------

def test_the_source_of_a_quote_names_the_scenarios_channel_and_the_default_is_unchanged():
    from app.scenarios.scoring import source_label
    post, said = {"kind": "message_posted"}, {"kind": "team_message", "from": "qa"}
    assert source_label(post) == "#incident-opd · You" and source_label(said) == "#incident-opd · Ananya"
    assert source_label(post, "#incident-duplicates") == "#incident-duplicates · You" and source_label(said, "#incident-duplicates") == "#incident-duplicates · Ananya"


def test_a_question_to_someone_who_is_not_on_the_incident_is_answered_with_this_scenarios_teammates(tmp_path):
    from api_helpers import wait_for
    from scenario_helpers import ScenarioLLM
    from test_scenario_debrief import events, manager
    client, mgr, settings = manager(tmp_path, ScenarioLLM())
    try:
        pid = client.post(f"/api/scenarios/{ID}/start").json()["id"]
        s = mgr.get(pid)
        wait_for(lambda: next(iter(events(s, "human_task_assigned")), None), 90, "the task")
        assert client.post(f"/api/projects/{pid}/channel", json={"text": "Meera, can you look at the page?"}).status_code == 200
        said = wait_for(lambda: next((e for e in events(s, "channel_message") if "is not on this incident" in e["text"]), None), 20, "Aarav's answer")
        assert said["from"] == "architect" and said["text"] == "Meera is not on this incident. Ask Ananya, Rohan or me."
        s.orch.stop()
    finally:
        mgr.shutdown()
