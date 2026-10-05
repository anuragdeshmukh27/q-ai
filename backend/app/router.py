"""The model router: which model does each employee use?

Order of precedence, with the reason kept for the UI:
1. a manual override from the Employee inspector (handled by the caller, it never reaches the router);
2. a pin in `config/models.yaml` (`router.pins`): a human decision, with its reason;
3. benchmark evidence: another model replaces the safe default for a role only if it beat the default's pass rate by `margin`,
   with at least `min_runs` benchmark runs on both. Ties and thin evidence keep the safe default, because a model swap on an 8 GB GPU
   costs a model load and the default is the model every full build has been proven on;
4. the safe default (or, if it is unavailable, the registry's capability default).

The router therefore can only move a role away from the default on evidence, and a pin overrides the evidence when a full build shows it hurts.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .registry import ModelConfig, ModelRegistry

BENCHMARKED_ROLES = ("architect", "planner", "backend", "frontend", "database", "reviewer", "qa", "analyst", "finish")  # analyst and finish: Task C (finish an imported project)
DEFAULT_MARGIN = 0.1
DEFAULT_MIN_RUNS = 2


@dataclass
class Route:
    model: ModelConfig
    reason: str
    source: str  # pin | score | default


class Router:
    def __init__(self, registry: ModelRegistry, board=None, ttl: float = 3.0):
        self.registry, self.board, self.ttl = registry, board, ttl
        self._cache: tuple[float, dict] | None = None
        self._lock = threading.Lock()

    # -- configuration --------------------------------------------------------------
    @property
    def config(self) -> dict:
        return self.registry.router_config

    @property
    def margin(self) -> float:
        return float(self.config.get("margin", DEFAULT_MARGIN))

    @property
    def min_runs(self) -> int:
        return int(self.config.get("min_runs", DEFAULT_MIN_RUNS))

    def default_model(self, capability: str) -> ModelConfig:
        sd = self.config.get("safe_default")
        if sd and sd in self.registry.models and self.registry.is_available(sd):
            return self.registry.get(sd)
        return self.registry.default_for(capability)

    def _matrix(self) -> dict:
        if self.board is None:
            return {}
        with self._lock:
            now = time.monotonic()
            if self._cache is None or now - self._cache[0] >= self.ttl:
                try:
                    self._cache = (now, self.board.summary()["matrix"])
                except Exception:  # a broken results file must never stop a build
                    self._cache = (now, {})
            return self._cache[1]

    def refresh(self) -> None:
        with self._lock:
            self._cache = None

    # -- the decision ---------------------------------------------------------------
    def choose(self, agent_id: str, capability: str, local_only: bool = True) -> Route:
        default = self.default_model(capability)
        pin = (self.config.get("pins") or {}).get(agent_id)
        if pin and pin.get("model") in self.registry.models and self.registry.is_available(pin["model"]):
            m = self.registry.get(pin["model"])
            if not (local_only and not m.local):
                return Route(m, f"pinned: {pin.get('reason', 'set in config/models.yaml')}", "pin")
        cells = self._matrix().get(agent_id, {})
        base = cells.get(default.id)
        if not base or base["runs"] < self.min_runs:
            return Route(default, "safe default: not enough benchmark runs for this role" if cells else "safe default: no benchmark data for this role", "default")
        best, best_cell = None, None
        for mid, cell in cells.items():
            if mid == default.id or cell["runs"] < self.min_runs or mid not in self.registry.models or not self.registry.is_available(mid):
                continue
            m = self.registry.get(mid)
            if local_only and not m.local:
                continue
            if best_cell is None or (cell["pass_rate"], -cell["avg_seconds"]) > (best_cell["pass_rate"], -best_cell["avg_seconds"]):
                best, best_cell = m, cell
        if best is not None and best_cell["pass_rate"] >= base["pass_rate"] + self.margin:
            return Route(best, f"benchmark: {best.name} passes {_pct(best_cell)} vs {default.name} {_pct(base)} "
                               f"(needs +{round(self.margin * 100)} points to switch)", "score")
        if best is not None:
            return Route(default, f"safe default: best challenger {best.name} {_pct(best_cell)} does not beat {default.name} {_pct(base)} by "
                                  f"{round(self.margin * 100)} points (a model swap costs a load)", "default")
        return Route(default, f"safe default: {_pct(base)} on {base['runs']} runs and no other model has enough runs", "default")

    def table(self, agent_ids: list[str], capabilities: dict[str, str]) -> list[dict]:
        """One row per employee for the leaderboard: the model the router would pick now and why."""
        rows = []
        for a in agent_ids:
            r = self.choose(a, capabilities.get(a, "coding"))
            rows.append({"agent": a, "model": r.model.id, "model_name": r.model.name, "source": r.source, "reason": r.reason})
        return rows


def _pct(cell: dict) -> str:
    return f"{round(cell['pass_rate'] * 100)}% ({cell['passed']}/{cell['runs']})"
