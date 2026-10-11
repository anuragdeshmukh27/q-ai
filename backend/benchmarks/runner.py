"""Runs the benchmark tasks for a list of models and records every run (model, role, pass, iterations, time, tokens, peak VRAM) in SQLite."""
from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config import WORKSPACE
from app.leaderboard import Leaderboard
from app.llm import LLMClient
from app.metrics import read_metrics
from app.registry import ModelRegistry
from app.scheduler import HttpOllamaControl, ModelScheduler

from .tasks import Ctx, Outcome, Task, all_tasks


class VramPeak:
    """Samples GPU memory while a task runs. The peak is reported relative to the idle baseline, i.e. what the model and its context cost."""

    def __init__(self, baseline_gb: float):
        self.baseline, self.peak = baseline_gb, baseline_gb
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            gpu = read_metrics().get("gpu")
            if gpu:
                self.peak = max(self.peak, gpu["used_gb"])
            self._stop.wait(0.7)

    def __enter__(self) -> "VramPeak":
        self._t.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._t.join(2)

    @property
    def gb(self) -> float:
        return round(max(0.0, self.peak - self.baseline), 2)


@dataclass
class RunRecord:
    model: str
    role: str
    task: str
    outcome: Outcome
    seconds: float
    peak_vram_gb: float


def unload_everything(control: HttpOllamaControl) -> None:
    for p in control.ps():
        control.unload(p["name"])
    end = time.time() + 15
    while control.ps() and time.time() < end:
        time.sleep(0.5)
    time.sleep(1.0)


TASK_TIMEOUT = 600  # seconds: a task that runs longer is stopped and recorded as a failed run ("timeout")


def run_with_timeout(task: Task, ctx: Ctx, timeout: float = TASK_TIMEOUT) -> Outcome:
    """Runs one task in a thread. Past the limit the task is asked to stop (a build's stop button) and the run is a failure; the GPU is only handed on after it stopped."""
    box: dict[str, Outcome] = {}

    def target() -> None:
        try:
            box["o"] = task.run(ctx)
        except Exception as e:  # a crash is a failed run, never a crashed benchmark
            box["o"] = Outcome(False, 0, 0, f"crashed: {type(e).__name__}: {str(e)[:160]}")

    t = threading.Thread(target=target, daemon=True, name=f"bench-{task.id}")
    t.start()
    t.join(timeout)
    if not t.is_alive():
        return box["o"]
    for stop in ctx.stoppers:
        try:
            stop()
        except Exception:
            pass
    t.join(300)  # at most one request still in flight
    return Outcome(False, 0, 0, f"timeout: still running after {round(timeout / 60)} minutes" + ("" if not t.is_alive() else " (and did not stop)"))


def run_benchmarks(model_ids: list[str], roles: list[str] | None, board: Leaderboard, reps: int | None = None,
                   log: Callable[[str], None] = print, workroot: Path | None = None, only: list[str] | None = None, timeout: float = TASK_TIMEOUT) -> list[RunRecord]:
    registry = ModelRegistry.load(env={})  # local models only: the leaderboard is the local-first story
    control = HttpOllamaControl()
    llm = LLMClient(registry, scheduler=ModelScheduler(registry, control))
    tasks: list[Task] = [t for t in all_tasks() if (not roles or t.role in roles) and (not only or t.id in only)]
    workroot = workroot or WORKSPACE / "_bench"
    out: list[RunRecord] = []
    for mid in model_ids:
        model = registry.get(mid)
        unload_everything(control)
        gpu = read_metrics().get("gpu")
        baseline = gpu["used_gb"] if gpu else 0.0
        log(f"== {model.name} (idle GPU {baseline:.2f} GB)")
        for task in tasks:
            for rep in range(1, (reps or task.reps) + 1):
                work = workroot / f"{mid}-{task.id}-{rep}"
                shutil.rmtree(work, ignore_errors=True)
                work.mkdir(parents=True, exist_ok=True)
                t0 = time.time()
                with VramPeak(baseline) as peak:
                    o = run_with_timeout(task, Ctx(model, registry, llm, work), timeout)
                secs = time.time() - t0
                board.record(mid, task.role, task.id, o.passed, o.iterations, secs, o.tokens, peak.gb)
                out.append(RunRecord(mid, task.role, task.id, o, secs, peak.gb))
                log(f"  {task.role:9} {task.id:28} {'PASS' if o.passed else 'FAIL'}  {secs:6.1f}s  it={o.iterations:<2} tok={o.tokens:<6} vram={peak.gb:.2f}  {o.detail[:110]}")
                shutil.rmtree(work, ignore_errors=True)
    unload_everything(control)  # a spilled 14b/32b must not stay in RAM when the benchmark is over
    return out
