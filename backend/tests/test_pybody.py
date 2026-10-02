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


def test_whole_function_sent_by_the_model_is_reduced_to_its_body():
    code = "from x import y\n\n@router.get('/x')\ndef second():\n    value = 1\n    return {'v': value}"
    out, problem = replace_function_body(SRC, "second", code)
    assert problem == ""
    assert "def second():\n    value = 1\n    return {'v': value}\n" in out and "from x import y" not in out
    compile(out, "x.py", "exec")
