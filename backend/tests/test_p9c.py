"""P9c: who wrote the code (authorship), the single-agent baseline, and the team-vs-single-agent report."""
import json

from app.authorship import measure, _py_functions
from app.baseline import SoloBuild, rules_plan, unimplemented
from app.events import EventBus
from app.leaderboard import baseline_report
from app.platforms import match_platform
from app.registry import ModelRegistry
from app.relations import synthesize_design
from app.scaffold import db_stub
from app.schemas import PlannerOutput, SpecOutput, drop_leaked, normalize_spec

from test_relational_build import RelationalLLM, act, db_scripts, router_scripts
from test_orchestrator import types


def uber():
    return synthesize_design(normalize_spec(match_platform("Build Uber"), "Build Uber"))


# -- authorship -------------------------------------------------------------------------------------------------

def test_a_function_whose_body_changed_is_the_agents_and_the_rest_is_generated(tmp_path):
    d = uber()
    stub = db_stub(d, "rides")
    (tmp_path / "database").mkdir()
    final = stub.replace("raise NotImplementedError", "return []", 1)  # the agent filled exactly one function
    (tmp_path / "database" / "rides.py").write_text(final, encoding="utf-8")
    report = measure(tmp_path, {"database/rides.py": stub}, set(), "fastapi-vanilla")
    f = report["files"][0]
    assert f["functions"] == stub.count("raise NotImplementedError")
    assert f["functions_agent"] == 1 and f["functions_generated"] == f["functions"] - 1 and f["functions_repair"] == 0
    assert f["lines_agent"] == 1 and f["lines_generated"] == f["lines"] - 1
    assert report["app"]["agent_share_functions"] == round(1 / f["functions"], 3)


def test_a_contract_repaired_file_counts_as_repair_not_as_agent_work(tmp_path):
    d = uber()
    repaired = db_stub(d, "rides", fill=True)
    (tmp_path / "database").mkdir()
    (tmp_path / "database" / "rides.py").write_text(repaired, encoding="utf-8")
    f = measure(tmp_path, {"database/rides.py": repaired}, {"database/rides.py"}, "fastapi-vanilla", {"spec_by": "platform table"})
    assert f["app"]["functions_agent"] == 0 and f["app"]["functions_repair"] == f["app"]["functions"] > 0
    assert f["app"]["lines_agent"] == 0 and f["app"]["lines_repair"] == f["app"]["lines"]
    assert f["repairs"] == ["database/rides.py"] and f["spec_by"] == "platform table"


def test_a_file_the_rules_never_wrote_and_the_tests_are_counted_separately(tmp_path):
    (tmp_path / "backend" / "api").mkdir(parents=True)
    (tmp_path / "backend" / "api" / "extra.py").write_text("def a():\n    return 1\n\n\ndef b():\n    return 2\n", encoding="utf-8")
    (tmp_path / "tests" / "api").mkdir(parents=True)
    (tmp_path / "tests" / "api" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (tmp_path / "tests" / "test_db_x.py").write_text("def test_db():\n    assert True\n", encoding="utf-8")
    r = measure(tmp_path, {}, set(), "fastapi-vanilla")
    assert r["app"]["functions"] == 2 and r["app"]["functions_agent"] == 2 and r["app"]["agent_share_lines"] == 1.0
    assert r["tests"] == {"files": 2, "lines": 4, "lines_agent": 2, "lines_generated": 2}, "a test an agent wrote is the agent's, a generated one is not"


def test_a_file_that_does_not_parse_has_no_functions_to_credit():
    assert _py_functions("def broken(:\n") is None


def test_javascript_functions_are_counted_and_an_edited_one_is_the_agents(tmp_path):
    generated = "function load() {\n  return 1\n}\nconst render = (x) => {\n  return x\n}\n"
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "app.js").write_text(generated.replace("return 1", "return 2"), encoding="utf-8")
    f = measure(tmp_path, {"static/app.js": generated}, set(), "fastapi-vanilla")["files"][0]
    assert (f["functions"], f["functions_agent"], f["functions_generated"]) == (2, 1, 1)


# -- the baseline -----------------------------------------------------------------------------------------------

def test_the_baseline_plan_places_the_same_files_the_team_names():
    d = uber()
    assert [t.files for t in rules_plan(d)] == [["database/rides.py"], ["backend/api/rides.py"], ["static/index.html", "static/style.css"], ["static/app.js"]]
    assert unimplemented(db_stub(d, "rides")) and unimplemented(db_stub(d, "rides", fill=True)) == []


class SoloLLM(RelationalLLM):
    def __init__(self, d, script):
        super().__init__(d)
        self.script = list(script)

    def call(self, model_id, messages, schema_model, temperature=0.2):
        from app.agent.actions import Action
        from app.llm import StructuredResult

        assert schema_model is Action or schema_model is SpecOutput, f"the single agent has no {schema_model.__name__} step"
        assert schema_model is not PlannerOutput
        if schema_model is Action:
            self.models_used.append((model_id, "Action"))
            assert "You are Solo" in messages[0]["content"] and "Backend rules" in messages[0]["content"]
            return StructuredResult(Action.model_validate(self.script.pop(0)), model_id, 1, 10, 5, 0.01, "{}")
        return super().call(model_id, messages, schema_model, temperature)


def solo_script(d):
    implements = [a for r in d.resources for a in db_scripts(d, r) if a["action"] == "implement"]
    implements += [a for r in d.resources for a in router_scripts(d, r) if a["action"] == "implement"]
    return implements + [act("run_tests"), act("finish", summary="the whole app is done")]


def test_one_agent_builds_the_whole_app_in_one_loop_with_no_team_around_it(tmp_path):
    d = uber()
    llm = SoloLLM(d, solo_script(d))
    bus = EventBus()
    o = SoloBuild("Build Uber", ModelRegistry.load(env={}), llm, bus, mode="autonomous", base=tmp_path, start_app=False)
    res = o.run()
    assert res.ok, res.problems
    assert [(t["id"], t["owner"], t["status"]) for t in res.tasks] == [("s1", "solo", "done")]
    seen = set(types(bus))
    assert not seen & {"review_result", "bug_filed", "merge_result", "contract_repair", "consultant_called"}, "no reviewer, QA, integrator or repair in the baseline"
    assert not [m for _, m in llm.models_used if m in ("ReviewOutput", "PlannerOutput", "BugTriage")]
    assert (res.root / "tests/qa/test_edge_cases.py").is_file(), "the complete suite is there from the start"
    report = json.loads((res.root / ".q/authorship.json").read_text(encoding="utf-8"))
    n = sum(1 for a in solo_script(d) if a["action"] == "implement")
    assert report["app"]["functions_agent"] == n and report["repairs"] == []
    assert o.authorship["app"]["functions"] == report["app"]["functions"]


def test_a_single_agent_that_cannot_make_the_tests_pass_fails_the_build_without_a_second_attempt(tmp_path):
    d = uber()
    llm = SoloLLM(d, [act("run_tests")] * 5)  # reruns the failing tests: the repeated-action rule stops it
    o = SoloBuild("Build Uber", ModelRegistry.load(env={}), llm, EventBus(), mode="autonomous", base=tmp_path, start_app=False)
    res = o.run()
    assert not res.ok and any("single agent stopped" in p for p in res.problems)
    assert [t["status"] for t in res.tasks] == ["failed"] and o.authorship["app"]["functions_agent"] == 0, "nothing was written by an agent, and nothing was repaired for it"


# -- the team's build records who wrote the code ----------------------------------------------------------------

def test_a_team_build_saves_its_authorship_and_how_the_design_was_made(tmp_path):
    from test_orchestrator import make

    d = uber()
    o, _ = make(tmp_path, RelationalLLM(d))
    o.goal = "Build Uber"
    res = o.run()
    assert res.ok, res.problems
    report = json.loads((res.root / ".q/authorship.json").read_text(encoding="utf-8"))
    assert report["spec_by"] == "platform table" and report["contract_by"] == "rules" and report["plan_by"] == "rules"
    assert report["app"]["functions_agent"] > 0 and report["app"]["lines_generated"] > report["app"]["lines_agent"], "the generated page and the stubs outweigh the agents' lines"
    assert next(f for f in report["files"] if f["path"] == "static/app.js")["lines_agent"] == 0, "the page that passed its tests was not touched by an agent"


# -- the report -------------------------------------------------------------------------------------------------

def run(goal, mode, ok, seconds=100, fa=10, fn=20, qa=0, review=0, repair=0, tp=40, tf=0):
    return {"goal_key": goal, "goal": f"Build {goal}", "mode": mode, "ok": ok, "seconds": seconds, "tests_passed": tp, "tests_failed": tf, "qa_bugs": qa,
            "review_requests": review, "contract_repairs": repair, "authorship": {"app": {"functions": fn, "functions_agent": fa, "lines": 200, "lines_agent": 50}}}


def test_the_baseline_report_totals_each_arm_per_goal_and_overall(tmp_path):
    runs = [run("a", "team", True, 100, review=1, repair=1), run("a", "team", True, 120), run("a", "solo", False, 60, tp=30, tf=10), run("a", "solo", True, 90),
            run("b", "team", False, 300, tp=20, tf=5), run("b", "solo", False, 200, tp=0, tf=50)]
    f = tmp_path / "b.json"
    f.write_text(json.dumps({"generated": "2026-10-04", "runs": runs + [{"mode": "weird", "goal_key": "x"}]}), encoding="utf-8")
    rep = baseline_report(f)
    a = rep["goals"][0]
    assert a["key"] == "a" and (a["team"]["passed"], a["team"]["runs"]) == (2, 2) and (a["solo"]["passed"], a["solo"]["runs"]) == (1, 2)
    assert a["team"]["avg_seconds"] == 110 and a["solo"]["avg_seconds_passed"] == 90
    assert a["team"]["review_requests"] == 1 and a["team"]["builds_with_repair"] == 1
    assert rep["overall"]["team"]["pass_rate"] == round(2 / 3, 3) and rep["overall"]["solo"]["test_pass_rate"] == round(70 / 130, 3)
    assert rep["overall"]["team"]["agent_share_functions"] == 0.5
    assert len(rep["runs"]) == 6, "rows with an unknown mode are ignored"


def test_the_baseline_report_is_empty_when_the_benchmark_was_not_run(tmp_path):
    assert baseline_report(tmp_path / "missing.json") == {"runs": [], "goals": [], "overall": {}}


# -- a product name that is not in platforms.py ---------------------------------------------------------------------

def test_a_short_goal_that_names_a_product_is_recognised_and_a_plain_goal_is_not():
    from app.platforms import brand_name

    assert [brand_name(g) for g in ("Build Notion", "Build a Dropbox clone", "Make me Google Maps", "build Tinder", "Build Notion.")] == ["Notion", "Dropbox", "Google Maps", "Tinder", "Notion"]
    assert [brand_name(g) for g in ("Build a todo app", "Build a calculator with history", "Build an expense tracker: description, amount", "Build Notion with databases, pages, sharing and comments for teams",
                                    "Build a Q&A forum with answers")] == [None] * 5


def test_the_leaked_words_of_the_prompt_examples_are_dropped_from_the_banner_unless_the_goal_is_about_reddit():
    base = lambda: SpecOutput.model_validate({"title": "T", "summary": "s", "features": ["f"], "not_included": ["login", "subreddits", "more than two kinds of things"],
                                              "resources": [{"name": "matches", "fields": [{"name": "name", "type": "string"}], "operations": ["list", "create"]}]})
    assert normalize_spec(drop_leaked(base(), "Build Tinder"), "Build Tinder").not_included == ["login"]
    assert "subreddits" in normalize_spec(drop_leaked(base(), "Build a reddit replica"), "Build a reddit replica").not_included



def test_an_unknown_product_name_is_built_by_rules_with_a_banner_even_when_the_model_cannot_write_a_spec(tmp_path):
    """Dropbox before: the free Architect path built 'files' with no banner (a failure of the judge test); now the design, plan and tests are generated, and the page says what it is."""
    from app.platforms import generic_spec
    from test_orchestrator import make

    d = synthesize_design(normalize_spec(generic_spec("Dropbox"), "Build Dropbox"))

    class NoSpec(RelationalLLM):
        def call(self, model_id, messages, schema_model, temperature=0.2):
            from app.llm import StructuredResult

            if schema_model is SpecOutput:  # an empty spec: it never passes the checks, so the Architect gives up on the model
                return StructuredResult(SpecOutput(title="x", summary="y"), model_id, 1, 10, 5, 0.01, "{}")
            return super().call(model_id, messages, schema_model, temperature)

    llm = NoSpec(d)
    o, bus = make(tmp_path, llm)
    o.goal = "Build Dropbox"
    res = o.run()
    assert res.ok, res.problems
    assert [m for _, m in llm.models_used if m in ("ArchitectOutput", "PlannerOutput")] == [], "the contract and the plan are rules, not the model's free design"
    page = (res.root / "static/index.html").read_text(encoding="utf-8") + (res.root / "static/app.js").read_text(encoding="utf-8")  # the shell keeps the note in its description
    assert "notIncluded" in page and "most of what the real Dropbox does" in page
    assert [r["name"] for r in json.loads((res.root / ".q/design.json").read_text(encoding="utf-8"))["resources"]] == ["items"]
    assert any(e["type"] == "agent_thought" and "plain list app" in e.get("text", "") for e in bus.history)


def test_a_model_spec_for_an_unknown_name_gets_the_banner_and_the_rules_path(tmp_path):
    from test_orchestrator import make

    llm = RelationalLLM()
    o, bus = make(tmp_path, llm)
    o.goal = "Build Notion"
    res = o.run()
    assert res.ok, res.problems
    spec = next(e for e in bus.history if e["type"] == "spec_ready")
    assert spec["not_included"][0] == "most of what the real Notion does"
    assert "most of what the real Notion does" in (res.root / "static/app.js").read_text(encoding="utf-8")
    assert [m for _, m in llm.models_used if m == "ArchitectOutput"] == []


def test_a_frontend_request_for_a_computed_element_says_where_the_numbers_are_filled_in(tmp_path):
    from test_orchestrator import FakeLLM, make

    o, _ = make(tmp_path, FakeLLM())
    t = {"id": "r1", "title": "Request", "owner": "frontend", "files": [], "kind": "request", "request": "Add a progress bar at the top showing how many todos are done",
         "acceptance": ["the request is done"], "status": "pending", "summary": "", "attempts": 0, "depends_on": []}
    text = o._task_text(t)
    assert "progress bar at the top" in text and "const data = await res.json();" in text and "data.items" in text and "UI.progress(" in text and "</header>" in text and "`replace`" in text
    assert "request-hook:top" in text and "request-hook:loaded" in text and "never type the numbers" in text


# -- a yes/no field on a feed page (Coursera: enrollments.certificate failed its own generated UI test) ---------------

def _spec(parent_fields, child_fields):
    return {"title": "App", "summary": "s", "features": ["Form to add one", "List"], "resources": [
        {"name": "courses", "fields": parent_fields, "operations": ["list", "create", "update", "delete"]},
        {"name": "enrollments", "parent": "courses", "fields": child_fields, "operations": ["list", "create", "update", "delete"]}]}


S = lambda n: {"name": n, "type": "string"}  # noqa: E731
B = lambda n: {"name": n, "type": "boolean"}  # noqa: E731


def test_a_yes_no_field_of_a_post_or_a_comment_is_a_checkbox_that_saves_at_once(tmp_path, monkeypatch):
    monkeypatch.setenv("Q_SHELL", "0")  # the one-page feed layout
    from test_p9b import node_check, run_generated
    from app.look import choose_look
    from app.uistub import page_stub, script_stub

    for parent, child in (([S("title"), B("featured")], [S("user")]), ([S("title")], [S("user"), B("certificate")]), ([S("title"), B("featured")], [S("user"), B("certificate")])):
        s = normalize_spec(SpecOutput.model_validate(_spec(parent, child)), "Build Coursera")
        d = synthesize_design(s)
        d.look = choose_look("Build Coursera", s, d)
        html, js = page_stub(d, s.title), script_stub(d, s.title)
        assert "onToggle" in js and 'done: "' in js
        failed, details = run_generated(js, html, d)
        assert failed == set(), details
        node_check(js, tmp_path)
        assert len(js.splitlines()) < 150


def test_the_ask_check_accepts_only_a_real_bar_at_the_top():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from ask_check import check_dom

    head = '<header class="app-header">T</header>'
    kit = '<div id="progress" class="progress"><div class="progress-label">2 of 4 done</div><div class="progress-track"><div class="progress-fill" style="width: 50%;"></div></div></div>'
    cards = '<section class="card">Add</section><section class="card">Todos</section>'
    assert check_dom(f"<main>{head}{kit}{cards}</main>")[0]
    assert check_dom(f'<main>{head}<progress value="2" max="4"></progress><p>2 of 4 done</p>{cards}</main>')[0]
    assert check_dom(f'<main>{head}<progress value="50" max="100"></progress><p>2 of 4 done</p>{cards}</main>')[0]
    assert not check_dom(f"<main>{head}{cards}{kit}</main>")[0], "below the cards is not the top"
    assert not check_dom(f"<main>{head}{kit.replace('2 of 4 done', '2 of 5 done')}{cards}</main>")[0], "a label that was typed in and is wrong"
    assert not check_dom(f"<main>{head}<p>2 of 4 done (50%)</p>{cards}</main>")[0], "text alone is not a bar"
    assert not check_dom(f'<main>{head}<div id="progress-bar" class="progress-bar"></div>{cards}</main>')[0], "an empty div is not a bar"
    assert not check_dom(f'<main>{head}<progress value="1" max="4"></progress>{cards}</main>')[0], "the wrong share"


# -- the `replace` action: a small edit instead of a rewritten page ----------------------------------------------------

def _frontend_box(tmp_path):
    from app.config import load_agents
    from app.tools import ToolBox

    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text('<header class="app-header">T</header>\n<section>A</section>\n', encoding="utf-8")
    return ToolBox(tmp_path, load_agents()["frontend"], mode="autonomous")


def test_replace_changes_only_the_text_it_names_and_reports_the_diff(tmp_path):
    from app.agent.actions import Action

    box = _frontend_box(tmp_path)
    r = box.execute(Action(thought="t", action="replace", path="static/index.html", pattern="</header>", content='</header>\n<div id="progress"></div>'))
    assert r.ok, r.output
    assert (tmp_path / "static/index.html").read_text(encoding="utf-8") == '<header class="app-header">T</header>\n<div id="progress"></div>\n<section>A</section>\n'


def test_replace_refuses_text_that_is_missing_or_ambiguous_and_says_how_to_fix_it(tmp_path):
    from app.agent.actions import Action

    box = _frontend_box(tmp_path)
    (tmp_path / "static" / "app.js").write_text("const a = 1;\nconst a = 1;\n", encoding="utf-8")
    absent = box.execute(Action(thought="t", action="replace", path="static/index.html", pattern="</footer>", content="x"))
    twice = box.execute(Action(thought="t", action="replace", path="static/app.js", pattern="const a = 1;", content="x"))
    assert not absent.ok and "not in static/index.html" in absent.output
    assert not twice.ok and "occurs 2 times" in twice.output and "longer" in twice.output
    assert "x" not in (tmp_path / "static/app.js").read_text(encoding="utf-8")


def test_replace_obeys_the_same_ownership_and_is_only_given_to_the_frontend_engineer(tmp_path):
    from app.agent.actions import Action
    from app.config import load_agents
    from app.sandbox.paths import SandboxError

    agents = load_agents()
    assert "replace" in agents["frontend"].tools and all("replace" not in a.tools for k, a in agents.items() if k != "frontend")
    box = _frontend_box(tmp_path)
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "main.py").write_text("x = 1\n", encoding="utf-8")
    r = box.execute(Action(thought="t", action="replace", path="backend/main.py", pattern="x = 1", content="x = 2"))
    assert not r.ok and r.data["decision"] == "deny", "outside the frontend engineer's paths"
    assert (tmp_path / "backend/main.py").read_text(encoding="utf-8") == "x = 1\n"


def test_a_replace_that_breaks_the_script_is_reported_like_any_other_write(tmp_path):
    from app.agent.actions import Action

    box = _frontend_box(tmp_path)
    (tmp_path / "static" / "app.js").write_text("const a = 1;\n", encoding="utf-8")
    r = box.execute(Action(thought="t", action="replace", path="static/app.js", pattern="const a = 1;", content="const a = ;"))
    assert not r.ok and "syntax" in r.output.lower()


def test_a_guessed_design_that_fails_the_checks_falls_back_to_a_plain_list_app_with_the_banner(tmp_path):
    """Strava (judge run 5): the model's spec gave a contract the checks reject, and nothing was built. For an unknown name it now falls back."""
    from app.agent.planning import AgentFailed
    from app.platforms import generic_spec
    from test_orchestrator import make

    d = synthesize_design(normalize_spec(generic_spec("Strava"), "Build Strava"))
    llm = RelationalLLM(d)
    o, bus = make(tmp_path, llm)
    o.goal = "Build Strava"
    real = o._relational_design
    calls = []

    def first_fails(presets):
        calls.append(1)
        if len(calls) == 1:
            raise AgentFailed("architect", "the generated contract is inconsistent: POST /api/activities/{activity_id}/goals: field 'type' must list the labels")
        return real(presets)

    o._relational_design = first_fails
    res = o.run()
    assert res.ok, res.problems
    assert len(calls) == 2
    assert any(e["type"] == "agent_thought" and "plain list app" in e.get("text", "") for e in bus.history)
    assert "most of what the real Strava does" in (res.root / "static/app.js").read_text(encoding="utf-8")


def test_a_known_platform_whose_design_fails_still_fails_loudly(tmp_path):
    """The fallback is only for names we do not know: a bug in a platform template must not be hidden behind a plain list app."""
    import pytest
    from app.agent.planning import AgentFailed
    from test_orchestrator import make

    o, _ = make(tmp_path, RelationalLLM())
    o.goal = "Build Instagram"

    def boom(presets):
        raise AgentFailed("architect", "the generated contract is inconsistent: x")

    o._relational_design = boom
    res = o.run()
    assert not res.ok and any("inconsistent" in p for p in res.problems)
