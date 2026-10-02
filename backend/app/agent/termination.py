"""Termination rules for the agent loop (CLAUDE.md section 5).

An agent stops when it hits max_iterations, when the same tests keep failing
(no improvement), when it repeats an identical action, or when the model keeps
producing invalid output. Each stop is an escalation, never a silent hang.
"""
from __future__ import annotations

from .actions import Action

MAX_ITERATIONS = "max_iterations"
NO_IMPROVEMENT = "no_improvement"
REPEATED_ACTION = "repeated_action"
INVALID_OUTPUT = "invalid_output"

REASON_TEXT = {
    MAX_ITERATIONS: "reached the iteration limit",
    NO_IMPROVEMENT: "the same tests kept failing for 3 test runs",
    REPEATED_ACTION: "repeated the same action 3 times in a row",
    INVALID_OUTPUT: "the model kept returning invalid output",
}


class TerminationTracker:
    def __init__(self, max_iterations: int = 8, no_improvement_window: int = 3, repeat_limit: int = 3, invalid_limit: int = 3):
        self.max_iterations = max_iterations
        self.window = no_improvement_window
        self.repeat_limit = repeat_limit
        self.invalid_limit = invalid_limit
        self.iterations = 0
        self._signatures: list[str] = []
        self._last_fp: str | None = None
        self._repeat = 0
        self._invalid = 0

    def record(self, action: Action, test_signature: str | None = None) -> None:
        """Record a completed iteration. `test_signature` is the failing-test set if tests ran ('' = passing)."""
        self.iterations += 1
        self._invalid = 0
        fp = action.fingerprint()
        self._repeat = self._repeat + 1 if fp == self._last_fp else 1
        self._last_fp = fp
        if test_signature is not None:
            self._signatures.append(test_signature)

    def record_failed(self) -> None:
        """An iteration whose model output was invalid even after the retry."""
        self.iterations += 1
        self._invalid += 1

    def repeat_warning(self) -> bool:
        return self._repeat == self.repeat_limit - 1

    def check(self) -> str | None:
        if self._repeat >= self.repeat_limit:
            return REPEATED_ACTION
        last = self._signatures[-self.window :]
        if len(last) == self.window and last[0] and len(set(last)) == 1:
            return NO_IMPROVEMENT
        if self._invalid >= self.invalid_limit:
            return INVALID_OUTPUT
        if self.iterations >= self.max_iterations:
            return MAX_ITERATIONS
        return None
