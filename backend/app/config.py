"""Paths, environment and the agent roster."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
WORKSPACE = ROOT / "workspace"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_env() -> None:
    """Load .env (never overriding variables that are already set)."""
    load_dotenv(ROOT / ".env")


def ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


class AgentConfig(BaseModel):
    id: str
    name: str
    role: str
    model_capability: str
    system_prompt_file: str
    tools: list[str]
    owned_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    max_iterations: int = 8
    sprite: dict = Field(default_factory=dict)
    desk: list[int] = Field(default_factory=lambda: [0, 0])


def load_agents(path: Path | None = None) -> dict[str, AgentConfig]:
    data = yaml.safe_load((path or CONFIG_DIR / "agents.yaml").read_text(encoding="utf-8"))
    return {a["id"]: AgentConfig(**a) for a in data["agents"]}
