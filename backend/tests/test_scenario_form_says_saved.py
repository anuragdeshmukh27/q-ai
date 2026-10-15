"""The scenario "The form says it saved" (the frontend engineer): its loader, the unlock of the page's shell, its seed (red as it is, green with the reference fix, red in a named way with every
naive fix), the proof that the backend is untouched and correct, and what the team says about it."""
from __future__ import annotations

import filecmp
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.scenarios.loader import SCENARIOS_DIR, ScenarioError, list_scenarios, load_scenario
from app.scenarios.rubric import load_rubric

from test_scenarios import copy_scenario, edit, run_suite

ID = "opd-form-says-saved"
FOLDER = SCENARIOS_DIR / ID
SEED = FOLDER / "seed"
PATCH = FOLDER / "autoplay" / "fix.patch"
FIXES = Path(__file__).parent / "scenario_fixes" / "form-says-saved"
UI = "tests/ui/test_refusals.py"
CREATE, PHONE = f"{UI}::test_a_taken_slot_keeps_the_booking_form_open_and_says_why", f"{UI}::test_an_invalid_phone_shows_the_servers_message_in_the_form"
EDIT, ACTION = f"{UI}::test_moving_an_appointment_onto_a_taken_slot_is_refused_on_screen", f"{UI}::test_a_refused_status_button_shows_an_error_not_the_success_text"
DELETE, BOARD = f"{UI}::test_a_refused_delete_does_not_say_removed", f"{UI}::test_a_refused_board_move_shows_an_error"
ALL_SIX = {CREATE, PHONE, EDIT, ACTION, DELETE, BOARD}


# -- the loader ----------------------------------------------------------------------------------------

def test_the_scenario_loads_with_a_frontend_engineer_and_rohan_as_a_teammate():
    s = load_scenario(ID)
    assert s.title == "The form says it saved" and s.role == "frontend" and s.rubric == "opd-form-says-saved-v1" and s.level == "Intermediate" and s.minutes == 25
    assert s.channel.name == "#incident-frontdesk" and s.seed_dir.joinpath("pytest.ini").is_file()
    assert set(s.characters) == {"qa", "architect", "backend", "planner"} and s.role not in s.characters
    assert s.task.files == ["static/shell.js"] and s.task.new_files == [] and len(s.task.acceptance_tests) == 6 and set(s.task.acceptance_tests) == ALL_SIX and len(s.guide) == 8
    assert [i.id for i in s.timeline][:3] == ["qa-report", "lead-update", "lead-nudge"]  # the ids the rules read
    assert [x.id for x in list_scenarios()] == ["opd-bookings-down", "opd-double-bookings", ID]  # the picker order: the id sorts last


def test_the_three_picker_cards_carry_the_same_fields():
    cards = [load_scenario(i).public() for i in ("opd-bookings-down", "opd-double-bookings", ID)]
    assert all(set(c) == {"id", "title", "summary", "role", "minutes", "level", "channel", "tests", "teammates"} for c in cards)
    assert [(c["role"], c["level"], c["minutes"]) for c in cards] == [("backend", "Intermediate", 25), ("database", "Advanced", 30), ("frontend", "Intermediate", 25)]
    assert cards[2]["teammates"] == ["qa", "architect", "backend", "planner"] and cards[2]["tests"] == 6
    assert "shell.js" not in json.dumps(cards[2]["summary"]) and "call()" not in json.dumps(cards[2])  # the cause stays on the server


def test_the_judges_are_not_the_person_who_plays():
    s = load_scenario(ID)
    r = load_rubric(s)
    assert [(c.id, c.judge) for c in r.criteria] == [("communication", "architect"), ("diagnosis", "backend"), ("fix_quality", "reviewer"), ("testing", "qa"), ("ownership", "architect")]
    assert all(c.judge != s.role for c in r.criteria) and r.max_total == 100 and r.measures == ["refusals"]


def test_only_this_scenario_unlocks_files_the_preset_locks():
    assert load_scenario("opd-bookings-down").unlock == [] and load_scenario("opd-double-bookings").unlock == []
    assert load_scenario(ID).unlock == ["static/shell.js", "static/shell.css", "static/ui-kit.js", "static/ui-kit.css"]


BREAKS = [
    ("an unlock that the preset does not lock", lambda r: r.update(unlock=["static/app.js"]), "unlock 'static/app.js' must be one file the preset locks"),
    ("an unlock of a whole folder", lambda r: r.update(unlock=["static/fonts/**"]), "must be one file the preset locks"),
    ("an unlock of a file the seed does not have", lambda r: r.update(unlock=["backend/validation.py"]) or r["task"]["files"].clear() or r["task"].update(files=["static/shell.js"]), "unlock 'backend/validation.py' is not in the seed"),
    ("the role you play as a character", lambda r: r["characters"].update(frontend=r["characters"]["qa"]), "the role you play"),
    ("an acceptance test that does not exist", lambda r: r["task"]["acceptance_tests"].append(f"{UI}::test_nothing"), "there is no function test_nothing"),
]


@pytest.mark.parametrize("what,change,message", BREAKS, ids=[b[0] for b in BREAKS])
def test_a_broken_scenario_is_refused(tmp_path, what, change, message):
    root = copy_scenario(tmp_path, ID)
    if what == "an unlock of a file the seed does not have":
        (root / ID / "seed" / "backend" / "validation.py").unlink()
    edit(root, change, ID)
    with pytest.raises(ScenarioError, match=re.escape(message)):
        load_scenario(ID, root)


# -- the evidence is what really happens ------------------------------------------------------------------------

def answers() -> dict:
    return json.loads((SEED / "tests" / "ui" / "answers.json").read_text(encoding="utf-8"))


def test_the_network_answers_ananya_quotes_are_the_real_answers_of_the_api():
    s = load_scenario(ID)
    quoted = {k: json.loads(re.search(r"(\{.*\})", v).group(1)) for k, v in s.evidence.items() if k in ("network", "phone", "stale")}
    a = answers()
    assert quoted["network"] == a["create_taken"]["body"] and a["create_taken"]["status"] == 409 and "answered 409" in s.evidence["network"]
    assert quoted["phone"] == a["create_bad_phone"]["body"] and a["create_bad_phone"]["status"] == 400 and "answered 400" in s.evidence["phone"]
    assert quoted["stale"] == a["action_refused"]["body"] and a["action_refused"]["status"] == 409 and "answered 409" in s.evidence["stale"]


def test_what_ananya_sees_is_what_the_page_does_on_the_seed():
    sys.path.insert(0, str(SEED))
    try:
        from tests.ui.probe import run_node
    finally:
        sys.path.remove(str(SEED))
    out = run_node(answers()["create_taken"], SEED)
    assert out["toasts"] == [{"kind": "success", "text": "Appointment added"}] and out["formOpen"] is False  # the dialog closes, the green toast
    s = load_scenario(ID)
    assert "'Appointment added'" in s.evidence["what_i_see"] and "closes" in s.evidence["what_i_see"]
    other = run_node(answers()["action_refused"], SEED)
    assert other["toasts"] == [{"kind": "success", "text": "Sana Sheikh: Cancelled"}] and "'Cancelled' toast" in s.evidence["stale"]


def test_the_slot_ananya_names_is_booked_in_the_production_data_by_the_patient_she_names():
    import sqlite3
    s = load_scenario(ID)
    conn = sqlite3.connect(":memory:")
    for sql in sorted((SEED / "database" / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")):
        conn.executescript(sql.read_text(encoding="utf-8"))  # production as it is after scenario 2's fix is in
    conn.executescript((SEED / "fixtures" / "prod_snapshot.sql").read_text(encoding="utf-8").replace("INSERT INTO appointments", "INSERT OR IGNORE INTO appointments"))
    row = conn.execute("SELECT a.status FROM appointments a JOIN doctors d ON d.id = a.doctor_id WHERE d.name = 'Dr. Farhan Ali' AND a.date = '2026-10-15' AND a.slot_at = '11:00' AND a.patient_name = 'Sana Sheikh' AND a.id = 12").fetchone()
    assert row == ("Booked",) and "appointment 12" in s.evidence["steps"] and "15 Oct 2026" in s.evidence["steps"] and "11:00" in s.evidence["steps"]


# -- the backend is the backend of scenario 2 with its fix: proof that the fault is the page's --------------------------

def test_nothing_but_the_page_differs_from_the_finished_app_of_scenario_2(tmp_path):
    two = SCENARIOS_DIR / "opd-double-bookings"
    base = tmp_path / "two"
    shutil.copytree(two / "seed", base, ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run(["git", "apply", str(two / "autoplay" / "fix.patch")], cwd=base, check=True)  # scenario 2 as its reference fix leaves it
    differ: list[str] = []

    def walk(a: Path, b: Path, rel: str = "") -> None:
        cmp = filecmp.dircmp(a, b, ignore=["__pycache__", ".pytest_cache"])
        text = lambda p: p.read_bytes().replace(bytes([13, 10]), bytes([10]))  # noqa: E731  (git apply may write CRLF on Windows)
        same_text = [n for n in cmp.diff_files if text(a / n) == text(b / n)]
        differ.extend(f"{rel}{n}" for n in cmp.left_only + cmp.right_only + [n for n in cmp.diff_files if n not in same_text])
        for d in cmp.common_dirs:
            walk(a / d, b / d, f"{rel}{d}/")

    walk(base, SEED)
    assert sorted(differ) == ["static/shell.js", "tests/regression/README.md", "tests/ui/answers.json", "tests/ui/fakedom.mjs", "tests/ui/probe.py", "tests/ui/refusals.mjs", "tests/ui/test_refusals.py"]
    assert not [d for d in differ if d.startswith(("backend/", "database/", "fixtures/", "tests/api", "tests/db", "tests/qa"))]  # the API, the database and their tests are byte for byte the same
    old = (base / "static" / "shell.js").read_text(encoding="utf-8").splitlines()
    new = (SEED / "static" / "shell.js").read_text(encoding="utf-8").splitlines()
    changed = [(o, n) for o, n in zip(old, new) if o != n]
    assert len(old) == len(new) and len(changed) == 2  # the header comment and the one condition
    assert "(locked preset file" in changed[0][0] and changed[1][1].strip().startswith("if (!res.ok && !data)")


# -- the seed: red as it is, green with the reference fix, red in a named way with each naive one ----------------------

def make_copy(base: Path, name: str, patch: Path | None = None) -> Path:
    dest = base / name
    shutil.copytree(SEED, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    if patch is not None:
        r = subprocess.run(["git", "apply", str(patch)], cwd=dest, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    return dest


@pytest.fixture(scope="module")
def copies(tmp_path_factory):
    return tmp_path_factory.mktemp("frontend")


def test_the_seed_fails_exactly_the_six_acceptance_tests(copies):
    rc, failed, out = run_suite(make_copy(copies, "red"))
    assert rc != 0
    assert failed == set(load_scenario(ID).task.acceptance_tests), out[-1500:]  # everything else in the suite, backend and database included, passes on the seed
    assert re.search(r"6 failed, 1\d\d passed", out)


def test_the_reference_fix_makes_the_whole_suite_green(copies):
    rc, failed, out = run_suite(make_copy(copies, "green", PATCH))
    assert rc == 0 and not failed, out[-1500:]
    assert re.search(r"1\d\d passed", out)


def test_the_reference_fix_is_one_changed_line_in_the_request_function():
    text = PATCH.read_text(encoding="utf-8")
    assert re.findall(r"^\+\+\+ b/(\S+)$", text, re.M) == ["static/shell.js"] and text.count("\n@@ ") == 1
    assert [l for l in text.splitlines() if l[:1] in "+-" and l[:3] not in ("+++", "---")] == ["-    if (!res.ok && !data) {  // nothing came back to show", "+    if (!res.ok) {"]


NAIVE_FIXES = [
    ("naive_create_form_only", {EDIT, ACTION, DELETE, BOARD}),  # only the New appointment form looks at the answer
    ("naive_409_only", {PHONE, DELETE}),  # only a conflict is an error: a bad phone (400) and a missing record (404) still say they saved
    ("naive_buttons_only", {CREATE, PHONE, EDIT}),  # Complete, Cancel and Delete look at the answer, the forms do not
    ("naive_message_lost", ALL_SIX),  # every refusal is an error, with nothing the person can read
    ("naive_appointments_only", set()),  # passes every test of the seed: only the debrief's check of the doctor and prescription forms finds it
]


@pytest.mark.parametrize("name,expected", NAIVE_FIXES, ids=[n for n, _ in NAIVE_FIXES])
def test_each_naive_fix_fails_the_tests_that_name_its_mistake(copies, name, expected):
    rc, failed, out = run_suite(make_copy(copies, name, FIXES / f"{name}.patch"))
    assert failed == expected, out[-2000:]


def test_the_naive_fix_the_weak_run_applies_is_the_one_the_tests_know():
    assert (FOLDER / "autoplay" / "naive_create_form.patch").read_bytes() == (FIXES / "naive_create_form_only.patch").read_bytes()


# -- the learner's own regression test -------------------------------------------------------------------------------

def test_the_reference_regression_test_fails_on_the_seed_and_passes_after_the_fix(copies):
    text = (FOLDER / "autoplay" / "regression_test.txt").read_text(encoding="utf-8")
    for name, patch, red in (("reg_red", None, True), ("reg_green", PATCH, False)):
        root = make_copy(copies, name, patch)
        (root / "tests" / "regression" / "test_regression_refusals.py").write_text(text, encoding="utf-8")
        rc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/regression"], cwd=root, capture_output=True, text=True).returncode
        assert (rc == 1) is red and (rc == 0) is not red, name  # exactly 1: a failing test, not an error in the test file


# -- what the learner may edit and the task document ---------------------------------------------------------------------

@pytest.fixture
def started(tmp_path):
    from api_helpers import wait_for
    from scenario_helpers import ScenarioLLM
    from test_scenario_debrief import events, manager
    client, mgr, settings = manager(tmp_path, ScenarioLLM())
    pid = client.post(f"/api/scenarios/{ID}/start").json()["id"]
    s = mgr.get(pid)
    wait_for(lambda: next(iter(events(s, "human_task_assigned")), None), 90, "the task")
    yield client, mgr, s, pid
    s.orch.stop()
    mgr.shutdown()


def test_the_learner_owns_the_pages_and_the_regression_tests_and_nothing_of_the_backend(started):
    client, mgr, s, pid = started
    ide = f"/api/projects/{pid}/ide/frontend"
    put = lambda path: client.put(f"{ide}/file", json={"path": path, "content": "// x\n"}).status_code  # noqa: E731
    assert [put(p) for p in ("static/shell.js", "static/app.js", "static/style.css", "static/ui-kit.js", "static/shell.css", "tests/regression/test_regression_mine.py")] == [200] * 6
    assert [put(p) for p in ("backend/main.py", "backend/api/appointments.py", "database/connection.py", "database/migrations/0008_one_booking_per_slot.sql", "tests/ui/test_refusals.py",
                             "tests/api/test_double_booking_api.py", "static/fonts/inter-latin-wght-normal.woff2")] == [403] * 7
    tree = {f["path"]: f for f in client.get(f"{ide}/tree").json()["files"]}
    assert tree["static/shell.js"]["writable"] and not tree["backend/main.py"]["writable"] and not tree["tests/ui/test_refusals.py"]["writable"]


def test_a_changed_backend_file_is_a_scope_rejection_at_submit(started):
    client, mgr, s, pid = started
    wt = s.orch._ide_worktree("frontend")
    (Path(wt) / "backend" / "main.py").write_text("# changed outside the IDE\n", encoding="utf-8")
    answer = client.post(f"/api/projects/{pid}/tasks/h1/submit").json()
    assert answer["ok"] is False and answer["stage"] == "scope" and answer["files"] == ["backend/main.py"]


def test_the_task_document_says_the_shell_is_yours(started):
    client, mgr, s, pid = started
    doc = client.get(f"/api/projects/{pid}/tasks/h1/doc").text
    assert "In this incident you also own `static/shell.js`, `static/shell.css`, `static/ui-kit.js`, `static/ui-kit.css`." in doc
    assert "`static/shell.js`" not in doc.split("Do not edit these")[1] and "`backend/main.py`" in doc.split("Do not edit these")[1]  # the others stay locked
    assert "- `tests/regression/**`" in doc and "static/**" in doc and "A taken slot" not in doc and "closes with a green 'Appointment added'" in doc


def test_the_reviewer_is_not_asked_to_shorten_the_shell_but_still_flags_a_long_new_file(started):
    client, mgr, s, pid = started
    wt = Path(s.orch._ide_worktree("frontend"))
    ide = f"/api/projects/{pid}/ide/frontend/file"
    shell = client.get(ide, params={"path": "static/shell.js"}).json()["content"]
    nl = chr(10)
    assert client.put(ide, json={"path": "static/shell.js", "content": shell + "// one more line" + nl}).status_code == 200
    long_file = "// a new, long file" + nl + nl.join(f"const a{i} = {i};" for i in range(200)) + nl
    assert client.put(ide, json={"path": "static/long.js", "content": long_file}).status_code == 200
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "work"], cwd=wt, check=True)
    problems = [(f.file, f.problem) for f in s.orch._automatic_findings(s.orch.agents["frontend"], wt, "frontend")]
    assert [f for f, p in problems if "lines; keep files under" in p] == ["static/long.js"]  # shell.js is 880 lines and not the learner's doing; a long file they add is
