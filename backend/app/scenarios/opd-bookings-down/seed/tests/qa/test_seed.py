"""Generated: the sample data loads into the finished schema (every row, every label, every rule). Do not edit; fix the database modules instead."""
import json
from pathlib import Path

from backend.seed import seed

ROOT = Path(__file__).resolve().parents[2]


def test_the_sample_data_loads_into_an_empty_database():
    expected = {t: len(rows) for t, rows in json.loads((ROOT / 'seed.json').read_text(encoding='utf-8')).items()}
    assert seed(force=True) == expected
