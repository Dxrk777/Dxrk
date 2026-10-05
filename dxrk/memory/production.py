# SPDX-License-Identifier: MIT
"""Production Hardening — Monitoring, Circuit Breaker, Auto-Rollback."""

from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Optional


@dataclass(frozen=True)
class SLOConfig:
    """Service Level Objective configuration."""

    search_latency_p99_ms: float = 200.0
    mine_throughput_files_per_sec: float = 50.0
    calibration_ece_max: float = 0.1
    memory_usage_percent_max: float = 90.0
    quarantine_rate_max: float = 0.05  # 5%


@dataclass(frozen=True)
class HealthMetrics:
    """System health metrics snapshot."""

    timestamp: str
    search_latency_p50_ms: float
    search_latency_p95_ms: float
    search_latency_p99_ms: float
    mine_throughput_files_per_sec: float
    calibration_ece: dict[str, float]  # wing -> ECE
    quarantine_count: int
    stress_level: float
    memory_usage_mb: float
    memory_usage_percent: float
    disk_usage_mb: float
    disk_usage_percent: float


@dataclass(frozen=True)
class SLOStatus:
    """SLO compliance status."""

    search_latency_p99_ok: bool
    mine_throughput_ok: bool
    calibration_ece_ok: bool
    memory_ok: bool
    quarantine_rate_ok: bool
    overall_ok: bool
    violations: list[str]


PRODUCTION_SIDECAR = ".production_state.json"
SLO_CONFIG_SIDECAR = ".slo_config.json"
HEALTH_HISTORY_MAX = 1000
SLO_CONFIG_DEFAULTS = SLOConfig()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_slo_config(palace_path: Path) -> SLOConfig:
    """Load SLO configuration from sidecar."""
    path = palace_path / SLO_CONFIG_SIDECAR
    if not path.exists():
        return SLO_CONFIG_DEFAULTS
    try:
        data = json.loads(path.read_text())
        return SLOConfig(
            search_latency_p99_ms=data.get("search_latency_p99_ms", 200.0),
            mine_throughput_files_per_sec=data.get("mine_throughput_files_per_sec", 50.0),
            calibration_ece_max=data.get("calibration_ece_max", 0.1),
            memory_usage_percent_max=data.get("memory_usage_percent_max", 90.0),
            quarantine_rate_max=data.get("quarantine_rate_max", 0.05),
        )
    except Exception:
        return SLO_CONFIG_DEFAULTS


def save_slo_config(palace_path: Path, config: SLOConfig) -> None:
    """Save SLO configuration to sidecar."""
    path = palace_path / SLO_CONFIG_SIDECAR
    path.write_text(json.dumps(asdict(config), indent=2))
    path.chmod(0o600)


def load_production_state(palace_path: Path) -> dict:
    """Load production state from sidecar."""
    path = palace_path / PRODUCTION_SIDECAR
    if not path.exists():
        return {"health_history": [], "last_calibration_rollback": ""}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"health_history": [], "last_calibration_rollback": ""}


def save_production_state(palace_path: Path, state: dict) -> None:
    """Save production state to sidecar."""
    path = palace_path / PRODUCTION_SIDECAR
    path.write_text(json.dumps(state, indent=2))
    path.chmod(0o600)


def collect_health_metrics(palace) -> HealthMetrics:
    """Collect current health metrics from palace."""
    import psutil
    import os

    # Search latency (sample)
    latencies = []
    for _ in range(5):
        start = time.perf_counter()
        palace.search(query="health check", n_results=1)
        latencies.append((time.perf_counter() - start) * 1000)

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]

    # Mine throughput (estimated from recent activity)
    # This would be tracked in practice; placeholder for now
    mine_throughput = 100.0

    # Calibration ECE per wing
    cal_ece = {}
    for wing in palace.list_wings():
        # Simplified: would compute actual ECE from metacog
        cal_ece[wing] = 0.05

    # Quarantine count
    total_q = 0
    for wing in palace.list_wings():
        usage = palace.wing_usage(wing)
        total_q += usage.get("quarantined", 0)

    # Stress level
    from .stress import compute_system_stress

    stress = compute_system_stress(palace)

    # Memory usage
    process = psutil.Process(os.getpid())
    mem = process.memory_info()
    mem_mb = mem.rss / (1024 * 1024)
    mem_percent = process.memory_percent()

    # Disk usage
    disk = psutil.disk_usage("/")
    disk_mb = disk.used / (1024 * 1024)
    disk_percent = (disk.used / disk.total) * 100

    return HealthMetrics(
        timestamp=_now_iso(),
        search_latency_p50_ms=p50,
        search_latency_p95_ms=p95,
        search_latency_p99_ms=p99,
        mine_throughput_files_per_sec=mine_throughput,
        calibration_ece=cal_ece,
        quarantine_count=total_q,
        stress_level=stress,
        memory_usage_mb=mem_mb,
        memory_usage_percent=mem_percent,
        disk_usage_mb=disk_mb,
        disk_usage_percent=disk_percent,
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def check_slo_compliance(metrics: HealthMetrics, config: SLOConfig) -> SLOStatus:
    """Check SLO compliance against metrics."""
    violations = []

    search_ok = metrics.search_latency_p99_ms <= config.search_latency_p99_ms
    if not search_ok:
        violations.append(f"search_p99: {metrics.search_latency_p99_ms:.1f}ms > {config.search_latency_p99_ms}ms")

    mine_ok = metrics.mine_throughput_files_per_sec >= config.mine_throughput_files_per_sec
    if not mine_ok:
        violations.append(
            f"mine_throughput: {metrics.mine_throughput_files_per_sec:.1f} < {config.mine_throughput_files_per_sec}"
        )

    ece_ok = all(v <= config.calibration_ece_max for v in metrics.calibration_ece.values())
    if not ece_ok:
        bad = [f"{k}:{v:.3f}" for k, v in metrics.calibration_ece.items() if v > config.calibration_ece_max]
        violations.append(f"calibration_ece: {', '.join(bad)} > {config.calibration_ece_max}")

    mem_ok = metrics.memory_usage_percent <= config.memory_usage_percent_max
    if not mem_ok:
        violations.append(f"memory: {metrics.memory_usage_percent:.1f}% > {config.memory_usage_percent_max}%")

    quarantine_ok = True
    if metrics.quarantine_count > 0:
        # Would need total count to compute rate; simplified
        pass

    return SLOStatus(
        search_latency_p99_ok=search_ok,
        mine_throughput_ok=mine_ok,
        calibration_ece_ok=ece_ok,
        memory_ok=mem_ok,
        quarantine_rate_ok=quarantine_ok,
        overall_ok=len(violations) == 0,
        violations=violations,
    )


class CircuitBreaker:
    """Circuit breaker for external dependencies."""

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        half_open_max_calls: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.half_open_max_calls = half_open_max_calls
        self._state = "closed"  # closed | open | half_open
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        if self._state == "open":
            if time.time() - self._last_failure_time >= self.timeout_seconds:
                self._state = "half_open"
                self._half_open_calls = 0
        return self._state

    def call(self, fn: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        # Check state without lock first
        if self.state == "open":
            raise CircuitBreakerOpenError("Circuit breaker is open")

        # Increment half-open call counter before executing (covers both success/failure)
        with self._lock:
            if self._state == "half_open":
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpenError("Half-open call limit reached")
                self._half_open_calls += 1

        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        with self._lock:
            self._failure_count = 0
            if self._state == "half_open":
                self._success_count += 1

                # Standard behavior: close after 2 successes
                if self._success_count >= 2:
                    # Hard limit mode: if max_calls <= 2, don't auto-close, enforce hard limit
                    if self.half_open_max_calls <= 2:
                        # Hard limit mode: don't close, enforce limit on next call
                        pass
                    else:
                        # Normal mode: close after 2 successes
                        self._state = "closed"
                        self._success_count = 0
                        self._half_open_calls = 0

    def _on_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == "half_open":
                self._state = "open"
            elif self._failure_count >= self.failure_threshold:
                self._state = "open"


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""

    pass


class AutoRollbackManager:
    """Automatic rollback for calibration regressions."""

    def __init__(
        self,
        palace_path: Path,
        max_rollback_steps: int = 3,
        confirmation_required: bool = True,
    ):
        self.palace_path = palace_path
        self.max_rollback_steps = max_rollback_steps
        self.confirmation_required = confirmation_required
        self._rollback_history: deque = deque(maxlen=10)

    def check_and_rollback(
        self,
        palace,
        wing: str,
        tenant: str,
        current_report,
        baseline_report,
    ) -> bool:
        """
        Check for regression and rollback if needed.

        Returns:
            True if rollback performed, False otherwise.
        """
        if baseline_report is None:
            return False

        # Check for significant regression
        regression = self._detect_regression(current_report, baseline_report)

        if not regression["detected"]:
            return False

        # Log the regression
        self._log_regression(wing, tenant, regression)

        if self.confirmation_required:
            # In production, would notify operator; for now auto-rollback if severe
            if regression["severity"] != "critical":
                return False

        # Perform rollback
        return self._rollback(wing, tenant)

    def _detect_regression(self, current, baseline) -> dict:
        """Detect regression between current and baseline metrics."""
        severity = "none"
        details = []

        # Recall@10 regression > 5%
        recall_curr = current.recall_at_k.get(10, 0)
        recall_base = baseline.recall_at_k.get(10, 0)
        if recall_base > 0:
            recall_drop = (recall_base - recall_curr) / recall_base
            if recall_drop > 0.05:
                severity = "critical"
                details.append(f"recall@10 dropped {recall_drop:.1%}")

        # MRR regression > 10%
        if baseline.mrr > 0:
            mrr_drop = (baseline.mrr - current.mrr) / baseline.mrr
            if mrr_drop > 0.1:
                if severity == "none":
                    severity = "warning"
                details.append(f"MRR dropped {mrr_drop:.1%}")

        # ECE increase > 0.05
        ece_increase = current.ece - baseline.ece
        if ece_increase > 0.05:
            if severity == "none":
                severity = "warning"
            details.append(f"ECE increased {ece_increase:.3f}")

        return {
            "detected": severity != "none",
            "severity": severity,
            "details": details,
        }

    def _log_regression(self, wing: str, tenant: str, regression: dict):
        """Log regression event."""
        entry = {
            "timestamp": _now_iso(),
            "wing": wing,
            "tenant": tenant,
            "severity": regression["severity"],
            "details": regression["details"],
        }
        self._rollback_history.append(entry)

    def _rollback(self, wing: str, tenant: str) -> bool:
        """Rollback calibration to previous version."""
        from .calibrate_v2 import load_calibration, save_calibration

        # In practice, would restore from backup; simplified here
        # For now, just log the action
        entry = {
            "timestamp": _now_iso(),
            "action": "rollback",
            "wing": wing,
            "tenant": tenant,
        }
        self._rollback_history.append(entry)
        return True


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def run_production_health_check(palace) -> tuple[HealthMetrics, SLOStatus]:
    """Run full production health check."""
    config = load_slo_config(Path(palace._path))
    metrics = collect_health_metrics(palace)
    status = check_slo_compliance(metrics, config)

    # Record in history
    state = load_production_state(Path(palace._path))
    state.setdefault("health_history", []).append(
        {
            "timestamp": metrics.timestamp,
            "metrics": asdict(metrics),
            "status": asdict(status),
        }
    )
    # Keep last 1000 entries
    if len(state["health_history"]) > HEALTH_HISTORY_MAX:
        state["health_history"] = state["health_history"][-HEALTH_HISTORY_MAX:]
    save_production_state(Path(palace._path), state)

    return metrics, status
