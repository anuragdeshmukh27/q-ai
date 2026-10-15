"""Attempt history is per scenario: a learner's attempts at "Bookings are down" and at "Double bookings" are numbered, scored and listed apart, and a demo of either never counts in them."""
from app.scenarios.autoplay import reference_fix, regression_test
from app.scenarios.reports import History

from api_helpers import wait_for
from scenario_helpers import ScenarioLLM
from test_scenario_debrief import events, manager, strong_attempt as strong_one

ONE, TWO = "opd-bookings-down", "opd-double-bookings"
MIGRATION = "database/migrations/0008_one_booking_per_slot.sql"
REGRESSION = "tests/regression/test_regression_double_booking.py"


def start(client, mgr, sid):
    r = client.post(f"/api/scenarios/{sid}/start")
    assert r.status_code == 201, r.text
    s = mgr.get(r.json()["id"])
    wait_for(lambda: next(iter(events(s, "human_task_assigned")), None), 90, "the task to be handed over")
    return r.json()["id"], s


def run_tests(client, s, pid, role):
    n = len(events(s, "human_test_result"))
    client.post(f"/api/projects/{pid}/ide/{role}/tests")
    return wait_for(lambda: len(events(s, "human_test_result")) > n and events(s, "human_test_result")[n], 120, "the test result")


def strong_two(client, s, pid):
    """The database engineer's strong attempt: tests, the data, the index migration, an update, a regression test, the migration, green, a closing post, Submit."""
    ide = f"/api/projects/{pid}/ide/database"
    assert run_tests(client, s, pid, "database")["ok"] is False
    client.get(f"{ide}/file", params={"path": "fixtures/prod_snapshot.sql"})
    client.get(f"{ide}/file", params={"path": "database/migrations/0006_index_appointments_by_doctor_and_slot.sql"})
    client.post(f"/api/projects/{pid}/channel", json={"text": "Update: nothing in the database stops a second Booked row for a slot; three slots already hold duplicates. Writing a migration."})
    assert client.put(f"{ide}/file", json={"path": REGRESSION, "content": regression_test(TWO)}).status_code == 200
    assert run_tests(client, s, pid, "database")["ok"] is False
    assert client.put(f"{ide}/file", json={"path": MIGRATION, "content": reference_fix({}, TWO, create=(MIGRATION,))[MIGRATION]}).status_code == 200
    assert run_tests(client, s, pid, "database")["ok"] is True
    client.post(f"/api/projects/{pid}/channel", json={"text": "Fix is ready: migration 0008 cancels the later duplicates and adds the partial unique index. Submitting."})
    answer = {}
    for _ in range(4):
        answer = client.post(f"/api/projects/{pid}/tasks/h1/submit").json()
        if answer["ok"]:
            break
    assert answer["ok"] and answer["stage"] == "accepted"


def finish(client, s, pid):
    wait_for(lambda: next(iter(events(s, "debrief_ended")), None), 120, "the debrief")
    return client.get(f"/api/projects/{pid}/report").json()


def test_each_scenario_counts_its_own_attempts_and_a_report_lists_only_its_own(tmp_path):
    client, mgr, settings = manager(tmp_path, ScenarioLLM("Rohan: the route only inserts the row; the rule belongs in the database."))
    try:
        pid, s = start(client, mgr, ONE)
        assert events(s, "scenario_started")[0]["attempt"] == 1
        strong_one(client, s, pid)
        first = finish(client, s, pid)
        assert first["scenario"] == ONE and first["attempt"] == 1 and [a["attempt"] for a in first["attempts"]] == [1]

        pid, s = start(client, mgr, TWO)  # the other scenario starts at attempt 1, whatever the first one has done
        assert events(s, "scenario_started")[0]["attempt"] == 1
        strong_two(client, s, pid)
        second = finish(client, s, pid)
        assert second["scenario"] == TWO and second["attempt"] == 1 and second["total"] == 100 and [a["attempt"] for a in second["attempts"]] == [1]
        assert [a["project"] for a in second["attempts"]] != [a["project"] for a in first["attempts"]]

        pid, s = start(client, mgr, TWO)  # a second attempt at the second scenario: 2, with its first attempt in the report
        assert events(s, "scenario_started")[0]["attempt"] == 2
        strong_two(client, s, pid)
        again = finish(client, s, pid)
        assert again["attempt"] == 2 and [(a["attempt"], a["total"]) for a in again["attempts"]] == [(1, 100), (2, 100)]

        pid, s = start(client, mgr, ONE)  # and the first scenario goes on from its own history
        assert events(s, "scenario_started")[0]["attempt"] == 2
        s.orch.stop()

        assert [(a["attempt"], a["total"]) for a in History(settings.workspace, ONE).attempts()] == [(1, 100)]
        assert [(a["attempt"], a["total"]) for a in History(settings.workspace, TWO).attempts()] == [(1, 100), (2, 100)]
        files = sorted(p.name for p in (settings.workspace / ".q-attempts").iterdir())
        assert files == [f"{ONE}.json", f"{TWO}.json"]  # one history file per scenario, no demo file
    finally:
        mgr.shutdown()
