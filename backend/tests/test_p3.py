"""P3: worktrees and merges, reviewer loop, QA -> owner -> fix loop (with an injected bug), integrator conflicts, parallel scheduling."""
import json
import subprocess

import pytest

from app.agent.planning import AmendOutput  # noqa: F401  (imported so FakeLLM's schema dispatch is exercised)
from app.agent.qa import guess_owner, parse_failures
from app.agent.review import ReviewItem, ReviewOutput, missing_tests, static_findings
from app.config import load_agents
from app.faults import _flip_operator
from app.repo import Repo, run_git
from app.integrator import Integrator, Resolution
from app.llm import StructuredResult
from app.project import create_project
from app.schemas import PlannerOutput

from test_orchestrator import API_POST, DB_LIST, PLAN, FakeLLM, act, make, types


def git_out(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8").stdout


# -- worktrees, merges ---------------------------------------------------------------

def test_every_agent_works_on_its_own_branch_and_the_integrator_merges_into_main(tmp_path):
    o, bus = make(tmp_path, FakeLLM())
    res = o.run()
    assert res.ok, res.problems
    branches = git_out(res.root, "branch", "--format=%(refname:short)").split()
    assert {"main", "agent/database", "agent/backend", "agent/frontend", "agent/qa"} <= set(branches)
    merges = git_out(res.root, "log", "main", "--merges", "--pretty=%s").splitlines()
    assert len(merges) == 5 and all(m.startswith("[integrator] merge agent/") for m in merges)
    # the work reached main only through merges, and each agent's commits are on its own branch
    assert "[backend] API router" in git_out(res.root, "log", "agent/backend", "--pretty=%s")
    assert (res.root / ".worktrees" / "backend" / "backend" / "api" / "calculator.py").is_file()
    assert [e["ok"] for e in bus.history if e["type"] == "merge_result"] == [True] * 5
    graph = json.loads((res.root / ".q/history/git-graph.json").read_text())
    assert any("agent/backend" in " ".join(c["refs"]) for c in graph)


def test_reviewer_requests_changes_and_the_engineer_fixes_them(tmp_path):
    llm = FakeLLM()
    llm.reviews = [ReviewOutput(verdict="REQUEST_CHANGES", summary="ordering", items=[ReviewItem(file="database/calculations.py", problem="limit the history to 100 rows")])]
    llm.scripts["Karan"] += [act("implement", path="database/calculations.py", function="list_history",
                                 content=DB_LIST.replace("DESC'", "DESC LIMIT 100'")), act("run_tests"), act("finish", summary="limited")]
    o, bus = make(tmp_path, llm)
    res = o.run()
    assert res.ok, res.problems
    t1 = [(e["round"], e["verdict"]) for e in bus.history if e["type"] == "review_result" and e["task"] == "t1"]
    assert t1 == [(1, "REQUEST_CHANGES"), (2, "PASS")]
    assert "REQUEST_CHANGES" in (res.root / ".q/reviews/t1-r1.md").read_text() and "PASS" in (res.root / ".q/reviews/t1-r2.md").read_text()
    assert "LIMIT 100" in (res.root / "database/calculations.py").read_text()
    assert "[database] address review (t1)" in git_out(res.root, "log", "--pretty=%s")
    assert any("Review requested changes" in m["text"] for m in o.messages.all() if m["recipient"] == "database")


def _always_request_changes(llm):
    llm.reviews = [ReviewOutput(verdict="REQUEST_CHANGES", summary="no", items=[ReviewItem(file="database/calculations.py", problem="rename things")])] * 3
    llm.scripts["Karan"] += [act("implement", path="database/calculations.py", function="list_history", content=DB_LIST.replace("DESC'", "DESC LIMIT 1'")),
                             act("run_tests"), act("finish", summary="r1"),
                             act("implement", path="database/calculations.py", function="list_history", content=DB_LIST.replace("DESC'", "DESC LIMIT 2'")),
                             act("run_tests"), act("finish", summary="r2")]


def test_unresolved_review_blocks_the_merge_until_the_work_is_redone_or_a_human_accepts(tmp_path, monkeypatch):
    from app import orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "MAX_REPLANS", 0)
    llm = FakeLLM()
    _always_request_changes(llm)
    llm.scripts["Karan"].append(act("finish", summary="retry: nothing more to change"))  # the second attempt; the reviewer then passes it
    o, bus = make(tmp_path / "a", llm)
    o.mode = "supervised"  # no approver -> the unresolved review is denied
    res = o.run()
    t = [(e["type"], e.get("reason") or e.get("task")) for e in bus.history if e["type"] in ("escalation", "merge_result", "task_assigned")]
    assert t[:2] == [("task_assigned", "t1"), ("escalation", "review_unresolved")]  # blocked before anything was merged
    assert t[2] == ("task_assigned", "t1")  # re-queued, not merged
    assert "blocked by unresolved review items" in o.memory.read("decisions.md")
    assert res.ok, res.problems

    llm = FakeLLM()
    _always_request_changes(llm)
    o, bus = make(tmp_path / "b", llm)  # autonomous: accepts and records it
    res = o.run()
    assert res.ok, res.problems
    assert "merged with open review items" in o.memory.read("decisions.md")
    assert [e["type"] for e in bus.history if e["type"] in ("escalation", "merge_result")][:2] == ["escalation", "merge_result"]


# -- QA -> owner -> fix --------------------------------------------------------------

def test_injected_bug_is_found_by_qa_routed_to_its_owner_fixed_reviewed_merged_and_retested(tmp_path):
    llm = FakeLLM()
    llm.scripts["Rohan"] += [act("implement", path="backend/api/calculator.py", function="handle_post_calculate", content=API_POST),
                             act("run_tests"), act("finish", summary="fixed the operator")]
    o, bus = make(tmp_path, llm, inject_fault=True)
    res = o.run()
    assert res.ok, res.problems

    faults = [e for e in bus.history if e["type"] == "fault_injected"]
    assert len(faults) == 1 and faults[0]["ok"] and faults[0]["owner"] == "backend" and faults[0]["file"] == "backend/api/calculator.py"

    qa_runs = [e for e in bus.history if e["type"] == "test_result" and e.get("agent") == "qa"]
    assert [e["passed"] for e in qa_runs] == [False, True]  # QA finds the bug, then sees it fixed
    assert any("test_contract_api" in t for t in qa_runs[0]["failed"])

    bugs = [e for e in bus.history if e["type"] == "bug_filed"]
    assert len(bugs) == 1 and bugs[0]["owner"] == "backend" and bugs[0]["verdict"] == "app_bug"
    report = (res.root / bugs[0]["path"]).read_text()
    assert "**Owner:** backend" in report and "**Status:** fixed" in report and "test_contract_api" in report
    assert any(m["sender"] == "qa" and m["recipient"] == "backend" for m in o.messages.all())

    fix = next(t for t in res.tasks if t["id"] == "b1")
    assert fix["owner"] == "backend" and fix["status"] == "done" and fix["kind"] == "bugfix"
    t = types(bus)
    assert t.index("fault_injected") < t.index("bug_filed") < t.index("bug_fixed") < t.index("project_done")
    assert [e["verdict"] for e in bus.history if e["type"] == "review_result" and e["task"] == "b1"] == ["PASS"]  # the fix was reviewed too

    log = git_out(res.root, "log", "main", "--pretty=%s").splitlines()
    inject_at = next(i for i, m in enumerate(log) if m.startswith("[fault-injection]"))
    assert any(m.startswith("[integrator] merge agent/backend: Fix bug 001") for m in log[:inject_at])  # the fix landed after the bug
    assert "- a + b" not in (res.root / "backend/api/calculator.py").read_text() and "x - y" not in (res.root / "backend/api/calculator.py").read_text()
    assert res.agent_stats["qa"]["iterations"] >= 1
    assert "triage" in "".join(llm.triaged).lower() or "test_contract_api" in "".join(llm.triaged)


# -- Integrator ----------------------------------------------------------------------

class ResolverLLM:
    def __init__(self, content):
        self.content = content

    def call(self, model_id, messages, schema_model, temperature=0.2):
        return StructuredResult(Resolution(content=self.content, summary="merged both"), model_id, 1, 1, 1, 0.0, "{}")


def conflicting_repo(tmp_path):
    root = create_project("conflict demo", base=tmp_path)
    repo = Repo(root)
    for who, line in (("backend", "BACKEND = 1\n"), ("frontend", "FRONTEND = 1\n")):
        wt = repo.worktree(who)
        (wt / "shared.py").write_text(line, encoding="utf-8")
        repo.commit(wt, f"[{who}] shared")
    return root, repo


def test_integrator_resolves_a_real_conflict_with_the_model(tmp_path):
    root, repo = conflicting_repo(tmp_path)
    events = []
    integ = Integrator(load_agents()["integrator"], repo, ResolverLLM("BACKEND = 1\nFRONTEND = 1\n"), "m", lambda t, **k: events.append((t, k)), mode="autonomous")
    assert integ.merge("backend", "b").ok
    res = integ.merge("frontend", "f")
    assert res.ok and res.resolved == ["shared.py"]
    assert (root / "shared.py").read_text() == "BACKEND = 1\nFRONTEND = 1\n"
    assert repo.conflicted_files() == [] and git_out(root, "status", "--porcelain").strip() == ""
    merged = [k for t, k in events if t == "merge_result"]
    assert merged[-1]["resolved"] == ["shared.py"] and merged[-1]["conflicts"] == ["shared.py"]


@pytest.mark.parametrize("content,approver,why", [
    ("<<<<<<< HEAD\nBACKEND = 1\n=======\nFRONTEND = 1\n>>>>>>> x\n", lambda *a: True, "markers"),
    ("BACKEND = 1\nFRONTEND = 1\n", lambda *a: False, "not approved"),
    ("def broken(:\n", lambda *a: True, "valid Python"),
])
def test_integrator_aborts_and_leaves_main_untouched_when_resolution_is_unusable_or_not_approved(tmp_path, content, approver, why):
    root, repo = conflicting_repo(tmp_path)
    events = []
    integ = Integrator(load_agents()["integrator"], repo, ResolverLLM(content), "m", lambda t, **k: events.append((t, k)), mode="supervised", approver=approver)
    run_git(root, "merge", "--no-ff", "-m", "m", "agent/backend")
    before = git_out(root, "rev-parse", "HEAD")
    res = integ.merge("frontend", "f")
    assert not res.ok and why in res.reason
    assert git_out(root, "rev-parse", "HEAD") == before and (root / "shared.py").read_text() == "BACKEND = 1\n"
    assert git_out(root, "status", "--porcelain").strip() == ""
    assert ("escalation", ) == tuple(t for t, k in events if t == "escalation")[:1]


# -- parallel scheduling -------------------------------------------------------------

PARALLEL_PLAN = {"tasks": [
    PLAN["tasks"][0],
    PLAN["tasks"][1],
    {"id": "t3", "title": "Page", "owner": "frontend", "depends_on": [], "files": ["static/index.html", "static/style.css"], "acceptance": ["has a form"]},
    {"id": "t4", "title": "Script", "owner": "frontend", "depends_on": ["t2", "t3"], "files": ["static/app.js"], "acceptance": ["calls the API"]},
]}


class ParallelLLM(FakeLLM):
    def call(self, model_id, messages, schema_model, temperature=0.2):
        if schema_model is PlannerOutput:
            self.models_used.append((model_id, schema_model.__name__))
            return StructuredResult(PlannerOutput.model_validate(PARALLEL_PLAN), model_id, 1, 1, 1, 0.0, "{}")
        return super().call(model_id, messages, schema_model, temperature)


def test_independent_tasks_of_different_owners_run_at_the_same_time_but_merges_are_one_at_a_time(tmp_path):
    o, bus = make(tmp_path, ParallelLLM(), max_parallel=2)
    res = o.run()
    assert res.ok, res.problems
    t = [(e["type"], e.get("task")) for e in bus.history if e["type"] in ("task_assigned", "merge_result")]
    # t1 (database) and t3 (frontend) have no dependencies: both start before either is merged
    assert t[0] == ("task_assigned", "t1") and t[1] == ("task_assigned", "t3") and t[2][0] == "merge_result"


def test_max_parallel_one_is_sequential(tmp_path):
    o, bus = make(tmp_path, ParallelLLM(), max_parallel=1)
    assert o.run().ok
    t = [e["type"] for e in bus.history if e["type"] in ("task_assigned", "merge_result")]
    assert t[:4] == ["task_assigned", "merge_result", "task_assigned", "merge_result"]


# -- small units ---------------------------------------------------------------------

PYTEST_OUT = """\
============================= test session starts =============================
=================================== FAILURES ===================================
____________________ test_post_api_calculate_1_adds ____________________
tests/api/test_contract_api.py:12: in test_post_api_calculate_1_adds
    assert r.status_code == 201, r.text
backend/api/calculator.py:30: in handle_post_calculate
    return db.add_calculation(a=req.a)
database/calculations.py:9: in add_calculation
    raise KeyError('x')
E   KeyError: 'x'
____________________ test_ui ____________________
tests/ui/test_script.py:5: in test_ui
    assert '/api/history' in js
E   AssertionError
=========================== short test summary info ============================
FAILED tests/api/test_contract_api.py::test_post_api_calculate_1_adds - KeyError: 'x'
FAILED tests/ui/test_script.py::test_ui - AssertionError
ERROR tests/qa/test_edge_cases.py
2 failed, 1 error in 0.30s
"""


def test_parse_failures_and_owner_routing():
    fs = parse_failures(PYTEST_OUT)
    assert [f.test_id for f in fs] == ["tests/api/test_contract_api.py::test_post_api_calculate_1_adds", "tests/ui/test_script.py::test_ui", "tests/qa/test_edge_cases.py"]
    assert fs[0].authoritative and "KeyError" in fs[0].message and "database/calculations.py:9" in fs[0].trace
    assert [guess_owner(f) for f in fs] == ["database", "frontend", "backend"]  # deepest app frame wins; no frame -> by test file
    assert fs[2].authoritative  # tests/qa is generated too


def test_static_review_findings():
    long_py = "x = 1\n" * 151
    files = {"backend/api/a.py": long_py + "eval(x)\n", "database/d.py": "conn.execute(f'SELECT * FROM t WHERE id={i}')\n",
             "static/app.js": "el.innerHTML = data;\n", "tests/test_x.py": "eval('1')\n"}
    probs = {(i.file, i.problem.split(";")[0].split(" (")[0][:20]) for i in static_findings(files)}
    files_hit = {f for f, _ in probs}
    assert files_hit == {"backend/api/a.py", "database/d.py", "static/app.js"}  # tests/ are not reviewed for these
    assert len([i for i in static_findings(files) if i.file == "backend/api/a.py"]) == 2  # size and eval
    assert missing_tests({"database/x.py": "a = 1\n"}, "database") and not missing_tests({"database/x.py": "a", "tests/test_db_x.py": "b"}, "database")
    assert not missing_tests({"backend/api/x.py": "a"}, "backend")


def test_fault_flip_changes_one_operator_and_leaves_strings_alone():
    src = 'msg = "a + b"\nx = 1  # a + b\ndef f(a, b):\n    return a + b\n'
    new, what = _flip_operator(src)
    assert new == 'msg = "a + b"\nx = 1  # a + b\ndef f(a, b):\n    return a - b\n' and "line 4" in what
    assert _flip_operator("x = 1\n") is None
