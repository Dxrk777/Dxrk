# SPDX-License-Identifier: MIT
"""IQ metrics: success rate, latency, auto-fix and evolution scoring"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class IQSnapshot:
    timestamp: str = ""
    success_rate: float = 0.0
    error_reduction: float = 0.0
    token_efficiency: float = 0.0
    latency_p50: float = 0.0
    test_pass_rate: float = 0.0
    auto_fix_rate: float = 0.0
    evolution_score: float = 0.0
    overall_iq: float = 0.0
    turns_completed: int = 0
    errors_fixed: int = 0


class IQMetrics:
    """Tracks turn/test/auto-fix/evolution statistics and scores overall IQ."""

    def __init__(self, path: str) -> None:
        self.mu = threading.Lock()
        self.path = path
        self.success_count = 0
        self.failure_count = 0
        self.total_tokens = 0
        self.total_latency = 0.0
        self.latencies: list[float] = []
        self.test_passes = 0
        self.test_fails = 0
        self.auto_fixes = 0
        self.auto_fix_fails = 0
        self.errors_fixed = 0
        self.evolutions = 0
        self.history: list[IQSnapshot] = []
        self.turns_count = 0
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except OSError:
            return
        except json.JSONDecodeError as exc:
            logger.info("[metrics] failed to unmarshal history: %s", exc)
            return
        self.history = [IQSnapshot(**s) for s in data]

    def _save(self) -> None:
        try:
            data = json.dumps([asdict(s) for s in self.history], indent=2)
        except TypeError as exc:
            logger.info("[metrics] failed to marshal history: %s", exc)
            return
        directory = os.path.dirname(self.path)
        try:
            os.makedirs(directory, mode=0o750, exist_ok=True)
        except OSError as exc:
            logger.info("[metrics] failed to create dir: %s", exc)
            return
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
        except OSError as exc:
            logger.info("[metrics] failed to write file: %s", exc)

    def record_turn(self, success: bool, tokens: int, latency_ms: float) -> None:
        snapshot_now = False
        with self.mu:
            self.turns_count += 1
            if success:
                self.success_count += 1
            else:
                self.failure_count += 1
            self.total_tokens += tokens
            self.total_latency += latency_ms
            self.latencies.append(latency_ms)
            if self.turns_count % 10 == 0:
                snapshot_now = True
        if snapshot_now:
            self._snapshot()

    def record_test_result(self, passed: bool) -> None:
        with self.mu:
            if passed:
                self.test_passes += 1
            else:
                self.test_fails += 1

    def record_auto_fix(self, success: bool) -> None:
        with self.mu:
            if success:
                self.auto_fixes += 1
                self.errors_fixed += 1
            else:
                self.auto_fix_fails += 1

    def record_evolution(self) -> None:
        with self.mu:
            self.evolutions += 1

    def score(self) -> IQSnapshot:
        with self.mu:
            total = self.success_count + self.failure_count
            success_rate = (self.success_count / total * 100) if total > 0 else 0.0
            test_total = self.test_passes + self.test_fails
            test_pass_rate = (
                (self.test_passes / test_total * 100) if test_total > 0 else 0.0
            )
            fix_total = self.auto_fixes + self.auto_fix_fails
            auto_fix_rate = (
                (self.auto_fixes / fix_total * 100) if fix_total > 0 else 0.0
            )
            if self.turns_count == 0 or self.total_tokens == 0:
                token_efficiency = 100.0
            else:
                token_efficiency = self.success_count / self.total_tokens * 10000
            latency_p50 = _median(self.latencies)
            error_reduction = self._calc_error_reduction()
            evolution_score = min(self.evolutions * 5.0, 100)
            overall_iq = (
                success_rate * 0.25
                + error_reduction * 0.20
                + token_efficiency * 0.15
                + (100 - latency_p50 / 10) * 0.10
                + test_pass_rate * 0.15
                + auto_fix_rate * 0.15
            )
            overall_iq = max(0.0, min(overall_iq, 100))
            return IQSnapshot(
                timestamp=datetime.now(UTC).isoformat(),
                success_rate=_round2(success_rate),
                error_reduction=_round2(error_reduction),
                token_efficiency=_round2(token_efficiency),
                latency_p50=_round2(latency_p50),
                test_pass_rate=_round2(test_pass_rate),
                auto_fix_rate=_round2(auto_fix_rate),
                evolution_score=_round2(evolution_score),
                overall_iq=_round2(overall_iq),
                turns_completed=self.turns_count,
                errors_fixed=self.errors_fixed,
            )

    def _calc_error_reduction(self) -> float:
        if len(self.history) < 2:
            return 50.0
        first = self.history[0]
        last = self.history[-1]
        if first.errors_fixed == 0:
            return 50.0
        reduction = (last.errors_fixed - first.errors_fixed) / first.errors_fixed * 100
        return min(reduction, 100)

    def _snapshot(self) -> None:
        snapshot = self.score()
        with self.mu:
            self.history.append(snapshot)
            if len(self.history) > 100:
                self.history = self.history[-100:]
        self._save()


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 0:
        return (ordered[mid - 1] + ordered[mid]) / 2
    return ordered[mid]


def _round2(x: float) -> float:
    return round(x * 100) / 100


def NewIQMetrics(path: str) -> IQMetrics:
    return IQMetrics(path)
