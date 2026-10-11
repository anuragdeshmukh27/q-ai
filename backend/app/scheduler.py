"""VRAM-aware model scheduler (CLAUDE.md section 8).

Every local LLM call goes through `slot(model, agent)`. The scheduler keeps the GPU inside a VRAM budget (total memory from nvidia-smi
minus ~1 GB headroom) and runs ONE model at a time unless two fit together:

- a call for a model that is not loaded unloads idle models (`keep_alive: 0`) until the new one fits, then loads it
  (the agent shows "coffee break" while that happens: `agent_state loading_model`);
- a call for a model while a DIFFERENT model is still answering other requests waits its turn (the agent shows `sleeping`);
- loads and unloads are announced as `model_loaded` / `model_unloaded`, and `metrics` events carry VRAM, RAM, loaded models and tokens/s.

Loaded models are read from Ollama's `/api/ps`, so the scheduler also sees models that something else loaded. Cloud models are not scheduled.

Partial offload: a model with `ram_gb` > 0 (qwen2.5-coder 14b/32b) does not fit the 8 GB GPU; Ollama keeps its first layers on the GPU and the rest in system
RAM. Such a "big" model is budgeted on VRAM plus RAM (total minus a RAM headroom for Windows and the build's own processes), always runs alone (everything else
is unloaded before it loads, and a big model that is resident is unloaded before any other model loads) and is released when the build is done (`release_big`),
with a short `keep_alive` as the backstop. One that cannot fit even alone is loaded anyway, with a `memory_pressure` warning: it will be slow, not wrong.
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
RAM_HEADROOM_GB = 6.0  # system RAM kept free for Windows, the browser, the editor and the build's own processes when a model spills into RAM
DEFAULT_TOTAL_GB = 8.0  # used only if nvidia-smi is unavailable
DEFAULT_RAM_GB = 16.0  # used only if psutil is unavailable
UNLOAD_WAIT = 20.0  # a 20 GB model takes a while to leave the GPU and RAM


class OllamaControl(Protocol):
    def ps(self) -> list[dict]: ...  # [{"name": "qwen2.5-coder:7b", "size_vram": bytes, "size": bytes (whole model; the rest of it is in RAM)}]
    def load(self, name: str, num_ctx: int, keep_alive: str) -> None: ...
    def unload(self, name: str) -> None: ...


class HttpOllamaControl:
    def __init__(self, host: str | None = None):
        self.host = (host or ollama_host()).rstrip("/")
        self.client = httpx.Client(timeout=httpx.Timeout(300, connect=5))

    def ps(self) -> list[dict]:
        try:
            r = self.client.get(f"{self.host}/api/ps", timeout=5)
            return [{"name": m.get("name") or m.get("model", ""), "size_vram": int(m.get("size_vram", 0)), "size": int(m.get("size", 0))} for m in r.json().get("models", [])]
        except (httpx.HTTPError, ValueError):
            return []

    def load(self, name: str, num_ctx: int, keep_alive: str) -> None:
        # the same num_ctx as the chat calls, otherwise Ollama reloads the model on the first real request
        self.client.post(f"{self.host}/api/generate", json={"model": name, "keep_alive": keep_alive, "options": {"num_ctx": num_ctx}}, timeout=600)

    def unload(self, name: str) -> None:
        self.client.post(f"{self.host}/api/generate", json={"model": name, "keep_alive": 0}, timeout=30)


def _same(a: str, b: str) -> bool:
    strip = lambda n: n[:-7] if n.endswith(":latest") else n  # noqa: E731
    return strip(a) == strip(b)


class ModelScheduler:
    def __init__(self, registry: ModelRegistry, control: OllamaControl | None = None, emit: Callable[..., object] | None = None,
                 headroom_gb: float = HEADROOM_GB, total_gb: Callable[[], float] | None = None, used_gb: Callable[[], float] | None = None,
                 ram_headroom_gb: float = RAM_HEADROOM_GB, ram_total_gb: Callable[[], float] | None = None, ram_used_gb: Callable[[], float] | None = None):
        self.registry = registry
        self.control = control or HttpOllamaControl()
        self.emit = emit  # set per session: scheduler events belong to the build being watched
        self.headroom_gb = headroom_gb
        self._total_gb = total_gb or self._gpu_total
        self._used_gb = used_gb or self._gpu_used
        self.ram_headroom_gb = ram_headroom_gb
        self._ram_total_gb = ram_total_gb or self._ram_total
        self._ram_used_gb = ram_used_gb or self._ram_used
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

    @staticmethod
    def _ram_total() -> float:
        ram = read_metrics().get("ram")
        return float(ram["total_gb"]) if ram else DEFAULT_RAM_GB

    @staticmethod
    def _ram_used() -> float:
        ram = read_metrics().get("ram")
        return float(ram["used_gb"]) if ram else 0.0

    def ram_budget_gb(self, ollama_ram_gb: float = 0.0) -> float:
        """System RAM a spilled model may use: total minus the headroom, or minus whatever the rest of the machine holds if that is more."""
        other = max(0.0, self._ram_used_gb() - ollama_ram_gb)
        return max(0.0, self._ram_total_gb() - max(self.ram_headroom_gb, other))

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
        return [{"id": m.id if m else p["name"], "name": p["name"], "vram_gb": round(p["size_vram"] / 1024 ** 3, 2), "ram_gb": round(self._ram_part(p), 2)} for m, p in self._resident()]

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

    @staticmethod
    def _gb(n: int) -> float:
        return n / 1024 ** 3

    @classmethod
    def _ram_part(cls, p: dict) -> float:
        """The part of a resident model that Ollama keeps in system RAM (0 when /api/ps does not say how big the whole model is)."""
        return max(0.0, cls._gb(p.get("size", 0) - p["size_vram"])) if p.get("size") else 0.0

    def _is_big(self, m: ModelConfig | None, p: dict) -> bool:
        return bool(m.big) if m is not None else self._ram_part(p) > 0.5

    def _make_ready(self, model: ModelConfig, agent: str | None) -> None:
        """Called with the lock held and no other model active: unload what does not fit, load `model` if it is not resident."""
        resident = self._resident()
        if any(m is not None and m.id == model.id for m, _ in resident):
            self._last_used[model.id] = time.monotonic()
            return
        used = sum(p["size_vram"] for _, p in resident) / 1024 ** 3
        used_ram = sum(self._ram_part(p) for _, p in resident)
        budget = self.budget_gb(used)
        ram_budget = self.ram_budget_gb(used_ram)
        # a big (partially offloaded) model is never loaded next to another model, and nothing is loaded next to a resident big one
        exclusive = model.big or any(self._is_big(m, p) for m, p in resident)
        # least recently used first; models we never used (or did not load) go first
        order = sorted(resident, key=lambda mp: self._last_used.get(mp[0].id, 0.0) if mp[0] else 0.0)
        unloaded = False
        for m, p in order:
            if not exclusive and used + model.vram_gb <= budget and used_ram + model.ram_gb <= ram_budget:
                break
            self.control.unload(p["name"])
            used -= p["size_vram"] / 1024 ** 3
            used_ram -= self._ram_part(p)
            unloaded = True
            self._tell("model_unloaded", model=m.id if m else p["name"], name=p["name"], reason=f"making room for {model.name}")
        if unloaded:
            self._wait_unloaded()
        if model.big:
            total_need = model.vram_gb + model.ram_gb
            if total_need > self.budget_gb() + self.ram_budget_gb():
                self._tell("memory_pressure", model=model.id, name=model.name, need_gb=round(total_need, 1),
                           budget_gb=round(self.budget_gb() + self.ram_budget_gb(), 1), note="more than VRAM plus free RAM: expect swapping and slow answers")
        if agent:
            self._tell("agent_state", agent=agent, state="loading_model")  # "coffee break"
        t0 = time.time()
        self._tell("model_loading", model=model.id, name=model.name, agent=agent or "")
        self.control.load(model.name, model.num_ctx, model.keep_alive or self.registry.keep_alive)
        self.swaps += 1
        self._tell("model_loaded", model=model.id, name=model.name, vram_gb=model.vram_gb, ram_gb=model.ram_gb, seconds=round(time.time() - t0, 1), agent=agent or "")
        self._tell("metrics", **self.snapshot())
        if agent:
            self._tell("agent_state", agent=agent, state="thinking")

    def release_big(self) -> list[str]:
        """Unload every partially offloaded model that nobody is using (a build or benchmark is done): they hold gigabytes of RAM the machine needs back."""
        gone = []
        with self._cv:
            if any(n > 0 for n in self._active.values()):
                return gone
            for m, p in self._resident():
                if self._is_big(m, p):
                    self.control.unload(p["name"])
                    gone.append(p["name"])
                    self._tell("model_unloaded", model=m.id if m else p["name"], name=p["name"], reason="the work is done")
            if gone:
                self._wait_unloaded()
        return gone

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
        return {"gpu": m.get("gpu"), "ram": m.get("ram"), "loaded": loaded, "ram_budget_gb": round(self.ram_budget_gb(sum(x.get("ram_gb", 0) for x in loaded)), 2), "budget_gb": round(self.budget_gb(sum(x["vram_gb"] for x in loaded)), 2),
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
