"""Simulation mode, step 2: tasks a person works on. A scripted fake team (no Ollama) plays the AI employees; the test plays the human."""
import subprocess
import threading

import pytest

from app.agent.review import ReviewItem, ReviewOutput
from app.events import EventBus
from app.llm import StructuredResult
from app.orchestrator import MAX_HUMAN_REVIEWS, Orchestrator
from app.registry import ModelRegistry
from app.sandbox.commands import ASK, CommandPolicy, apply_mode
from app.schemas import PlannerOutput

from api_helpers import make_client, wait_for
from test_orchestrator import DB_ADD, DB_LIST, DB_TESTS, FakeLLM

# database -> backend as the planner must order them; the page does not wait for the backend, so it runs while the database task waits for a person
SIM_PLAN = {"tasks": [
    {"id": "t1", "title": "DB functions", "owner": "database", "depends_on": [], "files": ["database/calculations.py"], "acceptance": ["add and list work"]},
    {"id": "t2", "title": "API router", "owner": "backend", "depends_on": ["t1"], "files": ["backend/api/calculator.py"], "acceptance": ["POST /api/calculate returns 201"]},
    {"id": "t3", "title": "Page", "owner": "frontend", "depends_on": [], "files": ["static/index.html", "static/style.css"], "acceptance": ["has a form"]},
    {"id": "t4", "title": "Script", "owner": "frontend", "depends_on": ["t3"], "files": ["static/app.js"], "acceptance": ["calls the API"]},
]}
CHANGES = ReviewOutput(verdict="REQUEST_CHANGES", summary="one thing to fix", items=[ReviewItem(file="database/calculations.py", problem="list_history returns the oldest rows first but the contract says newest first")])


class SimLLM(FakeLLM):
    """The FakeLLM with the plan above; the Reviewer's answers for the human's tasks come from `human_reviews` (the AI tasks' reviews are always PASS)."""

    def __init__(self, human_reviews=(), human_ids=("t1", "h1")):
        super().__init__()
        self.human_reviews, self.human_ids = list(human_reviews), human_ids

    def call(self, model_id, messages, schema_model, temperature=0.2):
        if schema_model is PlannerOutput:
            self.models_used.append((model_id, "PlannerOutput"))
            return StructuredResult(PlannerOutput.model_validate(SIM_PLAN), model_id, 1, 10, 5, 0.01, "{}")
        if schema_model is ReviewOutput and any(f"Task {i} " in messages[1]["content"] for i in self.human_ids):
            self.models_used.append((model_id, "ReviewOutput"))
            return StructuredResult(self.human_reviews.pop(0) if self.human_reviews else ReviewOutput(verdict="PASS", summary="looks fine"), model_id, 1, 10, 5, 0.01, "{}")
        return super().call(model_id, messages, schema_model, temperature)


def sim(tmp_path, llm, roles=("database",), **kw):
    bus = EventBus()
    o = Orchestrator("Build a calculator with history", ModelRegistry.load(env={}), llm, bus, mode="simulation", human_roles=roles, base=tmp_path, start_app=False, **kw)
    return o, bus


def start(o):
    out: dict = {}
    th = threading.Thread(target=lambda: out.update(res=o.run()), daemon=True)
    th.start()
    return th, out


def of_type(bus, t):
    return [e for e in bus.history if e["type"] == t]


def assigned(bus):
    return wait_for(lambda: next(iter(of_type(bus, "human_task_assigned")), None), 90, "the human task to be handed over")


def solve_db(worktree, tests=True):
    """What the person does in their editor: fill in the generated stub and add the tests the Reviewer asks the database engineer for."""
    from pathlib import Path
    wt = Path(worktree)
    path = wt / "database" / "calculations.py"
    parts = path.read_text(encoding="utf-8").split("    raise NotImplementedError")
    assert len(parts) == 3
    indent = lambda code: "\n".join("    " + line for line in code.splitlines())  # noqa: E731
    path.write_text(parts[0] + indent(DB_ADD) + parts[1] + indent(DB_LIST) + parts[2], encoding="utf-8", newline="\n")
    if tests:
        write_db_tests(wt)


def write_db_tests(wt):
    (wt / "tests").mkdir(exist_ok=True)
    (wt / "tests" / "test_db_calculations.py").write_text(DB_TESTS, encoding="utf-8", newline="\n")


def git_subjects(root):
    return subprocess.run(["git", "log", "--all", "--format=%s"], cwd=root, capture_output=True, text=True).stdout.splitlines()


# -- the human's database task waits while the AI employees keep working -----------------------------------

def test_the_human_task_waits_without_holding_a_worker_and_dependents_start_after_the_merge(tmp_path):
    o, bus = sim(tmp_path, SimLLM(), max_parallel=1)  # one AI worker: a waiting person must not take it
    th, out = start(o)
    ev = assigned(bus)
    plan = of_type(bus, "plan_created")[0]["tasks"]
    assert [t["id"] for t in plan if t.get("assignee") == "human"] == ["t1"] and all("assignee" not in t for t in plan if t["id"] != "t1")
    assert ev["agent"] == "database" and ev["task"] == "t1" and ev["owner"] == "database" and ev["files"] == ["database/calculations.py"]
    doc = (o.root / ev["doc"]).read_text(encoding="utf-8")
    assert "# t1: DB functions" in doc and ev["worktree"] in doc and "database/**" in doc and "NotImplementedError" in doc and "python -m pytest -q" in doc
    assert (o.root / ".worktrees" / "database" / "database" / "calculations.py").is_file() and ev["worktree"].endswith("database")
    # the page runs and is merged while the database desk waits for the person
    wait_for(lambda: o._status("t3") == "done", 90, "the AI page task to finish while the human task waits")
    assert o._status("t1") == "running" and o._status("t2") == "pending"
    assert [e["state"] for e in bus.history if e["type"] == "agent_state" and e["agent"] == "database"][-1] == "waiting_human"
    solve_db(ev["worktree"])
    result = o.submit_human_task("t1")
    assert result["ok"] and result["stage"] == "accepted"
    th.join(120)
    res = out["res"]
    assert res.ok, res.problems
    assert [t["status"] for t in res.tasks] == ["done"] * 5  # t1..t4 and QA's task
    t = [e["type"] + ":" + e.get("agent", "") for e in bus.history]
    merged = next(i for i, e in enumerate(bus.history) if e["type"] == "merge_result" and e["branch"] == "agent/database")
    backend_start = next(i for i, e in enumerate(bus.history) if e["type"] == "task_assigned" and e["agent"] == "backend")
    assert merged < backend_start, t  # the dependent starts after the human's work is merged
    assert "[human] DB functions" in git_subjects(o.root)
    assert not any(e["type"] in ("escalation", "contract_repair", "consultant_called") for e in bus.history)
    assert of_type(bus, "simulation_started")[0]["human_roles"] == ["database"]


def test_without_simulation_nothing_changes(tmp_path):
    from test_orchestrator import make
    o, bus = make(tmp_path, FakeLLM())
    res = o.run()
    assert res.ok and not of_type(bus, "simulation_started") and not of_type(bus, "human_task_assigned")
    assert all("assignee" not in t for e in of_type(bus, "plan_created") for t in e["tasks"])


# -- Submit ----------------------------------------------------------------------------------------------

def test_a_red_submit_leaves_the_task_open_and_a_fixed_one_is_merged(tmp_path):
    o, bus = sim(tmp_path, SimLLM())
    th, out = start(o)
    ev = assigned(bus)
    from pathlib import Path
    write_db_tests(Path(ev["worktree"]))  # tests that fail against the generated stub
    red = o.submit_human_task("t1")
    assert not red["ok"] and red["stage"] == "tests" and any("test_add_and_list" in f for f in red["failed"])
    r = of_type(bus, "human_submit_result")
    assert len(r) == 1 and r[0]["ok"] is False and r[0]["task"] == "t1" and r[0]["stage"] == "tests" and r[0]["failed"] == red["failed"]
    assert of_type(bus, "test_result")[-1]["passed"] is False
    assert o._status("t1") == "running" and [e["state"] for e in bus.history if e["type"] == "agent_state" and e["agent"] == "database"][-1] == "waiting_human"
    assert not any(e["type"] in ("escalation", "escalation_action", "contract_repair", "consultant_called") for e in bus.history)
    assert not any(e["type"] == "plan_created" and e.get("replan") for e in bus.history)  # no re-plan for a person
    assert "[human] DB functions" not in git_subjects(o.root)  # red work is not committed
    solve_db(ev["worktree"], tests=False)
    green = o.submit_human_task("t1")
    assert green["ok"] and green["stage"] == "accepted"
    assert [e["ok"] for e in of_type(bus, "human_submit_result")] == [False, True]
    th.join(120)
    assert out["res"].ok, out["res"].problems
    assert "[human] DB functions" in git_subjects(o.root)
    assert "INSERT INTO calculations" in (o.root / "database" / "calculations.py").read_text(encoding="utf-8")  # the person's code is on main


def test_the_reviewer_sends_green_work_back_twice_and_the_third_green_submit_is_accepted(tmp_path):
    o, bus = sim(tmp_path, SimLLM(human_reviews=[CHANGES, CHANGES, CHANGES]))
    th, out = start(o)
    ev = assigned(bus)
    solve_db(ev["worktree"])
    for rnd in range(1, MAX_HUMAN_REVIEWS + 1):
        back = o.submit_human_task("t1")
        assert not back["ok"] and back["stage"] == "review" and back["items"][0]["file"] == "database/calculations.py"
        fb = of_type(bus, "review_feedback")
        assert len(fb) == rnd and fb[-1]["task"] == "t1" and fb[-1]["round"] == rnd and "newest first" in fb[-1]["items"][0]["problem"]
        assert o._status("t1") == "running" and not of_type(bus, "human_submit_result")
    accepted = o.submit_human_task("t1")  # the third green submit: accepted although the Reviewer still has an item
    assert accepted["ok"] and accepted["stage"] == "accepted" and len(accepted["items"]) == 1
    assert len(of_type(bus, "review_feedback")) == MAX_HUMAN_REVIEWS
    assert [e["round"] for e in of_type(bus, "review_result") if e["task"] == "t1"] == [1, 2, 3]
    assert "accepted from the human with open review items" in o.memory.read("decisions.md")
    th.join(120)
    assert out["res"].ok, out["res"].problems


# -- a human task without the planner -----------------------------------------------------------------------

def test_add_human_task_works_without_the_planner(tmp_path):
    llm = SimLLM()
    o, bus = sim(tmp_path, llm, roles=())
    o._design()  # the project exists (design, repo, contract); no plan was ever made
    assert o.tasks == []
    t = o.add_human_task("database", "Add the list function", ["database/calculations.py"], ["tests/test_db_calculations.py"])
    assert t["id"] == "h1" and t["assignee"] == "human" and t["kind"] == "human" and t["status"] == "pending"
    assert of_type(bus, "plan_created")[-1]["reason"] == "human_task" and of_type(bus, "plan_created")[-1]["tasks"][0]["assignee"] == "human"
    with pytest.raises(ValueError):
        o.add_human_task("qa", "x", [], [])
    with pytest.raises(ValueError):
        o.add_human_task("backend", "x", [], [], depends_on=["t9"])
    th = threading.Thread(target=o._execute_tasks, daemon=True)
    th.start()
    ev = assigned(bus)
    assert ev["task"] == "h1" and ev["tests"] == ["tests/test_db_calculations.py"]
    assert "tests/test_db_calculations.py" in (o.root / ev["doc"]).read_text(encoding="utf-8")
    solve_db(ev["worktree"])
    assert o.submit_human_task("h1")["ok"]
    th.join(60)
    assert not th.is_alive() and o._status("h1") == "done"
    assert not any(s == "PlannerOutput" for _, s in llm.models_used)
    assert "INSERT INTO calculations" in (o.root / "database" / "calculations.py").read_text(encoding="utf-8")


def test_a_second_human_task_gets_the_next_id_and_waits_for_its_dependency(tmp_path):
    o, bus = sim(tmp_path, SimLLM(), roles=())
    o._design()
    a = o.add_human_task("database", "First", ["database/calculations.py"], [])
    b = o.add_human_task("backend", "Second", ["backend/api/calculator.py"], [], depends_on=[a["id"]])
    assert (a["id"], b["id"]) == ("h1", "h2") and a["acceptance"] == ["the task is done"]
    assert o._next_ready(set(), ai_free=False)["id"] == "h1"  # a human task needs no free AI worker
    a["status"] = "running"
    assert o._next_ready(set(), ai_free=False) is None  # h2 waits for h1


# -- Stop ----------------------------------------------------------------------------------------------------

def test_stop_while_a_human_task_waits_ends_the_build_cleanly(tmp_path):
    o, bus = sim(tmp_path, SimLLM())
    th, out = start(o)
    assigned(bus)
    o.stop()
    th.join(90)
    assert not th.is_alive()
    res = out["res"]
    assert not res.ok and any("task t1 (DB functions) stopped by you" in p for p in res.problems)
    assert o._status("t1") == "failed" and o._status("t2") == "blocked" and o._humans == {}
    assert [e["state"] for e in bus.history if e["type"] == "agent_state" and e["agent"] == "database"][-1] == "idle"
    assert bus.history[-1]["type"] == "project_done" and bus.history[-1]["ok"] is False
    with pytest.raises(ValueError):
        o.submit_human_task("t1")


def test_submit_refuses_what_is_not_waiting_for_the_person(tmp_path):
    o, bus = sim(tmp_path, SimLLM())
    th, out = start(o)
    assigned(bus)
    for tid in ("t2", "t3", "nope"):  # AI tasks and unknown ids
        with pytest.raises(ValueError):
            o.submit_human_task(tid)
    o.stop()
    th.join(90)


# -- the mode and the API -------------------------------------------------------------------------------------

def test_simulation_is_supervised_for_the_command_policy(tmp_path):
    policy = CommandPolicy(tmp_path)
    for cmd in ("python -m pytest -q", "pip install requests", "rm -rf /"):
        verdict = policy.check(cmd)
        assert apply_mode(verdict, "simulation") == apply_mode(verdict, "supervised")
    assert apply_mode(policy.check("pip install requests"), "simulation") == ASK  # not autonomous: risky commands still ask
    with pytest.raises(ValueError):
        apply_mode(policy.check("python -m pytest -q"), "nonsense")


def test_the_api_creates_a_simulation_serves_the_doc_takes_a_submit_and_validates_roles(tmp_path):
    client, settings, mgr = make_client(tmp_path)
    assert "simulation" in client.get("/api/config").json()["modes"]
    goal = "Build a calculator with history"
    assert client.post("/api/projects", json={"goal": goal, "mode": "simulation", "human_roles": ["qa"]}).status_code == 400
    assert client.post("/api/projects", json={"goal": goal, "mode": "supervised", "human_roles": ["backend"]}).status_code == 400
    assert client.post("/api/projects", json={"goal": goal, "mode": "simulation", "import_from": "C:/x"}).status_code in (400, 422)
    r = client.post("/api/projects", json={"goal": goal, "mode": "simulation", "human_roles": ["database", "database"]})
    assert r.status_code == 201 and r.json()["mode"] == "simulation"
    pid = r.json()["id"]
    s = mgr.get(pid)
    assert s.orch.human_roles == ("database",)
    ev = assigned(s.bus)
    doc = client.get(f"/api/projects/{pid}/tasks/t1/doc")
    assert doc.status_code == 200 and doc.headers["content-type"].startswith("text/markdown") and "# t1: DB functions" in doc.text
    assert client.get(f"/api/projects/{pid}/tasks/t9/doc").status_code == 404
    assert client.get(f"/api/projects/{pid}/tasks/t1.md/doc").status_code == 404
    assert client.post(f"/api/projects/{pid}/mode", json={"mode": "supervised"}).status_code == 409  # who plays which role is fixed at the start
    assert client.post(f"/api/projects/{pid}/mode", json={"mode": "simulation"}).status_code == 200
    assert client.post(f"/api/projects/{pid}/tasks/t2/submit").status_code == 409  # not the person's task
    from pathlib import Path
    write_db_tests(Path(ev["worktree"]))
    red = client.post(f"/api/projects/{pid}/tasks/t1/submit")
    assert red.status_code == 200 and red.json()["ok"] is False and red.json()["stage"] == "tests"
    solve_db(ev["worktree"], tests=False)
    green = client.post(f"/api/projects/{pid}/tasks/t1/submit")
    assert green.status_code == 200 and green.json()["ok"] is True and green.json()["stage"] == "accepted"
    wait_for(lambda: s.state in ("done", "failed"), 120, "the build")
    assert s.state == "done", s.status()["problems"]
    assert client.post(f"/api/projects/{pid}/tasks/t1/submit").status_code == 409  # already accepted
    mgr.shutdown()


def test_the_default_human_role_is_the_backend_and_the_stop_button_ends_the_build(tmp_path):
    client, settings, mgr = make_client(tmp_path)
    r = client.post("/api/projects", json={"goal": "Build a calculator with history", "mode": "simulation"})
    assert r.status_code == 201
    pid = r.json()["id"]
    s = mgr.get(pid)
    assert s.orch.human_roles == ("backend",)
    ev = assigned(s.bus)  # the database task is the AI's; the backend task is the person's and starts after it
    assert ev["owner"] == "backend" and ev["task"] == "t2"
    assert client.post(f"/api/projects/{pid}/escalation", json={"action": "stop", "agent": ""}).status_code == 200
    wait_for(lambda: s.state in ("done", "failed"), 90, "the stopped build")
    assert s.state == "failed" and [e["state"] for e in s.bus.history if e["type"] == "agent_state" and e["agent"] == "backend"][-1] == "idle"
    mgr.shutdown()


def test_a_replay_refuses_to_submit_and_serves_no_doc_for_a_recording_without_one(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import ROOT
    from app.main import create_app
    from app.session import SessionManager
    from api_helpers import make_settings
    settings = make_settings(tmp_path)
    settings.recordings = ROOT / "recordings"  # the committed recordings: the old ones must keep playing
    mgr = SessionManager(settings, ModelRegistry.load(env={}), llm_factory=lambda *a: pytest.fail("replay must never build a model client"))
    client = TestClient(create_app(settings, mgr))
    r = client.post("/api/projects", json={"goal": "x", "mode": "supervised", "demo": True, "recording": "todo-approvals", "speed": 1000})
    assert r.status_code == 201 and r.json()["kind"] == "replay"
    pid = r.json()["id"]
    assert client.post(f"/api/projects/{pid}/tasks/t1/submit").status_code == 409
    assert client.get(f"/api/projects/{pid}/tasks/t1/doc").status_code in (404, 409)
    mgr.shutdown()
