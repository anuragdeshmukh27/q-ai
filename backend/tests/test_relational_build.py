"""A reddit-style build (posts -> comments, votes, sort) with a scripted team: the spec is the only model-made contract input.

The engineers follow scripts built from the engine's own route hints and plain SQL; what is under test is everything around them:
the contract synthesized from the spec, the plan (one task per table and per router), per-resource stubs and generated tests, merges, QA and verification.
"""
import re

from app.agent.actions import Action
from app.relations import endpoints_for_resource, synthesize_design
from app.scaffold import _hints, _words
from app.schemas import PlannerOutput, SpecOutput, normalize_spec

from test_orchestrator import FakeLLM, make, types

SPEC = {
    "title": "Reddit replica", "summary": "Posts with comments and votes.",
    "features": ["Form to write a post", "Filter the list of posts by upvotes, downvotes, or created_at", "Open a post to add comments"],
    "resources": [
        {"name": "posts", "operations": ["list", "create", "update", "delete"], "fields": [
            {"name": "title", "type": "string"}, {"name": "content", "type": "string"}, {"name": "author", "type": "string"},
            {"name": "created_at", "type": "string"}, {"name": "upvotes", "type": "number"}, {"name": "downvotes", "type": "number"}]},
        {"name": "comments", "operations": ["list", "create", "update", "delete"], "fields": [
            {"name": "content", "type": "string"}, {"name": "author", "type": "string"}, {"name": "post_id", "type": "string"},
            {"name": "upvotes", "type": "number"}, {"name": "downvotes", "type": "number"}]},
        {"name": "subreddits", "operations": ["list"], "fields": [{"name": "name", "type": "string"}]},
    ],
}


def act(action, **kw):
    return {"thought": "t", "action": action, **kw}


def design():
    spec = normalize_spec(SpecOutput.model_validate(SPEC), "Build a reddit replica")
    return synthesize_design(spec)


def db_scripts(d, ri):
    """SQL written by hand (placeholders only), one `implement` per function, then the table's own tests."""
    p, s, fk = ri.name, ri.singular, ri.fk
    cols = ([fk] if fk else []) + [f.name for f in ri.fields]
    marks = ", ".join("?" for _ in cols)
    sets = ", ".join(f"{f.name} = ?" for f in ri.fields)
    vals = ", ".join(f.name for f in ri.fields)
    path = f"database/{p}.py"
    row = f"dict(conn.execute('SELECT * FROM {p} WHERE id = ?', (X,)).fetchone())"
    where = f"WHERE {fk} = ? " if fk else ""
    args = f"({fk},)" if fk else "()"
    bodies = {
        f"add_{s}": f"with connect(SCHEMA) as conn:\n    cur = conn.execute('INSERT INTO {p} ({', '.join(cols)}) VALUES ({marks})', ({', '.join(cols)},))\n    return {row.replace('X', 'cur.lastrowid')}",
        f"get_{s}": f"with connect(SCHEMA) as conn:\n    r = conn.execute('SELECT * FROM {p} WHERE id = ?', ({s}_id,)).fetchone()\n    return dict(r) if r else None",
        f"list_{p}": (f"with connect(SCHEMA) as conn:\n    if {'sort == ' + repr('top') if ri.sorts else 'False'}:\n        q = 'SELECT * FROM {p} {where}ORDER BY upvotes - downvotes DESC, id DESC'\n"
                      f"    else:\n        q = 'SELECT * FROM {p} {where}ORDER BY id DESC'\n    return [dict(r) for r in conn.execute(q, {args}).fetchall()]"),
        f"update_{s}": (f"with connect(SCHEMA) as conn:\n    conn.execute('UPDATE {p} SET {sets} WHERE id = ?', ({vals}, {s}_id))\n"
                        f"    r = conn.execute('SELECT * FROM {p} WHERE id = ?', ({s}_id,)).fetchone()\n    return dict(r) if r else None"),
        f"delete_{s}": (f"with connect(SCHEMA) as conn:\n" + ("    conn.execute('DELETE FROM comments WHERE post_id = ?', (post_id,))\n" if p == "posts" else "")
                        + f"    cur = conn.execute('DELETE FROM {p} WHERE id = ?', ({s}_id,))\n    return cur.rowcount > 0"),
    }
    for a in ri.actions:
        bodies[f"{a.name}_{s}"] = (f"with connect(SCHEMA) as conn:\n    conn.execute('UPDATE {p} SET {a.field} = {a.field} + 1 WHERE id = ?', ({s}_id,))\n"
                                   f"    r = conn.execute('SELECT * FROM {p} WHERE id = ?', ({s}_id,)).fetchone()\n    return dict(r) if r else None")
    out = [act("implement", path=path, function=fn, content=body) for fn, body in bodies.items()]
    first = ", ".join(["1"] if fk else []) + (", " if fk else "") + ", ".join(repr("x") for _ in ri.fields)
    test = f"from database.{p} import add_{s}, get_{s}\n\n\ndef test_round_trip():\n    row = add_{s}({first})\n    assert get_{s}(row['id'])['id'] == row['id']\n"
    return out + [act("write_file", path=f"tests/test_db_{p}.py", content=test), act("run_tests"), act("finish", summary=f"{p} data access done")]


def router_scripts(d, ri):
    out = []
    for e in endpoints_for_resource(d, ri.name):
        func = "handle_" + "_".join([e.method.lower()] + _words(e.path) + (["by"] + re.findall(r"\{(\w+)\}", e.path) if "{" in e.path else []))
        body = "\n".join(_hints(d, e))
        out.append(act("implement", path=f"backend/api/{ri.name}.py", function=func, content=body))
    return out + [act("run_tests"), act("finish", summary=f"{ri.name} router done")]


class RelationalLLM(FakeLLM):
    def __init__(self, d=None):
        super().__init__()
        d = d or design()
        self.scripts = {"Karan": [x for r in d.resources for x in db_scripts(d, r)], "Rohan": [x for r in d.resources for x in router_scripts(d, r)],
                        "Meera": [act("run_tests"), act("finish", summary="page done"), act("run_tests"), act("finish", summary="script done")]}

    def call(self, model_id, messages, schema_model, temperature=0.2):
        if schema_model is SpecOutput:
            self.models_used.append((model_id, "SpecOutput"))
            from app.llm import StructuredResult

            return StructuredResult(SpecOutput.model_validate(SPEC), model_id, 1, 10, 5, 0.01, "{}")
        assert schema_model is not PlannerOutput, "the plan of a relational design is not a model's job"
        return super().call(model_id, messages, schema_model, temperature)


def test_reddit_build_runs_end_to_end(tmp_path):
    llm = RelationalLLM()
    o, bus = make(tmp_path, llm)
    o.goal = "Build a discussion board with comments and votes"  # not a famous app: the scripted spec is the one used
    res = o.run()
    assert res.ok, res.problems
    assert [m for _, m in llm.models_used if m == "ArchitectOutput"] == [], "a relational contract is built by rules, not asked from the model"
    assert [t["files"] for t in res.tasks if t["owner"] in ("database", "backend")] == [
        ["database/posts.py"], ["database/comments.py"], ["backend/api/posts.py"], ["backend/api/comments.py"]]
    root = res.root
    for f in ("database/posts.py", "database/comments.py", "backend/api/posts.py", "backend/api/comments.py", "tests/api/test_contract_posts.py",
              "tests/api/test_contract_comments.py", "tests/qa/test_edge_cases.py", "tests/ui/test_script.py", "static/app.js"):
        assert (root / f).is_file(), f
    assert not (root / "tests/api/test_contract_api.py").exists()
    spec_event = next(e for e in bus.history if e["type"] == "spec_ready")
    assert "subreddits" in spec_event["not_included"]
    assert "Not in this version" in (root / ".q/spec.md").read_text(encoding="utf-8")
    assert "post_id" in (root / ".q/api_contract.json").read_text(encoding="utf-8")
    assert types(bus)[-1] == "project_done"


def test_a_generated_page_that_passes_its_tests_is_not_handed_to_the_model(tmp_path):
    llm = RelationalLLM()
    o, bus = make(tmp_path, llm)
    o.goal = "Build a discussion board with comments and votes"  # not a famous app: the scripted spec is the one used
    res = o.run()
    assert res.ok, res.problems
    assert len(llm.scripts["Meera"]) == 4, "the frontend engineer was never asked: the page generated from the contract already passed"
    assert any(e["type"] == "agent_thought" and "already passes every test" in e.get("text", "") for e in bus.history)


def test_a_famous_single_resource_app_is_built_by_rules_and_gets_a_table_with_a_stat_strip(tmp_path):
    """Uber: one resource, no parent, no votes. Its contract and plan come from the platform spec; the page is a table, not a feed."""
    from app.platforms import match_platform

    d = synthesize_design(normalize_spec(match_platform("Build Uber"), "Build Uber"))
    llm = RelationalLLM(d)
    o, bus = make(tmp_path, llm)
    o.goal = "Build Uber"
    res = o.run()
    assert res.ok, res.problems
    assert [m for _, m in llm.models_used if m in ("ArchitectOutput", "SpecOutput")] == [], "a famous app's spec and contract are not asked from the model"
    assert [t["files"] for t in res.tasks if t["owner"] in ("database", "backend")] == [["database/rides.py"], ["backend/api/rides.py"]]
    html, js = (res.root / "static/index.html").read_text(encoding="utf-8"), (res.root / "static/app.js").read_text(encoding="utf-8")
    assert "layout-table" in html and 'data-theme="industrial"' in html and "Not in this version" in html and "UI.renderTable(" in js and "UI.statStrip(" in js
    assert '"fare"' in js and '"status"' in js, "every field is a column, the fare included"
    assert any(e["type"] == "look_chosen" and e["layout"] == "table" for e in bus.history)
    assert len(llm.scripts["Meera"]) == 4, "the generated page passed its tests, so the frontend engineer was never asked"


def test_an_engineer_who_cannot_finish_a_router_is_rescued_by_the_contract_repair(tmp_path):
    d = design()
    llm = RelationalLLM(d)
    llm.scripts["Rohan"] = [act("run_tests")] * 3 + router_scripts(d, d.resources[1])  # the posts router: the engineer only re-runs the failing tests, then escalates
    o, bus = make(tmp_path, llm)
    o.goal = "Build a discussion board with comments and votes"
    res = o.run()
    assert res.ok, res.problems
    repair = [e for e in bus.history if e["type"] == "contract_repair"]
    assert [(e["path"], e["ok"]) for e in repair] == [("backend/api/posts.py", True)]
    assert "implement" not in (res.root / "backend/api/posts.py").read_text(encoding="utf-8")
    assert "NotImplementedError" not in (res.root / "backend/api/posts.py").read_text(encoding="utf-8")
    assert "Contract repair" in (res.root / ".q" / "decisions.md").read_text(encoding="utf-8")
    assert any(e["type"] == "agent_thought" and "Applying the functions the contract implies" in e.get("text", "") for e in bus.history)
    assert next(t for t in res.tasks if t["files"] == ["backend/api/posts.py"])["status"] == "done"


def test_a_database_task_is_rescued_the_same_way(tmp_path):
    d = design()
    llm = RelationalLLM(d)
    llm.scripts["Karan"] = [act("run_tests")] * 3 + db_scripts(d, d.resources[1])
    o, bus = make(tmp_path, llm)
    o.goal = "Build a discussion board with comments and votes"
    res = o.run()
    assert res.ok, res.problems
    assert [(e["path"], e["ok"]) for e in bus.history if e["type"] == "contract_repair"] == [("database/posts.py", True)]
