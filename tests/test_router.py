# SPDX-License-Identifier: MIT

"""Tests for the provider router and semantic cache (mirrors internal/router)."""

import time

from dxrk.query import ROLE_USER, Message, Response, Usage
from dxrk.router import (
    Capability,
    CachingRouter,
    CacheStats,
    CostConfig,
    CostTracker,
    DEFAULT_COSTS,
    ProviderEntry,
    QueryResponse,
    Router,
    SemanticCache,
    Strategy,
    StrategyFirstAvailable,
    StrategyLowestCost,
    StrategyRoundRobin,
    cosine_sim,
    default_key_fn,
    join_messages,
    new_router,
    simple_embed,
)


class MockProvider:
    def __init__(self, name: str, fail: bool = False, cost: int = 0) -> None:
        self.name = name
        self.fail = fail
        self.cost = cost

    def generate(self, messages, tools):
        if self.fail:
            return None, f"{self.name} failed"
        return (
            Response(
                text=f"{self.name} response",
                usage=Usage(input_tokens=self.cost, output_tokens=self.cost),
            ),
            None,
        )


def entry(
    name: str, fail: bool = False, cost: int = 0, model: str = "gpt-4o-mini"
) -> ProviderEntry:
    return ProviderEntry(
        name=name, model=model, provider=MockProvider(name, fail, cost)
    )


def key_for_index(i: int) -> str:
    return "k" + chr(ord("0") + i)


def val_for_index(i: int) -> str:
    return "v" + chr(ord("0") + i)


def test_router_first_available() -> None:
    router = new_router([entry("fail", fail=True), entry("ok", model="gpt-4o")])
    resp, err = router.generate([], [])
    assert err is None
    assert resp is not None
    assert resp.text == "ok response"


def test_router_all_fail() -> None:
    router = new_router([entry("a", fail=True), entry("b", fail=True)])
    resp, err = router.generate([], [])
    assert resp is None
    assert err is not None
    assert err.startswith("all providers failed:")


def test_router_round_robin() -> None:
    router = new_router(
        [entry("a"), entry("b")],
        strategy=Strategy.ROUND_ROBIN,
    )
    resp1, err1 = router.generate([], [])
    resp2, err2 = router.generate([], [])
    assert err1 is None and err2 is None
    assert resp1 is not None and resp2 is not None
    assert resp1.text != resp2.text


def test_router_lowest_cost() -> None:
    router = new_router(
        [entry("cheap", cost=10), entry("expensive", cost=100, model="gpt-4o")],
        strategy=Strategy.LOWEST_COST,
    )
    resp, err = router.generate([], [])
    assert err is None
    assert resp is not None
    assert resp.text == "cheap response"


def test_router_add_provider() -> None:
    router = new_router([entry("first")])
    router.add_provider(entry("second"))
    assert len(router.providers) == 2


def test_router_empty_providers() -> None:
    router = new_router([])
    resp, err = router.generate([], [])
    assert resp is None
    assert err == "all providers failed: no providers"


def test_cost_tracker_total_and_reset() -> None:
    tracker = CostTracker()
    tracker.add("gpt-4o-mini", 1000, 500)
    assert tracker.total() > 0.0
    tracker.reset()
    assert tracker.total() == 0.0


def test_cost_tracker_unknown_model() -> None:
    tracker = CostTracker()
    tracker.add("unknown-model", 1000, 500)
    assert tracker.total() == 0.0


def test_semantic_cache_set_and_get() -> None:
    cache = SemanticCache()
    cache.set(
        "hello world", QueryResponse(text="hi there", input_tokens=10, output_tokens=5)
    )
    resp, ok = cache.get("hello world")
    assert ok
    assert resp.text == "hi there"


def test_semantic_cache_miss() -> None:
    cache = SemanticCache()
    resp, ok = cache.get("nonexistent")
    assert not ok
    assert resp.text == ""


def test_semantic_cache_ttl() -> None:
    cache = SemanticCache(ttl=1e-9)
    cache.set("key", QueryResponse(text="value"))
    time.sleep(1e-6)
    resp, ok = cache.get("key")
    assert not ok
    assert resp.text == ""


def test_semantic_cache_eviction() -> None:
    cache = SemanticCache(max_size=3)
    for i in range(5):
        cache.set(key_for_index(i), QueryResponse(text=val_for_index(i)))
    resp, ok = cache.get(key_for_index(0))
    assert not ok
    assert resp.text == ""


def test_semantic_cache_update_existing() -> None:
    cache = SemanticCache()
    cache.set("key", QueryResponse(text="old"))
    cache.set("key", QueryResponse(text="new"))
    resp, ok = cache.get("key")
    assert ok
    assert resp.text == "new"


def test_semantic_cache_invalidate() -> None:
    cache = SemanticCache()
    cache.set("key", QueryResponse(text="value"))
    cache.invalidate("key")
    resp, ok = cache.get("key")
    assert not ok


def test_semantic_cache_clear() -> None:
    cache = SemanticCache()
    cache.set("a", QueryResponse(text="1"))
    cache.set("b", QueryResponse(text="2"))
    cache.clear()
    assert cache.stats().size == 0


def test_semantic_cache_custom_key_fn() -> None:
    cache = SemanticCache(key_fn=lambda s: s[:5])
    cache.set("hello world", QueryResponse(text="1"))
    cache.set("hello there", QueryResponse(text="2"))
    assert cache.stats().size == 1


def test_semantic_cache_stats() -> None:
    cache = SemanticCache(max_size=500, ttl=600.0)
    cache.set("key", QueryResponse(text="value"))
    cache.get("key")
    cache.get("key")
    stats = cache.stats()
    assert stats.size == 1
    assert stats.max_size == 500


def test_semantic_cache_semantic_matching() -> None:
    cache = SemanticCache(semantic_enabled=True, semantic_threshold=0.3)
    cache.set("What is the capital of France?", QueryResponse(text="Paris"))
    resp, ok = cache.get("What is the capital of France?")
    assert ok
    assert resp.text == "Paris"


def test_semantic_cache_semantic_near_miss() -> None:
    cache = SemanticCache(semantic_enabled=True, semantic_threshold=0.85)
    cache.set(
        "The quick brown fox jumps over the lazy dog",
        QueryResponse(text="animal"),
    )
    resp, ok = cache.get("a fast brown fox jumped over a sleepy dog")
    assert resp.text == ""


def test_semantic_cache_semantic_threshold() -> None:
    cache = SemanticCache(semantic_enabled=True, semantic_threshold=0.99)
    cache.set("The quick brown fox", QueryResponse(text="value"))
    resp, ok = cache.get("jumps over lazy dog")
    assert not ok
    assert resp.text == ""


def test_caching_router() -> None:
    router = new_router([entry("test")])
    cache = SemanticCache()
    caching = CachingRouter(router, cache)
    messages = [Message(role=ROLE_USER, content="hi")]
    resp1, err1 = caching.cached_generate(messages, [])
    resp2, err2 = caching.cached_generate(messages, [])
    assert err1 is None and err2 is None
    assert resp1 is not None and resp2 is not None
    assert resp1.text == "test response"
    assert resp2.text == "test response"


def test_default_key_fn_deterministic() -> None:
    assert default_key_fn("hello") == default_key_fn("hello")
    assert default_key_fn("hello") != default_key_fn("world")


def test_cosine_sim() -> None:
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    c = [0.0, 1.0, 0.0]
    assert cosine_sim(a, b) == 1.0
    assert cosine_sim(a, c) == 0.0
    assert cosine_sim([], []) == 0.0


def test_simple_embed_shape() -> None:
    vec = simple_embed("hello world")
    assert len(vec) == 128


def test_join_messages() -> None:
    messages = [Message(role=ROLE_USER, content="hi")]
    assert join_messages(messages) == "user: hi\n"
