"""P8: Reviewer diff without generated tests, recording cards, Ask-employee follow-ups inside a recording."""
import subprocess

from app.recording import list_recordings, load_recording
from app.repo import Repo
from app.session import CreateRequest

from api_helpers import make_manager, wait_for
from test_orchestrator import act


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def test_the_reviewer_diff_leaves_out_generated_tests_but_keeps_the_engineers_own_tests(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "t")
    git(tmp_path, "config", "user.email", "t@t")
    (tmp_path / "README.md").write_text("x\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "init")
    git(tmp_path, "checkout", "-b", "agent/backend")
    for rel in ("backend/api/a.py", "tests/api/test_contract_api.py", "tests/ui/test_page.py", "tests/qa/test_edge_cases.py", "tests/test_db.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("print(1)\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "work")
    git(tmp_path, "checkout", "main")
    repo = Repo(tmp_path)
    full = repo.diff_vs_main("backend")
    assert all(p in full for p in ("tests/api/test_contract_api.py", "tests/ui/test_page.py", "tests/qa/test_edge_cases.py"))
    shown = repo.diff_vs_main("backend", skip_generated_tests=True)
    assert "backend/api/a.py" in shown and "tests/test_db.py" in shown
    assert not any(p in shown for p in ("tests/api", "tests/ui", "tests/qa"))


def test_a_recording_carries_its_card_text_and_the_ask_employee_request_after_the_build(tmp_path):
    holder: list = []
    settings, mgr = make_manager(tmp_path, llm_holder=holder)
    try:
        s = mgr.create(CreateRequest(goal="Build a calculator with history", mode="autonomous", record_as="demo-ask",
                                     record_info={"title": "Calculator", "app": "Calculator app", "feature": "Ask employee", "junk": "x"},
                                     then_ask=[{"agent": "backend", "text": "Please double check the error format"}]))
        holder[0].scripts["Rohan"] += [act("run_tests"), act("finish", summary="nothing else needed")]
        wait_for(lambda: (settings.recordings / "demo-ask" / "meta.json").exists(), 120, "the recording")
        meta = list_recordings(settings.recordings)[0]
        assert meta["ok"] and (meta["title"], meta["app"], meta["feature"]) == ("Calculator", "Calculator app", "Ask employee") and "junk" not in meta
        types = [e["type"] for e in load_recording(settings.recordings, "demo-ask").events()]
        assert types.count("project_done") == 2 and types[-1] == "project_done"  # the build, then the request
        assert types.index("project_resumed") > types.index("project_done")
        assert s.state == "done"
    finally:
        mgr.shutdown()


def test_an_employee_goes_back_to_work_once_the_approval_is_decided():
    import threading
    from app.approvals import ApprovalQueue
    from app.events import EventBus
    bus = EventBus()
    states = {"architect": "thinking"}
    q = ApprovalQueue(bus.emit, 5.0, lambda a: states.get(a, "idle"))
    out = []
    t = threading.Thread(target=lambda: out.append(q.announce("architect", "write", "write .q/architecture.md", {})))
    t.start()
    wait_for(lambda: q.pending(), 5, "the approval")
    assert [e["state"] for e in bus.history if e["type"] == "agent_state"] == ["waiting_human"]
    q.resolve(q.pending()[0]["id"], True)
    t.join(5)
    assert out == [True]
    assert [e["state"] for e in bus.history if e["type"] == "agent_state"] == ["waiting_human", "thinking"]


def test_a_second_frontend_task_is_shown_the_page_that_already_exists(tmp_path):
    """The Planner sometimes splits the page over two tasks; the second engineer used to write a new app.js blind and lose the generated actions and filter."""
    from test_orchestrator import FakeLLM, make
    o, _ = make(tmp_path, FakeLLM())
    assert o.run().ok
    t = next(x for x in o.tasks if x["owner"] == "frontend")
    wt = o.repo.worktree("frontend")
    stub = o._page_stub({**t, "files": ["static/app.js"]}, o.agents["frontend"], wt, o.design)
    assert stub is not None and stub[0] == "static/app.js" and (wt / "static/app.js").read_text(encoding="utf-8") in stub[1]
    text = o._task_text({**t, "files": ["static/app.js"], "acceptance": ["x"]}, "", stub)
    assert "Do NOT start from scratch" in text


def test_a_search_box_promised_by_the_spec_reaches_the_page_even_if_the_architect_forgot_it():
    from app.schemas import ArchitectOutput, SpecOutput, add_spec_features
    spec = SpecOutput(title="Notes", summary="x", features=["Form to add a note", "Search functionality to find notes by text"])
    design = ArchitectOutput(preset="fastapi-vanilla", architecture="x", endpoints=[], ui_features=["Form with title", "List of notes"])
    add_spec_features(design, spec)
    assert any("Search box" in f for f in design.ui_features) and len(design.ui_features) == 3
    add_spec_features(design, spec)  # already there: nothing is added twice
    assert len(design.ui_features) == 3
    plain = ArchitectOutput(preset="fastapi-vanilla", architecture="x", endpoints=[], ui_features=["List"])
    add_spec_features(plain, SpecOutput(title="Todo", summary="x", features=["Form to add a todo"]))
    add_spec_features(plain, None)
    assert plain.ui_features == ["List"]


def test_a_calculator_page_says_calculate_not_add(tmp_path):
    from app.uistub import page_stub
    from test_orchestrator import FakeLLM, make
    o, _ = make(tmp_path, FakeLLM())
    assert o.run().ok
    page = page_stub(o.design, "Calculator")
    assert page is not None and ">Calculate<" in page and ">Add<" not in page


def _run_page_tests(html: str, tmp_path):
    """Run the generated page test file against a tiny app that serves `html`."""
    import subprocess, sys
    from app.contract_tests import ui_page_test_source
    from app.schemas import ArchitectOutput
    (tmp_path / "backend").mkdir(exist_ok=True)
    (tmp_path / "backend" / "__init__.py").write_text("")
    (tmp_path / "backend" / "main.py").write_text(
        "from fastapi import FastAPI\nfrom fastapi.responses import HTMLResponse, PlainTextResponse\napp = FastAPI()\n"
        f"@app.get('/', response_class=HTMLResponse)\ndef page():\n    return {html!r}\n"
        "@app.get('/static/{name}', response_class=PlainTextResponse)\ndef asset(name: str):\n    return 'x'\n")
    (tmp_path / "test_page.py").write_text(ui_page_test_source(ArchitectOutput(preset="x", architecture="x", endpoints=[], ui_features=[])))
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "test_page.py"], cwd=tmp_path, capture_output=True, text=True)


def test_a_page_with_a_duplicate_element_id_fails_the_generated_page_test_and_says_why(tmp_path):
    shell = '<link href="/static/ui-kit.css"><link href="/static/style.css"><script src="/static/app.js"></script>'
    bad = _run_page_tests(shell + '<section><strong id="total">0</strong></section><p><strong id="total">0</strong></p>', tmp_path)
    assert bad.returncode != 0 and "appear more than once: ['total']" in bad.stdout
    good = _run_page_tests(shell + '<section><strong id="total">0</strong></section><p><strong id="list">0</strong></p>', tmp_path)
    assert good.returncode == 0, good.stdout


def test_the_generated_starting_page_has_no_duplicate_ids(tmp_path):
    import re
    from app.uistub import page_stub
    from test_orchestrator import FakeLLM, make
    o, _ = make(tmp_path, FakeLLM())
    assert o.run().ok
    ids = re.findall(r'\sid="([^"]+)"', page_stub(o.design, "Calculator"))
    assert len(ids) == len(set(ids))
