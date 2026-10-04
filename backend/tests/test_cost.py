"""The cost meter: tokens, cloud prices from config/pricing.yaml, GPU electricity from power samples."""
import json
from pathlib import Path

from app.cost import compute, energy_kwh, load_pricing, report_for_recording
from app.recording import load_recording

ROOT = Path(__file__).resolve().parents[2]
PRICING = {"inr_per_usd": 85, "electricity_inr_per_kwh": 8, "fallback_gpu_watts": 80,
           "models": [{"id": "a", "name": "A", "input": 4.0, "output": 20.0}, {"id": "b", "name": "B", "input": 0.1, "output": 0.5}]}


def samples(watts, step=2.0):
    return [{"type": "metrics", "ts": 1000 + i * step, "gpu": {"power_w": w}} for i, w in enumerate(watts)]


def test_electricity_is_the_integral_of_the_measured_power():
    kwh, avg, measured = energy_kwh(samples([100, 100, 100, 100, 100, 100]), 10, 60)  # 100 W for 10 s
    assert measured and abs(avg - 100) < 1e-6 and abs(kwh - 100 * 10 / 3_600_000) < 1e-9


def test_without_power_samples_the_estimate_is_flagged_and_uses_the_fallback_watts():
    kwh, avg, measured = energy_kwh([{"type": "metrics", "ts": 1, "gpu": {"name": "x"}}], 3600, 80)
    assert not measured and avg == 80 and abs(kwh - 0.08) < 1e-9


def test_cloud_cost_is_tokens_times_the_editable_prices_and_the_rupee_rate():
    c = compute(1_000_000, 1_000_000, 100, samples([80, 80]), PRICING)
    by = {x["id"]: x for x in c["cloud"]}
    assert by["a"]["usd"] == 24.0 and by["a"]["inr"] == 2040.0 and by["b"]["usd"] == 0.6
    assert c["total_tokens"] == 2_000_000 and c["electricity"]["inr"] == round(c["electricity"]["kwh"] * 8, 3)


def test_the_shipped_pricing_has_the_five_agreed_models_and_rates():
    p = load_pricing()
    assert p["inr_per_usd"] == 85 and p["electricity_inr_per_kwh"] == 8
    assert {m["name"]: (m["input"], m["output"]) for m in p["models"]} == {
        "Claude Opus 5.5": (4.0, 20.0), "GPT-6 Sol": (2.0, 10.0), "Gemini 3.1 Pro": (2.0, 12.0), "Gemini 3.8 Flash": (0.75, 3.75), "GPT-6 Luna": (0.1, 0.5)}


def test_a_recording_without_a_cost_report_gets_one_from_its_saved_model_answers():
    rec = load_recording(ROOT / "recordings", "instagram")
    ev = rec.events()
    assert ev[-1]["type"] == "project_done" and ev[-2]["type"] == "cost_report"
    exact = sum(json.loads(l).get("prompt_tokens", 0) + json.loads(l).get("completion_tokens", 0) for l in (rec.path / "llm.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())
    assert ev[-2]["total_tokens"] == exact > 0
    assert report_for_recording(rec.path, ev)["total_tokens"] == exact


def test_costs_endpoint_lists_every_recording():
    from fastapi.testclient import TestClient
    from app.main import create_app

    rows = TestClient(create_app()).get("/api/costs").json()["rows"]
    assert {r["name"] for r in rows} >= {"calculator-fault", "flagship", "instagram"} and all(r["total_tokens"] > 0 and len(r["cloud"]) == 5 for r in rows)
