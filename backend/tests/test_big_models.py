"""Partially offloaded models (qwen2.5-coder 14b/32b): budget on VRAM plus RAM, never two big models, nothing next to a resident big one, released when done."""
from app.events import EventBus
from app.registry import ModelConfig, ModelRegistry
from app.scheduler import ModelScheduler

GB = 1024 ** 3


def reg():
    mk = lambda i, n, v, r=0.0: ModelConfig(id=i, provider="ollama", name=n, vram_gb=v, ram_gb=r)  # noqa: E731
    return ModelRegistry([mk("small", "small:4b", 3.6), mk("tiny", "tiny:3b", 2.5), mk("mid", "mid:14b", 5.7, 4.3), mk("huge", "huge:32b", 6.5, 13.5)], env={})


class Ollama:
    def __init__(self, registry, loaded=()):
        self.registry, self.calls, self.loaded = registry, [], {}
        for n in loaded:
            self._add(n)

    def _add(self, name):
        m = next(x for x in self.registry.models.values() if x.name == name)
        self.loaded[name] = (m.vram_gb, m.vram_gb + m.ram_gb)

    def ps(self):
        return [{"name": n, "size_vram": int(v * GB), "size": int(t * GB)} for n, (v, t) in self.loaded.items()]

    def load(self, name, num_ctx, keep_alive):
        self.calls.append(("load", name, keep_alive))
        self._add(name)

    def unload(self, name):
        self.calls.append(("unload", name))
        self.loaded.pop(name, None)


def make(loaded=(), ram_total=32.0, ram_used=16.0):
    r = reg()
    o = Ollama(r, loaded)
    bus = EventBus()
    s = ModelScheduler(r, o, bus.emit, headroom_gb=1.0, total_gb=lambda: 8.0, used_gb=lambda: 0.0, ram_headroom_gb=6.0,
                       ram_total_gb=lambda: ram_total, ram_used_gb=lambda: ram_used)
    return r, o, s, bus


def test_a_big_model_unloads_everything_first_even_if_a_small_one_would_fit():
    r, o, s, _ = make(["tiny:3b"])
    with s.slot(r.get("mid"), "reviewer"):
        pass
    assert o.calls == [("unload", "tiny:3b"), ("load", "mid:14b", r.keep_alive)]


def test_nothing_is_loaded_next_to_a_resident_big_model():
    r, o, s, _ = make(["mid:14b"])
    with s.slot(r.get("tiny"), "qa"):  # 5.7 + 2.5 = 8.2 > 7, but even a tiny one would be refused room beside a spilled model
        pass
    assert o.calls[0] == ("unload", "mid:14b") and o.calls[-1][:2] == ("load", "tiny:3b")


def test_two_big_models_are_never_resident_together():
    r, o, s, _ = make(["mid:14b"])
    with s.slot(r.get("huge"), "architect"):
        pass
    assert ("unload", "mid:14b") in o.calls and list(o.loaded) == ["huge:32b"]


def test_a_big_model_uses_its_own_keep_alive():
    r = reg()
    r.models["mid"].keep_alive = "5m"
    o = Ollama(r)
    s = ModelScheduler(r, o, EventBus().emit, total_gb=lambda: 8.0, used_gb=lambda: 0.0, ram_total_gb=lambda: 32.0, ram_used_gb=lambda: 10.0)
    with s.slot(r.get("mid"), "backend"):
        pass
    assert o.calls == [("load", "mid:14b", "5m")]


def test_a_big_model_that_exceeds_vram_plus_free_ram_loads_anyway_with_a_warning():
    r, o, s, bus = make(ram_used=26.0)  # 32 total, 26 used: 0 GB of RAM budget; 7 GB of VRAM budget; 20 GB needed
    with s.slot(r.get("huge"), "architect"):
        pass
    assert ("load", "huge:32b") == o.calls[0][:2]
    warn = [e for e in bus.history if e["type"] == "memory_pressure"]
    assert warn and warn[0]["need_gb"] == 20.0


def test_a_big_model_that_fits_the_budget_raises_no_warning():
    r, o, s, bus = make(ram_used=14.0)  # 12 GB of RAM budget (32 - max(6, 14)... = 18) + 7 GB of VRAM
    with s.slot(r.get("huge"), "architect"):
        pass
    assert not [e for e in bus.history if e["type"] == "memory_pressure"]


def test_the_ram_budget_is_total_minus_headroom_or_minus_what_the_rest_of_the_machine_holds():
    _, _, s, _ = make(ram_total=32.0, ram_used=3.0)
    assert s.ram_budget_gb() == 26.0
    _, _, s, _ = make(ram_total=32.0, ram_used=20.0)
    assert s.ram_budget_gb() == 12.0
    assert s.ram_budget_gb(ollama_ram_gb=10.0) == 22.0  # 10 of the 20 are the model's own


def test_release_big_unloads_the_big_model_only_and_only_when_idle():
    r, o, s, bus = make(["mid:14b"])
    with s.slot(r.get("mid"), "backend"):
        assert s.release_big() == []  # a call is running
    assert s.release_big() == ["mid:14b"] and o.loaded == {}
    assert [e["reason"] for e in bus.history if e["type"] == "model_unloaded"] == ["the work is done"]
    r, o, s, _ = make(["small:4b"])
    assert s.release_big() == [] and o.calls == []


def test_a_small_model_swap_still_works_as_before():
    r, o, s, _ = make(["small:4b"])
    with s.slot(r.get("tiny"), "qa"):  # 3.6 + 2.5 fits in 7 GB
        pass
    assert o.calls == [("load", "tiny:3b", r.keep_alive)]
