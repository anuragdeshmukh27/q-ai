"""Machine gauges for the top bar: GPU memory (nvidia-smi), RAM (psutil). Never raises; missing data is None."""
from __future__ import annotations

import subprocess
import time

import psutil

_CACHE: dict = {"at": 0.0, "value": None}
_TTL = 1.0  # nvidia-smi is slow-ish (~50 ms); several browsers polling must not multiply that


def _gpu() -> dict | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=4, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        name, used, total = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
        return {"name": name, "used_gb": round(float(used) / 1024, 2), "total_gb": round(float(total) / 1024, 2)}
    except Exception:
        return None


def read_metrics() -> dict:
    now = time.monotonic()
    if _CACHE["value"] is not None and now - _CACHE["at"] < _TTL:
        return _CACHE["value"]
    vm = psutil.virtual_memory()
    value = {"gpu": _gpu(), "ram": {"used_gb": round((vm.total - vm.available) / 1024 ** 3, 1), "total_gb": round(vm.total / 1024 ** 3, 1)}}
    _CACHE.update(at=now, value=value)
    return value
