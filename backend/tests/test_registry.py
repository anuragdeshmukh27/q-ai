import pytest

from app.registry import ModelRegistry, ModelConfig, UnknownModel


def cfg(**kw):
    base = dict(id="m", provider="ollama", name="m:1b", capabilities=["coding"], num_ctx=8192, vram_gb=2, enabled=True)
    base.update(kw)
    return ModelConfig(**base)


def test_real_config_gemini_models(monkeypatch):
    reg = ModelRegistry.load(env={"GEMINI_API_KEY": "k"})
    g = reg.get("gemini-flash")
    assert g.name == "gemini-3.8-flash" and g.provider == "gemini" and g.fallback == "gemini-flash-lite"
    assert reg.get("gemini-flash-lite").name == "gemini-3.1-flash-lite"
    assert all("2.5" not in m.name for m in reg.models.values() if m.provider == "gemini")
    assert reg.is_available("gemini-flash") and reg.is_available("gemini-flash-lite")


def test_gemini_unavailable_without_key():
    reg = ModelRegistry.load(env={})
    assert not reg.is_available("gemini-flash")
    assert not reg.is_available("groq-llama")
    assert reg.is_available("qwen25-coder-7b")


def test_empty_key_counts_as_unset():
    assert not ModelRegistry.load(env={"GEMINI_API_KEY": "  "}).is_available("gemini-flash")


def test_disabled_flag_wins_over_key():
    reg = ModelRegistry([cfg(id="g", provider="gemini", enabled=False, requires_env="K")], env={"K": "x"})
    assert not reg.is_available("g")


def test_all_ollama_models_set_num_ctx_explicitly():
    reg = ModelRegistry.load(env={})
    for m in reg.models.values():
        if m.provider == "ollama":
            assert m.num_ctx >= 8192


def test_default_for_prefers_local():
    reg = ModelRegistry.load(env={"GEMINI_API_KEY": "k"})
    assert reg.default_for("coding").id == "qwen25-coder-7b"
    assert reg.default_for("review").provider == "ollama"


def test_default_for_falls_back_to_cloud_when_no_local_has_the_capability():
    reg = ModelRegistry([cfg(id="loc", capabilities=["review"]), cfg(id="cl", provider="gemini", capabilities=["coding"])], env={})
    assert reg.default_for("coding").id == "cl"


def test_default_for_none_available():
    with pytest.raises(UnknownModel):
        ModelRegistry([cfg(capabilities=["review"])], env={}).default_for("coding")


def test_fallback_chain_skips_unavailable_and_cycles():
    reg = ModelRegistry(
        [
            cfg(id="a", provider="gemini", requires_env="K", fallback="b"),
            cfg(id="b", provider="gemini", requires_env="K", fallback="c"),
            cfg(id="c", fallback="a"),
        ],
        env={"K": "x"},
    )
    assert [m.id for m in reg.chain("a")] == ["a", "b", "c"]
    reg2 = ModelRegistry(reg.models.values(), env={})
    assert [m.id for m in reg2.chain("c")] == ["c"]


def test_unknown_model():
    with pytest.raises(UnknownModel):
        ModelRegistry.load(env={}).get("nope")


def test_dev_single_model_and_keep_alive_load_from_yaml():
    r = ModelRegistry.load(env={})
    assert r.single_model == "qwen25-coder-7b" and r.keep_alive == "60m"
