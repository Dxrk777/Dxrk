from datetime import datetime, timedelta

import pytest

from dxrk.cost import ModelUsage, SessionCost, calculate_cost


def test_calculate_cost_haiku():
    cost = calculate_cost("claude-haiku", 1_000_000, 0, 0, 0)
    assert cost == pytest.approx(0.25)
    cost = calculate_cost("claude-haiku", 0, 1_000_000, 0, 0)
    assert cost == pytest.approx(1.25)
    cost = calculate_cost("claude-haiku", 0, 0, 1_000_000, 0)
    assert cost == pytest.approx(0.03)
    cost = calculate_cost("claude-haiku", 0, 0, 0, 1_000_000)
    assert cost == pytest.approx(0.03)


def test_calculate_cost_sonnet():
    cost = calculate_cost("claude-sonnet", 1_000_000, 0, 0, 0)
    assert cost == pytest.approx(3.0)
    cost = calculate_cost("claude-sonnet", 0, 1_000_000, 0, 0)
    assert cost == pytest.approx(15.0)


def test_calculate_cost_opus():
    cost = calculate_cost("claude-opus", 1_000_000, 0, 0, 0)
    assert cost == pytest.approx(15.0)
    cost = calculate_cost("claude-opus", 0, 1_000_000, 0, 0)
    assert cost == pytest.approx(75.0)


def test_calculate_cost_default_model():
    cost = calculate_cost("gpt-4o", 1_000_000, 0, 0, 0)
    assert cost == pytest.approx(3.0)
    cost = calculate_cost("gpt-4o", 0, 1_000_000, 0, 0)
    assert cost == pytest.approx(15.0)


def test_calculate_cost_proportional():
    cost = calculate_cost("claude-sonnet", 500_000, 250_000, 0, 0)
    assert cost == pytest.approx(1.5 + 3.75)


def test_new_session_cost():
    sc = SessionCost("s1")
    assert sc.session_id == "s1"
    assert sc.models == {}
    assert sc.total_cost_usd == 0.0
    assert sc.total_input_tokens == 0
    assert sc.total_output_tokens == 0
    assert sc.start_time == sc.last_activity


def test_record_usage_accumulates():
    sc = SessionCost("s1")
    sc.record_usage("claude-sonnet", 1_000_000, 100_000, 0, 0, timedelta(seconds=1))
    sc.record_usage("claude-sonnet", 1_000_000, 100_000, 0, 0, timedelta(seconds=1))

    usage = sc.models["claude-sonnet"]
    assert usage.input_tokens == 2_000_000
    assert usage.output_tokens == 200_000
    assert usage.calls == 2
    assert usage.cost_usd == pytest.approx(2 * (3.0 + 1.5))
    assert usage.duration == timedelta(seconds=2)
    assert sc.total_cost_usd == pytest.approx(usage.cost_usd)
    assert sc.total_input_tokens == 2_000_000
    assert sc.total_output_tokens == 200_000
    assert sc.last_activity >= sc.start_time


def test_record_usage_separate_models():
    sc = SessionCost("s1")
    sc.record_usage("claude-haiku", 1_000_000, 0, 0, 0, timedelta())
    sc.record_usage("claude-opus", 1_000_000, 0, 0, 0, timedelta())
    assert len(sc.models) == 2
    assert sc.models["claude-haiku"].cost_usd == pytest.approx(0.25)
    assert sc.models["claude-opus"].cost_usd == pytest.approx(15.0)
    assert sc.total_cost_usd == pytest.approx(15.25)


def test_get_total_cost():
    sc = SessionCost("s1")
    assert sc.get_total_cost() == 0.0
    sc.record_usage("claude-haiku", 1_000_000, 0, 0, 0, timedelta())
    assert sc.get_total_cost() == pytest.approx(0.25)


def test_get_model_breakdown_copies():
    sc = SessionCost("s1")
    sc.record_usage("claude-sonnet", 1_000_000, 0, 0, 0, timedelta())
    breakdown = sc.get_model_breakdown()
    assert set(breakdown.keys()) == {"claude-sonnet"}
    assert breakdown["claude-sonnet"].calls == 1
    assert isinstance(breakdown["claude-sonnet"], ModelUsage)
    breakdown["claude-sonnet"].calls = 99
    assert sc.models["claude-sonnet"].calls == 1


def test_summary_empty_session():
    sc = SessionCost("s1")
    out = sc.summary()
    assert "Session: s1\n" in out
    assert "Total cost: $0.0000\n" in out
    assert "Total input tokens: 0\n" in out
    assert "Total output tokens: 0\n" in out
    assert "Duration: 0s\n" in out
    assert "Model breakdown:" not in out


def test_summary_with_models():
    sc = SessionCost("s1")
    sc.record_usage(
        "claude-sonnet", 1_000_000, 100_000, 50_000, 10_000, timedelta(seconds=2)
    )
    out = sc.summary()
    assert "Session: s1\n" in out
    assert "Total cost: $4.5180\n" in out
    assert "Total input tokens: 1000000\n" in out
    assert "Total output tokens: 100000\n" in out
    assert "Model breakdown:\n" in out
    assert (
        "  claude-sonnet: $4.5180 (1000000 input, 100000 output, 50000 cache read, "
        "10000 cache write, 1 calls)\n" in out
    )


def test_compact_empty_session():
    sc = SessionCost("s1")
    data = sc.compact()
    assert data["session_id"] == "s1"
    assert data["total_cost_usd"] == 0.0
    assert data["total_input_tokens"] == 0
    assert data["total_output_tokens"] == 0
    assert isinstance(data["start_time"], int)
    assert isinstance(data["last_activity"], int)
    assert data["models"] == {}


def test_compact_with_models():
    sc = SessionCost("s1")
    sc.record_usage(
        "claude-sonnet", 1_000_000, 100_000, 50_000, 10_000, timedelta(seconds=1)
    )
    data = sc.compact()
    assert data["session_id"] == "s1"
    assert data["total_cost_usd"] == pytest.approx(4.518)
    assert data["total_input_tokens"] == 1_000_000
    assert data["total_output_tokens"] == 100_000
    model = data["models"]["claude-sonnet"]
    assert model["input_tokens"] == 1_000_000
    assert model["output_tokens"] == 100_000
    assert model["cache_read_tokens"] == 50_000
    assert model["cache_creation_tokens"] == 10_000
    assert model["cost_usd"] == pytest.approx(4.518)
    assert model["calls"] == 1


def test_duration_format():
    sc = SessionCost("s1")
    sc.start_time = datetime.now() - timedelta(milliseconds=2500)
    sc.record_usage("claude-sonnet", 0, 0, 0, 0, timedelta())
    out = sc.summary()
    assert "Duration: 2.5s\n" in out
