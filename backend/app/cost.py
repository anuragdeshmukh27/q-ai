"""The cost of a build: the tokens it used, what the same tokens would cost on cloud models (config/pricing.yaml), and the electricity the GPU used here.

Electricity comes from the GPU power samples (`gpu.power_w` in the `metrics` events, read from nvidia-smi) integrated over the build; a recording made before the
meter existed has no samples, so its electricity is estimated from the average draw measured in a live build and says so (`measured: false`).
Tokens are exact: the live count of the build, or the token counts saved with every recorded model answer.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .config import ROOT

PRICING_FILE = ROOT / "config" / "pricing.yaml"


def load_pricing(path: Path | None = None) -> dict:
    try:
        data = yaml.safe_load((path or PRICING_FILE).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    data.setdefault("inr_per_usd", 85)
    data.setdefault("electricity_inr_per_kwh", 8)
    data.setdefault("fallback_gpu_watts", 60)
    data.setdefault("models", [])
    return data


def energy_kwh(metrics: list[dict], seconds: float, fallback_watts: float) -> tuple[float, float, bool]:
    """(kWh, average watts, measured) from the power samples of the build; the fallback average over `seconds` when there are none."""
    pts = sorted((m["ts"], float(m["gpu"]["power_w"])) for m in metrics if isinstance(m.get("gpu"), dict) and m["gpu"].get("power_w") is not None and "ts" in m)
    if len(pts) >= 2 and pts[-1][0] > pts[0][0]:
        joules = sum((t2 - t1) * (w1 + w2) / 2 for (t1, w1), (t2, w2) in zip(pts, pts[1:]))
        span = pts[-1][0] - pts[0][0]
        return joules / 3_600_000, joules / span, True
    return fallback_watts * seconds / 3_600_000, fallback_watts, False


def compute(prompt_tokens: int, completion_tokens: int, seconds: float, metrics: list[dict], pricing: dict | None = None) -> dict:
    p = pricing or load_pricing()
    kwh, watts, measured = energy_kwh(metrics, seconds, float(p["fallback_gpu_watts"]))
    rate = float(p["inr_per_usd"])
    cloud = []
    for m in p["models"]:
        usd = prompt_tokens / 1e6 * float(m["input"]) + completion_tokens / 1e6 * float(m["output"])
        cloud.append({"id": m["id"], "name": m["name"], "usd": round(usd, 4), "inr": round(usd * rate, 2)})
    return {"prompt_tokens": int(prompt_tokens), "completion_tokens": int(completion_tokens), "total_tokens": int(prompt_tokens + completion_tokens), "seconds": round(seconds, 1),
            "electricity": {"kwh": round(kwh, 5), "inr": round(kwh * float(p["electricity_inr_per_kwh"]), 3), "avg_watts": round(watts, 1), "measured": measured},
            "cloud": cloud, "inr_per_usd": rate, "inr_per_kwh": float(p["electricity_inr_per_kwh"])}


def report_for_recording(path: Path, events: list[dict]) -> dict | None:
    """The cost report of a recording that has none: exact tokens from llm.jsonl, electricity measured if the metrics events carry power, else estimated."""
    prompt = completion = 0
    try:
        for line in (path / "llm.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                prompt += int(d.get("prompt_tokens") or 0)
                completion += int(d.get("completion_tokens") or 0)
    except (OSError, ValueError):
        return None
    if not prompt and not completion:
        return None
    seconds = float(sum(e.get("seconds") or 0 for e in events if e["type"] == "project_done"))  # a build and its Ask-employee request each end with a project_done
    return compute(prompt, completion, seconds, [e for e in events if e["type"] == "metrics"])
