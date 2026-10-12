"""Step 5 after the hand-test, through the API: project-wide search (read-only files included, logged as a session event), the stats of a new file, and the channel's hints."""
import pytest

from scenario_helpers import ScenarioLLM
from test_scenario_debrief import events, manager, start

MIGRATION = "database/migrations/0007_rename_slot_time_to_slot_at.sql"


@pytest.fixture
def scenario(tmp_path):
    llm = ScenarioLLM("Migration 0007 renamed the column.")
    client, mgr, settings = manager(tmp_path, llm)
    pid, s = start(client, mgr)
    yield client, s, pid, llm
    s.orch.stop()
    mgr.shutdown()


def search(client, pid, q, role="backend"):
    return client.get(f"/api/projects/{pid}/ide/{role}/search", params={"q": q})


def test_a_search_finds_lines_in_every_file_of_the_folder_read_only_ones_included(scenario):
    client, s, pid, llm = scenario
    r = search(client, pid, "slot_time")
    assert r.status_code == 200
    out = r.json()
    paths = {f["path"]: f for f in out["results"]}
    assert out["query"] == "slot_time" and out["matches"] >= 6 and out["files"] == len(paths) == out["files"] and out["truncated"] is False
    assert {"backend/api/appointments.py", "backend/api/doctors.py", MIGRATION} <= set(paths)  # the migration is read-only for the learner and is searched anyway
    doctors = paths["backend/api/doctors.py"]
    assert doctors["count"] == 1 and doctors["lines"][0]["line"] == 95 and 'row["slot_time"]' in doctors["lines"][0]["text"]
    assert paths["backend/api/appointments.py"]["count"] == len(paths["backend/api/appointments.py"]["lines"]) >= 4
    assert out["matches"] == sum(f["count"] for f in out["results"])


def test_the_search_is_case_insensitive_literal_and_skips_caches_and_binaries(scenario):
    client, s, pid, llm = scenario
    assert search(client, pid, "SLOT_TIME").json()["matches"] == search(client, pid, "slot_time").json()["matches"]
    assert search(client, pid, "def (").json()["matches"] == 0  # not a pattern
    assert not [f for f in search(client, pid, "slot_time").json()["results"] if "__pycache__" in f["path"] or f["path"].endswith(".pyc")]
    assert search(client, pid, "zzz_not_there").json() == {"query": "zzz_not_there", "matches": 0, "files": 0, "truncated": False, "results": []}


def test_every_search_is_logged_with_its_query_and_how_much_it_found(scenario):
    client, s, pid, llm = scenario
    search(client, pid, "slot_time")
    search(client, pid, "nothing_like_this")
    logged = s.orch.log.events("search")
    assert [(e["query"], e["matches"] > 0) for e in logged] == [("slot_time", True), ("nothing_like_this", False)] and logged[0]["files"] >= 3 and logged[0]["role"] == "backend"
    assert client.get(f"/api/projects/{pid}/session").json()["summary"]["searches"] == 2
    assert [e["kind"] for e in events(s, "session_event") if e["kind"] == "search"] == ["search", "search"]


def test_a_search_must_be_two_to_two_hundred_characters_and_for_a_role_you_play(scenario):
    client, s, pid, llm = scenario
    assert search(client, pid, "a").status_code == 400 and search(client, pid, "x" * 201).status_code == 400 and search(client, pid, "  ").status_code == 400
    assert search(client, pid, "slot_time", role="frontend").status_code == 404
    assert s.orch.log.events("search") == []  # refused searches are not logged


def test_a_new_file_counts_its_lines_as_added_and_is_marked_created(scenario):
    client, s, pid, llm = scenario
    put = lambda path, content: client.put(f"/api/projects/{pid}/ide/backend/file", json={"path": path, "content": content})  # noqa: E731
    assert put("tests/regression/test_regression_a.py", "def test_a():\n    assert True\n\n\ndef test_b():\n    assert True\n").status_code == 200
    assert put("tests/regression/test_regression_empty.py", "").status_code == 200
    assert put("tests/regression/test_regression_a.py", "def test_a():\n    assert True\n").status_code == 200  # an edit of a file that exists now
    saved = s.orch.log.events("file_saved")
    assert [(e["path"].rsplit("/", 1)[1], e["added"], e["removed"], e["created"]) for e in saved] == [("test_regression_a.py", 6, 0, True), ("test_regression_empty.py", 0, 0, True), ("test_regression_a.py", 2, 0, False)]  # a file you created is all added, however often you save it


def test_a_status_update_is_acknowledged_once_and_costs_no_hint_but_a_question_does(scenario):
    client, s, pid, llm = scenario
    post = lambda text, to=None: client.post(f"/api/projects/{pid}/channel", json={"text": text, "to": to})  # noqa: E731
    assert post("Bookings fail since migration 0007 renamed slot_time to slot_at. Fixing now.").json()["pending"] == []
    assert post("Still on it, the routes first.", "architect").json()["pending"] == []
    s.orch.director.join()
    replies = [e for e in events(s, "channel_message") if e.get("reply_to")]
    assert [(e["from"], e["source"], e.get("hint", False)) for e in replies] == [("architect", "scripted", False), ("architect", "scripted", False)]
    assert llm.chat_calls == 0 and client.get(f"/api/projects/{pid}/session").json()["summary"]["hints"] == 0
    assert post("Karan, what changed on Monday?", "database").json()["pending"] == ["database"]
    s.orch.director.join()
    assert llm.chat_calls == 1 and client.get(f"/api/projects/{pid}/session").json()["summary"]["hints"] == 1
    hint = s.orch.log.events("hint_given")[0]
    assert hint["from"] == "database" and hint["text"] == "Migration 0007 renamed the column." and hint["n"] == 1

