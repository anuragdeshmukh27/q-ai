"""Fixes found by reading what a 7B was actually given: an oversize prompt, a retry at the same temperature, reviewer claims that can be checked."""
from app.agent.loop import fit_messages
from app.agent.review import ReviewItem, ReviewOutput, drop_unfounded
from app.memory import contract_brief
from app.orchestrator import Orchestrator


def _review(*problems: str) -> ReviewOutput:
    return ReviewOutput(verdict="REQUEST_CHANGES", summary="s", items=[ReviewItem(file="database/a.py", problem=p) for p in problems])


def test_reviewer_claims_that_the_file_disproves_are_dropped(tmp_path):
    (tmp_path / "database").mkdir()
    (tmp_path / "database" / "a.py").write_text("def add_a():\n    with connect(SCHEMA) as conn:\n        return 1\n", encoding="utf-8")
    out = drop_unfounded(_review("The file has a syntax error at the end", "The file contains 65 lines, over the 150-line limit",
                                 "The SCHEMA constant is not used", "This is inefficient", "does not implement `add_a`"), tmp_path)
    assert out.verdict == "PASS" and out.items == []


def test_a_claim_the_file_confirms_is_kept(tmp_path):
    (tmp_path / "database").mkdir()
    (tmp_path / "database" / "a.py").write_text("def add_a(:\n    pass\n", encoding="utf-8")
    out = drop_unfounded(_review("syntax error in add_a", "the detail text is wrong: expected 'Team not found'"), tmp_path)
    assert out.verdict == "REQUEST_CHANGES" and len(out.items) == 2


def test_a_missing_function_claim_is_kept_while_the_stub_is_unfilled(tmp_path):
    (tmp_path / "database").mkdir()
    (tmp_path / "database" / "a.py").write_text("def add_a():\n    raise NotImplementedError\n", encoding="utf-8")
    assert drop_unfounded(_review("does not implement `add_a`"), tmp_path).verdict == "REQUEST_CHANGES"


def test_the_brief_can_be_limited_to_one_router():
    contract = {"version": 1, "endpoints": [
        {"method": "GET", "path": "/api/a", "summary": "a", "request": {"fields": []}, "response": {"status": 200, "fields": []}, "errors": []},
        {"method": "GET", "path": "/api/b", "summary": "b", "request": {"fields": []}, "response": {"status": 200, "fields": []}, "errors": []}]}
    assert "/api/b" not in contract_brief(contract, {"/api/a"}) and "/api/a" in contract_brief(contract, {"/api/a"})
    assert "/api/b" in contract_brief(contract)


def test_the_first_reply_shape_names_the_file_and_its_first_function():
    text = Orchestrator._implement_example(("database/members.py", "x\ndef add_member(a):\n    pass\ndef get_member(i):\n    pass\n"))
    assert '"path": "database/members.py"' in text and '"function": "add_member"' in text and '"content"' in text


def test_a_retry_after_invalid_output_is_warmer():
    from test_providers import MSGS, FakeProvider, Out, llm_with

    temps: list[float] = []

    class Spy(FakeProvider):
        def chat(self, model, messages, schema=None, temperature=0.2):
            temps.append(temperature)
            return super().chat(model, messages, schema, temperature)

    llm_with({"m": Spy(['{"x": "nope"}', '{"x": 6}'])}).call("m", MSGS, Out, temperature=0.1)
    assert temps[1] > temps[0]


def test_fit_messages_keeps_the_task_first():
    msgs = fit_messages("sys", "task", [], 1000)
    assert msgs[1]["content"].startswith("task")


def test_size_and_missing_test_claims_are_dropped_when_the_files_disprove_them(tmp_path):
    (tmp_path / "database").mkdir()
    (tmp_path / "tests" / "db").mkdir(parents=True)
    (tmp_path / "database" / "mentors.py").write_text("def add_mentor():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "db" / "test_mentors.py").write_text("def test_add():\n    pass\n", encoding="utf-8")
    review = ReviewOutput(verdict="REQUEST_CHANGES", summary="s", items=[ReviewItem(
        file="database/mentors.py", problem="The file contains a large number of lines and a single function doing several jobs. It also lacks tests for `add_mentor`.")])
    assert drop_unfounded(review, tmp_path).verdict == "PASS"
    (tmp_path / "tests" / "db" / "test_mentors.py").unlink()
    only_tests = ReviewOutput(verdict="REQUEST_CHANGES", summary="s", items=[ReviewItem(file="database/mentors.py", problem="There are no tests for `add_mentor`.")])
    assert drop_unfounded(only_tests, tmp_path).verdict == "REQUEST_CHANGES"
