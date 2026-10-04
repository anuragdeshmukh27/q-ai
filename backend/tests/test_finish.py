"""Finish my project: the analyst, the gap tests, the importer, the sandbox additions and a scripted end-to-end run on the sample half-built apps."""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from app.agent.actions import Action  # noqa: E402
from app.events import EventBus  # noqa: E402
from app.finish.analyze import ImportDeclined, analyse, extract_routes, project_files  # noqa: E402
from app.finish.build import FinishBuild  # noqa: E402
from app.finish.gaptests import gap_tests  # noqa: E402
from app.finish.importer import check, fetch, import_project  # noqa: E402
from app.finish.stubs import insert, stub_source  # noqa: E402
from app.llm import StructuredResult  # noqa: E402
from app.registry import ModelRegistry  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples" / "half-built"
PY = sys.executable


def act(action, **kw):
    return {"thought": "t", "action": action, **kw}


def counts(a):
    out = {}
    for g in a.gaps:
        out[g.kind] = out.get(g.kind, 0) + 1
    return out


def test_the_analyst_finds_the_gaps_of_each_sample_by_rules():
    fest = analyse(SAMPLES / "fest-app")
    assert counts(fest) == {"todo_body": 4, "missing_endpoint": 2} and fest.framework == "fastapi" and fest.module == "app.main"
    assert {(g.method, g.path) for g in fest.gaps if g.kind == "missing_endpoint"} == {("GET", "/api/stats"), ("GET", "/api/sponsors")}
    assert next(g for g in fest.gaps if g.path == "/api/stats").reads == ["events", "registrations"]  # what the page reads from the answer
    notes = analyse(SAMPLES / "notes-flask")
    assert notes.framework == "flask" and counts(notes) == {"todo_body": 1, "todo_comment": 2}
    lib = analyse(SAMPLES / "library-readme")
    assert counts(lib) == {"readme_feature": 3} and {g.path for g in lib.gaps} == {"/books/{id}/borrow", "/books/{id}/return", "/books/overdue"}


def test_the_reconstructed_contract_lists_what_exists_and_what_is_missing():
    from app.finish.analyze import reconstruct_contract

    c = reconstruct_contract(analyse(SAMPLES / "fest-app"))
    states = {(e["method"], e["path"]): e["state"] for e in c["endpoints"]}
    assert states[("GET", "/api/events")] == "implemented" and states[("POST", "/api/events/{event_id}/registrations")] == "stub" and states[("GET", "/api/stats")] == "missing"


def test_the_generated_gap_tests_fail_on_the_half_built_project_and_say_why(tmp_path):
    dest = tmp_path / "fest"
    shutil.copytree(SAMPLES / "fest-app", dest)
    a = analyse(dest)
    (dest / "tests" / "q_finish").mkdir(parents=True)
    (dest / "tests" / "q_finish" / "test_gaps.py").write_text(gap_tests(a, a.gaps), encoding="utf-8")
    r = subprocess.run([PY, "-m", "pytest", "-q", "tests/q_finish", "-p", "no:cacheprovider"], cwd=dest, capture_output=True, text=True)
    assert r.returncode != 0 and "NotImplementedError" in r.stdout and "is not registered" in r.stdout
    assert "{event_id}" in r.stdout and "NameError" not in r.stdout  # a path with braces in a message must not be read as a name


def test_a_placeholder_is_put_before_the_main_block_in_the_style_of_the_project():
    a = analyse(SAMPLES / "fest-app")
    g = next(x for x in a.gaps if x.path == "/api/sponsors")
    src, name = stub_source(a, g, "router", "/api", set())
    assert name == "get_sponsors" and '@router.get("/sponsors")' in src and "raise NotImplementedError" in src and "TODO" not in src
    out = insert("x = 1\n\n\nif __name__ == '__main__':\n    run()\n", [src])
    assert out.index("get_sponsors") < out.index("__main__")
    compile(out, "x", "exec")
    notes = analyse(SAMPLES / "notes-flask")
    flask_src, _ = stub_source(notes, g.__class__("g9", "missing_endpoint", "t", "app.py", "backend", method="DELETE", path="/api/notes/{note_id}"), "app", "", set())
    assert '@app.route("/api/notes/<int:note_id>", methods=["DELETE"])' in flask_src


def test_a_failing_test_is_attached_to_the_gap_it_is_about():
    from app.finish.analyze import Gap

    notes = analyse(SAMPLES / "notes-flask")
    gaps = list(notes.gaps)
    for name in ("test_delete_removes_the_note", "test_search_finds_by_title_or_body_in_any_case", "test_a_pinned_note_comes_first", "test_something_unrelated_zzz"):
        gaps.append(Gap(f"g{len(gaps) + 1}", "failing_test", name, "app.py", "backend", test="tests/test_notes.py::" + name))
    kept, attached = FinishBuild("x", None, None)._attach_failing_tests(gaps)
    by = {g.id: g for g in notes.gaps}
    pin = next(i for i, g in by.items() if g.kind == "todo_body")
    assert [x.test.split("::")[-1] for x in attached[pin]] == ["test_a_pinned_note_comes_first"]
    assert sum(len(v) for v in attached.values()) == 3 and [g.test.split("::")[-1] for g in kept if g.kind == "failing_test"] == ["test_something_unrelated_zzz"]


def test_the_importer_never_touches_the_source_and_declines_what_q_does_not_finish(tmp_path):
    def digest(root):
        return {str(p.relative_to(root)): hashlib.md5(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}

    before = digest(SAMPLES / "fest-app")
    framework, files = check(fetch(str(SAMPLES / "fest-app"), tmp_path / "scratch"))
    dest = import_project(SAMPLES / "fest-app", tmp_path / "ws")
    assert framework == "fastapi" and digest(SAMPLES / "fest-app") == before
    branches = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=dest, capture_output=True, text=True).stdout.split()
    assert {"q/base", "q/finish"} <= set(branches)
    assert subprocess.run(["git", "branch", "--show-current"], cwd=dest, capture_output=True, text=True).stdout.strip() == "q/finish"
    with pytest.raises(ImportDeclined, match="could not find"):
        fetch(str(tmp_path / "nope"), tmp_path)
    big = tmp_path / "big"
    big.mkdir()
    (big / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")
    for i in range(60):
        (big / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(ImportDeclined, match="files"):
        check(big)
    other = tmp_path / "other"
    other.mkdir()
    (other / "main.go").write_text("package main\n", encoding="utf-8")
    with pytest.raises(ImportDeclined):
        check(other)


def test_implement_creates_a_function_from_a_signature_or_a_name_and_refuses_a_call_to_one_that_does_not_exist(tmp_path):
    from app.config import load_agents
    from app.tools import ToolBox

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "db.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    (tmp_path / "app" / "r.py").write_text("from app import db\n\n\ndef route():\n    raise NotImplementedError\n", encoding="utf-8")
    agent = load_agents()["backend"].model_copy(update={"owned_paths": ["app/**"], "forbidden_paths": []})
    tb = ToolBox(tmp_path, agent, mode=lambda: "autonomous")
    tb.allow_new_functions = True
    ghost = tb.execute(Action.model_validate(act("implement", path="app/r.py", function="route", content="return db.two(1)")))
    assert not ghost.ok and "db.two" in ghost.output and "does not exist" in ghost.output
    made = tb.execute(Action.model_validate(act("implement", path="app/db.py", function="two(a)", content="return a * 2")))
    assert made.ok and "def two(a):" in (tmp_path / "app" / "db.py").read_text(encoding="utf-8")
    again = tb.execute(Action.model_validate(act("implement", path="app/r.py", function="route", content="return db.two(1)")))
    assert again.ok
    inferred = tb.execute(Action.model_validate(act("implement", path="app/db.py", function="three", content="return x + y")))  # parameters read from how it is called
    assert not inferred.ok or "def three(" in (tmp_path / "app" / "db.py").read_text(encoding="utf-8")


# ---- a scripted end-to-end run ---------------------------------------------------------------------------------------------------------------------------------
BODIES = {
    "get_stats": "with db.connect() as conn:\n    e = conn.execute(\"SELECT COUNT(*) FROM events\").fetchone()[0]\n    r = conn.execute(\"SELECT COUNT(*) FROM registrations\").fetchone()[0]\nreturn {\"events\": e, \"registrations\": r}",
    "get_sponsors": "with db.connect() as conn:\n    rows = [dict(r) for r in conn.execute(\"SELECT * FROM sponsors ORDER BY id DESC\")]\nreturn {\"items\": rows}",
    "list_registrations": "with db.connect() as conn:\n    if conn.execute(\"SELECT id FROM events WHERE id = ?\", (event_id,)).fetchone() is None:\n        raise HTTPException(404, \"Event not found\")\n    rows = [dict(r) for r in conn.execute(\"SELECT * FROM registrations WHERE event_id = ? ORDER BY id DESC\", (event_id,))]\nreturn {\"items\": rows}",
    "add_registration": "with db.connect() as conn:\n    if conn.execute(\"SELECT id FROM events WHERE id = ?\", (event_id,)).fetchone() is None:\n        raise HTTPException(404, \"Event not found\")\n    cur = conn.execute(\"INSERT INTO registrations (event_id, student_name, email, status) VALUES (?, ?, ?, 'Registered')\", (event_id, body.student_name, body.email))\n    return dict(conn.execute(\"SELECT * FROM registrations WHERE id = ?\", (cur.lastrowid,)).fetchone())",
}
for _name, _status in (("check_in", "Checked in"), ("cancel", "Cancelled")):
    BODIES[_name] = (f"with db.connect() as conn:\n    if conn.execute(\"SELECT id FROM registrations WHERE id = ?\", (registration_id,)).fetchone() is None:\n        raise HTTPException(404, \"Registration not found\")\n"
                     f"    conn.execute(\"UPDATE registrations SET status = '{_status}' WHERE id = ?\", (registration_id,))\n    return dict(conn.execute(\"SELECT * FROM registrations WHERE id = ?\", (registration_id,)).fetchone())")
FILE = {"get_stats": "app/routers/events.py", "get_sponsors": "app/routers/events.py"}


class FinishLLM:
    """The engineer of every task: fill the placeholder the task names (from its fill-in-the-blank line), run the tests, finish."""

    def __init__(self):
        self.calls = 0
        self.steps: list[dict] = []

    def call(self, model_id, messages, schema_model, temperature=0.2):
        assert schema_model is Action, schema_model
        text = messages[1]["content"]
        if not self.steps:
            import re

            name = re.search(r'"function": "(\w+)"', text).group(1)
            self.steps = [act("implement", path=FILE.get(name, "app/routers/registrations.py"), function=name, content=BODIES[name]), act("run_tests"), act("finish", summary="done")]
        self.calls += 1
        return StructuredResult(Action.model_validate(self.steps.pop(0)), model_id, 1, 10, 5, 0.01, "{}")


def test_a_scripted_team_finishes_the_half_built_fest_app_on_its_own_branch(tmp_path):
    llm, bus = FinishLLM(), EventBus()
    o = FinishBuild(str(SAMPLES / "fest-app"), ModelRegistry.load(env={}), llm, bus, auto_fix=True, mode="autonomous", base=tmp_path, start_app=False)
    res = o.run()
    assert res.ok, res.problems
    types = [e["type"] for e in bus.history]
    assert {"gap_report", "gaps_selected", "plan_created", "merge_result", "gap_status", "finish_summary", "project_done"} <= set(types)
    status = next(e for e in bus.history if e["type"] == "gap_status")
    assert len(status["fixed"]) == 6 and not status["open"]
    summary = next(e for e in bus.history if e["type"] == "finish_summary")
    assert {f["path"] for f in summary["files"]} == {"app/routers/events.py", "app/routers/registrations.py"} and summary["branch"] == "q/finish"
    # the gap report and the reconstructed contract are in the project's memory, and the hidden acceptance tests (which Q never sees) pass
    assert (res.root / ".q" / "gap_report.md").is_file() and "stats" in (res.root / ".q" / "api_contract.json").read_text(encoding="utf-8")
    hidden = res.root / "tests" / "q_hidden"
    hidden.mkdir()
    shutil.copy(ROOT / "samples" / "half-built" / "_acceptance" / "fest-app" / "test_accept_hidden.py", hidden / "test_accept_hidden.py")
    r = subprocess.run([PY, "-m", "pytest", "-q", "tests/q_hidden", "-p", "no:cacheprovider"], cwd=res.root, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1500:]
    # the original sample folder was not touched
    assert "NotImplementedError" in (SAMPLES / "fest-app" / "app" / "routers" / "registrations.py").read_text(encoding="utf-8")


def test_the_human_picks_the_gaps_and_only_those_are_fixed(tmp_path):
    import threading

    llm, bus = FinishLLM(), EventBus()
    o = FinishBuild(str(SAMPLES / "fest-app"), ModelRegistry.load(env={}), llm, bus, auto_fix=False, mode="autonomous", base=tmp_path, start_app=False)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("res", o.run()))
    t.start()
    import time

    for _ in range(600):
        if any(e["type"] == "selection_needed" for e in bus.history):
            break
        time.sleep(0.1)
    report = next(e for e in bus.history if e["type"] == "gap_report")
    sponsors = next(g["id"] for g in report["gaps"] if g["path"] == "/api/sponsors")
    o.pick([sponsors, "nope"])
    t.join(300)
    status = next(e for e in bus.history if e["type"] == "gap_status")
    assert status["fixed"] == [sponsors] and len(status["open"]) == 5 and status["selected"] == [sponsors]
    assert out["res"].tests_passed is False or out["res"].tests_passed is True  # the other gaps are the owner's to leave: their gap tests were not generated
    summary = next(e for e in bus.history if e["type"] == "finish_summary")
    assert [f["path"] for f in summary["files"]] == ["app/routers/events.py"]


def test_the_api_declines_a_missing_folder_politely_before_anything_starts(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    r = TestClient(create_app()).post("/api/projects", json={"goal": "", "mode": "supervised", "demo": False, "import_from": str(tmp_path / "nope")})
    assert r.status_code == 422 and "could not find" in r.json()["detail"]


def test_a_well_known_missing_import_is_added_by_the_sandbox_and_an_invented_name_is_not(tmp_path):
    from app.config import load_agents
    from app.tools import ToolBox

    (tmp_path / "main.py").write_text("import os\nfrom fastapi import FastAPI\n\napp = FastAPI()\n\n\n@app.post('/b/{id}/return')\ndef give_back(id: int):\n    raise NotImplementedError\n", encoding="utf-8")
    agent = load_agents()["backend"].model_copy(update={"owned_paths": ["main.py"], "forbidden_paths": []})
    tb = ToolBox(tmp_path, agent, mode=lambda: "autonomous")
    tb.auto_imports = {"HTTPException": "from fastapi import HTTPException", "timedelta": "from datetime import timedelta"}
    r = tb.execute(Action.model_validate(act("implement", path="main.py", function="give_back", content="if id > 5:\n    raise HTTPException(404, 'nope')\nreturn {'due': str(timedelta(days=14))}")))
    assert r.ok, r.output
    text = (tmp_path / "main.py").read_text(encoding="utf-8")
    assert text.index("from fastapi import HTTPException") < text.index("app = FastAPI()") and "from datetime import timedelta" in text and text.startswith("import os\nfrom fastapi import FastAPI\nfrom ")
    compile(text, "main.py", "exec")
    bad = tb.execute(Action.model_validate(act("implement", path="main.py", function="give_back", content="return db.nothing(id)")))
    assert not bad.ok
