"""UI kit and the final polish task: the kit is always on the page, polish runs after QA, and a bad polish can never reach main."""
import subprocess

from test_orchestrator import FakeLLM, act, make, types

POLISHED_HTML = ("<!doctype html><html><head><link rel='stylesheet' href='/static/ui-kit.css'><link rel='stylesheet' href='/static/style.css'>"
                 "<script src='/static/ui-kit.js'></script></head><body><main class='container'><section class='card'><form id='f'></form>"
                 "<div id='list'></div></section></main><script src='/static/app.js'></script></body></html>")
POLISHED_JS = ("async function go() {\n  const list = document.getElementById('list');\n  UI.loading(list);\n"
               "  await fetch('/api/calculate');\n  const r = await fetch('/api/history');\n  const d = await r.json();\n"
               "  if (!d.items.length) UI.empty(list, 'No calculations yet');\n  for (const item of d.items) { list.textContent = item.operation; }\n}\ngo();\n")


def polish_script(llm):
    llm.scripts["Meera"] += [act("write_file", path="static/index.html", content=POLISHED_HTML), act("write_file", path="static/app.js", content=POLISHED_JS),
                             act("run_tests"), act("finish", summary="polished")]


def git_out(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def test_every_project_ships_the_ui_kit_and_the_served_page_always_links_it(tmp_path):
    o, _ = make(tmp_path, FakeLLM())
    res = o.run()
    assert res.ok, res.problems
    css = (res.root / "static" / "ui-kit.css").read_text(encoding="utf-8")
    for part in (".card", ".btn-secondary", ".table", ".badge-success", ".toast", ".empty-state", ".spinner", "prefers-reduced-motion"):
        assert part in css, part
    assert "window.UI" in (res.root / "static" / "ui-kit.js").read_text(encoding="utf-8")
    from fastapi.testclient import TestClient
    import importlib
    import sys
    sys.path.insert(0, str(res.root))
    try:
        for m in [m for m in sys.modules if m.split(".")[0] in ("backend", "database")]:
            del sys.modules[m]
        page = TestClient(importlib.import_module("backend.main").app).get("/").text
    finally:
        sys.path.remove(str(res.root))
        for m in [m for m in sys.modules if m.split(".")[0] in ("backend", "database")]:
            del sys.modules[m]
    # the scripted page never linked the kit itself; the server added it
    assert "/static/ui-kit.css" in page and "/static/ui-kit.js" in page and page.index("ui-kit.js") < page.index("/static/app.js")


def test_engineers_cannot_edit_the_ui_kit(tmp_path):
    o, _ = make(tmp_path, FakeLLM())
    o.run()
    from app.sandbox.paths import PathPolicy, SandboxError
    import pytest
    fe = o._engineer("frontend")
    pp = PathPolicy(o.root, fe.owned_paths, fe.forbidden_paths)
    for locked in ("static/ui-kit.css", "static/ui-kit.js"):
        with pytest.raises(SandboxError):
            pp.resolve_write(locked)
    pp.resolve_write("static/style.css")


def test_polish_is_off_by_default(tmp_path):
    o, bus = make(tmp_path, FakeLLM())
    res = o.run()
    assert res.ok and "polish_result" not in types(bus) and all(t["id"] != "p1" for t in res.tasks)


def test_polish_runs_after_qa_passes_and_merges_when_the_whole_suite_is_green(tmp_path):
    llm = FakeLLM()
    polish_script(llm)
    o, bus = make(tmp_path, llm, polish=True)
    res = o.run()
    assert res.ok, res.problems
    p1 = next(t for t in res.tasks if t["id"] == "p1")
    assert p1["status"] == "done" and p1["owner"] == "frontend" and p1["kind"] == "polish"
    t = types(bus)
    last_qa = max(i for i, e in enumerate(bus.history) if e["type"] == "test_result" and e.get("agent") == "qa")
    assigned = next(i for i, e in enumerate(bus.history) if e["type"] == "task_assigned" and e["task"] == "p1")
    assert last_qa < assigned < t.index("project_done")
    assert [e["ok"] for e in bus.history if e["type"] == "polish_result"] == [True]
    assert "UI.empty" in (res.root / "static" / "app.js").read_text(encoding="utf-8")
    assert "[frontend] Polish the UI with the UI kit" in git_out(res.root, "log", "agent/frontend", "--pretty=%s")
    assert res.tests_passed


def test_a_polish_that_fails_the_safety_check_is_skipped_and_main_stays_as_qa_left_it(tmp_path, monkeypatch):
    llm = FakeLLM()
    polish_script(llm)
    o, bus = make(tmp_path, llm, polish=True)
    monkeypatch.setattr(o, "_polish_check", lambda wt: "tests failed on the polished branch (1 failed)")
    res = o.run()
    assert res.ok, res.problems  # a skipped polish is not a failed build
    p1 = next(t for t in res.tasks if t["id"] == "p1")
    assert p1["status"] == "skipped" and "polish skipped" in p1["summary"]
    assert [e["ok"] for e in bus.history if e["type"] == "polish_result"] == [False]
    assert "UI.empty" not in (res.root / "static" / "app.js").read_text(encoding="utf-8")
    assert "Polish the UI" not in git_out(res.root, "log", "main", "--pretty=%s")
    assert "Polish skipped" in o.memory.read("decisions.md")


def test_polish_is_skipped_when_the_build_already_has_problems(tmp_path):
    llm = FakeLLM()
    o, bus = make(tmp_path, llm, polish=True)
    o.problems.append("earlier problem")
    o._design()
    o._polish()
    assert "polish_result" not in types(bus) and not any(t["id"] == "p1" for t in o.tasks)


def test_polish_is_on_for_live_builds_unless_switched_off_with_q_polish():
    from app.session import Settings
    assert Settings.from_env({}).polish is True
    assert Settings.from_env({"Q_POLISH": "0"}).polish is False
    assert Settings.from_env({"Q_POLISH": "off"}).polish is False


def test_polish_task_shows_the_current_files_and_skips_the_llm_review_but_not_the_static_checks(tmp_path):
    llm = FakeLLM()
    llm.scripts["Meera"] += [act("write_file", path="static/app.js", content=POLISHED_JS.replace("UI.empty(list, 'No calculations yet')", "list.innerHTML = '<b>none</b>'")),
                             act("run_tests"), act("finish", summary="polished")]
    seen = []
    real_call = llm.call

    def spy(model_id, messages, schema_model, temperature=0.2):
        seen.append((schema_model.__name__, messages[1]["content"] if len(messages) > 1 else ""))
        return real_call(model_id, messages, schema_model, temperature)

    llm.call = spy
    o, bus = make(tmp_path, llm, polish=True)
    res = o.run()
    assert res.ok, res.problems
    polish_prompts = [c for n, c in seen if "Task p1" in c]
    assert polish_prompts and "Current static/app.js" in polish_prompts[0] and "fetch('/api/history')" in polish_prompts[0]
    p1 = next(t for t in res.tasks if t["id"] == "p1")
    assert p1["status"] == "skipped" and "innerHTML" in p1["summary"]  # the static security check refused the polished script
    assert not any(e["type"] == "review_result" and e["task"] == "p1" for e in bus.history)


def test_a_polished_script_that_uses_no_ui_kit_helper_is_not_merged(tmp_path):
    o, _ = make(tmp_path, FakeLLM(), polish=True)
    o.run()
    wt = o.repo.worktree("frontend")
    (wt / "static" / "app.js").write_text("fetch('/api/calculate'); fetch('/api/history'); const x = item.operation;\n", encoding="utf-8")
    assert "UI kit helper" in o._polish_check(wt)
    (wt / "static" / "app.js").write_text("fetch('/api/calculate'); fetch('/api/history'); const x = item.operation; UI.num(1);\n", encoding="utf-8")
    assert o._polish_check(wt) == ""


def test_polish_that_changes_nothing_is_reported_as_nothing_to_change_and_merges_nothing(tmp_path):
    llm = FakeLLM()
    llm.scripts["Meera"] += [act("finish", summary="already looks right")]
    o, bus = make(tmp_path, llm, polish=True)
    res = o.run()
    assert res.ok, res.problems
    p1 = next(t for t in res.tasks if t["id"] == "p1")
    assert p1["status"] == "done" and "nothing to change" in p1["summary"]
    assert [(e["ok"], e["changed"]) for e in bus.history if e["type"] == "polish_result"] == [(True, False)]
    assert "Polish the UI" not in git_out(res.root, "log", "main", "--pretty=%s")


def test_a_polish_that_only_resends_the_existing_file_counts_as_nothing_to_change(tmp_path):
    llm = FakeLLM()
    llm.scripts["Meera"] += [act("read_file", path="static/app.js"), act("read_file", path="static/app.js"), act("read_file", path="static/app.js"),
                             act("read_file", path="static/app.js")]
    o, bus = make(tmp_path, llm, polish=True)
    res = o.run()
    assert res.ok, res.problems
    p1 = next(t for t in res.tasks if t["id"] == "p1")
    assert p1["status"] == "done" and "nothing to change" in p1["summary"]
    assert [(e["ok"], e["changed"]) for e in bus.history if e["type"] == "polish_result"] == [(True, False)]


def test_a_skipped_polish_leaves_no_half_polished_edits_in_the_frontend_worktree(tmp_path, monkeypatch):
    llm = FakeLLM()
    polish_script(llm)
    o, _ = make(tmp_path, llm, polish=True)
    monkeypatch.setattr(o, "_polish_check", lambda wt: "tests failed on the polished branch (1 failed)")
    res = o.run()
    wt = res.root / ".worktrees" / "frontend"
    assert "UI.empty" not in (wt / "static" / "app.js").read_text(encoding="utf-8")
    assert git_out(wt, "status", "--porcelain") == "" and git_out(res.root, "diff", "--name-only", "main...agent/frontend") == ""
