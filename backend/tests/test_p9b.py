"""P9b: famous apps by name, themes, layouts, header, plurals, blank required fields, and the generated pages that carry them."""
import re
import subprocess
from pathlib import Path

import pytest

from app.look import LAYOUTS, THEMES, choose_icon, choose_layout, choose_look, choose_theme, subtitle_of
from app.platforms import MAX_WORDS, PLATFORMS, match_platform
from app.relations import synthesize_design
from app.schemas import ArchitectOutput, SpecOutput, check_architecture, check_spec, label, normalize_spec, required_text, singular
from app.scaffold import route_stub
from app.uistub import page_stub, script_stub

from test_enrich import run_generated

KIT_DIR = Path(__file__).resolve().parents[1] / "app" / "presets" / "fastapi_vanilla" / "skeleton" / "static"
JUDGE_GOALS = {
    "Build Instagram": "instagram", "Build Twitter": "twitter", "Build Amazon": "amazon", "Build Zomato": "zomato", "Build YouTube": "youtube",
    "Build LinkedIn": "jobs", "Build WhatsApp": "chat", "Build Uber": "uber", "Build a hospital management system": "hospital", "Build a library management system": "library",
}


def platform_key(goal: str):
    text = goal.strip()
    from app.platforms import _COMPILED

    return next((k for k, rx, _ in _COMPILED if rx.search(text)), None) if ":" not in text and len(text.split()) <= MAX_WORDS else None


# --- famous apps ----------------------------------------------------------------------------------

@pytest.mark.parametrize("goal,key", JUDGE_GOALS.items())
def test_every_judge_goal_maps_to_its_platform(goal, key):
    assert platform_key(goal) == key
    assert match_platform(goal) is not None


@pytest.mark.parametrize("goal", [
    "Build a todo app with priorities", "Build a calculator with history", "Build a flappy bird game", "Build an expense tracker with categories and totals",
    "Build a notes app: title, content, tag Work/Personal/Ideas, search by text, edit and delete",  # detailed goals are followed as written
    "Build a reddit-style forum: posts with title, content and author, comments on each post, upvote and downvote posts, sort by top or newest, edit and delete",
    "Build an inventory list", "Build a contact book", "Build a habit tracker", "Build a quiz app"])
def test_other_goals_are_left_to_the_model(goal):
    assert match_platform(goal) is None


@pytest.mark.parametrize("key,words,spec", PLATFORMS)
def test_every_platform_spec_is_valid_and_builds_a_consistent_contract(key, words, spec):
    s = normalize_spec(SpecOutput.model_validate(spec), "Build " + key)
    assert check_spec(s) == [], key
    assert s.not_included, "a famous app is always bigger than its small version, and says what it leaves out"
    assert len(s.resources) == len(spec["resources"]) and [r.parent for r in s.resources] == [r.get("parent", "") for r in spec["resources"]], "normalizing must keep the authored shape"
    if len(s.resources) == 2 or any(r.actions for r in s.resources):  # related resources: the contract is generated and must pass its own checks
        design = synthesize_design(s)
        assert check_architecture(design, ["fastapi-vanilla"], s) == []
        assert choose_layout(design) == "feed"
        for r in design.resources:
            assert all(f.name != "post_id" for f in r.fields)


def test_every_platform_goal_gets_a_theme_a_layout_an_icon_and_a_subtitle():
    for goal in JUDGE_GOALS:
        s = normalize_spec(match_platform(goal), goal)
        if len(s.resources) == 1 and not s.resources[0].actions:
            continue  # a single resource goes through the Architect (rules choose its look the same way, see the layout tests below)
        d = synthesize_design(s)
        look = choose_look(goal, s, d)
        assert look.theme in THEMES and look.layout in LAYOUTS and look.icon and look.subtitle and look.not_included, goal


def test_the_movies_plural_is_a_movie():
    assert singular("movies") == "movie" and singular("repositories") == "repository" and singular("categories") == "category" and singular("issues") == "issue"


# --- themes, layouts, icons ------------------------------------------------------------------------

@pytest.mark.parametrize("goal,theme", [
    ("Build an expense tracker: description, amount, category Food/Transport/Housing/Fun/Other, date, total spent, filter by category", "finance"),
    ("Build a notes app: title, content, tag Work/Personal/Ideas, search by text, edit and delete", "paper"),
    ("Build an inventory list: item name, quantity, location Warehouse/Shop/Home, status In stock/Low/Out of stock", "industrial"),
    ("Build Instagram", "social"), ("Build Twitter", "social"), ("Build Amazon", "social"),
    ("Build Zomato", "food"), ("Build a recipe book", "food"), ("Build a hospital management system", "health"), ("Build a habit tracker", "health"),
    ("Build a library management system", "paper"), ("Build Uber", "industrial"),
    ("Build a todo app: title, description, priority Low/Medium/High, due date, mark as done", "default"), ("Build a calculator with history", "default"),
    ("Build a quiz app", "default")])
def test_the_theme_fits_the_goal(goal, theme):
    assert choose_theme(goal) == theme


def test_the_name_of_the_app_outweighs_the_words_in_its_field_list():
    # "Food" is an option of an expense category, not the subject of the app
    assert choose_theme("Build an expense tracker: description, amount, category Food/Transport/Housing") == "finance"


def test_six_themes_exist_in_the_kit_with_their_own_accent_font_and_header():
    css = (KIT_DIR / "ui-kit.css").read_text(encoding="utf-8")
    light = 0
    for theme in THEMES[1:]:
        block = re.search(r'\[data-theme="%s"\]\s*\{([^}]*)\}' % theme, css)
        assert block, theme
        assert "--primary:" in block.group(1) and "--font-head:" in block.group(1) or "--font:" in block.group(1), theme
        assert f'[data-theme="{theme}"] .app-header' in css, f"{theme} has its own header style"
        light += "color-scheme: light" in block.group(1)
    assert len(THEMES) == 7 and light >= 2, "six themes besides the default, at least two of them light"
    accents = {re.search(r"--primary: (#\w+)", re.search(r'\[data-theme="%s"\]\s*\{([^}]*)\}' % t, css).group(1)).group(1) for t in THEMES[1:]}
    assert len(accents) == 6, "every theme has its own accent colour"


def test_the_icon_comes_from_the_name_of_the_app():
    assert choose_icon("Build a contact book: name, phone", "Contact book", "cards") == "👤"
    assert choose_icon("Build Instagram", "Instagram", "feed") == "📸"
    assert choose_icon("Build a quiz app", "Quiz", "cards") == "🧠"
    assert choose_icon("Build something odd", "Thing", "table") == "📊"


def test_the_subtitle_is_the_first_sentence_of_the_spec_cut_to_one_line():
    long = SpecOutput(title="x", summary="Keep a list of tasks with a priority, a due date, and a status to mark them as done, and then some more words that make it too long. Second sentence.")
    s = subtitle_of(long, "x")
    assert len(s) <= 112 and "Second" not in s and s.endswith("…")
    assert subtitle_of(SpecOutput(title="x", summary="Short one. Another."), "x") == "Short one"
    assert subtitle_of(None, "x") == ""


def flat(fields, name="things", **over):
    """A single-resource design: POST/GET/PUT/DELETE of `name` with these fields (dicts with name/type/options)."""
    body = [{"name": "id", "type": "integer"}, *fields]
    d = {"preset": "fastapi-vanilla", "architecture": "x", "ui_features": over.pop("features", ["Form", "List"]),
         "endpoints": [
             {"method": "POST", "path": f"/api/{name}", "summary": "Add", "response_status": 201, "request_fields": fields, "response_fields": body,
              "examples": [{"description": "adds", "request": {}, "status": 201, "response": {}}]},
             {"method": "GET", "path": f"/api/{name}", "summary": "List", "response_fields": [{"name": "items", "type": "array"}], "examples": []},
             {"method": "PUT", "path": f"/api/{name}/{{id}}", "summary": "Edit", "request_fields": fields, "response_fields": body, "errors": [{"status": 404, "detail": "Not found"}], "examples": []},
             {"method": "DELETE", "path": f"/api/{name}/{{id}}", "summary": "Delete", "response_fields": [{"name": "deleted", "type": "boolean"}], "errors": [{"status": 404, "detail": "Not found"}], "examples": []}],
         "tables": [], "db_functions": []}
    return ArchitectOutput.model_validate(d)


S = {"name": "title", "type": "string"}
EXPENSE = [{"name": "description", "type": "string"}, {"name": "amount", "type": "number"}, {"name": "category", "type": "string", "options": ["Food", "Fun"]}, {"name": "date", "type": "string"}]
TODO = [S, {"name": "priority", "type": "string", "options": ["Low", "High"]}, {"name": "done", "type": "boolean"}]
NOTES = [S, {"name": "content", "type": "string"}, {"name": "phone", "type": "string"}]


def dressed(d, goal, summary="One line about the app.", left=()):
    spec = SpecOutput(title="My app", summary=summary, not_included=list(left))
    d.look = choose_look(goal, spec, d)
    return d


@pytest.mark.parametrize("fields,layout", [(EXPENSE, "table"), (TODO, "checklist"), (NOTES, "cards")])
def test_the_layout_follows_the_data(fields, layout):
    assert choose_layout(flat(fields)) == layout


def test_a_computed_result_is_a_calculator_panel_and_related_resources_are_a_feed():
    ops = {"name": "operation", "type": "string", "options": ["add", "subtract"]}
    calc = flat([{"name": "a", "type": "number"}, {"name": "b", "type": "number"}, ops])
    calc.endpoints[0].response_fields.append({"name": "result", "type": "number"})
    calc.endpoints[0].response_fields = [type(calc.endpoints[0].response_fields[0])(**f) if isinstance(f, dict) else f for f in calc.endpoints[0].response_fields]
    assert choose_layout(calc) == "calculator"
    feed = synthesize_design(normalize_spec(match_platform("Build Instagram"), "Build Instagram"))
    assert choose_layout(feed) == "feed"


# --- the generated pages ----------------------------------------------------------------------------

def node_check(js, tmp_path):
    f = tmp_path / "app.js"
    f.write_text(js, encoding="utf-8")
    out = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("fields,renderer,layout", [(EXPENSE, "renderTable", "table"), (TODO, "renderChecklist", "checklist"), (NOTES, "renderCards", "cards")])
def test_each_layout_page_passes_the_generated_ui_tests(fields, renderer, layout, tmp_path):
    d = dressed(flat(fields), "Build an expense tracker")
    html, js = page_stub(d, "My app"), script_stub(d, "My app")
    assert f"UI.{renderer}(" in js and f"layout-{layout}" in html
    failed, details = run_generated(js, html, d)
    assert failed == set(), details
    node_check(js, tmp_path)
    assert len(js.splitlines()) < 150


def test_the_header_has_an_icon_a_subtitle_the_theme_and_the_left_out_note():
    d = dressed(flat(EXPENSE), "Build an expense tracker", "Record what you spend. More text.", ["login and accounts", "charts"])
    html = page_stub(d, "Expense tracker")
    assert 'data-theme="finance"' in html
    assert '<span class="app-icon" aria-hidden="true">💰</span>' in html and '<p class="app-sub">Record what you spend</p>' in html
    assert "<strong>Not in this version:</strong> <span>login and accounts, charts.</span>" in html
    plain = page_stub(dressed(flat(EXPENSE), "Build an expense tracker"), "Expense tracker")
    assert "Not in this version" not in plain, "nothing is left out, so no note"


def test_a_page_without_a_look_keeps_the_plain_header():
    html = page_stub(flat(EXPENSE), "Things")
    assert 'class="page-header"' in html and "app-icon" not in html and 'data-theme="default"' in html


def test_numbers_are_shown_in_every_row_and_in_a_stat_strip():
    table = script_stub(dressed(flat(EXPENSE), "Build an expense tracker"), "x")
    assert '{ field: "amount", label: "Amount", format: "money" }' in table, "the amount is a column (it was missing from the rows)"
    assert "UI.statStrip(stats, shown" in table and 'sums: [{ field: "amount", label: "Total amount", format: "money" }]' in table and 'by: "category", byField: "amount"' in table
    stock = dressed(flat([S, {"name": "quantity", "type": "integer"}]), "Build a thing")
    assert '{ field: "quantity", label: "Quantity", format: "num" }' in script_stub(stock, "x")
    stock.look.layout = "cards"  # the other layouts show numbers as captioned values on the right of the row
    cards = script_stub(stock, "x")
    assert 'values: ["quantity"]' in cards and '"quantity": "Quantity"' in cards and "UI.statStrip" in cards
    html = page_stub(dressed(flat(EXPENSE), "Build an expense tracker"), "x")
    assert 'id="stats"' in html and 'id="total"' not in html
    assert "UI.statStrip" not in script_stub(dressed(flat(NOTES), "Build a notes app"), "x"), "no numbers, no strip"


def test_the_count_is_pluralised_by_the_kit():
    js = script_stub(dressed(flat(EXPENSE, name="expenses"), "Build an expense tracker"), "x")
    assert 'UI.count(shown.length, "expense", "expenses")' in js


def test_the_add_form_never_shows_a_done_box_but_the_list_does():
    d = dressed(flat(TODO), "Build a todo app")
    html, js = page_stub(d, "Todo"), script_stub(d, "Todo")
    assert 'id="done"' not in html and 'type="checkbox"' not in html, "a done box only makes sense after the item exists"
    assert "done: false" in js and 'done: "done"' in js and "onToggle" in js, "a new item is not done; the list ticks it"
    assert '"type": "checkbox"' in js, "the Edit dialog still has it"


def test_a_rating_input_is_limited_to_one_to_five():
    html = page_stub(dressed(flat([S, {"name": "rating", "type": "integer"}]), "Build a thing"), "x")
    assert 'id="rating" type="number" step="1" min="1" max="5"' in html


def test_internal_names_never_reach_the_user():
    assert label("group_value") == "Group" and label("order_name") == "Order" and label("due_date") == "Due date" and label("first_name") == "First name"
    d = dressed(flat([S, {"name": "group_value", "type": "string", "options": ["Family", "Work"]}]), "Build a contact book")
    html = page_stub(d, "x")
    assert ">Group<" in html and "Group value" not in html


def test_the_calculator_page_is_a_panel():
    ops = {"name": "operation", "type": "string", "options": ["add", "subtract"]}
    d = flat([{"name": "a", "type": "number"}, {"name": "b", "type": "number"}, ops])
    d.endpoints[0].response_fields.append(type(d.endpoints[0].response_fields[0])(name="result", type="number"))
    d = dressed(d, "Build a calculator with history")
    html = page_stub(d, "Calculator")
    assert "layout-calculator" in html and "calc-panel" in html and 'id="result" class="calc-result"' in html and ">Calculate<" in html


def test_a_page_that_loses_its_theme_or_its_note_fails_the_generated_page_test(tmp_path):
    from test_p8 import _run_page_tests
    from app.contract_tests import ui_page_test_source

    d = dressed(flat(EXPENSE), "Build an expense tracker", left=["charts"])
    src = ui_page_test_source(d)
    assert "test_page_keeps_its_theme" in src and "test_page_says_what_is_left_out" in src
    assert "test_page_says_what_is_left_out" not in ui_page_test_source(dressed(flat(EXPENSE), "Build an expense tracker"))
    shell = '<link href="/static/ui-kit.css"><link href="/static/style.css"><script src="/static/app.js"></script>'
    import subprocess as sp, sys
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "__init__.py").write_text("")

    def run(html):
        (tmp_path / "backend" / "main.py").write_text(
            "from fastapi import FastAPI\nfrom fastapi.responses import HTMLResponse, PlainTextResponse\napp = FastAPI()\n"
            f"@app.get('/', response_class=HTMLResponse)\ndef page():\n    return {html!r}\n"
            "@app.get('/static/{name}', response_class=PlainTextResponse)\ndef asset(name: str):\n    return 'x'\n")
        (tmp_path / "test_page.py").write_text(src)
        return sp.run([sys.executable, "-m", "pytest", "-q", "test_page.py"], cwd=tmp_path, capture_output=True, text=True)

    good = run(f'<html data-theme="finance">{shell}<p>Not in this version: charts</p>')
    assert good.returncode == 0, good.stdout
    bad = run(f'<html>{shell}')
    assert bad.returncode != 0 and "keep data-theme" in bad.stdout and "keep the note that lists what this version leaves out" in bad.stdout


# --- the feed page ----------------------------------------------------------------------------------

def feed_design(goal="Build Instagram"):
    s = normalize_spec(match_platform(goal), goal)
    d = synthesize_design(s)
    d.look = choose_look(goal, s, d)
    return d, s


def test_the_feed_page_is_a_forum_with_votes_a_byline_and_a_detail_view(tmp_path):
    d, s = feed_design("Build Twitter")
    html, js = page_stub(d, s.title), script_stub(d, s.title)
    for needle in ('id="feed-view"', 'id="detail"', 'id="post"', 'id="children"', 'id="child-form"', "Add a reply", "layout-feed", 'data-theme="social"', "Not in this version"):
        assert needle in html, needle
    assert html.index('id="children"') < html.index('id="child-form"'), "the form for a new reply sits under the replies"
    assert html.index('id="post"') < html.index('id="children"'), "the open post is above its replies"
    assert 'slot: "up"' in js and "score: item.likes" in js and "UI.renderFeed(list" in js and "UI.count(" in js
    assert 'author: "author"' in js and "commentCount" in js and 'noun: "reply"' in js
    failed, details = run_generated(js, html, d)
    assert failed == set(), details
    node_check(js, tmp_path)
    assert len(js.splitlines()) < 150


def test_two_counters_give_up_score_down():
    d, s = feed_design("Build Reddit")
    js = script_stub(d, s.title)
    assert 'slot: "up"' in js and 'slot: "down"' in js and "score: item.upvotes - item.downvotes" in js


def test_reviews_show_stars_and_averages_and_products_show_a_stat_strip(tmp_path):
    d, s = feed_design("Build Amazon")
    html, js = page_stub(d, s.title), script_stub(d, s.title)
    assert 'id="stats"' in html and 'id="child-stats"' in html
    assert 'formats: {"rating": "stars"}' in js and 'label: "Average rating"' in js and 'label: "Average price"' in js and 'by: "category"' in js
    assert 'min="1" max="5"' in html, "a rating is 1 to 5"
    failed, details = run_generated(js, html, d)
    assert failed == set(), details
    node_check(js, tmp_path)


@pytest.mark.parametrize("goal", ["Build Zomato", "Build YouTube", "Build LinkedIn", "Build WhatsApp", "Build a hospital management system", "Build a library management system"])
def test_every_famous_feed_page_passes_its_generated_ui_tests(goal, tmp_path):
    d, s = feed_design(goal)
    html, js = page_stub(d, s.title), script_stub(d, s.title)
    failed, details = run_generated(js, html, d)
    assert failed == set(), details
    node_check(js, tmp_path)
    assert len(js.splitlines()) < 150, goal
    assert "post_id" not in html


# --- blank required fields --------------------------------------------------------------------------

def test_required_text_is_every_text_field_that_is_not_an_optional_note():
    from app.schemas import FieldSpec

    f = lambda n, **k: FieldSpec(name=n, type=k.pop("type", "string"), **k)  # noqa: E731
    assert all(required_text(f(n)) for n in ("title", "content", "author", "name", "text", "caption", "sender", "member"))
    assert not any(required_text(f(n)) for n in ("description", "notes", "phone", "email", "due_date", "date", "tags", "message"))
    assert not required_text(f("category", options=["A"])) and not required_text(f("amount", type="number")) and not required_text(f("done", type="boolean"))


def test_the_request_models_use_the_validated_type_for_parents_and_children_alike():
    d, _ = feed_design("Build Instagram")
    from app.relations import endpoints_for_resource

    for resource in ("posts", "comments"):
        code = route_stub(d, endpoints_for_resource(d, resource), resource)
        compile(code, resource, "exec")
        assert "from backend.validation import Required" in code
        request = code.split("Request(BaseModel):")[1].split("class ")[0]
        assert "Required" in request, resource
        assert "Required" not in code.split("Response(BaseModel):")[1].split("@router")[0], "responses are not validated"


def test_the_locked_validation_helper_answers_400_with_a_message(tmp_path):
    import sys
    from fastapi.testclient import TestClient

    skeleton = KIT_DIR.parent
    sys.path.insert(0, str(skeleton))
    (tmp_path / "api").mkdir()
    try:
        from importlib import import_module

        for name in [n for n in sys.modules if n == "backend" or n.startswith("backend.")]:
            del sys.modules[name]
        backend = import_module("backend.main")
        from fastapi import APIRouter
        from pydantic import BaseModel
        from backend.validation import Required

        router = APIRouter()

        class Body(BaseModel):
            title: Required
            note: str
            count: int

        @router.post("/t")
        def t(req: Body):
            return {"ok": True}

        backend.app.include_router(router)
        c = TestClient(backend.app)
        ok = {"title": "a", "note": "", "count": 1}
        assert c.post("/t", json=ok).status_code == 200
        for blank in ("", "   ", "\t\n"):
            r = c.post("/t", json={**ok, "title": blank})
            assert r.status_code == 400 and r.json() == {"detail": "Title is required"}, r.text
        assert c.post("/t", json={"note": "", "count": 1}).status_code == 422, "a missing field is still FastAPI's 422"
        assert c.post("/t", json={**ok, "count": "x"}).status_code == 422
    finally:
        sys.path.remove(str(skeleton))
        for name in [n for n in sys.modules if n == "backend" or n.startswith("backend.")]:
            del sys.modules[name]


def test_the_kit_layouts_run_in_a_fake_dom():
    out = subprocess.run(["node", str(Path(__file__).parent / "js" / "kit_layouts.mjs"), str(KIT_DIR / "ui-kit.js")], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0 and "kit layouts ok" in out.stdout, out.stderr[-1500:]


def test_a_contract_that_defines_its_own_400_keeps_its_own_text():
    """Regression: the Architect's todo contract says 'Title must not be empty' (400); the automatic 'Title is required' broke that example and the todo build."""
    from app.contract_tests import edge_test_source
    from app.schemas import ErrorSpec
    from test_enrich import design

    d = design()
    post = next(e for e in d.endpoints if e.method == "POST")
    code = route_stub(d, [post], "todos")
    assert "title: Required" in code.split("class PostTodosRequest")[1].split("class ")[0] or "title: str" in code, "no declared 400: the automatic validation applies"
    assert "def test_post_api_todos_rejects_blank_title" in edge_test_source(d)
    unrelated = ErrorSpec(status=400, detail="Division by zero")
    post.errors.append(unrelated)
    assert "title: Required" in route_stub(d, [post], "todos"), "a 400 about something else does not switch the automatic validation off"
    post.errors.remove(unrelated)
    post.errors.append(ErrorSpec(status=400, detail="Title must not be empty"))
    code = route_stub(d, [post], "todos")
    request = code.split("PostTodosRequest(BaseModel):")[1].split("class ")[0]
    assert "Required" not in request and "title: str" in request, "the contract's own 400 is the engineer's to write"
    assert "rejects_blank_title" not in edge_test_source(d)


def test_a_server_computed_field_next_to_a_title_does_not_make_a_calculator():
    """Regression (a real expense build): the Architect added a response-only `total_spent`; the page got a Calculate button and an empty result box."""
    d = dressed(flat(EXPENSE, name="expenses"), "Build an expense tracker")
    d.endpoints[0].response_fields.append(type(d.endpoints[0].response_fields[0])(name="total_spent", type="number"))
    html, js = page_stub(d, "Expense tracker"), script_stub(d, "Expense tracker")
    assert choose_layout(d) == "table"
    assert ">Add<" in html and ">Calculate<" not in html and 'id="result"' not in html and 'getElementById("result")' not in js
    failed, details = run_generated(js, html, d)
    assert failed == set(), details
