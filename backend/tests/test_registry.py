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


def test_keep_alive_and_router_section_load_from_yaml():
    r = ModelRegistry.load(env={})
    assert not hasattr(r, "single_model")  # the dev single-model switch is gone: the router chooses
    assert r.keep_alive == "60m"
    assert r.router_config["safe_default"] == "qwen25-coder-7b" and r.router_config["margin"] > 0


# -- a model that is not pulled in Ollama is never available ------------------------------------------------

PULLED = {"qwen2.5-coder:7b", "qwen3:4b", "llama3.2:3b"}


def with_probe(names, router=None):
    base = ModelRegistry.load(env={})
    reg = ModelRegistry(base.models.values(), env={}, router=router if router is not None else base.router_config)
    reg.installed_probe = lambda: names
    return reg


def test_a_local_model_that_is_not_pulled_is_unavailable():
    reg = with_probe(PULLED)
    assert reg.is_available("qwen25-coder-7b") and reg.is_available("qwen3-4b")
    assert not reg.is_available("qwen25-coder-14b") and not reg.is_available("qwen25-coder-32b")
    assert {m.id for m in reg.available() if m.local} == {"qwen25-coder-7b", "qwen3-4b", "llama32-3b"}
    assert [m.id for m in reg.chain("qwen25-coder-14b")] == []


def test_latest_tag_counts_as_the_same_model():
    reg = with_probe({"qwen2.5-coder:7b:latest", "qwen3:4b"})
    assert reg.is_available("qwen25-coder-7b")


def test_without_a_probe_or_when_ollama_cannot_be_asked_nothing_is_filtered():
    assert ModelRegistry.load(env={}).is_available("qwen25-coder-14b")
    assert with_probe(None).is_available("qwen25-coder-14b")  # Ollama unreachable and nothing known: do not hide models


def test_the_last_known_list_survives_an_unreachable_ollama(monkeypatch):
    answers = iter([PULLED, None])
    reg = with_probe(None)
    reg.installed_probe = lambda: next(answers)
    clock = [0.0]
    monkeypatch.setattr("app.registry.time.monotonic", lambda: clock[0])
    assert not reg.is_available("qwen25-coder-14b")
    clock[0] = 60.0  # the list has expired and Ollama does not answer
    assert not reg.is_available("qwen25-coder-14b") and reg.is_available("qwen25-coder-7b")


def test_a_model_pulled_later_is_picked_up_after_the_cache_expires(monkeypatch):
    pulled = set(PULLED)
    reg = with_probe(None)
    reg.installed_probe = lambda: set(pulled)
    clock = [0.0]
    monkeypatch.setattr("app.registry.time.monotonic", lambda: clock[0])
    assert not reg.is_available("qwen25-coder-14b")
    pulled.add("qwen2.5-coder:14b")
    assert not reg.is_available("qwen25-coder-14b")  # still cached
    clock[0] = 60.0
    assert reg.is_available("qwen25-coder-14b")


def test_the_router_never_routes_to_a_model_that_is_not_pulled(tmp_path):
    from app.leaderboard import Leaderboard
    from app.router import Router
    b = Leaderboard(tmp_path / "q.db", shipped=None)
    for model, passed in (("qwen25-coder-7b", 1), ("qwen25-coder-14b", 4)):  # 25% vs 100%: the margin rule picks the 14b ...
        for i in range(4):
            b.record(model, "reviewer", f"t{i}", i < passed, 3, 10.0, 400, 5.0)
    no_pins = {"safe_default": "qwen25-coder-7b", "margin": 0.1, "min_runs": 2, "pins": {}}
    assert Router(with_probe(PULLED | {"qwen2.5-coder:14b"}, no_pins), b).choose("reviewer", "review").model.id == "qwen25-coder-14b"
    assert Router(with_probe(PULLED, no_pins), b).choose("reviewer", "review").model.id == "qwen25-coder-7b"  # ... unless it is not installed
    pinned = {**no_pins, "pins": {"reviewer": {"model": "qwen25-coder-32b", "reason": "x"}}}
    assert Router(with_probe(PULLED, pinned), b).choose("reviewer", "review").model.id == "qwen25-coder-7b"  # a pin on a missing model is ignored
    assert Router(with_probe({"qwen3:4b"}, no_pins), b).choose("reviewer", "review").model.id == "qwen3-4b"  # the safe default itself is missing


def test_the_shipped_config_pins_the_backend_to_the_7b_and_routes_nothing_to_a_missing_model(tmp_path):
    from app.leaderboard import Leaderboard, SHIPPED_RESULTS
    from app.router import BENCHMARKED_ROLES, Router
    reg = with_probe(PULLED)
    pin = reg.router_config["pins"]["backend"]
    assert pin["model"] == "qwen25-coder-7b" and "14b not installed" in pin["reason"]
    router = Router(reg, Leaderboard(tmp_path / "q.db", shipped=SHIPPED_RESULTS))
    for role in BENCHMARKED_ROLES:
        assert reg.is_available(router.choose(role, "coding").model.id), role
    assert router.choose("backend", "coding").source == "pin"
