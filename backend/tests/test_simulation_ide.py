"""Simulation mode, step 3: the in-app IDE endpoints (files, save, run tests) and the scope check on Submit. The fake team plays the AI employees; the test plays the person."""
import subprocess
from pathlib import Path

import pytest

from api_helpers import make_client, wait_for
from test_simulation import SimLLM, assigned, of_type, sim, solve_db, start, write_db_tests

GOAL = "Build a calculator with history"


@pytest.fixture
def build(tmp_path):
    """A running simulation build where the person plays the database engineer, waiting at their task."""
    client, settings, mgr = make_client(tmp_path)
    r = client.post("/api/projects", json={"goal": GOAL, "mode": "simulation", "human_roles": ["database"]})
    assert r.status_code == 201
    pid = r.json()["id"]
    s = mgr.get(pid)
    ev = assigned(s.bus)
    yield client, s, pid, ev, Path(ev["worktree"])
    s.orch.stop()
    mgr.shutdown()


def ide(pid, role="database", what="tree"):
    return f"/api/projects/{pid}/ide/{role}/{what}"


def result(s, n=1):
    return wait_for(lambda: len(of_type(s.bus, "human_test_result")) >= n and of_type(s.bus, "human_test_result")[n - 1], 90, "the test result")


# -- files -------------------------------------------------------------------------------------------

def test_the_tree_marks_what_the_person_may_edit_and_who_owns_the_rest(build):
    client, s, pid, ev, wt = build
    tree = client.get(ide(pid)).json()
    assert tree["ready"] and tree["task"] == "t1" and tree["running"] is False and tree["names"]["backend"]
    files = {f["path"]: f for f in tree["files"]}
    assert files["database/calculations.py"]["writable"] and files["database/calculations.py"]["owner"] == "database"
    assert files["database/connection.py"]["writable"] is False and files["database/connection.py"]["owner"] == "database"  # locked: the preset's
    assert files["backend/main.py"]["writable"] is False and files["backend/main.py"]["owner"] == "backend"
    assert not any(f["writable"] for p, f in files.items() if p.startswith(("tests/api/", "backend/", "static/")))
    assert not any(p.startswith((".git/", ".worktrees/", "__pycache__")) for p in files)
    assert tree["editable"][0] == "database/**"


def test_save_writes_only_inside_the_owned_paths(build):
    client, s, pid, ev, wt = build
    put = lambda path, content="x = 1\n": client.put(ide(pid, what="file"), json={"path": path, "content": content})  # noqa: E731
    ok = put("database/calculations.py", "# mine\n")
    assert ok.status_code == 200 and ok.json()["path"] == "database/calculations.py" and (wt / "database" / "calculations.py").read_text(encoding="utf-8") == "# mine\n"
    assert client.get(ide(pid, what="file"), params={"path": "database/calculations.py"}).json()["content"] == "# mine\n"
    assert put("database/helpers.py").status_code == 200 and (wt / "database" / "helpers.py").is_file()  # a new file in my folder
    assert put("tests/test_db_extra.py").status_code == 200  # the database engineer's own tests
    for bad in ("backend/api/calculator.py", "backend/main.py", "database/connection.py", "tests/api/test_x.py", "static/app.js", ".q/spec.md", "../outside.py",
                "database/../../outside.py", "C:/Windows/x.py", "/etc/x", ".git/config", "database/.git/x"):
        r = put(bad)
        assert r.status_code in (400, 403), (bad, r.status_code, r.text)
        assert r.json()["detail"] if "detail" in r.json() else r.json()
    assert not (wt.parent.parent / "outside.py").exists() and not (wt.parent / "outside.py").exists() and not (wt / "outside.py").exists()
    assert not (wt / "backend" / "api" / "calculator.py").exists() and not (wt / "static" / "app.js").read_text(encoding="utf-8").startswith("x = 1")
    assert client.put(ide(pid, what="file"), json={"path": "database/big.py", "content": "x" * 400_000}).status_code == 413


def test_reading_refuses_paths_outside_the_project(build):
    client, s, pid, ev, wt = build
    get = lambda path: client.get(ide(pid, what="file"), params={"path": path})  # noqa: E731
    assert get("backend/main.py").status_code == 200  # everything inside the project is readable
    for bad in ("../x", "..\\x", "C:/Windows/win.ini", "/etc/passwd", ".git/config", ""):
        assert get(bad).status_code in (400, 404), bad
    assert get("nope.py").status_code == 404


def test_only_a_role_the_person_plays_has_an_ide(build):
    client, s, pid, ev, wt = build
    for role in ("backend", "frontend", "qa", "nobody"):
        assert client.get(ide(pid, role)).status_code == 404
        assert client.put(ide(pid, role, "file"), json={"path": "backend/x.py", "content": ""}).status_code == 404
        assert client.post(ide(pid, role, "tests")).status_code == 404


def test_nothing_can_be_edited_without_an_open_task(build):
    client, s, pid, ev, wt = build
    solve_db(ev["worktree"])
    assert client.post(f"/api/projects/{pid}/tasks/t1/submit").json()["stage"] == "accepted"
    tree = client.get(ide(pid)).json()
    assert tree["task"] is None and not any(f["writable"] for f in tree["files"])
    assert client.put(ide(pid, what="file"), json={"path": "database/calculations.py", "content": ""}).status_code == 409
    assert client.post(ide(pid, what="tests")).status_code == 409
    assert client.get(ide(pid, what="file"), params={"path": "database/calculations.py"}).status_code == 200  # still readable


def test_the_ide_is_not_ready_before_the_role_has_a_folder(tmp_path):
    o, bus = sim(tmp_path, SimLLM())
    assert o.ide_tree("database")["ready"] is False  # nothing was designed yet
    from app.humanide import IDEError
    with pytest.raises(IDEError) as e:
        o.ide_read("database", "x.py")
    assert e.value.status == 409
    with pytest.raises(IDEError) as e:
        o.ide_tree("backend")  # a role the person does not play: not even a tree
    assert e.value.status == 404


# -- run tests -------------------------------------------------------------------------------------------

def test_a_red_run_streams_its_output_and_lists_every_test(build):
    client, s, pid, ev, wt = build
    write_db_tests(wt)  # tests that fail against the generated stub
    r = client.post(ide(pid, what="tests"))
    assert r.status_code == 200 and r.json() == {"started": True, "task": "t1"}
    res = result(s)
    assert res["ok"] is False and res["task"] == "t1" and res["agent"] == "database" and res["failed"] >= 1
    ids = {t["id"]: t["outcome"] for t in res["tests"]}
    assert ids["tests/test_db_calculations.py::test_add_and_list"] == "failed"
    assert res["passed"] + res["failed"] == len([o for o in ids.values() if o in ("passed", "failed")])
    assert "failed" in res["summary"]
    out = [e["line"] for e in of_type(s.bus, "human_test_output")]
    assert any("test_add_and_list" in l for l in out) and any("NotImplementedError" in l for l in out)
    assert of_type(s.bus, "human_test_started")[0]["task"] == "t1"
    assert [e["type"] for e in s.bus.history if e["type"].startswith("human_test_")][0] == "human_test_started"
    assert s.bus.history.index(of_type(s.bus, "human_test_output")[0]) < s.bus.history.index(of_type(s.bus, "human_test_result")[0])  # the lines come before the verdict
    assert client.get(ide(pid)).json()["running"] is False
    assert s.orch._status("t1") == "running"  # a test run does not submit anything
    assert not of_type(s.bus, "human_submit_result")


def test_a_green_run_after_saving_through_the_api(build):
    client, s, pid, ev, wt = build
    solve_db(ev["worktree"], tests=False)
    from test_orchestrator import DB_TESTS
    assert client.put(ide(pid, what="file"), json={"path": "tests/test_db_calculations.py", "content": DB_TESTS}).status_code == 200
    assert client.post(ide(pid, what="tests")).status_code == 200
    res = result(s)
    assert res["ok"] is True and res["failed"] == 0 and res["passed"] >= 1 and "passed" in res["summary"]
    assert all(t["outcome"] == "passed" for t in res["tests"])


def test_one_run_at_a_time_and_no_submit_during_a_run(build):
    client, s, pid, ev, wt = build
    write_db_tests(wt)
    first = client.post(ide(pid, what="tests"))
    assert first.status_code == 200
    second = client.post(ide(pid, what="tests"))  # the first is still collecting: pytest takes longer than a request
    assert second.status_code == 409 and "already running" in second.json()["detail"]
    assert client.post(f"/api/projects/{pid}/tasks/t1/submit").status_code == 409
    assert client.get(ide(pid)).json()["running"] is True
    result(s)
    wait_for(lambda: client.get(ide(pid)).json()["running"] is False, 10, "the run to be released")
    assert client.post(ide(pid, what="tests")).status_code == 200  # and a new run is fine afterwards
    result(s, 2)


def test_stop_kills_a_run_in_progress(build):
    client, s, pid, ev, wt = build
    (wt / "tests").mkdir(exist_ok=True)
    (wt / "tests" / "test_db_slow.py").write_text("import time\n\ndef test_slow():\n    time.sleep(60)\n", encoding="utf-8")
    assert client.post(ide(pid, what="tests")).status_code == 200
    wait_for(lambda: any("collected" in e["line"] for e in of_type(s.bus, "human_test_output")), 60, "the slow test to start")
    s.orch.stop()
    res = result(s)
    assert res["ok"] is False and "stopped" in res["summary"]


# -- Submit checks the scope too -------------------------------------------------------------------------------

def test_submit_rejects_files_outside_the_role_and_lists_them(build):
    client, s, pid, ev, wt = build
    solve_db(ev["worktree"])
    (wt / "backend" / "api" / "calculator.py").write_text("# sneaky\n", encoding="utf-8")  # edited outside the IDE
    (wt / "static" / "extra.js").write_text("// hi\n", encoding="utf-8")
    (wt / "database" / "connection.py").write_text("# locked\n", encoding="utf-8")
    r = client.post(f"/api/projects/{pid}/tasks/t1/submit")
    body = r.json()
    assert r.status_code == 200 and body["ok"] is False and body["stage"] == "scope"
    assert body["files"] == ["backend/api/calculator.py", "database/connection.py", "static/extra.js"]
    assert all(f in body["summary"] for f in body["files"])
    ev_res = of_type(s.bus, "human_submit_result")[-1]
    assert ev_res["stage"] == "scope" and ev_res["files"] == body["files"] and ev_res["ok"] is False
    assert not of_type(s.bus, "test_result") and "[human] DB functions" not in subprocess.run(["git", "log", "--all", "--format=%s"], cwd=s.orch.root, capture_output=True, text=True).stdout
    assert s.orch._status("t1") == "running"
    # even a commit made by hand does not hide it
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run(["git", "-c", "user.name=me", "-c", "user.email=me@x", "commit", "-qm", "mine"], cwd=wt, check=True)
    assert client.post(f"/api/projects/{pid}/tasks/t1/submit").json()["stage"] == "scope"
    # reverting them lets the work through, with the generated stub and tests that came with the task not counted as the person's change
    subprocess.run(["git", "checkout", "main", "--", "database/connection.py"], cwd=wt, check=True)
    (wt / "backend" / "api" / "calculator.py").unlink()
    (wt / "static" / "extra.js").unlink()
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run(["git", "-c", "user.name=me", "-c", "user.email=me@x", "commit", "-qm", "revert"], cwd=wt, check=True)
    ok = client.post(f"/api/projects/{pid}/tasks/t1/submit").json()
    assert ok["ok"] is True and ok["stage"] == "accepted", ok
    wait_for(lambda: s.state in ("done", "failed"), 120, "the build")
    assert s.state == "done", s.status()["problems"]


def test_a_person_who_only_edits_their_own_files_is_never_flagged(build):
    client, s, pid, ev, wt = build
    solve_db(ev["worktree"])  # the generated stub, its tests and the person's changes: all inside the role
    assert client.post(f"/api/projects/{pid}/tasks/t1/submit").json()["stage"] == "accepted"


def test_the_ide_endpoints_refuse_a_replay(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import ROOT
    from app.main import create_app
    from app.registry import ModelRegistry
    from app.session import SessionManager
    from api_helpers import make_settings
    settings = make_settings(tmp_path)
    settings.recordings = ROOT / "recordings"
    mgr = SessionManager(settings, ModelRegistry.load(env={}), llm_factory=lambda *a: pytest.fail("replay must never build a model client"))
    client = TestClient(create_app(settings, mgr))
    pid = client.post("/api/projects", json={"goal": "x", "mode": "supervised", "demo": True, "recording": "todo-approvals", "speed": 1000}).json()["id"]
    assert client.get(ide(pid)).status_code == 409
    assert client.put(ide(pid, what="file"), json={"path": "a.py", "content": ""}).status_code == 409
    assert client.post(ide(pid, what="tests")).status_code == 409
    mgr.shutdown()
