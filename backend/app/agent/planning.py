"""Architect, Planner and contract amendments: structured single-shot agents with a validate-and-repair loop.

These roles produce documents, not code, so instead of the tool loop they make a schema-constrained call,
check it semantically, and feed any problems back to the model (up to the agent's max_iterations).
"""
from __future__ import annotations

import json
from typing import Callable, TypeVar

from pydantic import BaseModel, Field

from ..config import PROMPTS_DIR, AgentConfig
from ..llm import InvalidOutputError, LLMClient
from ..providers.base import ProviderError
from ..schemas import ArchitectOutput, Endpoint, PlannerOutput, check_acceptance, check_architecture, check_plan

T = TypeVar("T", bound=BaseModel)
MAX_ATTEMPTS = 3


class AgentFailed(Exception):
    """A planning agent could not produce a valid result; the reason is safe to show to a human."""

    def __init__(self, agent: str, reason: str):
        super().__init__(f"{agent}: {reason}")
        self.agent, self.reason = agent, reason


class AmendOutput(BaseModel):
    approve: bool
    reason: str
    endpoints: list[Endpoint] = Field(default_factory=list, description="The COMPLETE new endpoint list when approved, else empty")


def role_prompt(agent: AgentConfig) -> str:
    text = (PROMPTS_DIR / agent.system_prompt_file).read_text(encoding="utf-8")
    return text.replace("{name}", agent.name).replace("{role}", agent.role)


def structured_step(
    agent: AgentConfig,
    llm: LLMClient,
    model_id: str,
    system: str,
    user: str,
    schema: type[T],
    check: Callable[[T], list[str]],
    emit: Callable[..., object],
    max_attempts: int = MAX_ATTEMPTS,
) -> tuple[T, dict]:
    """Returns the validated output and usage stats {iterations, prompt_tokens, completion_tokens, seconds}."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    stats = {"iterations": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0}
    last = "no valid output"
    for n in range(1, max_attempts + 1):
        stats["iterations"] = n
        emit("iteration", agent=agent.id, n=n, max=max_attempts)
        emit("agent_state", agent=agent.id, state="thinking")
        try:
            out = llm.call(model_id, messages, schema)
        except InvalidOutputError as e:
            last = f"model returned invalid output: {e}"
            emit("error", agent=agent.id, message=last)
            continue
        except ProviderError as e:
            emit("agent_state", agent=agent.id, state="error")
            emit("error", agent=agent.id, message=str(e))
            raise AgentFailed(agent.id, f"model unavailable: {e}") from e
        stats["prompt_tokens"] += out.prompt_tokens
        stats["completion_tokens"] += out.completion_tokens
        stats["seconds"] += out.seconds
        problems = check(out.parsed)  # type: ignore[arg-type]
        if not problems:
            emit("agent_thought", agent=agent.id, text=f"{agent.role} produced a valid result", model=out.model_id,
                 tokens=out.completion_tokens, seconds=out.seconds)
            emit("agent_state", agent=agent.id, state="idle")
            return out.parsed, stats  # type: ignore[return-value]
        last = "; ".join(problems)[:600]
        emit("agent_thought", agent=agent.id, text=f"Result rejected, fixing: {last[:160]}", model=out.model_id,
             tokens=out.completion_tokens, seconds=out.seconds)
        messages += [
            {"role": "assistant", "content": out.raw},
            {"role": "user", "content": "That design has problems. Fix ALL of them and reply with the full corrected JSON:\n- " + "\n- ".join(problems)},
        ]
    emit("agent_state", agent=agent.id, state="waiting_human")
    emit("escalation", agent=agent.id, task="planning", reason="no_valid_output", detail=last, iterations=stats["iterations"], recent=[])
    raise AgentFailed(agent.id, last)


def run_architect(agent, llm, model_id, goal: str, presets: dict[str, str], emit, forced_preset: str | None = None):
    listing = "\n".join(f"- {n}: {d}" for n, d in presets.items())
    user = f"Goal: {goal}\n\nAvailable presets:\n{listing}"
    if forced_preset:
        user += f"\n\nUse preset `{forced_preset}`."
    return structured_step(agent, llm, model_id, role_prompt(agent), user, ArchitectOutput,
                           lambda a: check_architecture(a, list(presets)) + ([f"preset must be {forced_preset}"] if forced_preset and a.preset != forced_preset else []),
                           emit)


def run_planner(agent, llm, model_id, goal: str, contract_text: str, schema_text: str, needs_db: bool, endpoints: list[Endpoint], emit):
    user = f"Goal: {goal}\n\n{contract_text}\n\n{schema_text}"
    return structured_step(agent, llm, model_id, role_prompt(agent), user, PlannerOutput,
                           lambda p: check_plan(p, needs_db, endpoints), emit)


def run_replanner(agent, llm, model_id, goal: str, failed: dict, reason: str, recent: list[str], contract_text: str, schema_text: str,
                  first_new_id: int, needs_db: bool, emit):
    """Hand a repeatedly failing task back to the Planner: it returns replacement tasks (narrower, or the same file made simpler)."""
    user = (
        f"Goal: {goal}" + chr(10) * 2 + contract_text + chr(10) * 2 + schema_text + chr(10) * 2
        + f"The failed task ({reason}):" + chr(10) + json.dumps(failed, indent=1) + chr(10)
        + f"What the engineer did last: {recent or 'see the files in the project'}" + chr(10) * 2
        + f"New ids to use: t{first_new_id}, t{first_new_id + 1}, ... Reply with only the replacement task(s)."
    )
    system = (PROMPTS_DIR / "replanner.md").read_text(encoding="utf-8").replace("{name}", agent.name).replace("{role}", agent.role)

    def check(p: PlannerOutput) -> list[str]:
        problems = [] if p.tasks else ["no tasks"]
        ids = {t.id for t in p.tasks}
        files = [f for t in p.tasks for f in t.files]
        if len(files) != len(set(files)):
            problems.append("a file appears in more than one task; every file belongs to exactly one task")
        if sorted(files) != sorted(failed["files"]) and len(failed["files"]) == 1:
            problems.append(f"the task must still create exactly {failed['files']}")
        for t in p.tasks:
            problems += check_acceptance(t)
            if t.owner != failed["owner"]:
                problems.append(f"{t.id}: the owner must stay {failed['owner']}")
            if t.id == failed["id"] or t.id in (failed.get("depends_on") or []):
                problems.append(f"{t.id}: use a new id")
            problems += [f"{t.id}: depends on unknown {d}" for d in t.depends_on if d not in ids and d not in failed.get("depends_on", [])]
        return problems

    return structured_step(agent, llm, model_id, system, user, PlannerOutput, check, emit)


def run_amendment(agent, llm, model_id, request: str, sender: str, contract_text: str, emit):
    """Only the Architect decides on contract changes."""
    user = (
        f"{sender} asks for a change to the API contract:\n\"{request}\"\n\nCurrent contract:\n{contract_text}\n\n"
        "Decide. Approve only if the change is necessary and small. If approved, return the COMPLETE new endpoint list "
        "(unchanged endpoints included, exactly as before). If denied, return an empty endpoint list and explain why."
    )

    def check(a: AmendOutput) -> list[str]:
        if a.approve and not a.endpoints:
            return ["approved but the endpoint list is empty"]
        return check_architecture_endpoints(a.endpoints) if a.approve else []

    return structured_step(agent, llm, model_id, role_prompt(agent), user, AmendOutput, check, emit)


def check_architecture_endpoints(endpoints: list[Endpoint]) -> list[str]:
    dummy = ArchitectOutput(preset="x", architecture="x", endpoints=endpoints, ui_features=["x"])
    return [p for p in check_architecture(dummy, ["x"])]
