"""Benchmark results (CLAUDE.md section 8): role x model, in SQLite plus the pre-recorded results shipped with the repo.

The benchmark runner (`backend/benchmarks`) writes rows to SQLite and can export them to `backend/benchmarks/results.json`. That file is
committed, so the leaderboard and the router have real numbers on a fresh checkout. Per (role, model) cell, runs from the local database
replace the shipped runs (a re-run on this machine wins); cells without local runs use the shipped ones.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from sqlalchemy import Boolean, Column, Float, Integer, MetaData, String, Table, create_engine, insert, select

from .config import ROOT

SHIPPED_RESULTS = ROOT / "backend" / "benchmarks" / "results.json"

_meta = MetaData()
_runs = Table(
    "benchmark_runs", _meta,
    Column("id", Integer, primary_key=True),
    Column("ts", Integer), Column("model", String), Column("role", String), Column("task", String),
    Column("passed", Boolean), Column("iterations", Integer), Column("seconds", Float),
    Column("tokens", Integer), Column("peak_vram_gb", Float),
)


class Leaderboard:
    def __init__(self, db_path: Path, shipped: Path | None = SHIPPED_RESULTS):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        self._lock = threading.Lock()
        self._shipped_path = shipped
        _meta.create_all(self._engine)

    def record(self, model: str, role: str, task: str, passed: bool, iterations: int = 0, seconds: float = 0.0,
               tokens: int = 0, peak_vram_gb: float = 0.0) -> None:
        with self._lock, self._engine.begin() as c:
            c.execute(insert(_runs).values(ts=int(time.time()), model=model, role=role, task=task, passed=passed,
                                           iterations=iterations, seconds=seconds, tokens=tokens, peak_vram_gb=peak_vram_gb))

    def rows(self) -> list[dict]:
        """Runs in the local database."""
        with self._lock, self._engine.begin() as c:
            return [dict(r) for r in c.execute(select(_runs).order_by(_runs.c.id)).mappings().all()]

    def shipped(self) -> list[dict]:
        """The pre-recorded runs committed with the repo (empty if the file is missing or unreadable)."""
        if not self._shipped_path or not Path(self._shipped_path).is_file():
            return []
        try:
            data = json.loads(Path(self._shipped_path).read_text(encoding="utf-8"))
            return [r for r in data.get("runs", []) if {"model", "role", "task", "passed"} <= set(r)]
        except (OSError, ValueError, AttributeError):
            return []

    def meta(self) -> dict:
        try:
            data = json.loads(Path(self._shipped_path).read_text(encoding="utf-8")) if self._shipped_path else {}
            return {k: data[k] for k in ("generated", "machine", "notes") if k in data}
        except (OSError, ValueError, TypeError):
            return {}

    def effective_rows(self) -> list[dict]:
        local = self.rows()
        have = {(r["role"], r["model"]) for r in local}
        return [{**r, "source": "live"} for r in local] + [{**r, "source": "shipped"} for r in self.shipped() if (r["role"], r["model"]) not in have]

    def export(self, path: Path = SHIPPED_RESULTS, machine: str = "", notes: str = "") -> int:
        """Write the effective rows as the shipped results file. Returns the number of runs."""
        runs = [{k: (round(r.get(k, 0), 1) if k == "seconds" else r.get(k, 0)) for k in ("model", "role", "task", "passed", "iterations", "seconds", "tokens", "peak_vram_gb")}
                for r in self.effective_rows()]
        Path(path).write_text(json.dumps({"generated": time.strftime("%Y-%m-%d"), "machine": machine, "notes": notes, "runs": runs}, indent=1) + "\n", encoding="utf-8")
        return len(runs)

    def summary(self) -> dict:
        """Role x model matrix of averaged results, plus the raw run count."""
        runs = self.effective_rows()
        cells: dict[tuple[str, str], list[dict]] = {}
        for r in runs:
            cells.setdefault((r["role"], r["model"]), []).append(r)
        matrix: dict[str, dict[str, dict]] = {}
        for (role, model), rs in cells.items():
            n = len(rs)
            secs = sum(r["seconds"] for r in rs)
            toks = sum(r["tokens"] for r in rs)  # prompt + generated tokens processed (not a generation speed: that is in the Models table)
            matrix.setdefault(role, {})[model] = {
                "runs": n, "passed": sum(1 for r in rs if r["passed"]), "pass_rate": round(sum(1 for r in rs if r["passed"]) / n, 3),
                "avg_iterations": round(sum(r["iterations"] for r in rs) / n, 1), "avg_seconds": round(secs / n, 1),
                "avg_tokens": round(toks / n),
                "peak_vram_gb": round(max(r["peak_vram_gb"] for r in rs), 2), "source": rs[0]["source"],
                "tasks": [{"task": r["task"], "passed": bool(r["passed"]), "iterations": r["iterations"], "seconds": round(r["seconds"], 1)} for r in rs],
            }
        return {"runs": len(runs), "roles": sorted(matrix), "models": sorted({m for r in matrix.values() for m in r}), "matrix": matrix, **self.meta()}
