# SPDX-License-Identifier: MIT
"""Production Hardening tests — Monitoring, Circuit Breaker, Auto-Rollback."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

from dxrk.memory.production import (
    SLOConfig,
    HealthMetrics,
    SLOStatus,
    load_slo_config,
    save_slo_config,
    load_production_state,
    save_production_state,
    collect_health_metrics,
    check_slo_compliance,
    CircuitBreaker,
    CircuitBreakerOpenError,
    AutoRollbackManager,
    _now_iso,
    run_production_health_check,
)


class TestSLOConfig:
    def test_default_config(self) -> None:
        """Default SLO config has sensible values."""
        config = SLOConfig()
        assert config.search_latency_p99_ms == 200.0
        assert config.mine_throughput_files_per_sec == 50.0
        assert config.calibration_ece_max == 0.1
        assert config.memory_usage_percent_max == 90.0
        assert config.quarantine_rate_max == 0.05

    def test_persist_load_cycle(self, tmp_path: Path) -> None:
        """Save and load SLO config."""
        config = SLOConfig(
            search_latency_p99_ms=300.0,
            mine_throughput_files_per_sec=100.0,
            calibration_ece_max=0.05,
            memory_usage_percent_max=80.0,
            quarantine_rate_max=0.02,
        )
        save_slo_config(tmp_path, config)
        loaded = load_slo_config(tmp_path)
        assert loaded.search_latency_p99_ms == 300.0
        assert loaded.mine_throughput_files_per_sec == 100.0
        assert loaded.calibration_ece_max == 0.05
        assert loaded.memory_usage_percent_max == 80.0
        assert loaded.quarantine_rate_max == 0.02

    def test_load_missing_returns_defaults(self, tmp_path: Path) -> None:
        loaded = load_slo_config(tmp_path)
        assert loaded.search_latency_p99_ms == 200.0


class TestHealthMetrics:
    def test_slo_compliance_all_ok(self) -> None:
        """SLO compliance when all metrics within bounds."""
        metrics = HealthMetrics(
            timestamp=_now_iso(),
            search_latency_p50_ms=50.0,
            search_latency_p95_ms=150.0,
            search_latency_p99_ms=180.0,
            mine_throughput_files_per_sec=100.0,
            calibration_ece={"w1": 0.03},
            quarantine_count=2,
            stress_level=0.2,
            memory_usage_mb=500.0,
            memory_usage_percent=50.0,
            disk_usage_mb=1000.0,
            disk_usage_percent=30.0,
        )
        config = SLOConfig()
        status = check_slo_compliance(metrics, config)
        assert status.overall_ok is True
        assert status.search_latency_p99_ok is True
        assert status.mine_throughput_ok is True
        assert status.calibration_ece_ok is True
        assert status.memory_ok is True
        assert len(status.violations) == 0

    def test_slo_violations(self) -> None:
        """SLO violations detected correctly."""
        metrics = HealthMetrics(
            timestamp=_now_iso(),
            search_latency_p50_ms=200.0,
            search_latency_p95_ms=250.0,
            search_latency_p99_ms=300.0,  # exceeds 200ms
            mine_throughput_files_per_sec=30.0,  # below 50
            calibration_ece={"w1": 0.15},  # exceeds 0.1
            quarantine_count=5,
            stress_level=0.8,
            memory_usage_mb=1000.0,
            memory_usage_percent=95.0,  # exceeds 90%
            disk_usage_mb=2000.0,
            disk_usage_percent=80.0,
        )
        config = SLOConfig()
        status = check_slo_compliance(metrics, config)
        assert status.overall_ok is False
        assert status.search_latency_p99_ok is False
        assert status.mine_throughput_ok is False
        assert status.calibration_ece_ok is False
        assert status.memory_ok is False
        assert "search_p99" in " ".join(status.violations)
        assert "mine_throughput" in " ".join(status.violations)
        assert "calibration_ece" in " ".join(status.violations)
        assert "memory" in " ".join(status.violations)


class TestCircuitBreaker:
    def test_closed_state_allows_calls(self) -> None:
        """Closed state allows function calls."""
        cb = CircuitBreaker(failure_threshold=3)
        result = cb.call(lambda x: x * 2, 5)
        assert result == 10
        assert cb.state == "closed"

    def test_opens_after_threshold(self) -> None:
        """Circuit opens after failure threshold."""
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)

        for _ in range(3):
            try:
                cb.call(lambda: 1 / 0)
            except ZeroDivisionError:
                pass

        assert cb.state == "open"

        # Should reject calls when open
        try:
            cb.call(lambda: 42)
            assert False, "Should have raised"
        except Exception as e:
            assert "open" in str(e).lower()

    def test_half_open_after_timeout(self) -> None:
        """Circuit goes half-open after timeout."""
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=1)

        # Trigger open
        for _ in range(2):
            try:
                cb.call(lambda: 1 / 0)
            except ZeroDivisionError:
                pass

        assert cb.state == "open"

        # Wait for timeout
        time.sleep(1.1)

        # Should be half-open
        assert cb.state == "half_open"

    def test_half_open_allows_limited_calls(self) -> None:
        """Half-open state allows limited successful calls."""
        cb = CircuitBreaker(failure_threshold=1, timeout_seconds=1, half_open_max_calls=2)

        # Trigger open
        try:
            cb.call(lambda: 1 / 0)
        except ZeroDivisionError:
            pass

        time.sleep(1.1)
        assert cb.state == "half_open"

        # Should allow limited calls
        result = cb.call(lambda x: x + 1, 5)
        assert result == 6

        # Second call should work
        result = cb.call(lambda x: x + 1, 10)
        assert result == 11

        # Third call should be rejected
        try:
            cb.call(lambda: 42)
            assert False, "Should have raised"
        except Exception as e:
            assert "limit" in str(e).lower() or "open" in str(e).lower()

    def test_closes_after_successes_in_half_open(self) -> None:
        """Circuit closes after 2 successes in half-open."""
        cb = CircuitBreaker(failure_threshold=1, timeout_seconds=1, half_open_max_calls=5)

        # Trigger open
        try:
            cb.call(lambda: 1 / 0)
        except ZeroDivisionError:
            pass

        time.sleep(1.1)
        assert cb.state == "half_open"

        # Two successes should close
        cb.call(lambda x: x + 1, 1)
        cb.call(lambda x: x + 1, 2)
        assert cb.state == "closed"

    def test_failure_in_half_open_reopens(self) -> None:
        """Failure in half-open immediately reopens."""
        cb = CircuitBreaker(failure_threshold=1, timeout_seconds=1, half_open_max_calls=5)

        try:
            cb.call(lambda: 1 / 0)
        except ZeroDivisionError:
            pass

        time.sleep(1.1)
        assert cb.state == "half_open"

        # Failure should reopen
        try:
            cb.call(lambda: 1 / 0)
        except ZeroDivisionError:
            pass

        assert cb.state == "open"


class TestAutoRollbackManager:
    def test_detects_recall_regression(self) -> None:
        """Detects recall@10 regression > 5%."""
        from dxrk.memory.production import AutoRollbackManager
        from dxrk.memory.eval_harness import EvalReport

        manager = AutoRollbackManager(Path("/tmp"))

        current = Mock()
        current.recall_at_k = {10: 0.6}
        current.mrr = 0.5
        current.ece = 0.1

        baseline = Mock()
        baseline.recall_at_k = {10: 0.7}  # 14% drop
        baseline.mrr = 0.5
        baseline.ece = 0.05

        regression = manager._detect_regression(current, baseline)
        assert regression["detected"] is True
        assert regression["severity"] == "critical"

    def test_detects_mrr_regression(self) -> None:
        """Detects MRR regression > 10%."""
        from dxrk.memory.production import AutoRollbackManager

        manager = AutoRollbackManager(Path("/tmp"))

        current = Mock()
        current.recall_at_k = {10: 0.7}
        current.mrr = 0.4  # 20% drop from 0.5
        current.ece = 0.1

        baseline = Mock()
        baseline.recall_at_k = {10: 0.7}
        baseline.mrr = 0.5
        baseline.ece = 0.1

        regression = manager._detect_regression(current, baseline)
        assert regression["detected"] is True
        assert regression["severity"] == "warning"

    def test_detects_ece_increase(self) -> None:
        """Detects ECE increase > 0.05."""
        from dxrk.memory.production import AutoRollbackManager

        manager = AutoRollbackManager(Path("/tmp"))

        current = Mock()
        current.recall_at_k = {10: 0.7}
        current.mrr = 0.5
        current.ece = 0.15  # 0.1 increase

        baseline = Mock()
        baseline.recall_at_k = {10: 0.7}
        baseline.mrr = 0.5
        baseline.ece = 0.05

        regression = manager._detect_regression(current, baseline)
        assert regression["detected"] is True
        assert regression["severity"] == "warning"

    def test_no_regression_when_within_bounds(self) -> None:
        """No regression detected when metrics within bounds."""
        from dxrk.memory.production import AutoRollbackManager

        manager = AutoRollbackManager(Path("/tmp"))

        current = Mock()
        current.recall_at_k = {10: 0.72}
        current.mrr = 0.48  # 4% drop
        current.ece = 0.08  # 0.03 increase

        baseline = Mock()
        baseline.recall_at_k = {10: 0.75}
        baseline.mrr = 0.5
        baseline.ece = 0.05

        regression = manager._detect_regression(current, baseline)
        assert regression["detected"] is False

    def test_logs_regression(self, tmp_path: Path) -> None:
        """Logs regression events."""
        from dxrk.memory.production import AutoRollbackManager

        manager = AutoRollbackManager(Path("/tmp"))

        current = Mock()
        current.recall_at_k = {10: 0.6}
        current.mrr = 0.5
        current.ece = 0.1

        baseline = Mock()
        baseline.recall_at_k = {10: 0.7}
        baseline.mrr = 0.5
        baseline.ece = 0.05

        regression = manager._detect_regression(current, baseline)
        manager._log_regression("w1", "t1", regression)

        assert len(manager._rollback_history) == 1
        entry = manager._rollback_history[0]
        assert entry["wing"] == "w1"
        assert entry["tenant"] == "t1"
        assert entry["severity"] == "critical"
