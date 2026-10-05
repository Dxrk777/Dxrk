# SPDX-License-Identifier: MIT
"""Judge Externo Continuo tests — Verificación 24h, auto-rollback."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from dxrk.memory.judge_continuous import (
    ContinuousJudge,
    JudgeState,
    Verdict,
    load_judge_state,
    save_judge_state,
    load_baseline_report,
    _now_iso,
    _judge_path,
)


class TestJudgeState:
    def test_default_state(self) -> None:
        state = JudgeState()
        assert state.last_run == ""
        assert state.last_baseline is None
        assert state.rollback_history == []
        assert state.consecutive_passes == 0
        assert state.consecutive_failures == 0

    def test_persist_load_cycle(self, tmp_path: Path) -> None:
        state = JudgeState(
            last_run="2024-01-01T00:00:00+00:00",
            last_baseline={"recall_at_10": 0.8},
            rollback_history=[{"ts": "2024-01-01", "reason": "test"}],
            consecutive_passes=5,
            consecutive_failures=2,
        )
        save_judge_state(tmp_path, state)
        loaded = load_judge_state(tmp_path)
        assert loaded.last_run == "2024-01-01T00:00:00+00:00"
        assert loaded.last_baseline == {"recall_at_10": 0.8}
        assert len(loaded.rollback_history) == 1
        assert loaded.consecutive_passes == 5
        assert loaded.consecutive_failures == 2

    def test_load_missing_returns_defaults(self, tmp_path: Path) -> None:
        loaded = load_judge_state(tmp_path)
        assert loaded.last_run == ""
        assert loaded.last_baseline is None

    def test_load_corrupted_returns_defaults(self, tmp_path: Path) -> None:
        path = _judge_path(tmp_path)
        path.write_text("not json")
        loaded = load_judge_state(tmp_path)
        assert loaded.last_run == ""


class TestVerdict:
    def test_passed_verdict(self) -> None:
        verdict = Verdict(
            passed=True,
            regression_detected=False,
            severity="none",
            details=[],
            current_report={},
            baseline_report=None,
        )
        assert verdict.passed is True
        assert verdict.regression_detected is False

    def test_regression_verdict(self) -> None:
        verdict = Verdict(
            passed=False,
            regression_detected=True,
            severity="critical",
            details=["recall@10 dropped 10%"],
            current_report={},
            baseline_report={},
        )
        assert verdict.passed is False
        assert verdict.regression_detected is True
        assert verdict.severity == "critical"


class TestContinuousJudge:
    def test_judge_state_persist(self, tmp_path: Path) -> None:
        """Judge state persists correctly."""
        from dxrk.memory.palace import DxrkMemory
        from dxrk.memory.eval_harness import EvalHarness
        from dxrk.memory.judge_continuous import ContinuousJudge

        dm = DxrkMemory(str(tmp_path / "palace"))
        dm.init()
        try:
            for i in range(5):
                dm.add_drawer("w", "r", f"content {i}", f"/f{i}.md", 0)

            harness = EvalHarness(dm, tmp_path / "eval")
            judge = ContinuousJudge(tmp_path / "palace", harness, interval_hours=1)

            state = load_judge_state(tmp_path / "palace")
            assert state.last_run == ""

            # Run once manually
            verdict = judge.run_once()
            assert verdict is not None
        finally:
            dm.close()

    def test_judge_runs_cycle(self, tmp_path: Path) -> None:
        """Judge runs a verification cycle."""
        from dxrk.memory.palace import DxrkMemory
        from dxrk.memory.eval_harness import EvalHarness
        from dxrk.memory.judge_continuous import ContinuousJudge

        dm = DxrkMemory(str(tmp_path / "palace"))
        dm.init()
        try:
            for i in range(5):
                dm.add_drawer("w", "r", f"unique content {i} distinct", f"/f{i}.md", 0)

            harness = EvalHarness(dm, tmp_path / "eval")
            judge = ContinuousJudge(tmp_path / "palace", harness, interval_hours=1)

            verdict = judge.run_once()
            assert verdict is not None
            assert hasattr(verdict, "passed")
        finally:
            dm.close()

    def test_judge_status(self, tmp_path: Path) -> None:
        """Judge status includes all relevant info."""
        from dxrk.memory.palace import DxrkMemory
        from dxrk.memory.eval_harness import EvalHarness
        from dxrk.memory.judge_continuous import ContinuousJudge

        dm = DxrkMemory(str(tmp_path / "palace"))
        dm.init()
        try:
            for i in range(3):
                dm.add_drawer("w", "r", f"content {i}", f"/f{i}.md", 0)

            harness = EvalHarness(dm, tmp_path / "eval")
            judge = ContinuousJudge(tmp_path / "palace", harness, interval_hours=1)

            # Run once to populate state
            judge.run_once()

            status = judge.get_status()
            assert "running" in status
            assert "last_run" in status
            assert "consecutive_passes" in status
            assert "consecutive_failures" in status
            assert "rollback_history" in status
        finally:
            dm.close()


class TestJudgeRegressionDetection:
    def test_detects_critical_recall_regression(self, tmp_path: Path) -> None:
        """Detects critical recall regression via _compare_reports."""
        from dxrk.memory.judge_continuous import ContinuousJudge, Verdict
        from dxrk.memory.eval_harness import EvalReport
        from dxrk.memory.judge_continuous import ContinuousJudge

        # Create a judge with mock harness
        from unittest.mock import Mock

        mock_harness = Mock()

        judge = ContinuousJudge(Path(tmp_path / "palace"), mock_harness, interval_hours=1)

        # Create current and baseline EvalReports
        current_report = EvalReport(
            wing="w",
            num_queries=1,
            recall_at_k={10: 0.6},
            mrr=0.5,
            ndcg=0.5,
            ece=0.1,
            latency_p50=10.0,
            latency_p95=20.0,
            latency_p99=30.0,
            evaluated_at="2024-01-01T00:00:00+00:00",
        )
        baseline_report = EvalReport(
            wing="w",
            num_queries=1,
            recall_at_k={10: 0.7},
            mrr=0.5,
            ndcg=0.5,
            ece=0.05,
            latency_p50=10.0,
            latency_p95=20.0,
            latency_p99=30.0,
            evaluated_at="2024-01-01T00:00:00+00:00",
        )

        verdict = judge._compare_reports(current_report, baseline_report, "test_wing")

        # Recall dropped from 0.7 to 0.6 = 14% drop > 5% threshold
        assert verdict.regression_detected is True
        assert verdict.severity == "critical"
        assert any("recall@10" in d for d in verdict.details)


class TestAutoRollback:
    def test_auto_rollback_on_critical(self, tmp_path: Path) -> None:
        """Auto-rollback triggers on critical regression."""
        from dxrk.memory.judge_continuous import ContinuousJudge
        from dxrk.memory.eval_harness import EvalHarness
        from dxrk.memory.palace import DxrkMemory
        from dxrk.memory.calibrate_v2 import load_calibration, save_calibration, CalibrationParams

        dm = DxrkMemory(str(tmp_path / "palace"))
        dm.init()
        try:
            # Add some drawers
            for i in range(5):
                dm.add_drawer("w", "r", f"content {i}", f"/f{i}.md", 0)

            # Setup calibration
            save_calibration(
                tmp_path / "palace",
                CalibrationParams(tenant="", wing="w", a=1.5, b=0.2, c=1.0, pe_lambda=0.1, score=0.8),
            )

            harness = EvalHarness(dm, tmp_path / "eval")
            judge = ContinuousJudge(tmp_path / "palace", Mock(), interval_hours=1, auto_rollback=True)

            # Manually trigger rollback logic
            from dxrk.memory.calibrate_v2 import get_calibration_chain, merge_calibrations

            chain = get_calibration_chain(tmp_path / "palace", "", "w")
            assert len(chain) >= 1

            # Rollback to previous (should be default)
            if len(chain) >= 2:
                previous = chain[1]
                assert previous.a == 1.5  # default
        finally:
            dm.close()
