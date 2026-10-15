"""Autoplay ("Watch a run") of "The form says it saved": a scripted frontend engineer plays the real scenario with the LLM stubbed. The scores are the rubric's own: a strong run 100, the weak
run 30. A virtual clock that only the script moves lets a whole incident, nudge included, run in a few seconds of real time (the pages are really run in Node)."""
import pytest

from app.scenarios.reports import History

from api_helpers import wait_for
from scenario_helpers import ScenarioLLM
from test_autoplay import events, make
from test_autoplay_double_bookings import play, watch

ID = "opd-form-says-saved"
OTHER = "opd-double-bookings"
SHELL = "static/shell.js"
REGRESSION = "tests/regression/test_regression_refusals.py"


@pytest.fixture
def world(tmp_path):
    client, mgr, settings = make(tmp_path, ScenarioLLM("Rohan: the API answers correctly, 409 with a detail message; look at what the page does with it."))
    yield client, mgr, settings
    mgr.shutdown()


def test_the_strong_run_scores_100_and_the_screen_has_every_event_it_needs(world):
    client, mgr, settings = world
    pid, s, rep = play(client, mgr, "strong", ID)
    assert rep["total"] == 100 and [c["score"] for c in rep["criteria"]] == [4, 4, 4, 4, 4] and rep["scenario"] == ID
    assert rep["fairness"]["dropped"] == [] and rep["fairness"]["points"] == 20 and all(r["verified"] for r in rep["rows"])
    assert rep["kind"] == "demo" and rep["variant"] == "strong" and rep["attempt"] == 1
    assert [c["judge_name"] for c in rep["criteria"]] == ["Aarav", "Rohan", "Vikram", "Ananya", "Aarav"]
    assert rep["fairness"]["tests_rerun"]["ok"] is True
    started = events(s, "autoplay_started")[0]
    assert started["variant"] == "strong" and started["total"] == len(started["labels"]) and "form still closes with a green 'Appointment added'" in started["doc"] and started["tree"]["ready"]
    assert [e["path"] for e in events(s, "autoplay_open_file")] == ["tests/api/test_double_booking_api.py", "backend/main.py", SHELL]
    assert [e["writable"] for e in events(s, "autoplay_open_file")] == [False, False, True]  # the API and its tests are Rohan's: read-only; the page's shell is yours in this incident
    assert events(s, "autoplay_search")[0]["q"] == "409" and events(s, "autoplay_search")[0]["result"]["matches"] >= 1
    assert [e["path"] for e in events(s, "autoplay_edit")] == [REGRESSION, SHELL]
    assert "if (!res.ok) {" in events(s, "autoplay_edit")[1]["content"] and "!data" not in events(s, "autoplay_edit")[1]["content"].split("async function call")[1].split("return data")[0]
    assert [e["focus"] for e in events(s, "autoplay_step")][-1] == "debrief" and {e["focus"] for e in events(s, "autoplay_step")} == {"ide", "chat", "debrief"}
    assert events(s, "autoplay_ended")[0]["reason"] == "done" and events(s, "scenario_started")[0]["channel"]["name"] == "#incident-frontdesk"
    info = client.get(f"/api/projects/{pid}/session").json()
    kinds = [e["kind"] for e in info["events"]]
    assert kinds.count("file_saved") == 2 and kinds.count("search") == 1 and info["summary"]["hints"] <= 1
    assert not any(e.get("auto") for e in info["events"] if e["kind"] == "file_opened")
    assert [m["text"][:3] for m in events(s, "channel_message") if m.get("source") == "learner"] == ["On ", "Upd", "Fix"]
    assert "#incident-opd" not in str([r["source"] for r in rep["rows"]])


def test_the_weak_run_scores_exactly_30_and_the_gaps_are_the_ones_it_was_given(world):
    client, mgr, settings = world
    pid, s, rep = play(client, mgr, "weak", ID)
    assert [(c["id"], c["score"]) for c in rep["criteria"]] == [("communication", 0), ("diagnosis", 0), ("fix_quality", 4), ("testing", 0), ("ownership", 2)]
    assert rep["total"] == 30 and rep["kind"] == "demo" and rep["variant"] == "weak"
    held = {r["rule"] for r in rep["rows"] if r["kind"] == "strength"}
    assert held == {"every_path_reports_refusal", "refusal_message_shown", "small_change", "suite_green_on_main", "within_time_box", "no_scope_rejection"}
    gaps = {r["rule"] for r in rep["rows"] if r["kind"] == "gap"}
    assert {"first_update", "no_nudges", "names_the_cause", "reproduced_first", "read_the_response", "found_the_failing_code", "no_red_submit", "regression_test_added", "few_hints"} <= gaps
    log = client.get(f"/api/projects/{pid}/session").json()["events"]
    kinds = [e["kind"] for e in log]
    first_save = kinds.index("file_saved")
    assert "test_run" not in kinds[:first_save] and not any(e["kind"] == "message_posted" for e in log[:first_save])  # a patch first: no tests, no answer read, no update
    assert any(e["kind"] == "team_message" and e.get("ref") == "lead-nudge" for e in log)
    red = [e for e in log if e["kind"] == "submit_result" and not e["ok"]]
    assert [e["stage"] for e in red] == ["tests"] and log[-1]["kind"] == "session_finished"
    assert sorted(f.split("::")[1] for f in red[0]["failed"]) == sorted([  # the booking form was patched: every other screen still says it saved
        "test_moving_an_appointment_onto_a_taken_slot_is_refused_on_screen", "test_a_refused_status_button_shows_an_error_not_the_success_text",
        "test_a_refused_delete_does_not_say_removed", "test_a_refused_board_move_shows_an_error"])
    edits = events(s, "autoplay_edit")
    assert [e["path"] for e in edits] == [SHELL, SHELL] and "refused" in edits[0]["content"] and "if (!res.ok) {" in edits[1]["content"]
    assert [e["from"] for e in log if e["kind"] == "hint_given"] == ["backend", "backend"]  # Rohan's pointer at four minutes, then the question the script asks him


def test_the_two_runs_differ_by_seventy_and_both_are_demos(world):
    client, mgr, settings = world
    _, _, strong = play(client, mgr, "strong", ID)
    _, _, weak = play(client, mgr, "weak", ID)
    assert strong["total"] - weak["total"] == 70 and strong["rubric"] == weak["rubric"] == {"id": "opd-form-says-saved-v1", "version": 1}


def test_a_demo_of_the_third_scenario_has_its_own_history_and_never_counts_as_an_attempt(world):
    client, mgr, settings = world
    play(client, mgr, "strong", ID)
    assert History(settings.workspace, ID).attempts() == [] and History(settings.workspace, OTHER).attempts() == []
    assert [(a["attempt"], a["total"], a["variant"]) for a in History(settings.workspace, ID, "demo").attempts()] == [(1, 100, "strong")]
    assert History(settings.workspace, OTHER, "demo").attempts() == []


def test_stop_in_the_middle_cleans_up_a_run_of_the_third_scenario(world):
    client, mgr, settings = world
    pid, s = watch(client, mgr, "strong", ID)
    wait_for(lambda: events(s, "autoplay_edit") and events(s, "autoplay_edit")[0], 240, "the first edit")
    root = s.root
    r = client.post(f"/api/projects/{pid}/autoplay/stop")
    assert r.status_code == 200 and r.json()["stopped"] is True and not s.autoplay.alive()
    assert not events(s, "debrief_started") and client.get(f"/api/projects/{pid}/report").status_code == 404 and not root.exists()
    assert History(settings.workspace, ID, "demo").attempts() == []


def test_the_speed_switch_and_the_bad_requests_work_on_scenario_3(world):
    client, mgr, settings = world
    assert client.post(f"/api/scenarios/{ID}/autoplay", json={"variant": "great"}).status_code == 400
    pid, s = watch(client, mgr, "weak", ID)
    assert client.post(f"/api/projects/{pid}/autoplay/speed", json={"speed": 2}).json() == {"speed": 2}
    assert events(s, "autoplay_speed")[-1]["speed"] == 2
    assert client.post(f"/api/projects/{pid}/autoplay/stop").status_code == 200
