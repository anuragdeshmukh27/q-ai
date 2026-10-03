"""P7: model router, VRAM-aware scheduler, shipped benchmark results, fast live mode, Ask-employee project state."""
import json
import threading
import time

from app.contract_tests import list_view_fields, ui_script_test_source
from app.agent.review import ReviewItem, ReviewOutput
from app.events import EventBus
from app.leaderboard import Leaderboard
from app.registry import ModelRegistry
from app.router import Router
from app.schemas import ArchitectOutput
from app.scheduler import ModelScheduler
from app.session import Tracker
from app.config import load_agents

from test_orchestrator import DB_LIST, DESIGN, FakeLLM, act, make, types
from test_polish import POLISHED_HTML, POLISHED_JS

REG = ModelRegistry.load(env={})


def board(tmp_path, runs, shipped=None):
    b = Leaderboard(tmp_path / "q.db", shipped=shipped)
    for model, role, passed_n, total in runs:
        for i in range(total):
            b.record(model, role, f"task{i}", i < passed_n, 4, 10.0, 500, 4.6)
    return b


# -- router -------------------------------------------------------------------------------------------

def test_without_benchmark_evidence_every_role_uses_the_safe_default(tmp_path):
    r = Router(REG, board(tmp_path, []))
    for agent, cap in (("architect", "reasoning"), ("reviewer", "review"), ("backend", "coding"), ("database", "sql")):
        route = r.choose(agent, cap)
        assert route.model.id == "qwen25-coder-7b" and route.source == "default" and "no benchmark data" in route.reason


def test_a_challenger_must_beat_the_default_by_the_margin_on_enough_runs(tmp_path):
    r = Router(REG, board(tmp_path, [("qwen25-coder-7b", "reviewer", 2, 4), ("qwen3-4b", "reviewer", 4, 4),  # 50% vs 100%: switch
                                    ("qwen25-coder-7b", "planner", 3, 4), ("qwen3-4b", "planner", 3, 4),    # tie: stay (a swap costs a model load)
                                    ("qwen25-coder-7b", "qa", 2, 4), ("qwen3-4b", "qa", 3, 4),             # +25 points: switch
                                    ("qwen25-coder-7b", "architect", 4, 4), ("qwen3-4b", "architect", 1, 1)])) # one run: not enough evidence
    assert r.choose("reviewer", "review").model.id == "qwen3-4b" and r.choose("reviewer", "review").source == "score"
    assert "100%" in r.choose("reviewer", "review").reason and "50%" in r.choose("reviewer", "review").reason
    assert r.choose("planner", "reasoning").model.id == "qwen25-coder-7b" and "does not beat" in r.choose("planner", "reasoning").reason
    assert r.choose("qa", "review").model.id == "qwen3-4b"
    assert r.choose("architect", "reasoning").model.id == "qwen25-coder-7b"


def test_the_router_changes_a_model_choice_when_the_scores_change(tmp_path):
    b = board(tmp_path, [("qwen25-coder-7b", "reviewer", 3, 4)])
    r = Router(REG, b, ttl=0)
    assert r.choose("reviewer", "review").model.id == "qwen25-coder-7b"
    for i in range(4):
        b.record("llama32-3b", "reviewer", f"t{i}", True, 2, 3.0, 200, 2.5)
    assert r.choose("reviewer", "review").model.id == "llama32-3b"  # 100% vs 75%


def test_a_pin_beats_the_scores_and_explains_itself(tmp_path):
    reg = ModelRegistry(REG.models.values(), env={}, router={"safe_default": "qwen25-coder-7b", "margin": 0.1, "min_runs": 2,
                                                            "pins": {"reviewer": {"model": "qwen25-coder-7b", "reason": "full builds got worse with the 4B"}}})
    r = Router(reg, board(tmp_path, [("qwen25-coder-7b", "reviewer", 1, 4), ("qwen3-4b", "reviewer", 4, 4)]))
    route = r.choose("reviewer", "review")
    assert route.model.id == "qwen25-coder-7b" and route.source == "pin" and "full builds got worse" in route.reason


def test_the_router_never_returns_an_unavailable_or_cloud_model_for_a_local_build(tmp_path):
    reg = ModelRegistry(REG.models.values(), env={}, router=REG.router_config)
    b = board(tmp_path, [("qwen25-coder-7b", "backend", 0, 4), ("gemini-flash", "backend", 4, 4)])
    assert Router(reg, b).choose("backend", "coding").model.id == "qwen25-coder-7b"  # no API key -> unavailable


def test_the_orchestrator_asks_the_router_but_a_manual_override_wins(tmp_path):
    b = board(tmp_path, [("qwen25-coder-7b", "reviewer", 1, 4), ("qwen3-4b", "reviewer", 4, 4)])
    llm = FakeLLM()
    o, _ = make(tmp_path / "w", llm, router=Router(REG, b))
    o.run()
    used = {(m, s) for m, s in llm.models_used}
    assert ("qwen3-4b", "ReviewOutput") in used and all(m == "qwen25-coder-7b" for m, s in used if s != "ReviewOutput")
    llm2 = FakeLLM()
    o2, _ = make(tmp_path / "w2", llm2, router=Router(REG, b), overrides={"reviewer": "llama32-3b"})
    o2.run()
    assert ("llama32-3b", "ReviewOutput") in set(llm2.models_used)


# -- shipped benchmark results ---------------------------------------------------------------------------

def test_shipped_results_fill_the_leaderboard_and_local_runs_replace_their_cell(tmp_path):
    shipped = tmp_path / "results.json"
    shipped.write_text(json.dumps({"generated": "2026-10-03", "machine": "test", "runs": [
        {"model": "qwen3-4b", "role": "qa", "task": "a", "passed": True, "iterations": 1, "seconds": 2.0, "tokens": 100, "peak_vram_gb": 3.6},
        {"model": "qwen3-4b", "role": "qa", "task": "b", "passed": False, "iterations": 2, "seconds": 4.0, "tokens": 300, "peak_vram_gb": 3.6},
        {"model": "llama32-3b", "role": "qa", "task": "a", "passed": True, "iterations": 1, "seconds": 1.0, "tokens": 90, "peak_vram_gb": 2.5}]}))
    b = Leaderboard(tmp_path / "q.db", shipped=shipped)
    s = b.summary()
    assert s["runs"] == 3 and s["generated"] == "2026-10-03" and s["matrix"]["qa"]["qwen3-4b"]["pass_rate"] == 0.5
    assert s["matrix"]["qa"]["qwen3-4b"]["source"] == "shipped" and s["matrix"]["qa"]["qwen3-4b"]["avg_tokens"] == 200
    b.record("qwen3-4b", "qa", "a", True, 1, 1.0, 50, 3.6)
    s = b.summary()
    assert s["matrix"]["qa"]["qwen3-4b"]["runs"] == 1 and s["matrix"]["qa"]["qwen3-4b"]["source"] == "live"  # this machine's run replaces the cell
    assert s["matrix"]["qa"]["llama32-3b"]["source"] == "shipped"
    out = tmp_path / "out.json"
    assert b.export(out, machine="m") == 2 and len(json.loads(out.read_text())["runs"]) == 2


def test_the_committed_results_are_real_and_cover_the_local_models():
    b = Leaderboard.__new__(Leaderboard)  # read only the committed file
    from app.leaderboard import SHIPPED_RESULTS
    b._shipped_path = SHIPPED_RESULTS
    runs = b.shipped()
    assert runs, "backend/benchmarks/results.json must be committed so the leaderboard is not empty on demo day"
    assert {r["model"] for r in runs} >= {"qwen25-coder-7b", "qwen3-4b", "llama32-3b"}
    assert {r["role"] for r in runs} >= {"architect", "planner", "backend", "frontend", "database", "reviewer", "qa"}


# -- scheduler -----------------------------------------------------------------------------------------------

class FakeOllama:
    def __init__(self, loaded=None):
        self.loaded = dict(loaded or {})  # ollama name -> GB
        self.calls: list[tuple] = []

    def ps(self):
        return [{"name": n, "size_vram": int(gb * 1024 ** 3)} for n, gb in self.loaded.items()]

    def load(self, name, num_ctx, keep_alive):
        self.calls.append(("load", name, num_ctx))
        self.loaded[name] = next(m.vram_gb for m in REG.models.values() if m.name == name)

    def unload(self, name):
        self.calls.append(("unload", name))
        self.loaded.pop(name, None)


def sched(ollama):
    bus = EventBus()
    s = ModelScheduler(REG, ollama, bus.emit, headroom_gb=1.0, total_gb=lambda: 8.0, used_gb=lambda: 0.0)
    return s, bus


def ev(bus, *kinds):
    return [(e["type"], e.get("state") or e.get("model")) for e in bus.history if e["type"] in kinds]


def test_swapping_models_unloads_the_idle_one_and_shows_a_coffee_break():
    ol = FakeOllama({"qwen2.5-coder:7b": 4.7})
    s, bus = sched(ol)
    with s.slot(REG.get("qwen3-4b"), "reviewer"):  # 4.7 + 3.6 does not fit in 7 GB
        pass
    assert ol.calls == [("unload", "qwen2.5-coder:7b"), ("load", "qwen3:4b", 8192)]
    assert ev(bus, "model_unloaded", "model_loaded", "agent_state") == [
        ("model_unloaded", "qwen25-coder-7b"), ("agent_state", "loading_model"), ("model_loaded", "qwen3-4b"), ("agent_state", "thinking")]


def test_a_resident_model_is_not_reloaded_and_two_small_models_share_the_gpu():
    ol = FakeOllama({"qwen3:4b": 3.6})
    s, bus = sched(ol)
    with s.slot(REG.get("qwen3-4b"), "qa"):
        pass
    assert ol.calls == []  # already resident
    with s.slot(REG.get("llama32-3b"), "qa"):  # 3.6 + 2.5 = 6.1 fits in 7 GB
        pass
    assert ol.calls == [("load", "llama3.2:3b", 8192)] and "model_unloaded" not in types(bus)


def test_cloud_models_are_not_scheduled():
    ol = FakeOllama()
    s, bus = sched(ol)
    with s.slot(REG.get("gemini-flash"), "backend"):
        pass
    assert ol.calls == [] and bus.history == []


def test_an_agent_waits_asleep_while_a_different_model_is_busy():
    ol = FakeOllama({"qwen2.5-coder:7b": 4.7})
    s, bus = sched(ol)
    order = []
    release = threading.Event()

    def busy():
        with s.slot(REG.get("qwen25-coder-7b"), "backend"):
            order.append("backend working")
            release.wait(5)
            order.append("backend done")

    def waiting():
        with s.slot(REG.get("qwen3-4b"), "reviewer"):
            order.append("reviewer working")

    a = threading.Thread(target=busy)
    a.start()
    while "backend working" not in order:
        time.sleep(0.01)
    b = threading.Thread(target=waiting)
    b.start()
    time.sleep(0.8)
    assert order == ["backend working"] and ("agent_state", "sleeping") in ev(bus, "agent_state")
    release.set()
    a.join(5)
    b.join(5)
    assert order == ["backend working", "backend done", "reviewer working"]
    assert ev(bus, "agent_state")[-1] == ("agent_state", "thinking") and ol.calls[0] == ("unload", "qwen2.5-coder:7b")


def test_a_waiting_swap_is_not_starved_by_later_calls_for_the_loaded_model():
    ol = FakeOllama({"qwen2.5-coder:7b": 4.7})
    s, _ = sched(ol)
    order, release = [], threading.Event()

    def call(name, model, hold=None):
        with s.slot(REG.get(model), name):
            order.append(f"{name} in")
            if hold:
                hold.wait(5)

    a = threading.Thread(target=call, args=("A", "qwen25-coder-7b", release))
    a.start()
    while "A in" not in order:
        time.sleep(0.01)
    b = threading.Thread(target=call, args=("B", "qwen3-4b"))
    b.start()
    time.sleep(0.6)  # B is queued behind A's model
    c = threading.Thread(target=call, args=("C", "qwen25-coder-7b"))
    c.start()
    time.sleep(0.6)
    assert order == ["A in"]  # C did not jump the queue although its model is the loaded one
    release.set()
    [t.join(8) for t in (a, b, c)]
    assert order == ["A in", "B in", "C in"]


def test_same_model_calls_run_together_without_swaps():
    ol = FakeOllama({"qwen2.5-coder:7b": 4.7})
    s, _ = sched(ol)
    inside = []
    barrier = threading.Barrier(2, timeout=5)

    def go():
        with s.slot(REG.get("qwen25-coder-7b"), "x"):
            inside.append(1)
            barrier.wait()

    ts = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ts]
    [t.join(8) for t in ts]
    assert len(inside) == 2 and ol.calls == []


# -- the list views and the labels ---------------------------------------------------------------------------

def test_the_generated_ui_test_requires_every_list_field_to_be_read_from_the_item():
    d = ArchitectOutput.model_validate(DESIGN)
    assert list_view_fields(d) == ["operation"]  # a and b are too short to search for; result is not entered by the user
    src = ui_script_test_source(d)
    ns: dict = {}
    # run the generated test body against two scripts
    import re
    for js, ok in (("fetch('/api/history'); row.operation", True), ("fetch('/api/history'); body: {operation: x}", False)):
        pat = re.search(r"assert re\.search\((.*?), js\)", src).group(1)
        hit = re.search(eval(pat, {"field": "operation", "re": re}), js)
        assert bool(hit) is ok
    assert "def test_list_view_shows_every_field_of_an_item" in src and "badge" in src
    compile(src, "generated", "exec")


def test_the_frontend_prompt_states_the_generic_list_and_label_rules():
    from app.config import PROMPTS_DIR
    text = (PROMPTS_DIR / "frontend.md").read_text(encoding="utf-8")
    assert "EVERY field" in text and "badges" in text and "never shows a bare number" in text and "2 pending" in text


def test_a_request_task_tells_the_engineer_to_label_counters(tmp_path):
    o, _ = make(tmp_path, FakeLLM())
    t = {"id": "r1", "title": "Request: add a counter", "owner": "frontend", "kind": "request", "request": "show how many are pending", "acceptance": ["done"]}
    text = o._task_text(t)
    assert "text label" in text and "2 pending" in text


# -- fast live mode ------------------------------------------------------------------------------------------------

def fix_script(llm):
    llm.scripts["Karan"] += [act("implement", path="database/calculations.py", function="list_history", content=DB_LIST.replace("DESC'", "DESC LIMIT 100'")),
                             act("run_tests"), act("finish", summary="limited")]


def test_fast_live_mode_allows_one_llm_review_and_accepts_a_clean_fix_without_a_second_one(tmp_path):
    llm = FakeLLM()
    llm.reviews = [ReviewOutput(verdict="REQUEST_CHANGES", summary="x", items=[ReviewItem(file="database/calculations.py", problem="limit the history to 100 rows")])]
    fix_script(llm)
    o, bus = make(tmp_path, llm, fast_live=True)
    res = o.run()
    assert res.ok, res.problems
    t1 = [e for e in bus.history if e["type"] == "review_result" and e["task"] == "t1"]
    assert [(e["round"], e["verdict"]) for e in t1] == [(1, "REQUEST_CHANGES"), (2, "PASS")]
    assert "automatic checks are clean" in t1[1]["summary"]
    assert sum(1 for _, s in llm.models_used if s == "ReviewOutput") == 4  # one model review per task, none for the fix
    assert "LIMIT 100" in (res.root / "database/calculations.py").read_text()


def test_fast_live_mode_static_findings_still_block_after_the_single_round(tmp_path):
    llm = FakeLLM()
    bad = DB_LIST.replace("conn.execute('SELECT * FROM calculations ORDER BY id DESC')", "conn.execute(f'SELECT * FROM calculations ORDER BY id DESC')")
    llm.reviews = [ReviewOutput(verdict="REQUEST_CHANGES", summary="x", items=[ReviewItem(file="database/calculations.py", problem="change it")])]
    llm.scripts["Karan"] += [act("implement", path="database/calculations.py", function="list_history", content=bad), act("run_tests"), act("finish", summary="fixed")]
    o, bus = make(tmp_path, llm, fast_live=True)  # autonomous: accepts the unresolved review and records it
    res = o.run()
    assert [e["verdict"] for e in bus.history if e["type"] == "review_result" and e["task"] == "t1"] == ["REQUEST_CHANGES"]  # no second review, no clean pass
    assert any(e["type"] == "escalation" and e.get("reason") == "review_unresolved" for e in bus.history)
    assert "merged with open review items" in o.memory.read("decisions.md") and "SQL is built from strings" in o.memory.read("decisions.md")


def test_normal_mode_still_allows_three_review_rounds(tmp_path):
    import app.orchestrator as om
    assert om.MAX_REVIEW_ROUNDS == 3
    o, _ = make(tmp_path, FakeLLM())
    assert o.fast_live is False


def test_fast_live_mode_skips_the_polish_pass_when_the_page_already_uses_the_kit(tmp_path):
    llm = FakeLLM()
    llm.scripts["Meera"] = llm.scripts["Meera"][:4] + [act("write_file", path="static/index.html", content=POLISHED_HTML),
                                                         act("write_file", path="static/app.js", content=POLISHED_JS), act("run_tests"), act("finish", summary="script")]
    # the page task writes index.html first; give it the kit page and a script that already uses two helpers
    llm.scripts["Meera"][0] = act("write_file", path="static/index.html", content=POLISHED_HTML)
    o, bus = make(tmp_path, llm, polish=True, fast_live=True)
    res = o.run()
    assert res.ok, res.problems
    polish = [e for e in bus.history if e["type"] == "polish_result"]
    assert polish and polish[0]["ok"] and "fast live mode" in polish[0].get("skipped", "")
    assert not any(t["id"] == "p1" for t in res.tasks)  # no polish agent ran at all


def test_without_fast_live_mode_the_polish_task_still_runs(tmp_path):
    from test_polish import polish_script
    llm = FakeLLM()
    polish_script(llm)
    o, bus = make(tmp_path, llm, polish=True, fast_live=False)
    res = o.run()
    assert any(t["id"] == "p1" for t in res.tasks)


# -- Ask employee: the project is in progress again ---------------------------------------------------------------

def test_a_request_on_a_finished_project_reopens_it_and_only_the_involved_agents_are_done(tmp_path):
    llm = FakeLLM()
    o, bus = make(tmp_path, llm)
    assert o.run().ok
    tracker = Tracker(load_agents())
    for e in bus.history:
        tracker.on_event(e)
    assert tracker.finished and tracker.finished["ok"]
    llm.scripts["Rohan"] += [act("run_tests"), act("finish", summary="nothing else needed")]
    o.add_request("backend", "double check the error format")
    resumed = [e for e in bus.history if e["type"] == "project_resumed"]
    assert len(resumed) == 1 and resumed[0]["agent"] == "backend"
    for e in bus.history[-6:]:
        tracker.on_event(e)
    assert tracker.finished is None  # in progress again
    o.finish_requests()
    done = [e for e in bus.history if e["type"] == "project_done"]
    assert len(done) == 2 and done[-1]["request"] is True and done[-1]["involved"] == ["backend"] and done[-1]["ok"]
    assert types(bus).count("project_resumed") == 1


# -- the UI kit's list helper -------------------------------------------------------------------------------------------

def test_ui_kit_renders_a_whole_list_in_one_call_with_every_field_badge_and_button():
    import shutil
    import subprocess
    from pathlib import Path
    kit = Path(__file__).parents[1] / "app" / "presets" / "fastapi_vanilla" / "skeleton" / "static" / "ui-kit.js"
    assert "renderList" in kit.read_text(encoding="utf-8") and "listItem" in kit.read_text(encoding="utf-8")
    if not shutil.which("node"):
        return
    out = subprocess.run(["node", str(Path(__file__).parent / "js" / "kit_dom.mjs"), str(kit)], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    text = out.stdout
    assert 'class="list-item done"' in text and "Buy milk" in text and "two litres" in text  # title, detail line, done strike-through
    assert 'badge badge-danger">High' in text and 'badge badge-info">whatever' in text  # priority badges, coloured by value
    assert text.count("Delete") == 2 and "clicked 1" in text and "None yet" in text  # buttons are wired; the empty state shows


def test_the_frontend_prompt_and_example_use_the_list_helper_not_dom_code():
    from app.config import PROMPTS_DIR
    text = (PROMPTS_DIR / "frontend.md").read_text(encoding="utf-8")
    assert "UI.renderList(" in text and "do NOT build list items with DOM code" in text
    example = text[text.index("Worked example: `static/app.js`"):]
    assert "UI.renderList(list, data.items" in example and "createElement" not in example
    d = ArchitectOutput.model_validate(DESIGN)
    import re
    src = ui_script_test_source(d)
    pattern = eval(re.search(r"re\.search\((.*?), js\)", src).group(1), {"field": "operation", "re": re})
    assert re.search(pattern, 'UI.renderList(list, items, (i) => ({ title: "operation", badges: ["operation"] }))')
    assert not re.search(pattern, "body: JSON.stringify({ operation: document.getElementById('operation').value })")
