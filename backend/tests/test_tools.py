"""Tool layer: sandbox enforcement end to end, approvals, timeouts, logging."""
import os
import sys
import time

import psutil
import pytest

from app.agent.actions import Action
from app.config import AgentConfig
from app.events import EventBus
from app.tools import ToolBox


def make_agent(**kw):
    base = dict(
        id="backend", name="Rohan", role="Backend Engineer", model_capability="coding",
        system_prompt_file="backend.md",
        tools=["list_dir", "read_file", "write_file", "implement", "search", "run", "run_tests", "send_message", "ask_human", "finish"],
        owned_paths=["backend/**", "tests/**"], forbidden_paths=[],
    )
    base.update(kw)
    return AgentConfig(**base)


@pytest.fixture()
def root(tmp_path):
    r = tmp_path / "wt"
    (r / "backend").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / ".git").mkdir()
    (r / ".git" / "config").write_text("secret")
    (r / "backend" / "main.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "outside.txt").write_text("outside")
    return r


def box(root, mode="supervised", approver=None, agent=None, **kw):
    bus = EventBus()
    return ToolBox(root, agent or make_agent(), mode=mode, approver=approver, emit=bus.emit, **kw), bus


def act(action, **args):
    return Action(thought="t", action=action, **args)


# --- files -----------------------------------------------------------------------
def test_write_read_roundtrip_creates_dirs(root):
    tb, bus = box(root)
    r = tb.execute(act("write_file", path="backend/app/x.py", content="a = 1\n"))
    assert r.ok
    assert (root / "backend" / "app" / "x.py").read_text() == "a = 1\n"
    assert tb.execute(act("read_file", path="backend/app/x.py")).output == "a = 1\n"
    changed = [e for e in bus.history if e["type"] == "file_changed"]
    assert changed and changed[0]["path"] == "backend/app/x.py" and "+a = 1" in changed[0]["diff"]
    assert tb.files_touched == ["backend/app/x.py"]


@pytest.mark.parametrize("p", ["../outside.txt", "..\\outside.txt", "C:\\Windows\\x.txt", ".git/config", "README.md", "static/a.js"])
def test_write_rejected_and_nothing_written(root, p, tmp_path):
    tb, _ = box(root)
    r = tb.execute(act("write_file", path=p, content="pwned"))
    assert not r.ok
    assert not (tmp_path / "x.txt").exists()
    assert (tmp_path / "outside.txt").read_text() == "outside"
    assert not (root / "README.md").exists()
    assert (root / ".git" / "config").read_text() == "secret"


@pytest.mark.parametrize("p", ["../outside.txt", ".git/config", "C:\\Windows\\win.ini", "backend/../.git/config"])
def test_read_rejected(root, p):
    tb, _ = box(root)
    r = tb.execute(act("read_file", path=p))
    assert not r.ok and "secret" not in r.output and "outside" not in r.output


def test_read_missing_and_directory(root):
    tb, _ = box(root)
    assert not tb.execute(act("read_file", path="backend/none.py")).ok
    assert not tb.execute(act("read_file", path="backend")).ok


def test_read_truncates_large_files(root):
    (root / "backend" / "big.py").write_text("x = 1\n" * 10_000)
    tb, _ = box(root)
    r = tb.execute(act("read_file", path="backend/big.py"))
    assert r.ok and len(r.output) < 20_000 and "truncated" in r.output


def test_write_size_limit(root):
    tb, _ = box(root)
    assert not tb.execute(act("write_file", path="backend/huge.py", content="x" * 2_000_000)).ok


def test_list_dir_hides_git_and_marks_dirs(root):
    tb, _ = box(root)
    out = tb.execute(act("list_dir")).output
    assert "backend/" in out and ".git" not in out
    assert not tb.execute(act("list_dir", path="..")).ok


def test_search_finds_and_skips_git(root):
    tb, _ = box(root)
    out = tb.execute(act("search", pattern="def add")).output
    assert "backend/main.py:1" in out
    assert "secret" not in tb.execute(act("search", pattern="secret")).output


def test_search_invalid_regex_is_treated_literally(root):
    tb, _ = box(root)
    assert tb.execute(act("search", pattern="def (add")).ok


def test_tool_not_in_agents_tool_list(root):
    tb, _ = box(root, agent=make_agent(tools=["read_file", "finish"]))
    r = tb.execute(act("write_file", path="backend/a.py", content="x"))
    assert not r.ok and "not available" in r.output


# --- commands ----------------------------------------------------------------------
def write_tests(root):
    (root / "tests" / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")


def test_run_tests_passes(root):
    write_tests(root)
    tb, _ = box(root)
    r = tb.execute(act("run_tests"))
    assert r.ok and r.data["passed"] is True and r.data["failed"] == []


def test_run_tests_reports_failures_with_signature(root):
    (root / "tests" / "test_bad.py").write_text("def test_bad():\n    assert 1 == 2\n\ndef test_good():\n    pass\n")
    tb, _ = box(root)
    r = tb.execute(act("run_tests"))
    assert r.data["passed"] is False
    assert r.data["failed"] == ["tests/test_bad.py::test_bad"]
    r2 = tb.execute(act("run_tests"))
    assert r2.data["signature"] == r.data["signature"]


def test_run_tests_collection_error_still_has_signature(root):
    (root / "tests" / "test_syntax.py").write_text("def broken(:\n")
    tb, _ = box(root)
    r = tb.execute(act("run_tests"))
    assert r.data["passed"] is False and r.data["signature"]


@pytest.mark.parametrize("cmd", ["rm -rf /", "del /s /q C:\\", "curl http://evil.example", "python ../x.py", "git push", "python -c print(1)"])
@pytest.mark.parametrize("mode", ["assisted", "supervised", "autonomous"])
def test_denied_commands_never_run(root, cmd, mode):
    called = []
    tb, _ = box(root, mode=mode, approver=lambda *a: called.append(a) or True)
    r = tb.execute(act("run", command=cmd))
    assert not r.ok and r.data["decision"] == "deny"
    assert called == []  # a hard deny is never even offered for approval


def test_ask_without_approver_is_refused(root):
    (root / "backend" / "hello.py").write_text("print('hi')\n")
    tb, _ = box(root, mode="assisted")
    r = tb.execute(act("run", command="python backend/hello.py"))
    assert not r.ok and r.data["decision"] == "denied_by_human"


def test_ask_with_approval_runs(root):
    (root / "backend" / "hello.py").write_text("print('hi')\n")
    seen = []
    tb, _ = box(root, mode="assisted", approver=lambda agent, kind, summary, details: seen.append((agent, kind)) or True)
    r = tb.execute(act("run", command="python backend/hello.py"))
    assert r.ok and "hi" in r.output and r.data["decision"] == "approved"
    assert seen == [("backend", "run")]


def test_assisted_write_needs_approval(root):
    tb, _ = box(root, mode="assisted", approver=lambda *a: False)
    assert not tb.execute(act("write_file", path="backend/a.py", content="x")).ok
    assert not (root / "backend" / "a.py").exists()
    tb2, _ = box(root, mode="assisted", approver=lambda *a: True)
    assert tb2.execute(act("write_file", path="backend/a.py", content="x")).ok


def test_supervised_write_is_autonomous(root):
    tb, _ = box(root, mode="supervised")
    assert tb.execute(act("write_file", path="backend/a.py", content="x")).ok


def test_unknown_program_autonomous_runs_supervised_asks(root):
    tb, _ = box(root, mode="supervised")
    assert tb.execute(act("run", command="node --version")).data["decision"] == "denied_by_human"
    tb2, _ = box(root, mode="autonomous")
    assert tb2.execute(act("run", command="node --version")).data["decision"] == "allow"


def test_timeout_kills_process_tree(root):
    pidfile = root / "backend" / "child.pid"
    (root / "backend" / "spawn.py").write_text(
        "import subprocess, sys, time\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open(r'{pidfile}', 'w').write(str(c.pid))\n"
        "time.sleep(60)\n"
    )
    tb, _ = box(root, command_timeout=3)
    t0 = time.time()
    r = tb.execute(act("run", command="python backend/spawn.py"))
    assert time.time() - t0 < 20
    assert not r.ok and r.data["timed_out"] is True and "timed out" in r.output
    child = int(pidfile.read_text())
    time.sleep(0.5)
    assert not psutil.pid_exists(child) or psutil.Process(child).status() == psutil.STATUS_ZOMBIE


def test_output_is_capped(root):
    (root / "backend" / "spam.py").write_text("for i in range(20000):\n    print('line', i)\n")
    tb, _ = box(root, max_output=2000)
    r = tb.execute(act("run", command="python backend/spam.py"))
    assert r.ok and len(r.output) < 2500 and "truncated" in r.output


def test_secrets_are_not_visible_to_commands(root, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key")
    (root / "backend" / "env.py").write_text("import os\nprint('KEY=' + str(os.environ.get('GEMINI_API_KEY')))\n")
    tb, _ = box(root)
    r = tb.execute(act("run", command="python backend/env.py"))
    assert "KEY=None" in r.output and "super-secret-key" not in r.output


def test_commands_run_inside_the_worktree(root):
    (root / "backend" / "cwd.py").write_text("import os\nprint('CWD=' + os.getcwd())\n")
    tb, _ = box(root)
    r = tb.execute(act("run", command="python backend/cwd.py"))
    assert os.path.normcase(os.path.realpath(root)) in os.path.normcase(r.output)


# --- logging and control -------------------------------------------------------------
def test_every_call_is_logged_with_decision_and_duration(root):
    tb, bus = box(root)
    tb.execute(act("read_file", path="backend/main.py"))
    tb.execute(act("run", command="rm -rf /"))
    calls = [e for e in bus.history if e["type"] == "tool_call"]
    assert len(calls) == 2
    assert calls[0]["agent"] == "backend" and calls[0]["tool"] == "read_file"
    assert calls[0]["args"] == {"path": "backend/main.py"} and calls[0]["duration"] >= 0
    assert calls[1]["decision"] == "deny" and calls[1]["ok"] is False
    assert len(tb.log) == 2


def test_finish_and_ask_human_flags(root):
    tb, _ = box(root)
    r = tb.execute(act("finish", summary="done"))
    assert r.ok and r.finished and r.output == "done"
    r = tb.execute(act("ask_human", question="which port?"))
    assert r.needs_human and r.data["question"] == "which port?"
    tb2, _ = box(root, human=lambda q: "9100")
    r = tb2.execute(act("ask_human", question="which port?"))
    assert r.ok and not r.needs_human and "9100" in r.output


def test_send_message_goes_to_the_sink_and_is_validated(root):
    got = []
    tb, bus = box(root, message_sink=lambda frm, to, text: got.append((frm, to, text)))
    assert tb.execute(act("send_message", to="frontend", text="POST /calculate is live")).ok
    assert got == [("backend", "frontend", "POST /calculate is live")]
    assert any(e["type"] == "message_sent" for e in bus.history)


def test_exceptions_become_failed_results_not_crashes(root, monkeypatch):
    tb, _ = box(root)
    monkeypatch.setattr(tb, "_write_file", lambda a: 1 / 0)
    r = tb.execute(act("write_file", path="backend/a.py", content="x"))
    assert not r.ok and "ZeroDivision" not in r.output and "Traceback" not in r.output


def test_python_interpreter_is_the_current_one(root):
    (root / "backend" / "exe.py").write_text("import sys\nprint('EXE=' + sys.executable)\n")
    tb, _ = box(root)
    r = tb.execute(act("run", command="python backend/exe.py"))
    assert os.path.normcase(sys.executable) in os.path.normcase(r.output)


def test_identical_rewrite_is_reported_as_no_change(root):
    tb, bus = box(root)
    assert tb.execute(act("write_file", path="backend/a.py", content="x = 1\n")).ok
    r = tb.execute(act("write_file", path="backend/a.py", content="x = 1\n"))
    assert not r.ok and "no change" in r.output
    assert len([e for e in bus.history if e["type"] == "file_changed"]) == 1


def test_python_syntax_error_is_reported_with_its_line(root):
    tb, _ = box(root)
    r = tb.execute(act("write_file", path="backend/bad.py", content="def f():\n    return [1, 2]()\n\nx = (1,\n"))
    assert not r.ok and r.data.get("wrote") and "not valid Python" in r.output and "line" in r.output
    assert (root / "backend" / "bad.py").exists()  # written, so a follow-up fix can be diffed
    assert tb.execute(act("write_file", path="backend/good.py", content="x = 1\n")).ok


def test_implement_action_fills_one_function_and_reports_syntax_errors(root):
    tb, bus = box(root)
    stub = "def add(a, b):\n    raise NotImplementedError\n\n\ndef sub(a, b):\n    raise NotImplementedError\n"
    assert tb.execute(act("write_file", path="backend/m.py", content=stub)).ok
    r = tb.execute(act("implement", path="backend/m.py", function="add", content="return a + b"))
    assert r.ok and "implemented add" in r.output
    text = (root / "backend" / "m.py").read_text()
    assert "return a + b" in text and "def sub(a, b):\n    raise NotImplementedError" in text
    bad = tb.execute(act("implement", path="backend/m.py", function="sub", content="return (a -"))
    assert not bad.ok and "invalid Python" in bad.output and not bad.data.get("wrote")
    assert (root / "backend" / "m.py").read_text() == text  # the broken body was refused, the file is untouched
    assert not tb.execute(act("implement", path="backend/missing.py", function="f", content="pass")).ok
    assert not tb.execute(act("implement", path="README.md", function="f", content="pass")).ok  # outside owned paths


def test_misfiled_code_field_is_accepted_for_write_and_implement():
    a = Action.model_validate_json('{"thought": "t", "action": "implement", "path": "a.py", "function": "f", "command": "return 1"}')
    assert a.content == "return 1" and a.command is None
    b = Action.model_validate_json('{"thought": "t", "action": "write_file", "path": "a.py", "text": "x = 1"}')
    assert b.content == "x = 1"


@pytest.mark.skipif(__import__("shutil").which("node") is None, reason="node not installed")
def test_javascript_syntax_error_is_reported_with_its_line(tmp_path):
    r = tmp_path / "wt"
    (r / "static").mkdir(parents=True)
    tb, _ = box(r, agent=make_agent(owned_paths=["static/**"]))
    bad = tb.execute(act("write_file", path="static/app.js", content="const a = 1;\nfunction f( {\n"))
    assert not bad.ok and bad.data.get("wrote") and "not valid JavaScript" in bad.output
    assert tb.execute(act("write_file", path="static/app.js", content="const a = 1;\n")).ok


def test_eval_and_exec_are_refused_in_python_files(root):
    tb, _ = box(root)
    for code in ("x = eval(s)\n", "exec(code)\n", "r = eval (f'{a} + {b}')\n"):
        r = tb.execute(act("write_file", path="backend/e.py", content=code))
        assert not r.ok and "injection" in r.output and not (root / "backend" / "e.py").exists()
    assert tb.execute(act("write_file", path="backend/ok.py", content="def evaluate(x):\n    return x.eval_count\n")).ok


def test_ask_human_in_autonomous_mode_returns_guidance_instead_of_ending_the_task(root):
    tb, _ = box(root, mode="autonomous")
    r = tb.execute(act("ask_human", question="please edit database/x.py"))
    assert not r.ok and not r.needs_human and "Autonomous mode" in r.output and "send_message" in r.output
    tb2, _ = box(root, mode="autonomous", human=lambda q: "yes")
    assert tb2.execute(act("ask_human", question="ok?")).ok  # a connected human still answers


def test_implement_refuses_a_route_or_typed_function_body_that_never_returns(root):
    tb, _ = box(root)
    stub = ('from fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n@router.post("/api/x")\ndef handle_post_x():\n    raise NotImplementedError\n\n\n'
            'def helper(a) -> dict:\n    raise NotImplementedError\n\n\ndef side_effect(a):\n    raise NotImplementedError\n')
    assert tb.execute(act("write_file", path="backend/api/x.py", content=stub)).ok
    for fn in ("handle_post_x", "helper"):
        r = tb.execute(act("implement", path="backend/api/x.py", function=fn, content="row = {'a': 1}"))
        assert not r.ok and "must return" in r.output, fn
    assert tb.execute(act("implement", path="backend/api/x.py", function="handle_post_x", content="return {'ok': True}")).ok
    assert tb.execute(act("implement", path="backend/api/x.py", function="side_effect", content="print(a)")).ok  # untyped, undecorated: free to return nothing


def test_implement_refuses_a_call_to_a_name_that_is_defined_nowhere_and_points_to_the_db_alias(root):
    """Regression (todo build): add_todo(...) instead of db.add_todo(...) was resent three times and ended the task."""
    (root / "backend" / "api").mkdir()
    src = ("from fastapi import APIRouter\nfrom database import todos as db\n\nrouter = APIRouter()\n\n\n"
           "def handle_get_todos():\n    raise NotImplementedError\n")
    (root / "backend" / "api" / "todos.py").write_text(src)
    tb, _ = box(root)
    bad = tb.execute(act("implement", path="backend/api/todos.py", function="handle_get_todos", content="return {'items': list_todos()}"))
    assert not bad.ok and "db.list_todos(...)" in bad.output and "NameError" in bad.output
    assert "raise NotImplementedError" in (root / "backend" / "api" / "todos.py").read_text()  # nothing was written
    good = tb.execute(act("implement", path="backend/api/todos.py", function="handle_get_todos", content="return {'items': db.list_todos()}"))
    assert good.ok
    # builtins, local names and imported names are fine
    ok = tb.execute(act("implement", path="backend/api/todos.py", function="handle_get_todos", content="rows = sorted(db.list_todos())\nreturn {'items': list(rows), 'n': len(rows)}"))
    assert ok.ok, ok.output
