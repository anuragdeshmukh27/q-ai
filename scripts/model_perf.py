"""Measure a local model on this machine: load time, generation speed at num_ctx 8192, GPU memory and RAM it takes.

    backend\\.venv\\Scripts\\python.exe scripts\\model_perf.py qwen2.5-coder:14b [more names] [--out backend/benchmarks/model_perf.json]

One model at a time (everything is unloaded first and again afterwards). Ollama reports how the model was split in /api/ps: `size_vram` is the part on
the GPU, the rest of `size` lives in system RAM (partial offload). Speeds come from Ollama's own eval counters, not wall clock.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.metrics import read_metrics  # noqa: E402

HOST = "http://localhost:11434"
GB = 1024 ** 3
PROMPT = ("Write a Python function `parse_duration(text)` that turns strings like '1h30m', '45s' and '2d4h' into a number of seconds, "
          "raise ValueError for anything else, and then write five pytest tests for it. Explain each test in one sentence.")
RUNS = 3  # first run is the warm-up and is reported separately


def ps() -> list[dict]:
    return httpx.get(f"{HOST}/api/ps", timeout=10).json().get("models", [])


def unload_all() -> None:
    for m in ps():
        httpx.post(f"{HOST}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60)
    end = time.time() + 40
    while ps() and time.time() < end:
        time.sleep(0.5)
    time.sleep(2)


def ram_used_gb() -> float:
    vm = psutil.virtual_memory()
    return (vm.total - vm.available) / GB


def measure(name: str, num_ctx: int = 8192) -> dict:
    unload_all()
    gpu0 = read_metrics()["gpu"]["used_gb"]
    ram0 = ram_used_gb()
    t0 = time.time()
    r = httpx.post(f"{HOST}/api/generate", json={"model": name, "keep_alive": "5m", "options": {"num_ctx": num_ctx}}, timeout=600)
    r.raise_for_status()
    load_s = time.time() - t0
    time.sleep(2)
    loaded = next(m for m in ps() if m["name"].startswith(name.split(":")[0]) and name.split(":")[1] in m["name"])
    gpu1 = read_metrics()["gpu"]["used_gb"]
    ram1 = ram_used_gb()
    runs = []
    for i in range(RUNS):
        body = {"model": name, "stream": False, "keep_alive": "5m", "think": False,
                "messages": [{"role": "user", "content": PROMPT}], "options": {"num_ctx": num_ctx, "temperature": 0.2, "num_predict": 200}}
        t = time.time()
        d = httpx.post(f"{HOST}/api/chat", json=body, timeout=600).json()
        wall = time.time() - t
        runs.append({"gen_tok_s": round(d["eval_count"] / (d["eval_duration"] / 1e9), 2), "prompt_tok_s": round(d["prompt_eval_count"] / max(d["prompt_eval_duration"], 1) * 1e9, 1),
                     "tokens": d["eval_count"], "wall_s": round(wall, 1)})
        print(f"  run {i + 1}: {runs[-1]}", flush=True)
    gpu2 = read_metrics()["gpu"]["used_gb"]
    ram2 = ram_used_gb()
    good = runs[1:] or runs
    out = {
        "model": name, "num_ctx": num_ctx, "load_s": round(load_s, 1), "ollama_size_gb": round(loaded["size"] / GB, 2),
        "size_vram_gb": round(loaded["size_vram"] / GB, 2), "size_ram_gb": round((loaded["size"] - loaded["size_vram"]) / GB, 2),
        "gpu_used_delta_gb": round(max(gpu1, gpu2) - gpu0, 2), "ram_used_delta_gb": round(max(ram1, ram2) - ram0, 2),
        "gen_tok_s": round(sum(r["gen_tok_s"] for r in good) / len(good), 2), "prompt_tok_s": round(sum(r["prompt_tok_s"] for r in good) / len(good), 1),
        "gpu_share_pct": round(100 * loaded["size_vram"] / loaded["size"]), "runs": runs, "idle_gpu_gb": gpu0, "idle_ram_gb": round(ram0, 1),
    }
    unload_all()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--out", default=str(ROOT / "backend" / "benchmarks" / "model_perf.json"))
    args = ap.parse_args()
    path = Path(args.out)
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"machine": "RTX 5070 Laptop 8 GB VRAM, 32 GB RAM, num_ctx 8192", "models": {}}
    for name in args.models:
        print(f"== {name}", flush=True)
        data["models"][name] = res = measure(name)
        print(json.dumps({k: v for k, v in res.items() if k != "runs"}), flush=True)
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
