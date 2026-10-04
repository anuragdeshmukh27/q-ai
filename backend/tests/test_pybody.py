"""`implement`: replace one function body, never touching imports, decorators or signatures."""
from app.pybody import replace_function_body

SRC = '''from fastapi import APIRouter

router = APIRouter()


def first(a: int) -> int:
    """Doc."""
    # hint
    raise NotImplementedError


@router.get("/x")
def second():
    raise NotImplementedError


def third():
    return 3
'''


def test_fills_stub_keeping_docstring_comment_signature_and_neighbours():
    out, problem = replace_function_body(SRC, "first", "return a + 1")
    assert problem == ""
    assert 'def first(a: int) -> int:\n    """Doc."""\n    return a + 1\n' in out
    assert '@router.get("/x")\ndef second():\n    raise NotImplementedError' in out and "def third():\n    return 3" in out
    compile(out, "x.py", "exec")


def test_comments_above_the_first_statement_are_kept():
    src = "def f():\n    # error: 400 x\n    raise NotImplementedError\n"
    out, _ = replace_function_body(src, "f", "return 1")
    assert out == "def f():\n    # error: 400 x\n    return 1\n"


def test_multiline_body_is_dedented_and_reindented():
    out, problem = replace_function_body(SRC, "second", "    x = 1\n    if x:\n        return {'a': x}\n    return {}")
    assert problem == ""
    assert "def second():\n    x = 1\n    if x:\n        return {'a': x}\n    return {}\n" in out
    compile(out, "x.py", "exec")


def test_replaces_a_working_body_too():
    out, _ = replace_function_body(SRC, "third", "return 4")
    assert "def third():\n    return 4\n" in out and "return 3" not in out


def test_rejects_def_line_unknown_function_and_empty_body():
    assert "INSIDE" in replace_function_body(SRC, "first", "@router.get('/x')\nreturn 1")[1]
    assert "no function named 'nope'" in replace_function_body(SRC, "nope", "return 1")[1]
    assert "first" in replace_function_body(SRC, "nope", "return 1")[1]
    assert replace_function_body(SRC, "first", "  \n")[1]


def test_one_line_function_and_broken_source_are_refused():
    assert "one line" in replace_function_body("def f(): return 1\n", "f", "return 2")[1]
    assert "does not parse" in replace_function_body("def f(:\n", "f", "return 2")[1]


BIG = '''def handle(req):
    if req.op not in ("add", "sub"):
        raise ValueError("bad")
    result = {"add": operator.sub, "sub": operator.sub}[req.op](req.a, req.b)
    row = save(req, result)
    return {"result": result, "id": row["id"]}
'''


def test_a_one_line_fix_cannot_wipe_out_a_working_function():
    """Regression from the first real recording: the bug fix sent only the faulty line and deleted the validation, the save and the return."""
    out, problem = replace_function_body(BIG, "handle", 'result = {"add": operator.add, "sub": operator.sub}[req.op](req.a, req.b)')
    assert out == "" and "WHOLE body" in problem
    assert "row = save(req, result)" in problem and 'raise ValueError("bad")' in problem  # the current body is shown, to copy and edit
    fixed, problem = replace_function_body(BIG, "handle", "\n".join(l[4:] for l in BIG.splitlines()[1:]).replace('"add": operator.sub', '"add": operator.add'))
    assert problem == "" and 'operator.add' in fixed and "row = save(req, result)" in fixed and "def handle(req):" in fixed


def test_short_bodies_and_real_shrinks_of_small_functions_are_still_allowed():
    assert replace_function_body(SRC, "third", "return 4")[1] == ""  # tiny old body: free to rewrite
    two = "def f():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    return a\n"
    assert replace_function_body(two, "f", "a = 1\nb = 2\nc = 3\nreturn a")[1] == ""  # not below half


def test_whole_function_sent_by_the_model_is_reduced_to_its_body():
    code = "from x import y\n\n@router.get('/x')\ndef second():\n    value = 1\n    return {'v': value}"
    out, problem = replace_function_body(SRC, "second", code)
    assert problem == ""
    assert "def second():\n    value = 1\n    return {'v': value}\n" in out and "from x import y" not in out
    compile(out, "x.py", "exec")


# --- names read but defined nowhere (a 7B writes `appointment_id` where the route's parameter is `id`) ---------------------------------

def test_a_variable_that_is_not_a_parameter_is_reported():
    import ast
    from app.pybody import undefined_variables

    src = ("from database import appointments as db\nfrom fastapi import HTTPException\nLIMIT = 5\n\n\n"
           "def put(id: int, req):\n    row = db.get_appointment(appointment_id)\n    return row\n")
    assert undefined_variables(ast.parse(src), "put") == (["appointment_id"], ["id", "req"])


def test_everything_that_is_bound_is_fine():
    import ast
    from app.pybody import undefined_variables

    src = ("import json\nfrom typing import Literal\nLIMIT = 5\nTABLE = 'x'\n\n\ndef helper():\n    return 1\n\n\n"
           "def put(id: int, req, *args, **kw):\n"
           "    total = 0\n    for i, (a, b) in enumerate(args):\n        total += i + a + b\n"
           "    rows = [r for r in kw if r not in LIMIT]\n    sq = lambda z: z * z\n"
           "    with open('f') as fh, open('g') as gh:\n        text = fh.read() + gh.read()\n"
           "    try:\n        x = json.loads(text)\n    except ValueError as err:\n        raise HTTPException(400, str(err))\n"
           "    def inner(q):\n        return q + total\n    return {'a': helper(), 'b': inner(sq(2)), 'c': len(rows), 'd': TABLE, 't': type(x).__name__, 'u': __name__}\n")
    assert undefined_variables(ast.parse(src), "put")[0] == ["HTTPException"], "HTTPException is the one name this file never imports"
    ok = src.replace("raise HTTPException(400, str(err))", "raise ValueError(str(err))")
    assert undefined_variables(ast.parse(ok), "put")[0] == []


def test_implement_refuses_an_undefined_variable_and_says_which_names_exist(tmp_path):
    from test_tools import act, box

    root = tmp_path / "wt"
    (root / "backend" / "api").mkdir(parents=True)
    (root / ".git").mkdir()
    stub = root / "backend" / "api" / "a.py"
    stub.write_text("from database import appointments as db\n\n\ndef put(id: int, req):\n    raise NotImplementedError\n")
    tb, _ = box(root)
    bad = tb.execute(act("implement", path="backend/api/a.py", function="put", content="row = db.get_appointment(appointment_id)\nreturn row"))
    assert not bad.ok and "`appointment_id` is not defined inside put" in bad.output and "(id, req)" in bad.output
    assert "NotImplementedError" in stub.read_text(), "nothing was written"
    good = tb.execute(act("implement", path="backend/api/a.py", function="put", content="row = db.get_appointment(id)\nreturn row"))
    assert good.ok, good.output
