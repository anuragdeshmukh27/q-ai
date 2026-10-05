"""The agent loop: think -> act -> observe with JSON actions until finish or a limit is hit."""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import Callable

from ..config import PROMPTS_DIR, AgentConfig
from ..llm import InvalidOutputError, LLMClient, agent_context
from ..providers.base import ProviderError
from ..tools import ToolBox, ToolResult
from .actions import Action
from .termination import REASON_TEXT, TerminationTracker

STATE_BY_ACTION = {
    "list_dir": "reading", "read_file": "reading", "search": "reading",
    "write_file": "typing", "implement": "typing", "replace": "typing", "run": "executing", "run_tests": "testing",
    "send_message": "walking", "ask_human": "waiting_human", "finish": "idle",
}
STALL_HINT = (
    "\n\nWARNING: the same tests failed again; one more identical failure escalates the task. For EACH failing assertion decide: "
    "if it expects a value the code could not know in advance (a timestamp, an id) or contradicts the task's acceptance criteria, "
    "rewrite the TEST. Otherwise change the exact line of code that the failure points to. Do not send the same file again."
)
BASE_TEMPERATURE = 0.1
OBSERVATION_CHARS = 3000
CHARS_PER_TOKEN = 3  # conservative; keeps the prompt inside num_ctx


@dataclass
class AgentResult:
    status: str  # finished | escalated | waiting_human | error
    reason: str = ""
    summary: str = ""
    iterations: int = 0
    files_touched: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    last_test: dict | None = None
    question: str = ""


@dataclass
class Step:
    assistant: dict
    observation: dict
    digest: str


def build_system_prompt(agent: AgentConfig) -> str:
    protocol = (PROMPTS_DIR / "_protocol.md").read_text(encoding="utf-8")
    role = (PROMPTS_DIR / agent.system_prompt_file).read_text(encoding="utf-8")
    return (
        protocol.replace("{name}", agent.name)
        .replace("{role}", agent.role)
        .replace("{tools}", ", ".join(agent.tools))
        .replace("{owned}", ", ".join(agent.owned_paths) or "(nothing)")
        + "\n\n"
        + role
    )


def trim_observation(text: str, limit: int = OBSERVATION_CHARS) -> str:
    if len(text) <= limit:
        return text
    head, tail = limit * 2 // 5, limit * 3 // 5  # failures and summaries are at the end
    return text[:head] + "\n[... omitted ...]\n" + text[-tail:]


def fit_messages(system: str, first_user: str, steps: list[Step], budget_chars: int) -> list[dict]:
    """System + task + as many recent steps as fit; older steps collapse into a digest."""
    keep = list(steps)

    def size(ks: list[Step], digest: str) -> int:
        return len(system) + len(first_user) + len(digest) + sum(len(s.assistant["content"]) + len(s.observation["content"]) for s in ks)

    dropped = 0
    digest = ""
    while len(keep) > 2 and size(keep, digest) > budget_chars:
        keep.pop(0)
        dropped += 1
        digest = "\n\nEarlier steps (details omitted):\n" + "\n".join(f"- {s.digest}" for s in steps[:dropped][-30:])
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": first_user + digest}]
    for s in keep:
        msgs += [s.assistant, s.observation]
    return msgs


def _digest(n: int, a: Action, ok: bool) -> str:
    arg = a.path or a.command or a.pattern or a.to or ""
    return f"{n}. {a.action} {arg}".strip() + (": ok" if ok else ": failed")


def run_agent(agent: AgentConfig, *args, **kwargs) -> AgentResult:
    """Run one task; every model call inside it is attributed to `agent` (the scheduler shows who waits for the GPU)."""
    with agent_context(agent.id):
        return _run_agent(agent, *args, **kwargs)


def _run_agent(
    agent: AgentConfig,
    task: str,
    toolbox: ToolBox,
    llm: LLMClient,
    model_id: str,
    system_prompt: str | None = None,
    num_ctx: int = 8192,
    context: str = "",
    emit: Callable[..., object] | None = None,
    stop: Callable[[], bool] | None = None,
) -> AgentResult:
    emit = emit or toolbox.emit
    system = system_prompt or build_system_prompt(agent)
    budget = max(4000, (num_ctx - 1536) * CHARS_PER_TOKEN)
    room = budget - len(system) - len(task) - 1500  # a prompt that does not fit num_ctx loses its START (the system prompt and the task): the project context gives way, never the task
    if context and len(context) > max(room, 1500):
        context = context[:max(room, 1500)] + "\n[... project context shortened ...]"
    first_user = f"## Task\n{task}" + (f"\n\n## Project context\n{context}" if context else "")
    tracker = TerminationTracker(agent.max_iterations)
    steps: list[Step] = []
    res = AgentResult("running")
    dirty = False  # code changed since the last test run
    stuck = 0  # consecutive rejected writes: the model keeps re-sending the same broken code
    invalid, invalid_note = 0, ""  # consecutive replies that were not a valid action, and why the last one was refused

    def result(status: str, reason: str = "", **kw) -> AgentResult:
        res.status, res.reason, res.iterations = status, reason, tracker.iterations
        res.files_touched = list(toolbox.files_touched)
        for k, v in kw.items():
            setattr(res, k, v)
        return res

    def escalate(reason: str, status: str = "escalated") -> AgentResult:
        detail = REASON_TEXT.get(reason, reason)
        emit("escalation", agent=agent.id, task=task[:200], reason=reason, detail=detail, iterations=tracker.iterations,
             recent=[s.digest for s in steps[-5:]])
        emit("agent_state", agent=agent.id, state="waiting_human")
        return result(status, reason)

    for n in count(1):
        if stop is not None and stop():  # the human pressed "Stop build"
            emit("agent_state", agent=agent.id, state="idle")
            return result("stopped", "stopped by you")
        emit("iteration", agent=agent.id, n=n, max=agent.max_iterations)
        emit("agent_state", agent=agent.id, state="thinking")
        messages = fit_messages(system, first_user, steps, budget)
        if invalid_note:  # the model is told why its last reply was refused (it would otherwise send the same one again)
            messages = [*messages, {"role": "user", "content": f"Your last reply was refused: {invalid_note}\nReply again with ONE complete JSON action."}]
        try:
            out = llm.call(model_id, messages, Action, temperature=min(0.9, BASE_TEMPERATURE + 0.3 * (stuck + invalid)))  # warmer when stuck, to escape loops
            invalid, invalid_note = 0, ""
        except InvalidOutputError as e:
            emit("error", agent=agent.id, message=f"model returned invalid output: {e}")
            invalid += 1  # the retry says why the reply was refused and is a little warmer, so it can differ
            invalid_note = str(e)[:400]
            tracker.record_failed()
            stuck += 1  # the next call is warmer: the same prompt at the same temperature gives the same invalid reply
            reason = tracker.check()
            if reason:
                return escalate(reason)
            continue
        except ProviderError as e:
            emit("agent_state", agent=agent.id, state="error")
            emit("error", agent=agent.id, message=str(e))
            emit("escalation", agent=agent.id, task=task[:200], reason="model_unavailable", detail=str(e),
                 iterations=tracker.iterations, recent=[])
            return result("error", "model_unavailable", summary=str(e))

        res.prompt_tokens += out.prompt_tokens
        res.completion_tokens += out.completion_tokens
        action: Action = out.parsed  # type: ignore[assignment]
        emit("agent_thought", agent=agent.id, text=action.thought, model=out.model_id, tokens=out.completion_tokens, seconds=out.seconds)
        emit("agent_state", agent=agent.id, state=STATE_BY_ACTION[action.action] if action.action != "finish" else "thinking")

        tr = _execute(action, toolbox, emit, agent, res.last_test, dirty)
        if action.action in ("write_file", "implement", "replace") and (tr.ok or tr.data.get("wrote")):
            dirty = True
        signature = None
        if action.action == "run_tests" and "signature" in tr.data:
            signature = tr.data["signature"]
            res.last_test = {k: tr.data[k] for k in ("passed", "failed", "summary", "signature")}
            dirty = False
            emit("test_result", agent=agent.id, **res.last_test)
        stuck = stuck + 1 if (action.action in ("write_file", "implement", "replace") and not tr.ok) else 0
        tracker.record(action, signature)
        step = _step(len(steps) + 1, action, tr, tracker.repeat_warning(), action.action == "run_tests" and tracker.stall_warning())
        steps.append(step)
        if len(steps) > 1:  # remind the model what it just did, so it does not loop on the same move
            step.observation["content"] += "\nYour last actions: " + "; ".join(s.digest for s in steps[-3:])

        if tr.finished:
            emit("agent_state", agent=agent.id, state="idle")
            return result("finished", summary=tr.output)
        if tr.needs_human:
            emit("escalation", agent=agent.id, task=task[:200], reason="waiting_human", detail=tr.data.get("question", ""),
                 iterations=tracker.iterations, recent=[s.digest for s in steps[-5:]])
            emit("agent_state", agent=agent.id, state="waiting_human")
            return result("waiting_human", "waiting_human", question=tr.data.get("question", ""))
        reason = tracker.check()
        if reason:
            return escalate(reason)
    raise AssertionError("unreachable")


def _execute(action: Action, toolbox: ToolBox, emit, agent: AgentConfig, last_test: dict | None, dirty: bool) -> ToolResult:
    if action.action == "finish" and "run_tests" in agent.tools and toolbox.files_touched:
        if last_test is None or not last_test["passed"] or dirty:
            why = "you have not run the tests since your last change" if (last_test and last_test["passed"]) or last_test is None else "tests are failing"
            msg = f"Cannot finish: {why}. Run run_tests, fix any failures, then finish."
            emit("tool_call", agent=agent.id, tool="finish", args=action.args(), ok=False, decision="rejected", duration=0, output=msg)
            return ToolResult(False, msg, {"decision": "rejected"})
    return toolbox.execute(action)


def _step(n: int, action: Action, tr: ToolResult, repeat_warning: bool, stalled: bool = False) -> Step:
    text = trim_observation(tr.output)
    if action.action == "run_tests" and tr.data.get("passed"):
        text = f"All tests passed. {tr.data.get('summary', '')}\nA warning in the output is harmless: do not ask anyone about it. Call finish now with a one-line summary."
    elif action.action == "run_tests" and tr.data.get("digest"):
        # the exception of each failing test comes first: in a long traceback it would be cut away by the trimming below
        text = "What failed (read this first):\n" + tr.data["digest"][:1500] + "\n\nFull output (trimmed):\n" + text
    obs = f"Result of {action.action} ({'ok' if tr.ok else 'FAILED'}):\n{text}"
    if repeat_warning:
        obs += "\n\nWARNING: you repeated the same action. Do something different or the task will be escalated."
    if stalled:
        obs += STALL_HINT
    return Step(
        {"role": "assistant", "content": action.model_dump_json(exclude_none=True)},
        {"role": "user", "content": obs},
        _digest(n, action, tr.ok),
    )
