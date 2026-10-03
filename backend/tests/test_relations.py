"""Related resources and actions: spec repair, the synthesized contract, the plan, stubs, generated tests, the generated page."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.contract_tests import api_test_source, edge_test_source, ui_page_test_source, ui_script_test_source
from app.relation_tests import db_test_source
from app.relations import endpoints_for_resource, plan_for_relations, synthesize_design
from app.scaffold import db_stub, route_stub
from app.schemas import (ArchitectOutput, SpecOutput, check_architecture, check_plan, check_spec, is_relational, normalize_plan, normalize_spec, spec_text)
from app.uistub import page_stub, script_stub

from relations_reference import write as write_reference

SKELETON = Path(__file__).resolve().parents[1] / "app" / "presets" / "fastapi_vanilla" / "skeleton"
KIT = SKELETON / "static" / "ui-kit.js"
HARNESS = Path(__file__).parent / "js" / "page_relations.mjs"

# the spec the 7B wrote for "Build a reddit replica" (workspace/build-a-reddit-replica/.q/spec.md), with its mistakes
FAILED_SPEC = {
    "title": "Reddit Replica", "summary": "Post, comment and vote.",
    "resources": [
        {"name": "posts", "operations": ["list", "create", "update", "delete"], "fields": [
            {"name": "title", "type": "string"}, {"name": "content", "type": "string"}, {"name": "author", "type": "string"},
            {"name": "created_at", "type": "string"}, {"name": "upvotes", "type": "number"}, {"name": "downvotes", "type": "number"}]},
        {"name": "comments", "operations": ["list", "create", "update", "delete"], "fields": [
            {"name": "content", "type": "string"}, {"name": "author", "type": "string"}, {"name": "post_id", "type": "string"},
            {"name": "created_at", "type": "string"}, {"name": "upvotes", "type": "number"}, {"name": "downvotes", "type": "number"}]},
    ],
    "features": ["Form to post a new article", "Ability to upvote and downvote posts and comments",
                 "Filter the list of posts by upvotes, downvotes, or created_at"],
}


def spec(**over) -> SpecOutput:
    return normalize_spec(SpecOutput.model_validate({**FAILED_SPEC, **over}), "Build a reddit replica")


def design() -> ArchitectOutput:
    return synthesize_design(spec())


# -- the spec ---------------------------------------------------------------------------------

def test_the_failed_spec_is_repaired_mechanically():
    s = spec()
    posts, comments = s.resources
    assert comments.parent == "posts" and not any(f.name == "post_id" for f in comments.fields), "post_id is the link, not a string field"
    for r in (posts, comments):
        assert {f.name for f in r.fields} == ({"title", "content", "author"} if r is posts else {"content", "author"}) | {"upvotes", "downvotes"}
        assert all(f.type == "integer" for f in r.fields if f.name.endswith("votes"))
        assert [(a.name, a.field, a.kind) for a in r.actions] == [("upvote", "upvotes", "increment"), ("downvote", "downvotes", "increment")]
        assert r.sorts == ["new", "top"]
    assert not any("ilter" in f for f in s.features) and "Sort the list by Newest or Top" in s.features, "filter by upvotes / created_at is a sort"
    assert check_spec(s) == [] and is_relational(s)
    assert "Belongs to posts" in spec_text(s)


def test_a_bigger_goal_keeps_two_resources_and_says_what_was_left_out():
    extra = {"name": "subreddits", "operations": ["list"], "fields": [{"name": "name", "type": "string"}]}
    s = normalize_spec(SpecOutput.model_validate({**FAILED_SPEC, "resources": [*FAILED_SPEC["resources"], extra]}), "Build a reddit replica with login")
    assert [r.name for r in s.resources] == ["posts", "comments"]
    assert s.not_included == ["subreddits", "login and accounts"]
    assert "Not in this version: subreddits, login and accounts." in spec_text(s)


def test_two_unrelated_resources_become_one():
    s = normalize_spec(SpecOutput.model_validate({"title": "x", "summary": "y", "features": ["f"], "resources": [
        {"name": "books", "operations": ["list"], "fields": [{"name": "title", "type": "string"}]},
        {"name": "movies", "operations": ["list"], "fields": [{"name": "title", "type": "string"}]}]}), "")
    assert [r.name for r in s.resources] == ["books"] and s.not_included == ["movies"] and not is_relational(s)


def test_a_plain_single_resource_spec_is_not_touched():
    plain = {"title": "Todo app", "summary": "Tasks.", "features": ["Form", "Filter the list by status"], "resources": [
        {"name": "todos", "operations": ["list", "create"], "fields": [{"name": "title", "type": "string"}, {"name": "done", "type": "boolean"}]}]}
    s = normalize_spec(SpecOutput.model_validate(plain), "Build a todo app")
    assert s.model_dump() == {**SpecOutput.model_validate(plain).model_dump(), "not_included": []} and not is_relational(s)


def test_the_fallback_switch_builds_only_the_parent(monkeypatch):
    monkeypatch.setenv("Q_RELATIONS", "0")
    s = spec()
    assert [r.name for r in s.resources] == ["posts"] and "comments" in s.not_included
    assert [a.name for a in s.resources[0].actions] == ["upvote", "downvote"] and is_relational(s)


# -- the contract -----------------------------------------------------------------------------

def test_the_synthesized_contract_has_no_reported_problem():
    d = design()
    assert check_architecture(d, ["fastapi-vanilla"], spec()) == []
    by = {(e.method, e.path): e for e in d.endpoints}
    assert set(by) == {("GET", "/api/posts"), ("POST", "/api/posts"), ("PUT", "/api/posts/{id}"), ("DELETE", "/api/posts/{id}"),
                       ("POST", "/api/posts/{id}/upvote"), ("POST", "/api/posts/{id}/downvote"),
                       ("GET", "/api/posts/{post_id}/comments"), ("POST", "/api/posts/{post_id}/comments"),
                       ("PUT", "/api/comments/{id}"), ("DELETE", "/api/comments/{id}"),
                       ("POST", "/api/comments/{id}/upvote"), ("POST", "/api/comments/{id}/downvote")}
    for (method, _), e in by.items():
        if method in ("POST", "PUT"):
            assert not {f.name for f in e.request_fields} & {"upvotes", "downvotes", "post_id"}, "counters and the link never come from the client"
    assert [f.name for f in by[("GET", "/api/posts")].request_fields] == ["sort"] and by[("GET", "/api/posts")].request_fields[0].options == ["new", "top"]
    for key in (("POST", "/api/posts/{id}/upvote"), ("POST", "/api/posts/{post_id}/comments"), ("GET", "/api/posts/{post_id}/comments")):
        assert any(x.status == 404 for x in by[key].errors)
    assert {f.name: f.type for f in by[("POST", "/api/posts/{id}/upvote")].response_fields}["upvotes"] == "integer"
    comments = next(t for t in d.tables if t.name == "comments")
    assert [(c.name, c.type) for c in comments.columns if c.name == "post_id"] == [("post_id", "INTEGER")]


@pytest.mark.parametrize("change,message", [
    (lambda d: setattr(next(e for e in d.endpoints if e.method == "POST" and e.path == "/api/posts"), "request_fields",
                       [*next(e for e in d.endpoints if e.method == "POST" and e.path == "/api/posts").request_fields,
                        type(d.endpoints[0].request_fields[0])(name="upvotes", type="number")]), "counter the server owns"),
    (lambda d: setattr(d.endpoints[-1], "response_fields", [type(d.endpoints[0].request_fields[0])(name="post_id", type="string")]), "must be integer"),
    (lambda d: setattr(next(t for t in d.tables if t.name == "comments").columns[1], "type", "TEXT"), "must be INTEGER"),
    (lambda d: d.ui_features.append("Filter the list of posts by upvotes"), "is a sort, not a filter"),
])
def test_the_checks_reject_the_reported_contract_problems(change, message):
    d = design()
    change(d)
    assert any(message in p for p in check_architecture(d, ["fastapi-vanilla"])), check_architecture(d, ["fastapi-vanilla"])


def test_a_flat_child_with_a_body_foreign_key_is_rejected_and_told_to_nest():
    d = ArchitectOutput.model_validate({
        "preset": "fastapi-vanilla", "architecture": "x", "ui_features": ["x"],
        "endpoints": [
            {"method": "GET", "path": "/api/posts", "summary": "l", "response_fields": [{"name": "items", "type": "array"}], "examples": [{"description": "l", "status": 200}]},
            {"method": "POST", "path": "/api/comments", "summary": "c", "response_status": 201, "request_fields": [{"name": "text", "type": "string"}, {"name": "post_id", "type": "integer"}],
             "response_fields": [{"name": "id", "type": "integer"}], "examples": [{"description": "c", "request": {"text": "t", "post_id": 1}, "status": 201, "response": {}}]}],
        "tables": [{"name": "posts", "columns": [{"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY AUTOINCREMENT"}]},
                   {"name": "comments", "columns": [{"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY AUTOINCREMENT"}]}],
        "db_functions": [{"name": "list_posts", "signature": "list_posts() -> list[dict]", "description": "all"}]})
    assert any("child list is nested" in p and "/api/posts/{post_id}/<children>" in p for p in check_architecture(d, ["fastapi-vanilla"]))


# -- the plan ---------------------------------------------------------------------------------

def test_one_task_per_table_and_per_router_and_never_all_tables():
    d = design()
    plan = normalize_plan(plan_for_relations(d))
    assert check_plan(plan, True, d.endpoints, len(d.tables)) == []
    owners = [(t.owner, t.files) for t in plan.tasks]
    assert owners == [("database", ["database/posts.py"]), ("database", ["database/comments.py"]), ("backend", ["backend/api/posts.py"]),
                      ("backend", ["backend/api/comments.py"]), ("frontend", ["static/index.html", "static/style.css"]), ("frontend", ["static/app.js"])]
    assert not any("all tables" in t.title.lower() for t in plan.tasks)
    comments_router = plan.tasks[3]
    assert {"t1", "t2", "t3"} <= set(comments_router.depends_on), "the child router waits for both tables and the parent router"


def test_a_model_plan_with_one_task_for_all_tables_is_rejected():
    from app.schemas import PlannerOutput

    d = design()
    plan = PlannerOutput.model_validate({"tasks": [
        {"id": "t1", "title": "Implement data access functions for all tables", "owner": "database", "files": ["database/data_access.py"], "acceptance": ["x"]},
        {"id": "t2", "title": "API", "owner": "backend", "depends_on": ["t1"], "files": ["backend/api/posts.py"], "acceptance": ["x"]},
        {"id": "t3", "title": "Page", "owner": "frontend", "files": ["static/index.html"], "acceptance": ["x"]}]})
    assert any("one database task per table" in p for p in check_plan(plan, True, d.endpoints, 2))


# -- stubs ------------------------------------------------------------------------------------

def test_stubs_are_per_table_and_per_router():
    d = design()
    posts_db, comments_db = db_stub(d, "posts"), db_stub(d, "comments")
    compile(posts_db, "p", "exec"), compile(comments_db, "c", "exec")
    assert "def upvote_post(post_id: int)" in posts_db and "def add_comment" not in posts_db and "def add_comment(post_id: int" in comments_db
    assert posts_db.count("CREATE TABLE") == comments_db.count("CREATE TABLE") == 2, "every module's SCHEMA creates both tables, so deleting a post can delete its comments"
    assert "DELETE FROM comments WHERE post_id = ?" in posts_db
    router = route_stub(d, endpoints_for_resource(d, "comments"), "comments", ("posts",))
    compile(router, "r", "exec")
    assert "from database import posts as posts_db" in router and "sort: Literal['new', 'top'] = 'new'" in router
    assert 'if posts_db.get_post(post_id) is None: raise HTTPException(status_code=404, detail="Post not found")' in router
    assert "def handle_post_comments_upvote_by_id(id: int)" in router


def test_single_resource_designs_do_not_change():
    plain = ArchitectOutput.model_validate({
        "preset": "fastapi-vanilla", "architecture": "x", "ui_features": ["x"],
        "endpoints": [{"method": "GET", "path": "/api/items", "summary": "l", "response_fields": [{"name": "items", "type": "array"}]}],
        "tables": [{"name": "items", "columns": [{"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY AUTOINCREMENT"}]}],
        "db_functions": [{"name": "list_items", "signature": "list_items() -> list[dict]", "description": "all"}]})
    assert db_stub(plain) == db_stub(plain, None) and plain.resources == []
    assert "# body:" not in route_stub(plain, plain.endpoints, "items")
    assert "resources" not in ArchitectOutput.model_json_schema()["properties"], "the model never sees the engine's resource model"


# -- generated tests and page against a hand-written correct app --------------------------------

def project(tmp_path, **mutation):
    d = design()
    root = tmp_path / "app"
    shutil.copytree(SKELETON, root)
    (root / "tests" / "api").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "qa").mkdir(parents=True, exist_ok=True)
    for r in d.resources:
        (root / "tests" / "api" / f"test_contract_{r.name}.py").write_text(api_test_source(d, r.name), encoding="utf-8")
    (root / "tests" / "db").mkdir(exist_ok=True)
    for r in d.resources:
        (root / "tests" / "db" / f"test_{r.name}.py").write_text(db_test_source(d, r), encoding="utf-8")
    (root / "tests" / "qa" / "test_edge_cases.py").write_text(edge_test_source(d), encoding="utf-8")
    (root / "tests" / "ui").mkdir(exist_ok=True)
    (root / "tests" / "ui" / "test_page.py").write_text(ui_page_test_source(d), encoding="utf-8")
    (root / "tests" / "ui" / "test_script.py").write_text(ui_script_test_source(d), encoding="utf-8")
    (root / "static" / "index.html").write_text(page_stub(d, "Reddit"), encoding="utf-8")
    (root / "static" / "app.js").write_text(script_stub(d, "Reddit"), encoding="utf-8")
    write_reference(root, re.search(r'SCHEMA = "(.*)"', db_stub(d, "posts")).group(1), **mutation)
    return root


def run_pytest(root, *args):
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", *args], cwd=root, capture_output=True, text=True)
    return r.returncode, [l.split("::")[-1].split(" - ")[0] for l in r.stdout.splitlines() if l.startswith("FAILED")], r.stdout[-1500:]


def test_generated_tests_pass_on_a_correct_app(tmp_path):
    code, failed, out = run_pytest(project(tmp_path))
    assert code == 0, out


@pytest.mark.parametrize("mutation,caught_by", [
    ({"break_cascade": True}, "test_deleting_a_post_deletes_its_comments"),
    ({"break_404": True}, "test_comments_of_an_unknown_post_are_404"),
    ({"client_counters": True}, "test_posts_counters_never_come_from_the_client"),
])
def test_generated_tests_catch_the_classic_mistakes(tmp_path, mutation, caught_by):
    code, failed, out = run_pytest(project(tmp_path, **mutation))
    assert code != 0 and caught_by in failed, out


def test_generated_page_is_valid_small_and_passes_its_ui_tests(tmp_path):
    root = project(tmp_path)
    js = (root / "static" / "app.js").read_text(encoding="utf-8")
    assert len(js.splitlines()) < 150, "the reviewer asks to cut files over 150 lines"
    assert subprocess.run(["node", "--check", str(root / "static" / "app.js")], capture_output=True).returncode == 0
    code, _, out = run_pytest(root, "tests/ui")
    assert code == 0, out


def test_generated_page_runs_in_a_fake_dom(tmp_path):
    root = project(tmp_path)
    r = subprocess.run(["node", str(HARNESS), str(KIT), str(root / "static" / "index.html"), str(root / "static" / "app.js")], capture_output=True, text=True)
    assert r.returncode == 0 and "page ok" in r.stdout, r.stderr[-1500:]


def test_the_page_test_notices_a_missing_vote_button(tmp_path):
    root = project(tmp_path)
    js = (root / "static" / "app.js").read_text(encoding="utf-8")
    (root / "static" / "app.js").write_text(js.replace("upvotePost(item.id)", "console.log(item.id)"), encoding="utf-8")
    code, failed, out = run_pytest(root, "tests/ui")
    assert code != 0 and "test_every_item_endpoint_has_a_button_in_the_list" in failed, out


def test_a_forgotten_parent_is_inferred_for_unmistakable_children():
    raw = {"title": "x", "summary": "y", "features": ["Form"], "resources": [
        {"name": "posts", "operations": ["list", "create"], "fields": [{"name": "title", "type": "string"}]},
        {"name": "comments", "operations": ["list", "create"], "fields": [{"name": "content", "type": "string"}]}]}
    s = normalize_spec(SpecOutput.model_validate(raw), "")
    assert [(r.name, r.parent) for r in s.resources] == [("posts", ""), ("comments", "posts")] and is_relational(s)
    raw["resources"] = raw["resources"][::-1]  # the child listed first
    s = normalize_spec(SpecOutput.model_validate(raw), "")
    assert [(r.name, r.parent) for r in s.resources] == [("posts", ""), ("comments", "posts")]
    raw["resources"] = [{**raw["resources"][1], "name": "projects"}, {**raw["resources"][0], "name": "milestones"}]
    raw["features"] = ["Each project has milestones"]
    s = normalize_spec(SpecOutput.model_validate(raw), "")
    assert [(r.name, r.parent) for r in s.resources] == [("projects", ""), ("milestones", "projects")]


def test_generated_database_tests_catch_a_missing_cascade_and_a_wrong_order(tmp_path):
    code, failed, out = run_pytest(project(tmp_path, break_cascade=True), "tests/db")
    assert code != 0 and "test_deleting_a_post_deletes_its_comments" in failed, out
    root = project(tmp_path / "b")
    db = (root / "database" / "comments.py").read_text(encoding="utf-8")
    (root / "database" / "comments.py").write_text(db.replace('else "id DESC"', 'else "id ASC"'), encoding="utf-8")
    code, failed, out = run_pytest(root, "tests/db")
    assert code != 0 and "test_list_is_newest_first" in failed, out
