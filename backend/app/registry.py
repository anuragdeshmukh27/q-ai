"""Model registry loaded from config/models.yaml."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Mapping

import yaml
from pydantic import BaseModel, Field

from .config import CONFIG_DIR


class UnknownModel(Exception):
    pass


class ModelConfig(BaseModel):
    id: str
    provider: str  # ollama | gemini | openai_compat
    name: str
    capabilities: list[str] = Field(default_factory=list)
    num_ctx: int = 8192
    vram_gb: float = 0
    enabled: bool = True
    requires_env: str | None = None
    fallback: str | None = None

    @property
    def local(self) -> bool:
        return self.provider == "ollama"


class ModelRegistry:
    def __init__(self, models: Iterable[ModelConfig], env: Mapping[str, str] | None = None, keep_alive: str = "10m",
                 router: Mapping | None = None):
        self.models: dict[str, ModelConfig] = {m.id: m for m in models}
        self.env = os.environ if env is None else env
        self.keep_alive = keep_alive
        self.router_config: dict = dict(router or {})  # the `router:` section of models.yaml (see router.py)

    @classmethod
    def load(cls, path: Path | None = None, env: Mapping[str, str] | None = None) -> "ModelRegistry":
        data = yaml.safe_load((path or CONFIG_DIR / "models.yaml").read_text(encoding="utf-8"))
        return cls([ModelConfig(**m) for m in data["models"]], env, data.get("keep_alive", "10m"), data.get("router"))

    def get(self, model_id: str) -> ModelConfig:
        try:
            return self.models[model_id]
        except KeyError:
            raise UnknownModel(f"unknown model: {model_id}") from None

    def is_available(self, model_id: str) -> bool:
        """Enabled in the config and, for cloud models, its API key is set."""
        m = self.get(model_id)
        if not m.enabled:
            return False
        return not m.requires_env or bool(self.env.get(m.requires_env, "").strip())

    def available(self) -> list[ModelConfig]:
        return [m for m in self.models.values() if self.is_available(m.id)]

    def default_for(self, capability: str) -> ModelConfig:
        """Local first (the pitch), cloud only if no local model has the capability."""
        cands = [m for m in self.available() if capability in m.capabilities]
        if not cands:
            raise UnknownModel(f"no available model with capability '{capability}'")
        return sorted(cands, key=lambda m: not m.local)[0]

    def chain(self, model_id: str) -> list[ModelConfig]:
        """The model followed by its fallbacks, skipping unavailable ones."""
        out, seen, cur = [], set(), model_id
        while cur and cur not in seen:
            seen.add(cur)
            m = self.get(cur)
            if self.is_available(cur):
                out.append(m)
            cur = m.fallback
        return out
