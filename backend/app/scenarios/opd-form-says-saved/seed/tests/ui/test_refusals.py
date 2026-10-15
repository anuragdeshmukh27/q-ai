"""What the pages do with the answers of the API. The page runs in Node (tests/ui/refusals.mjs) and is given the REAL answers of the real API (tests/ui/probe.py `live_answers`),
so these tests say what a person at the front desk sees when the server refuses a request, or accepts it."""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from tests.ui.probe import live_answers, pinned_answers, run_node


@pytest.fixture
def live():
    with TestClient(app) as client:
        return live_answers(client)


def shown(live, name):
    case = live[name]
    return case["body"]["detail"], run_node(case)


def no_success_message(out):
    assert not [t["text"] for t in out["toasts"] if t["kind"] == "success"], f"the page announced a success: {out['toasts']}"


def refused_in_the_form(live, name):
    detail, out = shown(live, name)
    assert out["formOpen"], f"the form closed although the server answered {live[name]['status']} {detail!r}: nothing was saved"
    assert out["formError"] == detail, f"the form should say what the server said ({detail!r}), it says {out['formError']!r}"
    assert out["saveEnabled"], "the Save button stays disabled after a refusal: the person cannot try again"
    no_success_message(out)


def refused_with_a_toast(live, name):
    detail, out = shown(live, name)
    errors = [t["text"] for t in out["toasts"] if t["kind"] == "error"]
    assert any(detail in t for t in errors), f"the page should show an error saying {detail!r}; the toasts are {out['toasts']}"
    no_success_message(out)


# --- what a refusal looks like on the screen ----------------------------------------------------------------------------------------------------------

def test_a_taken_slot_keeps_the_booking_form_open_and_says_why(live):
    refused_in_the_form(live, "create_taken")


def test_an_invalid_phone_shows_the_servers_message_in_the_form(live):
    refused_in_the_form(live, "create_bad_phone")


def test_moving_an_appointment_onto_a_taken_slot_is_refused_on_screen(live):
    refused_in_the_form(live, "edit_taken")


def test_a_refused_status_button_shows_an_error_not_the_success_text(live):
    refused_with_a_toast(live, "action_refused")


def test_a_refused_delete_does_not_say_removed(live):
    refused_with_a_toast(live, "delete_missing")


def test_a_refused_board_move_shows_an_error(live):
    refused_with_a_toast(live, "board_refused")


# --- what must keep working -----------------------------------------------------------------------------------------------------------------------

def test_a_saved_booking_still_closes_the_form_and_says_so(live):
    out = run_node(live["create_ok"])
    assert not out["formOpen"] and [t["text"] for t in out["toasts"] if t["kind"] == "success"] == ["Appointment added"]
    assert out["reloaded"] > 0, "the list is read again after a booking"


def test_a_saved_edit_status_change_and_delete_still_say_so(live):
    said = {name: [t["text"] for t in run_node(live[name])["toasts"] if t["kind"] == "success"] for name in ("edit_ok", "action_ok", "delete_ok")}
    assert said == {"edit_ok": ["Saved"], "action_ok": ["Sana Sheikh: Cancelled"], "delete_ok": ["Removed"]}


def test_an_answer_that_is_not_json_still_shows_an_error(live):
    out = run_node(live["no_json"])
    assert out["formOpen"] and out["formError"] == "Please check your input"
    no_success_message(out)


def test_the_pinned_answers_are_what_the_api_says(live):
    """tests/ui/answers.json is the copy the debrief uses; it must say what the API says today."""
    pinned = pinned_answers()
    for name, case in live.items():
        assert pinned[name]["status"] == case["status"], name
        assert pinned[name].get("body", {}).get("detail") == case.get("body", {}).get("detail"), name
