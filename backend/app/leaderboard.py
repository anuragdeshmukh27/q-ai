"""Benchmark results in SQLite (CLAUDE.md section 8). The benchmark runner (P7) writes rows; the API and the router read them."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from sqlalchemy import Boolean, Column, Float, Integer, MetaData, String, Table, create_engine, insert, select

_meta = MetaData()
_runs = Table(
    "benchmark_runs", _meta,
    Column("id", Integer, primary_key=True),
    Column("ts", Integer), Column("model", String), Column("role", String), Column("task", String),
    Column("passed", Boolean), Column("iterations", Integer), Column("seconds", Float),
    Column("tokens", Integer), Column("peak_vram_gb", Float),
)


class Leaderboard:
    def __init__(self, db_path: Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        self._lock = threading.Lock()
        _meta.create_all(self._engine)

    def record(self, model: str, role: str, task: str, passed: bool, iterations: int = 0, seconds: float = 0.0,
               tokens: int = 0, peak_vram_gb: float = 0.0) -> None:
        with self._lock, self._engine.begin() as c:
            c.execute(insert(_runs).values(ts=int(time.time()), model=model, role=role, task=task, passed=passed,
                                           iterations=iterations, seconds=seconds, tokens=tokens, peak_vram_gb=peak_vram_gb))

    def rows(self) -> list[dict]:
        with self._lock, self._engine.begin() as c:
            return [dict(r) for r in c.execute(select(_runs).order_by(_runs.c.id)).mappings().all()]

    def summary(self) -> dict:
        """Role x model matrix of averaged results, plus the raw run count."""
        runs = self.rows()
        cells: dict[tuple[str, str], list[dict]] = {}
        for r in runs:
            cells.setdefault((r["role"], r["model"]), []).append(r)
        matrix: dict[str, dict[str, dict]] = {}
        for (role, model), rs in cells.items():
            n = len(rs)
            matrix.setdefault(role, {})[model] = {
                "runs": n, "pass_rate": round(sum(1 for r in rs if r["passed"]) / n, 3),
                "avg_iterations": round(sum(r["iterations"] for r in rs) / n, 1), "avg_seconds": round(sum(r["seconds"] for r in rs) / n, 1),
                "avg_tokens": round(sum(r["tokens"] for r in rs) / n), "peak_vram_gb": max(r["peak_vram_gb"] for r in rs),
            }
        return {"runs": len(runs), "roles": sorted(matrix), "models": sorted({m for r in matrix.values() for m in r}), "matrix": matrix}
