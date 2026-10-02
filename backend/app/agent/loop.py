"""The agent loop: think -> act -> observe with JSON actions until finish or a limit is hit."""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import Callable

from ..config import PROMPTS_DIR, AgentConfig
from ..llm import InvalidOutputError, LLMClient
from ..providers.base import ProviderError
from ..tools import ToolBox, ToolResult
from .actions import Action
from .termination import REASON_TEXT, TerminationTracker

STATE_BY_ACTION = {
    "list_dir": "reading", "read_file": "reading", "search": "reading",
    "write_file": "typing", "run": "executing", "run_tests": "testing",
    "send_message": "walking", "ask_human": "waiting_human", "finish": "idle",
}
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


def run_agent(
    agent: AgentConfig,
    task: str,
    toolbox: ToolBox,
    llm: LLMClient,
    model_id: str,
    system_prompt: str | None = None,
    num_ctx: int = 8192,
    context: str = "",
    emit: Callable[..., object] | None = None,
) -> AgentResult:
    emit = emit or toolbox.emit
    system = system_prompt or build_system_prompt(agent)
    first_user = f"## Task\n{task}" + (f"\n\n## Project context\n{context}" if context else "")
    budget = max(4000, (num_ctx - 1536) * CHARS_PER_TOKEN)
    tracker = TerminationTracker(agent.max_iterations)
    steps: list[Step] = []
    res = AgentResult("running")
    dirty = False  # code changed since the last test run

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
        emit("iteration", agent=agent.id, n=n, max=agent.max_iterations)
        emit("agent_state", agent=agent.id, state="thinking")
        messages = fit_messages(system, first_user, steps, budget)
        try:
            out = llm.call(model_id, messages, Action)
        except InvalidOutputError as e:
            emit("error", agent=agent.id, message=f"model returned invalid output: {e}")
            tracker.record_failed()
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
        if action.action == "write_file" and tr.ok:
            dirty = True
        signature = None
        if action.action == "run_tests" and "signature" in tr.data:
            signature = tr.data["signature"]
            res.last_test = {k: tr.data[k] for k in ("passed", "failed", "summary", "signature")}
            dirty = False
            emit("test_result", agent=agent.id, **res.last_test)
        tracker.record(action, signature)
        steps.append(_step(len(steps) + 1, action, tr, tracker.repeat_warning()))

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


def _step(n: int, action: Action, tr: ToolResult, repeat_warning: bool) -> Step:
    text = trim_observation(tr.output)
    if action.action == "run_tests" and tr.data.get("passed"):
        text = f"All tests passed. {tr.data.get('summary', '')}\n" + text[-600:]
    obs = f"Result of {action.action} ({'ok' if tr.ok else 'FAILED'}):\n{text}"
    if repeat_warning:
        obs += "\n\nWARNING: you repeated the same action. Do something different or the task will be escalated."
    return Step(
        {"role": "assistant", "content": action.model_dump_json(exclude_none=True)},
        {"role": "user", "content": obs},
        _digest(n, action, tr.ok),
    )
