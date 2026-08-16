# SPDX-License-Identifier: MIT

"""Tests for the cost optimizer and budget tracking (mirrors internal/costopt)."""


import pytest

from dxrk.costopt import BudgetConfig, CostOptimizer
from dxrk.query import Response, Usage
from dxrk.router import (
    Capability,
    CapVision,
    ProviderEntry,
    Router,
    SemanticCache,
)


class MockProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    def generate(self, messages, tools):
        return (
            Response(
                text=f"{self.name} response",
                usage=Usage(input_tokens=0, output_tokens=0),
            ),
            None,
        )


def entry(
    name: str,
    model: str = "gpt-4o-mini",
    capabilities: list[Capability] | None = None,
) -> ProviderEntry:
    return ProviderEntry(
        name=name,
        model=model,
        provider=MockProvider(name),
        capabilities=capabilities if capabilities is not None else [],
    )


def optimizer(providers=None, budget=None, cache=None, path: str = "") -> CostOptimizer:
    return CostOptimizer(
        Router(providers=providers if providers is not None else []),
        cache if cache is not None else SemanticCache(),
        budget if budget is not None else BudgetConfig(),
        path,
    )


def test_new_cost_optimizer() -> None:
    co = optimizer(
        budget=BudgetConfig(
            daily_limit_usd=10, monthly_limit_usd=100, alert_threshold=0.8
        )
    )
    assert co is not None


def test_record_usage() -> None:
    co = optimizer()
    co.record_usage("gpt-4o", 1000, 500)
    st = co.get_budget_status()
    assert st.daily_spent > 0


def test_current_spend() -> None:
    co = optimizer()
    co.record_usage("gpt-4o", 1000, 500)
    co.record_usage("claude-sonnet-4", 2000, 1000)
    st = co.get_budget_status()
    assert st.daily_spent > 0
    assert st.monthly_spent == st.daily_spent


def test_record_usage_unknown_model() -> None:
    co = optimizer()
    co.record_usage("unknown-model", 1000, 500)
    st = co.get_budget_status()
    assert st.daily_spent == 0


def test_budget_exceeded() -> None:
    co = optimizer(
        budget=BudgetConfig(daily_limit_usd=1, monthly_limit_usd=1, alert_threshold=0.5)
    )
    co.record_usage("gpt-4o", 100000, 100000)
    co.record_usage("gpt-4o", 100000, 100000)
    st = co.get_budget_status()
    assert len(st.alerts) > 0
    assert st.alerts[0].level in ("warning", "critical")


def test_select_best_provider() -> None:
    co = optimizer(
        providers=[
            entry("provider-a", model="gpt-4o"),
            entry("provider-b", model="claude-sonnet-4"),
        ]
    )
    best = co.select_best_provider([])
    assert best is not None


def test_select_best_provider_with_capabilities() -> None:
    co = optimizer(
        providers=[
            entry("basic", model="gpt-4o-mini"),
            entry("vision", model="gpt-4o", capabilities=[CapVision]),
        ]
    )
    best = co.select_best_provider([Capability.VISION])
    assert best.name == "vision"


def test_select_best_provider_no_match() -> None:
    co = optimizer()
    with pytest.raises(ValueError):
        co.select_best_provider([Capability.VISION])


def test_alert_threshold() -> None:
    co = optimizer(
        budget=BudgetConfig(daily_limit_usd=5, monthly_limit_usd=5, alert_threshold=0.5)
    )
    co.record_usage("gpt-4o", 500000, 250000)
    st = co.get_budget_status()
    assert len(st.alerts) > 0


def test_get_provider_scores() -> None:
    co = optimizer(
        providers=[
            entry("fast", model="gpt-4o-mini"),
            entry("powerful", model="claude-sonnet-4"),
        ]
    )
    scores = co.get_provider_scores()
    assert len(scores) == 2
    for s in scores:
        assert s.name != ""
        assert s.score > 0


def test_budget_status_zero_limits() -> None:
    co = optimizer()
    st = co.get_budget_status()
    assert st.daily_percent == 0
    assert st.monthly_percent == 0


def test_cache_hit_rate() -> None:
    cache = SemanticCache()
    co = optimizer(cache=cache)
    st = co.get_budget_status()
    assert st.cache_hit_rate == 0


def test_save_and_load(tmp_path) -> None:
    path = str(tmp_path / "costopt" / "state.json")
    co = optimizer(path=path)
    co.record_usage("gpt-4o", 1000, 500)
    st = co.get_budget_status()
    assert st.daily_spent > 0

    co2 = optimizer(path=path)
    st2 = co2.get_budget_status()
    assert st2.daily_spent == st.daily_spent
    assert st2.monthly_spent == st.monthly_spent
