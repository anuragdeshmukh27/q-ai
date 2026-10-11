"""Model registry loaded from config/models.yaml."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Iterable, Mapping

import httpx
import yaml
from pydantic import BaseModel, Field

from .config import CONFIG_DIR, ollama_host

INSTALLED_TTL = 10.0  # seconds a list of pulled models is trusted: a model pulled mid-session is picked up soon


class UnknownModel(Exception):
    pass


def same_name(a: str, b: str) -> bool:
    """Ollama names a model with or without its `:latest` tag."""
    strip = lambda n: n[:-7] if n.endswith(":latest") else n  # noqa: E731
    return strip(a) == strip(b)


def ollama_installed_probe(host: str | None = None, client: httpx.Client | None = None) -> Callable[[], set[str] | None]:
    """A probe for `ModelRegistry.installed_probe`: the models Ollama has pulled (`/api/tags`), or None when it cannot be reached."""
    base = (host or ollama_host()).rstrip("/")

    def probe() -> set[str] | None:
        try:
            r = (client or httpx).get(f"{base}/api/tags", timeout=3)
            r.raise_for_status()
            return {m.get("name") or m.get("model", "") for m in r.json().get("models", [])}
        except (httpx.HTTPError, ValueError):
            return None

    return probe


class ModelConfig(BaseModel):
    id: str
    provider: str  # ollama | gemini | openai_compat
    name: str
    capabilities: list[str] = Field(default_factory=list)
    num_ctx: int = 8192
    vram_gb: float = 0  # GPU memory the model takes at its num_ctx
    ram_gb: float = 0  # partial offload: the part of the model that stays in system RAM (0 = fits in VRAM)
    keep_alive: str | None = None  # how long Ollama keeps THIS model after its last request (default: the registry's)
    enabled: bool = True
    requires_env: str | None = None
    fallback: str | None = None

    @property
    def local(self) -> bool:
        return self.provider == "ollama"

    @property
    def big(self) -> bool:
        """A local model that does not fit the GPU alone: its layers are split between VRAM and RAM, so it runs by itself."""
        return self.local and self.ram_gb > 0


class ModelRegistry:
    def __init__(self, models: Iterable[ModelConfig], env: Mapping[str, str] | None = None, keep_alive: str = "10m",
                 router: Mapping | None = None):
        self.models: dict[str, ModelConfig] = {m.id: m for m in models}
        self.env = os.environ if env is None else env
        self.keep_alive = keep_alive
        self.router_config: dict = dict(router or {})  # the `router:` section of models.yaml (see router.py)
        self.installed_probe: Callable[[], set[str] | None] | None = None  # names of the models Ollama has pulled; None = do not check (tests, replay)
        self._installed_cache: tuple[float, set[str] | None] | None = None

    @classmethod
    def load(cls, path: Path | None = None, env: Mapping[str, str] | None = None) -> "ModelRegistry":
        data = yaml.safe_load((path or CONFIG_DIR / "models.yaml").read_text(encoding="utf-8"))
        return cls([ModelConfig(**m) for m in data["models"]], env, data.get("keep_alive", "10m"), data.get("router"))

    def get(self, model_id: str) -> ModelConfig:
        try:
            return self.models[model_id]
        except KeyError:
            raise UnknownModel(f"unknown model: {model_id}") from None

    def _installed(self) -> set[str] | None:
        """Model names Ollama has pulled, cached for a few seconds; None when no probe is set or Ollama cannot be asked."""
        if self.installed_probe is None:
            return None
        now = time.monotonic()
        if self._installed_cache is None or now - self._installed_cache[0] >= INSTALLED_TTL:
            try:
                names = self.installed_probe()
            except Exception:
                names = None
            if names is None and self._installed_cache is not None:
                names = self._installed_cache[1]  # Ollama did not answer: keep what we knew
            self._installed_cache = (now, names)
        return self._installed_cache[1]

    def is_available(self, model_id: str) -> bool:
        """Enabled in the config, for cloud models its API key is set, and for local models it is pulled in Ollama (when that can be checked)."""
        m = self.get(model_id)
        if not m.enabled:
            return False
        if m.requires_env and not self.env.get(m.requires_env, "").strip():
            return False
        if m.local:
            installed = self._installed()
            if installed is not None and not any(same_name(m.name, n) for n in installed):
                return False
        return True

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
