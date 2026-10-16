"""Autoplay ("Watch a run") of "Double bookings": a scripted database engineer plays the real scenario with the LLM stubbed. The scores are the rubric's own, so the exact numbers are
the rubric's: a strong run 100, the weak run 30. A virtual clock that only the script moves lets a whole incident, nudge included, run in seconds."""
import pytest

from app.scenarios.autoplay import reference_fix
from app.scenarios.reports import History
from app.scenarios.scripts import SCRIPTS, script_for

from api_helpers import wait_for
from scenario_helpers import ScenarioLLM
from test_autoplay import events, make

pytestmark = pytest.mark.slow  # whole module is slow (see backend/tests/conftest.py)

ID = "opd-double-bookings"
OTHER = "opd-bookings-down"
MIGRATION = "database/migrations/0008_one_booking_per_slot.sql"


def watch(client, mgr, variant, scenario=ID, speed=1):
    r = client.post(f"/api/scenarios/{scenario}/autoplay", json={"variant": variant, "speed": speed})
    assert r.status_code == 201, r.text
    return r.json()["id"], mgr.get(r.json()["id"])


def play(client, mgr, variant, scenario=ID):
    pid, s = watch(client, mgr, variant, scenario)
    ended = wait_for(lambda: next(iter(events(s, "autoplay_ended")), None), 420, "the run to end")
    assert ended["reason"] == "done", ended
    wait_for(lambda: next(iter(events(s, "debrief_ended")), None), 60, "the debrief")
    return pid, s, client.get(f"/api/projects/{pid}/report").json()


@pytest.fixture
def world(tmp_path):
    client, mgr, settings = make(tmp_path, ScenarioLLM("Rohan: the route only inserts the row; the rule belongs in the database."))
    yield client, mgr, settings
    mgr.shutdown()


def test_the_strong_run_scores_100_and_the_screen_has_every_event_it_needs(world):
    client, mgr, settings = world
    pid, s, rep = play(client, mgr, "strong")
    assert rep["total"] == 100 and [c["score"] for c in rep["criteria"]] == [4, 4, 4, 4, 4] and rep["scenario"] == ID
    assert rep["fairness"]["dropped"] == [] and rep["fairness"]["points"] == 20 and all(r["verified"] for r in rep["rows"])
    assert rep["kind"] == "demo" and rep["variant"] == "strong" and rep["attempt"] == 1
    assert [c["judge_name"] for c in rep["criteria"]] == ["Aarav", "Rohan", "Vikram", "Ananya", "Aarav"]
    assert rep["fairness"]["tests_rerun"]["ok"] is True
    started = events(s, "autoplay_started")[0]
    assert started["variant"] == "strong" and started["total"] == len(started["labels"]) and "two patients were booked with the same doctor" in started["doc"] and started["tree"]["ready"]
    assert [e["path"] for e in events(s, "autoplay_open_file")] == ["fixtures/prod_snapshot.sql", "database/migrations/0006_index_appointments_by_doctor_and_slot.sql"]
    assert [e["writable"] for e in events(s, "autoplay_open_file")] == [False, True]  # the data is read-only for you; migrations are yours (database/**)
    assert events(s, "autoplay_search")[0]["q"] == "UNIQUE" and events(s, "autoplay_search")[0]["result"]["matches"] >= 1
    assert [e["path"] for e in events(s, "autoplay_edit")] == ["tests/regression/test_regression_double_booking.py", MIGRATION]
    assert "WHERE status = 'Booked'" in events(s, "autoplay_edit")[1]["content"]
    assert [e["focus"] for e in events(s, "autoplay_step")][-1] == "debrief" and {e["focus"] for e in events(s, "autoplay_step")} == {"ide", "chat", "debrief"}
    assert events(s, "autoplay_ended")[0]["reason"] == "done" and events(s, "scenario_started")[0]["channel"]["name"] == "#incident-duplicates"
    info = client.get(f"/api/projects/{pid}/session").json()
    kinds = [e["kind"] for e in info["events"]]
    assert kinds.count("file_saved") == 2 and kinds.count("search") == 1 and info["summary"]["hints"] <= 1
    assert not any(e.get("auto") for e in info["events"] if e["kind"] == "file_opened")
    assert [m["text"][:3] for m in events(s, "channel_message") if m.get("source") == "learner"] == ["On ", "Upd", "Fix"]
    assert "#incident-opd" not in str([r["source"] for r in rep["rows"]])


def test_the_weak_run_scores_exactly_30_and_the_gaps_are_the_ones_it_was_given(world):
    client, mgr, settings = world
    pid, s, rep = play(client, mgr, "weak")
    assert [(c["id"], c["score"]) for c in rep["criteria"]] == [("communication", 0), ("diagnosis", 0), ("fix_quality", 4), ("testing", 0), ("ownership", 2)]
    assert rep["total"] == 30 and rep["kind"] == "demo" and rep["variant"] == "weak"
    held = {r["rule"] for r in rep["rows"] if r["kind"] == "strength"}
    assert held == {"no_row_deleted", "duplicates_resolved", "partial_index_present", "suite_green_on_main", "within_time_box", "no_scope_rejection"}
    gaps = {r["rule"] for r in rep["rows"] if r["kind"] == "gap"}
    assert {"first_update", "no_nudges", "names_the_cause", "reproduced_first", "looked_at_the_data", "no_red_submit", "regression_test_added", "few_hints"} <= gaps
    log = client.get(f"/api/projects/{pid}/session").json()["events"]
    kinds = [e["kind"] for e in log]
    first_save = kinds.index("file_saved")
    assert "test_run" not in kinds[:first_save] and not any(e["kind"] == "message_posted" for e in log[:first_save])  # a migration first: no tests, no data, no update
    assert any(e["kind"] == "team_message" and e.get("ref") == "lead-nudge" for e in log)
    red = [e for e in log if e["kind"] == "submit_result" and not e["ok"]]
    assert [e["stage"] for e in red] == ["tests"] and log[-1]["kind"] == "session_finished"  # one red submit, and the Reviewer asks for nothing about tests the role may not write
    assert any("test_duplicate_bookings_are_cancelled_not_deleted" in f for f in red[0]["failed"])  # the naive migration deleted the rows
    edits = events(s, "autoplay_edit")
    assert [e["path"] for e in edits] == [MIGRATION, MIGRATION] and "DELETE FROM appointments" in edits[0]["content"] and "DELETE" not in edits[1]["content"]
    assert [e["from"] for e in log if e["kind"] == "hint_given"] == ["backend", "backend"]  # Rohan's pointer at four minutes, then the question the script asks him


def test_the_two_runs_differ_by_seventy_and_both_are_demos(world):
    client, mgr, settings = world
    _, _, strong = play(client, mgr, "strong")
    _, _, weak = play(client, mgr, "weak")
    assert strong["total"] - weak["total"] == 70 and strong["rubric"] == weak["rubric"] == {"id": "opd-double-bookings-v1", "version": 1}


def test_a_demo_of_each_scenario_has_its_own_history_and_never_counts_as_an_attempt(world):
    client, mgr, settings = world
    play(client, mgr, "strong", ID)
    play(client, mgr, "weak", OTHER)
    assert History(settings.workspace, ID).attempts() == [] and History(settings.workspace, OTHER).attempts() == []
    assert [(a["attempt"], a["total"], a["variant"]) for a in History(settings.workspace, ID, "demo").attempts()] == [(1, 100, "strong")]
    assert [(a["attempt"], a["total"], a["variant"]) for a in History(settings.workspace, OTHER, "demo").attempts()] == [(1, 30, "weak")]  # numbered from 1 in its own file


def test_stop_in_the_middle_cleans_up_a_double_bookings_run(world):
    client, mgr, settings = world
    pid, s = watch(client, mgr, "strong")
    wait_for(lambda: events(s, "autoplay_edit") and events(s, "autoplay_edit")[0], 240, "the first edit")
    root = s.root
    r = client.post(f"/api/projects/{pid}/autoplay/stop")
    assert r.status_code == 200 and r.json()["stopped"] is True and not s.autoplay.alive()
    assert not events(s, "debrief_started") and client.get(f"/api/projects/{pid}/report").status_code == 404 and not root.exists()
    assert History(settings.workspace, ID, "demo").attempts() == []


def test_the_speed_switch_and_the_bad_requests_work_on_scenario_2(world):
    client, mgr, settings = world
    assert client.post(f"/api/scenarios/{ID}/autoplay", json={"variant": "great"}).status_code == 400
    pid, s = watch(client, mgr, "weak")
    assert client.post(f"/api/projects/{pid}/autoplay/speed", json={"speed": 2}).json() == {"speed": 2}
    assert events(s, "autoplay_speed")[-1]["speed"] == 2
    assert client.post(f"/api/projects/{pid}/autoplay/stop").status_code == 200


def test_every_scenario_that_can_be_watched_has_a_script_and_the_others_are_refused(world, monkeypatch):
    client, mgr, settings = world
    assert set(SCRIPTS) == {OTHER, ID, "opd-form-says-saved"}
    with pytest.raises(ValueError, match="no scripted run"):
        script_for("opd-unknown", None)  # type: ignore[arg-type]
    monkeypatch.delitem(SCRIPTS, ID)
    r = client.post(f"/api/scenarios/{ID}/autoplay", json={"variant": "strong"})
    assert r.status_code == 400 and "no scripted run" in r.json()["detail"]
    assert client.post("/api/scenarios/nope/autoplay", json={"variant": "strong"}).status_code == 404


def test_the_reference_migration_is_the_patch_and_the_naive_one_ships_with_the_script():
    from pathlib import Path
    folder = Path(__file__).parent.parent / "app" / "scenarios" / ID / "autoplay"
    assert reference_fix({}, ID, create=(MIGRATION,))[MIGRATION] == (folder / "0008_one_booking_per_slot.sql").read_text(encoding="utf-8")
    naive = Path(__file__).parent / "scenario_fixes" / "double-bookings" / "naive_delete.sql"
    assert (folder / "naive_0008.sql").read_text(encoding="utf-8") == naive.read_text(encoding="utf-8")
