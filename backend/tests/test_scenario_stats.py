"""Step 5, second hand-test: the +/- lines of a save are against the file as the incident started (a file you created is all added), and the IDE's deliberate opens are logged."""
import pytest

from app.scenarios.scoring import event_text
from scenario_helpers import ScenarioLLM
from test_scenario_debrief import manager, start


@pytest.fixture
def scenario(tmp_path):
    client, mgr, settings = manager(tmp_path, ScenarioLLM())
    pid, s = start(client, mgr)
    yield client, s, pid
    s.orch.stop()
    mgr.shutdown()


def test_a_file_created_with_plus_and_pasted_is_all_added_however_often_it_is_saved(scenario):
    client, s, pid = scenario
    ide = f"/api/projects/{pid}/ide/backend"
    put = lambda path, content: client.put(f"{ide}/file", json={"path": path, "content": content})  # noqa: E731
    path = "tests/regression/test_regression_pasted.py"
    assert put(path, "").status_code == 200  # the "+" of the IDE creates the file empty
    for n in (42, 30, 42):  # pasted, replaced by something shorter, pasted again
        assert put(path, "".join(f"line {i}\n" for i in range(n))).status_code == 200
    saved = [(e["added"], e["removed"], e["created"]) for e in s.orch.log.events("file_saved")]
    assert saved == [(0, 0, True), (42, 0, False), (30, 0, False), (42, 0, False)]
    assert [event_text(e) for e in s.orch.log.events("file_saved")] == [f"Created {path} (empty file)", f"Saved {path} (+42 -0 lines)", f"Saved {path} (+30 -0 lines)", f"Saved {path} (+42 -0 lines)"]


def test_a_file_of_the_seed_is_compared_with_the_seed_not_with_the_save_before(scenario):
    client, s, pid = scenario
    ide = f"/api/projects/{pid}/ide/backend"
    put = lambda content: client.put(f"{ide}/file", json={"path": "backend/api/appointments.py", "content": content})  # noqa: E731
    seed = client.get(f"{ide}/file", params={"path": "backend/api/appointments.py"}).json()["content"].split("\n")
    one = list(seed)
    one[11] += "  # first"
    two = list(one)
    two[12] += "  # second"
    assert put("\n".join(one)).status_code == 200 and put("\n".join(two)).status_code == 200 and put("\n".join(seed)).status_code == 200  # the last one is back to the seed
    assert [(e["added"], e["removed"]) for e in s.orch.log.events("file_saved")] == [(1, 1), (2, 2), (0, 0)]


def test_clicking_a_file_that_is_open_already_is_a_deliberate_open_the_ide_logs_once(scenario):
    client, s, pid = scenario
    ide = f"/api/projects/{pid}/ide/backend"
    client.get(f"{ide}/file", params={"path": "backend/api/appointments.py", "auto": "true"})  # the IDE showed its first file by itself
    assert [(e["path"], e.get("auto", False)) for e in s.orch.log.events("file_opened")] == [("backend/api/appointments.py", True)]
    assert [x["state"] for x in s.orch.guide.state()["steps"]][1] == "todo"
    client.get(f"{ide}/file", params={"path": "backend/api/appointments.py"})  # the learner clicks it (the client reads it again so that the click is logged)
    assert [(e["path"], e.get("auto", False)) for e in s.orch.log.events("file_opened")][1:] == [("backend/api/appointments.py", False)]
    assert [x["state"] for x in s.orch.guide.state()["steps"]][1] == "done"
