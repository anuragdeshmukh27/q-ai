"""Agent loop with a scripted LLM: finish gating, escalation, context fitting."""
import pytest

from app.agent.actions import Action
from app.agent.loop import Step, build_system_prompt, fit_messages, run_agent, trim_observation
from app.config import AgentConfig, load_agents
from app.events import EventBus
from app.llm import InvalidOutputError, StructuredResult
from app.providers.base import ProviderError
from app.tools import ToolBox


class ScriptedLLM:
    """Replays a list of Actions (or exceptions); records the messages it was given."""

    def __init__(self, script):
        self.script, self.seen = list(script), []

    def call(self, model_id, messages, schema_model, temperature=0.2):
        self.seen.append(messages)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return StructuredResult(item, model_id, 1, 100, 20, 0.5, "")


def A(action, **kw):
    return Action(thought=f"doing {action}", action=action, **kw)


def W(path, content):
    return A("write_file", path=path, content=content)


GOOD_CODE = "def add(a, b):\n    return a + b\n"
GOOD_TEST = "from backend.calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
BAD_CODE = "def add(a, b):\n    return a - b\n"


@pytest.fixture()
def agent():
    return AgentConfig(
        id="backend", name="Rohan", role="Backend Engineer", model_capability="coding", system_prompt_file="backend.md",
        tools=["list_dir", "read_file", "write_file", "search", "run", "run_tests", "send_message", "ask_human", "finish"],
        owned_paths=["backend/**", "tests/**"], max_iterations=8,
    )


@pytest.fixture()
def env(tmp_path, agent):
    root = tmp_path / "proj"
    (root / "backend").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "backend" / "__init__.py").write_text("")
    (root / "pytest.ini").write_text("[pytest]\npythonpath = .\ntestpaths = tests\n")
    bus = EventBus()
    return root, bus, ToolBox(root, agent, emit=bus.emit)


def go(agent, env, script, **kw):
    root, bus, tb = env
    llm = ScriptedLLM(script)
    res = run_agent(agent, "Implement add()", tb, llm, "m", system_prompt="SYS", **kw)
    return res, bus, llm


def types(bus):
    return [e["type"] for e in bus.history]


def test_happy_path(agent, env):
    res, bus, llm = go(agent, env, [
        W("backend/calc.py", GOOD_CODE), W("tests/test_calc.py", GOOD_TEST), A("run_tests"), A("finish", summary="add done"),
    ])
    assert res.status == "finished" and res.summary == "add done" and res.iterations == 4
    assert res.files_touched == ["backend/calc.py", "tests/test_calc.py"]
    assert res.last_test["passed"] is True
    assert res.prompt_tokens == 400 and res.completion_tokens == 80
    t = types(bus)
    for expected in ("iteration", "agent_state", "agent_thought", "tool_call", "file_changed", "test_result"):
        assert expected in t
    states = [e["state"] for e in bus.history if e["type"] == "agent_state"]
    assert {"thinking", "typing", "testing", "idle"} <= set(states)
    assert llm.seen[0][0]["content"] == "SYS" and "Implement add()" in llm.seen[0][1]["content"]


def test_cannot_finish_before_running_tests(agent, env):
    res, bus, llm = go(agent, env, [
        W("backend/calc.py", GOOD_CODE), W("tests/test_calc.py", GOOD_TEST),
        A("finish", summary="early"), A("run_tests"), A("finish", summary="ok"),
    ])
    assert res.status == "finished" and res.summary == "ok" and res.iterations == 5
    rejected = [e for e in bus.history if e["type"] == "tool_call" and e["decision"] == "rejected"]
    assert len(rejected) == 1
    assert "Cannot finish" in llm.seen[3][-1]["content"]


def test_cannot_finish_with_failing_tests_then_fixes(agent, env):
    res, bus, _ = go(agent, env, [
        W("backend/calc.py", BAD_CODE), W("tests/test_calc.py", GOOD_TEST), A("run_tests"),
        A("finish", summary="hope"), W("backend/calc.py", GOOD_CODE), A("run_tests"), A("finish", summary="fixed"),
    ], )
    assert res.status == "finished" and res.summary == "fixed"
    assert res.last_test["passed"]


def test_finish_after_a_later_edit_requires_rerun(agent, env):
    res, _, _ = go(agent, env, [
        W("backend/calc.py", GOOD_CODE), W("tests/test_calc.py", GOOD_TEST), A("run_tests"),
        W("backend/extra.py", "x = 1\n"), A("finish", summary="stale"), A("run_tests"), A("finish", summary="fresh"),
    ])
    assert res.summary == "fresh"


def test_finish_without_any_writes_is_allowed(agent, env):
    res, _, _ = go(agent, env, [A("list_dir"), A("finish", summary="nothing to do")])
    assert res.status == "finished"


def test_max_iterations_escalates(agent, env):
    agent.max_iterations = 4
    res, bus, _ = go(agent, env, [W(f"backend/f{i}.py", f"x = {i}\n") for i in range(10)])
    assert res.status == "escalated" and res.reason == "max_iterations" and res.iterations == 4
    esc = [e for e in bus.history if e["type"] == "escalation"]
    assert len(esc) == 1 and esc[0]["reason"] == "max_iterations" and esc[0]["agent"] == "backend"
    assert [e["state"] for e in bus.history if e["type"] == "agent_state"][-1] == "waiting_human"


def test_repeated_action_warns_then_escalates(agent, env):
    res, bus, llm = go(agent, env, [A("read_file", path="backend/__init__.py")] * 5)
    assert res.status == "escalated" and res.reason == "repeated_action" and res.iterations == 3
    assert "WARNING" in llm.seen[2][-1]["content"]
    assert "WARNING" not in llm.seen[1][-1]["content"]


def test_same_failing_tests_escalate_as_no_improvement(agent, env):
    res, _, _ = go(agent, env, [
        W("backend/calc.py", BAD_CODE), W("tests/test_calc.py", GOOD_TEST), A("run_tests"),
        W("backend/calc.py", BAD_CODE + "# 1\n"), A("run_tests"),
        W("backend/calc.py", BAD_CODE + "# 2\n"), A("run_tests"),
    ])
    assert res.status == "escalated" and res.reason == "no_improvement"


def test_single_invalid_output_is_survivable(agent, env):
    res, bus, _ = go(agent, env, [InvalidOutputError("bad"), A("finish", summary="ok")])
    assert res.status == "finished"
    assert any(e["type"] == "error" for e in bus.history)


def test_three_invalid_outputs_escalate(agent, env):
    res, _, _ = go(agent, env, [InvalidOutputError("bad")] * 3)
    assert res.status == "escalated" and res.reason == "invalid_output"


def test_provider_failure_is_an_error_not_a_crash(agent, env):
    res, bus, _ = go(agent, env, [ProviderError("Ollama is not reachable")])
    assert res.status == "error" and "Ollama" in res.summary
    assert any(e["type"] == "escalation" for e in bus.history)


def test_ask_human_pauses_the_task(agent, env):
    res, bus, _ = go(agent, env, [A("ask_human", question="Which port?"), A("finish", summary="x")])
    assert res.status == "waiting_human" and res.question == "Which port?"
    assert [e["state"] for e in bus.history if e["type"] == "agent_state"][-1] == "waiting_human"


def test_denied_command_is_an_observation_not_a_stop(agent, env):
    res, _, llm = go(agent, env, [A("run", command="rm -rf /"), A("finish", summary="gave up")])
    assert res.status == "finished"
    assert "denied" in llm.seen[1][-1]["content"] and "FAILED" in llm.seen[1][-1]["content"]


def test_unauthorised_write_is_an_observation(agent, env):
    res, _, llm = go(agent, env, [W("README.md", "x"), A("finish", summary="ok")])
    assert res.status == "finished"
    assert "outside this agent's owned paths" in llm.seen[1][-1]["content"]


# --- context fitting ---------------------------------------------------------------------
def mk_steps(n, size=500):
    return [
        Step({"role": "assistant", "content": "a" * size}, {"role": "user", "content": "o" * size}, f"{i}. read_file x{i}: ok")
        for i in range(1, n + 1)
    ]


def test_fit_keeps_everything_when_small():
    msgs = fit_messages("S", "TASK", mk_steps(3, 10), 10_000)
    assert len(msgs) == 2 + 6 and msgs[1]["content"] == "TASK"


def test_fit_drops_oldest_steps_into_a_digest_and_keeps_the_task():
    steps = mk_steps(20, 500)
    msgs = fit_messages("S", "TASK", steps, 6_000)
    total = sum(len(m["content"]) for m in msgs)
    assert total <= 6_000
    assert msgs[1]["content"].startswith("TASK") and "Earlier steps" in msgs[1]["content"]
    assert "1. read_file x1: ok" in msgs[1]["content"]
    assert msgs[-2:] == [steps[-1].assistant, steps[-1].observation]  # newest step kept


def test_fit_always_keeps_the_two_latest_steps():
    msgs = fit_messages("S", "TASK", mk_steps(5, 5_000), 100)
    assert len(msgs) == 2 + 4


def test_trim_observation_keeps_head_and_tail():
    s = "H" * 100 + "M" * 10_000 + "TAIL-FAILURE"
    out = trim_observation(s, 1000)
    assert len(out) < 1100 and out.startswith("H") and out.endswith("TAIL-FAILURE") and "omitted" in out


def test_long_runs_stay_inside_the_prompt_budget(agent, env):
    agent.max_iterations = 30
    script = [W(f"backend/f{i}.py", "x = 1\n" * 300) for i in range(30)]
    _, _, llm = go(agent, env, script, num_ctx=4096)
    budget = (4096 - 1536) * 3
    assert all(sum(len(m["content"]) for m in msgs) <= max(budget, 4000) + 400 for msgs in llm.seen)


# --- prompts -----------------------------------------------------------------------------
def test_system_prompt_lists_tools_and_ownership():
    a = load_agents()["backend"]
    p = build_system_prompt(a)
    assert "Rohan" in p and "backend/**" in p and "run_tests" in p
    assert not any(ph in p for ph in ("{name}", "{role}", "{tools}", "{owned}"))
    assert "finish" in p and "fastapi" in p.lower()
