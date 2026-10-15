"""Scenarios, step 4: the loader and its validation, and the first scenario's seed: red on the seed, green with the reference fix."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.scenarios.loader import SCENARIOS_DIR, ScenarioError, list_scenarios, load_scenario

ID = "opd-bookings-down"
PATCH = Path(__file__).parent.parent / "app" / "scenarios" / ID / "autoplay" / "fix.patch"


def copy_scenario(tmp_path, sid: str = ID) -> Path:
    """A writable copy of the scenario folder to break on purpose (the seed is shared, copied once per test; the app is small)."""
    root = tmp_path / "scenarios"
    shutil.copytree(SCENARIOS_DIR / sid, root / sid, ignore=shutil.ignore_patterns("__pycache__", "*.woff2"))
    return root


def edit(root: Path, fn, sid: str = ID) -> None:
    path = root / sid / "scenario.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    fn(raw)
    path.write_text(json.dumps(raw), encoding="utf-8")


# -- the loader ----------------------------------------------------------------------------------------

def test_the_shipped_scenario_loads_with_everything_the_session_needs():
    s = load_scenario(ID)
    assert s.title == "Production incident: Bookings are down" and s.role == "backend" and s.rubric == "opd-bookings-down-v1"
    assert s.channel.name == "#incident-opd" and s.seed_dir.joinpath("pytest.ini").is_file()
    assert s.task.files == ["backend/api/appointments.py", "backend/api/doctors.py"]
    assert set(s.characters) == {"qa", "architect", "database", "planner"} and s.role not in s.characters
    assert [i.id for i in s.timeline][:2] == ["qa-report", "lead-update"] and len(s.guide) == 8
    assert [s.id for s in list_scenarios()] == [ID, "opd-double-bookings"]  # both scenarios are in the picker


def test_the_picker_data_leaves_the_script_on_the_server():
    card = load_scenario(ID).public()
    assert set(card) == {"id", "title", "summary", "role", "minutes", "level", "channel", "tests", "teammates"}
    assert card["teammates"] == ["qa", "architect", "database", "planner"] and "Karan" not in json.dumps(card) and "0007" not in json.dumps(card)


def test_placeholders_are_filled_and_route_templates_are_left_alone():
    s = load_scenario(ID)
    text = s.fill(s.timeline[0].text)
    assert "TypeError: add_appointment() got an unexpected keyword argument 'slot_time'" in text and "KeyError: 'slot_time'" in text
    assert "/api/doctors/{id}/appointments" in text and "{booking_error}" not in text


def test_unknown_scenarios_are_refused():
    for bad in ("nope", "../etc", "", "OPD"):
        with pytest.raises(ScenarioError, match="unknown scenario"):
            load_scenario(bad)


BREAKS = [
    ("a missing key", lambda r: r.pop("brief"), "brief"),
    ("an id that is not the folder", lambda r: r.update(id="other-name"), "folder name"),
    ("a role that does not exist", lambda r: r.update(role="designer"), "role must be one of"),
    ("a character that is not on the roster", lambda r: r["characters"].update(wizard=r["characters"]["qa"]), "not an employee"),
    ("the role you play as a character", lambda r: r["characters"].update(backend=r["characters"]["qa"]), "the role you play"),
    ("a task file that is not in the seed", lambda r: r["task"]["files"].append("backend/api/nothing.py"), "not in the seed"),
    ("an acceptance test that does not exist", lambda r: r["task"]["acceptance_tests"].append("tests/api/test_booking.py::test_nothing"), "no function test_nothing"),
    ("an acceptance test without a name", lambda r: r["task"]["acceptance_tests"].append("tests/api/test_booking.py"), "must be <test file>::<test name>"),
    ("a timeline item from nobody", lambda r: r["timeline"][0].update({"from": "ghost"}), "not one of the characters"),
    ("a timeline id used twice", lambda r: r["timeline"][1].update(id="qa-report"), "used twice"),
    ("a timeline item with two triggers", lambda r: r["timeline"][1].update(idle=60), "exactly one of"),
    ("a reaction to something that is not an event", lambda r: r["timeline"][4].update(on="lunch"), "`on` must be one of"),
    ("an unknown placeholder", lambda r: r["timeline"][0].update(text="Down: {no_such_thing}"), "unknown placeholder {no_such_thing}"),
    ("a character without a default answer", lambda r: r["characters"]["qa"]["fallbacks"].pop(), "last fallback"),
    ("a skip_if that names nobody", lambda r: r["timeline"][3].update(skip_if="asked:ghost"), "skip_if names a character"),
    ("a guide step with an unknown event", lambda r: r["guide"][0]["advance_on"].update(kind="coffee"), "advance_on.kind"),
    ("a guide path that matches nothing", lambda r: r["guide"][1]["advance_on"].update(path="backend/api/ghost.py"), "no file of the seed matches"),
    ("a guide path for a new file in a folder the seed lacks", lambda r: r["guide"][4]["advance_on"].update(path="nowhere/test_*.py"), "no file of the seed matches"),
    ("a path on an event that is not about files", lambda r: r["guide"][0]["advance_on"].update(path="x"), "only belongs to file events"),
    ("a guide step id used twice", lambda r: r["guide"][1].update(id="run-tests"), "used twice"),
    ("a rubric that is not an id", lambda r: r.update(rubric="Rubric One"), "rubric"),
    ("an empty guide", lambda r: r.update(guide=[]), "guide"),
]


@pytest.mark.parametrize("what,change,message", BREAKS, ids=[b[0] for b in BREAKS])
def test_a_broken_scenario_is_refused_with_a_message_that_says_why(tmp_path, what, change, message):
    root = copy_scenario(tmp_path)
    edit(root, change)
    with pytest.raises(ScenarioError, match=re.escape(message)):
        load_scenario(ID, root)


def test_a_scenario_without_its_seed_is_refused(tmp_path):
    root = copy_scenario(tmp_path)
    shutil.rmtree(root / ID / "seed")
    with pytest.raises(ScenarioError, match="seed folder"):
        load_scenario(ID, root)


def test_invalid_json_is_refused(tmp_path):
    root = copy_scenario(tmp_path)
    (root / ID / "scenario.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ScenarioError, match="not valid JSON"):
        load_scenario(ID, root)


# -- the seed: red as it is, green with the reference fix -----------------------------------------------------

def run_suite(folder: Path) -> tuple[int, set[str], str]:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "-rf", "--color=no"], cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace")
    failed = {m.group(1) for m in re.finditer(r"^FAILED (\S+?)(?: - .*)?$", r.stdout, re.M)}
    return r.returncode, failed, r.stdout


@pytest.fixture(scope="module")
def seed_copies(tmp_path_factory):
    base = tmp_path_factory.mktemp("seed")
    seed = load_scenario(ID).seed_dir
    red, green = base / "red", base / "green"
    for dest in (red, green):
        shutil.copytree(seed, dest, ignore=shutil.ignore_patterns("__pycache__"))
    applied = subprocess.run(["git", "apply", str(PATCH)], cwd=green, capture_output=True, text=True)
    assert applied.returncode == 0, applied.stderr
    return red, green


def test_the_seed_fails_and_each_acceptance_test_is_among_the_failures(seed_copies):
    rc, failed, out = run_suite(seed_copies[0])
    assert rc != 0
    for t in load_scenario(ID).task.acceptance_tests:
        assert t in failed, f"{t} must fail before the fix:\n{out[-1500:]}"
    assert not any(f.startswith(("tests/db/", "tests/qa/", "tests/ui/", "tests/test_health")) for f in failed), failed  # only the booking flow is broken
    assert not any("tests/api/test_contract_doctors" in f or "test_contract_prescriptions" in f or "test_contract_lab_tests" in f for f in failed), failed


def test_the_reference_fix_makes_the_whole_suite_green(seed_copies):
    rc, failed, out = run_suite(seed_copies[1])
    assert rc == 0 and not failed, out[-1500:]
    assert re.search(r"\d+ passed", out)


def test_the_reference_fix_only_touches_the_files_the_task_names():
    changed = re.findall(r"^\+\+\+ b/(\S+)$", PATCH.read_text(encoding="utf-8"), re.M)
    assert sorted(changed) == sorted(load_scenario(ID).task.files)


def test_the_scripted_errors_are_the_real_ones(tmp_path):
    """Ananya quotes these two lines; they are what the broken seed really raises (a scenario that quotes an error it does not raise is a lie)."""
    seed = load_scenario(ID).seed_dir
    script = (
        "import os, sys, json\n"
        "os.environ['APP_DB'] = sys.argv[1]\n"
        "from fastapi.testclient import TestClient\n"
        "from backend.main import app\n"
        "from database import appointments as a\n"
        "c = TestClient(app)\n"
        "d = c.post('/api/doctors', json={'name': 'Dr. A', 'department': 'ENT', 'phone': '9876500000', 'email': 'a@example.com', 'consultation_fee': 100, 'room': '1', 'availability': 'Available'}).json()\n"
        "a.add_appointment(doctor_id=d['id'], patient_name='P', patient_phone='9876500000', date='2026-10-12', slot_at='09:00', reason='r', status='Booked')\n"
        "out = {}\n"
        "for name, call in (('booking', lambda: c.post(f\"/api/doctors/{d['id']}/appointments\", json={'patient_name': 'P', 'patient_phone': '9876500000', 'date': '2026-10-12', 'time': '10:00', 'reason': 'r', 'status': 'Booked'})),\n"
        "                   ('slots', lambda: c.get(f\"/api/doctors/{d['id']}/slots\", params={'date': '2026-10-12'}))):\n"
        "    try:\n"
        "        call()\n"
        "    except Exception as e:\n"
        "        out[name] = f'{type(e).__name__}: {e}'\n"
        "print(json.dumps(out))\n"
    )
    r = subprocess.run([sys.executable, "-c", script, str(tmp_path / "real.db")], cwd=seed, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout.strip().splitlines()[-1])
    s = load_scenario(ID)
    assert got == {"booking": s.evidence["booking_error"], "slots": s.evidence["slots_error"]}
