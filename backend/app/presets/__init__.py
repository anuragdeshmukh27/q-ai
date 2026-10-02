"""Stack presets for generated apps: a skeleton plus run and test commands."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

PRESETS_DIR = Path(__file__).resolve().parent
DEFAULT_PRESET = "fastapi-vanilla"


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    run_cmd: str  # contains {port}
    test_cmd: str
    health_path: str
    frontend_dir: str
    skeleton: Path


def load_preset(name: str = DEFAULT_PRESET) -> Preset:
    folder = PRESETS_DIR / name.replace("-", "_")
    meta_file = folder / "preset.yaml"
    if not meta_file.is_file():
        raise ValueError(f"unknown preset: {name}")
    meta = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
    return Preset(skeleton=folder / "skeleton", **meta)


def list_presets() -> list[str]:
    return sorted(p.parent.name.replace("_", "-") for p in PRESETS_DIR.glob("*/preset.yaml"))
