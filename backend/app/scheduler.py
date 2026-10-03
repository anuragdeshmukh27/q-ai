"""VRAM-aware model scheduler (CLAUDE.md section 8).

Every local LLM call goes through `slot(model, agent)`. The scheduler keeps the GPU inside a VRAM budget (total memory from nvidia-smi
minus ~1 GB headroom) and runs ONE model at a time unless two fit together:

- a call for a model that is not loaded unloads idle models (`keep_alive: 0`) until the new one fits, then loads it
  (the agent shows "coffee break" while that happens: `agent_state loading_model`);
- a call for a model while a DIFFERENT model is still answering other requests waits its turn (the agent shows `sleeping`);
- loads and unloads are announced as `model_loaded` / `model_unloaded`, and `metrics` events carry VRAM, RAM, loaded models and tokens/s.

Loaded models are read from Ollama's `/api/ps`, so the scheduler also sees models that something else loaded. Cloud models are not scheduled.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Callable, Protocol

import httpx

from .config import ollama_host
from .metrics import read_metrics
from .registry import ModelConfig, ModelRegistry

HEADROOM_GB = 1.0
DEFAULT_TOTAL_GB = 8.0  # used only if nvidia-smi is unavailable
UNLOAD_WAIT = 8.0


class OllamaControl(Protocol):
    def ps(self) -> list[dict]: ...  # [{"name": "qwen2.5-coder:7b", "size_vram": bytes}]
    def load(self, name: str, num_ctx: int, keep_alive: str) -> None: ...
    def unload(self, name: str) -> None: ...


class HttpOllamaControl:
    def __init__(self, host: str | None = None):
        self.host = (host or ollama_host()).rstrip("/")
        self.client = httpx.Client(timeout=httpx.Timeout(300, connect=5))

    def ps(self) -> list[dict]:
        try:
            r = self.client.get(f"{self.host}/api/ps", timeout=5)
            return [{"name": m.get("name") or m.get("model", ""), "size_vram": int(m.get("size_vram", 0))} for m in r.json().get("models", [])]
        except (httpx.HTTPError, ValueError):
            return []

    def load(self, name: str, num_ctx: int, keep_alive: str) -> None:
        # the same num_ctx as the chat calls, otherwise Ollama reloads the model on the first real request
        self.client.post(f"{self.host}/api/generate", json={"model": name, "keep_alive": keep_alive, "options": {"num_ctx": num_ctx}})

    def unload(self, name: str) -> None:
        self.client.post(f"{self.host}/api/generate", json={"model": name, "keep_alive": 0}, timeout=30)


def _same(a: str, b: str) -> bool:
    strip = lambda n: n[:-7] if n.endswith(":latest") else n  # noqa: E731
    return strip(a) == strip(b)


class ModelScheduler:
    def __init__(self, registry: ModelRegistry, control: OllamaControl | None = None, emit: Callable[..., object] | None = None,
                 headroom_gb: float = HEADROOM_GB, total_gb: Callable[[], float] | None = None, used_gb: Callable[[], float] | None = None):
        self.registry = registry
        self.control = control or HttpOllamaControl()
        self.emit = emit  # set per session: scheduler events belong to the build being watched
        self.headroom_gb = headroom_gb
        self._total_gb = total_gb or self._gpu_total
        self._used_gb = used_gb or self._gpu_used
        self._cv = threading.Condition()
        self._active: dict[str, int] = {}
        self._last_used: dict[str, float] = {}
        self._queue: list[tuple[int, str]] = []
        self._ticket = 0
        self.swaps = 0

    # -- budget ---------------------------------------------------------------------
    @staticmethod
    def _gpu_total() -> float:
        gpu = read_metrics().get("gpu")
        return float(gpu["total_gb"]) if gpu else DEFAULT_TOTAL_GB

    @staticmethod
    def _gpu_used() -> float:
        gpu = read_metrics().get("gpu")
        return float(gpu["used_gb"]) if gpu else 0.0

    def budget_gb(self, ollama_gb: float = 0.0) -> float:
        """What models may use: total GPU memory minus the headroom, or minus whatever other programs (the desktop) hold if that is more."""
        other = max(0.0, self._used_gb() - ollama_gb)
        return max(1.0, self._total_gb() - max(self.headroom_gb, other))

    def _tell(self, type: str, **data) -> None:
        if self.emit:
            try:
                self.emit(type, **data)
            except Exception:
                pass

    def _resident(self) -> list[tuple[ModelConfig | None, dict]]:
        """Models Ollama has loaded right now, matched to the registry where possible."""
        out = []
        for p in self.control.ps():
            m = next((x for x in self.registry.models.values() if x.local and _same(x.name, p["name"])), None)
            out.append((m, p))
        return out

    def loaded(self) -> list[dict]:
        return [{"id": m.id if m else p["name"], "name": p["name"], "vram_gb": round(p["size_vram"] / 1024 ** 3, 2)} for m, p in self._resident()]

    # -- the slot -------------------------------------------------------------------
    @contextmanager
    def slot(self, model: ModelConfig, agent: str | None = None):
        """Hold the GPU for one model call. Waits for a different busy model, makes room, loads the model, then runs the caller."""
        if not model.local:
            yield
            return
        slept = False
        with self._cv:
            ticket = self._ticket = self._ticket + 1
            self._queue.append((ticket, model.id))
            try:
                # First come, first served across models: a call may start when no OTHER model is busy and nobody who asked earlier for another
                # model is still waiting (otherwise a stream of calls for the loaded model would starve the one that needs a swap).
                while any(n > 0 for mid, n in self._active.items() if mid != model.id) or any(t < ticket and mid != model.id for t, mid in self._queue):
                    if not slept and agent:
                        self._tell("agent_state", agent=agent, state="sleeping")
                        slept = True
                    self._cv.wait(0.5)
            finally:
                self._queue.remove((ticket, model.id))
            self._active[model.id] = self._active.get(model.id, 0) + 1
            try:
                self._make_ready(model, agent)
            except BaseException:
                self._active[model.id] -= 1
                self._cv.notify_all()
                raise
        if slept and agent:
            self._tell("agent_state", agent=agent, state="thinking")
        try:
            yield
        finally:
            with self._cv:
                self._active[model.id] -= 1
                self._last_used[model.id] = time.monotonic()
                self._cv.notify_all()

    def _make_ready(self, model: ModelConfig, agent: str | None) -> None:
        """Called with the lock held and no other model active: unload what does not fit, load `model` if it is not resident."""
        resident = self._resident()
        if any(m is not None and m.id == model.id for m, _ in resident):
            self._last_used[model.id] = time.monotonic()
            return
        used = sum(p["size_vram"] for _, p in resident) / 1024 ** 3
        budget = self.budget_gb(used)
        # least recently used first; models we never used (or did not load) go first
        order = sorted(resident, key=lambda mp: self._last_used.get(mp[0].id, 0.0) if mp[0] else 0.0)
        unloaded = False
        for m, p in order:
            if used + model.vram_gb <= budget:
                break
            self.control.unload(p["name"])
            used -= p["size_vram"] / 1024 ** 3
            unloaded = True
            self._tell("model_unloaded", model=m.id if m else p["name"], name=p["name"], reason=f"making room for {model.name}")
        if unloaded:
            self._wait_unloaded()
        if agent:
            self._tell("agent_state", agent=agent, state="loading_model")  # "coffee break"
        t0 = time.time()
        self._tell("model_loading", model=model.id, name=model.name, agent=agent or "")
        self.control.load(model.name, model.num_ctx, self.registry.keep_alive)
        self.swaps += 1
        self._tell("model_loaded", model=model.id, name=model.name, vram_gb=model.vram_gb, seconds=round(time.time() - t0, 1), agent=agent or "")
        self._tell("metrics", **self.snapshot())
        if agent:
            self._tell("agent_state", agent=agent, state="thinking")

    def _wait_unloaded(self) -> None:
        end = time.time() + UNLOAD_WAIT
        while time.time() < end:
            if sum(p["size_vram"] for _, p in self._resident()) / 1024 ** 3 < 0.2:
                return
            time.sleep(0.25)

    # -- observability --------------------------------------------------------------
    def snapshot(self, tokens_per_s: float = 0.0) -> dict:
        m = read_metrics()
        loaded = self.loaded()
        return {"gpu": m.get("gpu"), "ram": m.get("ram"), "loaded": loaded, "budget_gb": round(self.budget_gb(sum(x["vram_gb"] for x in loaded)), 2),
                "active": sum(self._active.values()), "swaps": self.swaps, "tokens_per_s": round(tokens_per_s, 1)}


class MetricsSampler:
    """Emits a `metrics` event every `interval` seconds while a build runs (the UI gauges and the recording use them)."""

    def __init__(self, scheduler: ModelScheduler, emit: Callable[..., object], tps: Callable[[], float] = lambda: 0.0, interval: float = 2.0):
        self.scheduler, self.emit, self.tps, self.interval = scheduler, emit, tps, interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="metrics", daemon=True)

    def start(self) -> "MetricsSampler":
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.emit("metrics", **self.scheduler.snapshot(self.tps()))
            except Exception:
                pass
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
