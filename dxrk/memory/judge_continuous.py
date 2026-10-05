# SPDX-License-Identifier: MIT
"""Judge Externo Continuo — Verificación 24h, auto-rollback continuo."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .calibrate_v2 import get_calibration_chain
from .eval_harness import EvalHarness, EvalReport

JUDGE_SIDECAR = ".judge_state.json"
JUDGE_HISTORY_MAX = 1000


@dataclass
class JudgeState:
    """Persistent judge state."""

    last_run: str = ""
    last_baseline: dict | None = None
    rollback_history: list[dict] = field(default_factory=list)
    consecutive_passes: int = 0
    consecutive_failures: int = 0


@dataclass(frozen=True)
class Verdict:
    """Judge verdict for a change."""

    passed: bool
    regression_detected: bool
    severity: str  # "none" | "warning" | "critical"
    details: list[str]
    current_report: dict
    baseline_report: dict | None
    auto_rollback: bool = False


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _judge_path(palace_path: str | Path) -> Path:
    return Path(palace_path) / JUDGE_SIDECAR


def load_judge_state(palace_path: str | Path) -> JudgeState:
    """Load judge state from sidecar."""
    path = _judge_path(palace_path)
    if not path.exists():
        return JudgeState()
    try:
        data = json.loads(path.read_text())
        return JudgeState(
            last_run=data.get("last_run", ""),
            last_baseline=data.get("last_baseline"),
            rollback_history=data.get("rollback_history", []),
            consecutive_passes=data.get("consecutive_passes", 0),
            consecutive_failures=data.get("consecutive_failures", 0),
        )
    except Exception:
        return JudgeState()


def save_judge_state(palace_path: str | Path, state: JudgeState) -> None:
    """Save judge state to sidecar."""
    path = _judge_path(palace_path)
    data = {
        "last_run": state.last_run,
        "last_baseline": state.last_baseline,
        "rollback_history": state.rollback_history[-JUDGE_HISTORY_MAX:],
        "consecutive_passes": state.consecutive_passes,
        "consecutive_failures": state.consecutive_failures,
    }
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)


def load_baseline_report(palace_path: str | Path, wing: str) -> dict | None:
    """Load baseline evaluation report for a wing."""
    from dxrk.memory.palace import DxrkMemory

    from .eval_harness import EvalHarness

    dm = DxrkMemory(str(palace_path))
    try:
        dm.init()
        harness = EvalHarness(dm, Path(dm.palace_path) / "eval")
        report = harness.run(wing=wing)
        return asdict(report)
    finally:
        dm.close()


def save_baseline_report(palace_path: str | Path, wing: str, report: dict) -> None:
    """Save baseline report for a wing."""

    # Reports are saved by EvalHarness.run()
    pass


class ContinuousJudge:
    """Juez externo que ejecuta verificación continua cada N horas."""

    def __init__(
        self,
        palace_path: Path,
        eval_harness: EvalHarness,
        interval_hours: int = 24,
        regression_thresholds: dict | None = None,
        auto_rollback: bool = True,
    ):
        self.palace_path = str(palace_path)
        self.eval_harness = eval_harness
        self.interval_seconds = interval_hours * 3600
        self.auto_rollback = auto_rollback
        self.regression_thresholds = regression_thresholds or {
            "recall_drop_pct": 0.05,  # 5% recall drop
            "mrr_drop_pct": 0.10,  # 10% MRR drop
            "ece_increase": 0.05,  # 0.05 ECE increase
        }
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_verdict: Verdict | None = None

    def start(self) -> None:
        """Start the continuous judge loop."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the continuous judge loop."""
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        """Main judge loop."""
        while self._running:
            try:
                self._run_verification_cycle()
            except Exception as e:
                # Log error but continue
                print(f"Judge cycle error: {e}")

            # Sleep until next interval
            for _ in range(self.interval_seconds):
                if not self._running:
                    break
                time.sleep(1)

    def _run_verification_cycle(self) -> Verdict:
        """Run a single verification cycle."""
        wings: list[str] = []
        # Get all wings from eval harness
        for wing_path in self.eval_harness.eval_dir.glob("*.jsonl"):
            wings.append(wing_path.stem)

        for wing in wings:
            verdict = self._verify_wing(str(wing))
            self._last_verdict = verdict

            # Update judge state
            state = load_judge_state(self.palace_path)
            state.last_run = _now_iso()

            if verdict.passed:
                state.consecutive_passes += 1
                state.consecutive_failures = 0
            else:
                state.consecutive_failures += 1
                state.consecutive_passes = 0

            save_judge_state(self.palace_path, state)

        return self._last_verdict or Verdict(
            passed=True, regression_detected=False, severity="none", details=[], current_report={}, baseline_report=None
        )

    def _verify_wing(self, wing: str) -> Verdict:
        """Verify a single wing against its baseline."""
        from dxrk.memory.palace import DxrkMemory

        dm = DxrkMemory(str(self.palace_path))
        try:
            dm.init()
            # Get current evaluation
            current_report_dict = load_baseline_report(self.palace_path, wing)
            if not current_report_dict:
                return Verdict(
                    passed=True,
                    regression_detected=False,
                    severity="none",
                    details=["No current evaluation available"],
                    current_report={},
                    baseline_report=None,
                )

            current_report = EvalReport(**current_report_dict)

            # Load baseline
            baseline_report = load_baseline_report(Path(self.palace_path), wing)

            if baseline_report is None:
                # First run: save as baseline, pass
                from dataclasses import asdict

                save_baseline_report(Path(self.palace_path), wing, asdict(self.eval_harness.run(wing)))
                return Verdict(
                    passed=True,
                    regression_detected=False,
                    severity="none",
                    details=["First run - established baseline"],
                    current_report=current_report_dict,
                    baseline_report=None,
                )

            baseline = EvalReport(**baseline_report)

            # Detect regression
            verdict = self._compare_reports(current_report, baseline, wing)

            # Auto-rollback if regression detected and auto_rollback enabled
            if verdict.regression_detected and self.auto_rollback and verdict.severity == "critical":
                from dxrk.memory.palace import DxrkMemory

                from .calibrate_v2 import save_calibration

                dm = DxrkMemory(str(self.palace_path))
                try:
                    dm.init()
                    # Load calibration chain and rollback
                    chain = get_calibration_chain(Path(self.palace_path), "", wing)
                    if len(chain) >= 2:
                        # Restore previous calibration
                        previous = chain[1]
                        save_calibration(Path(self.palace_path), previous)

                        # Log rollback
                        self._log_rollback(wing, "", "auto_rollback_critical")
                finally:
                    dm.close()

                verdict = Verdict(
                    passed=verdict.passed,
                    regression_detected=verdict.regression_detected,
                    severity=verdict.severity,
                    details=verdict.details + ["Auto-rollback triggered"],
                    current_report=verdict.current_report,
                    baseline_report=verdict.baseline_report,
                    auto_rollback=True,
                )

            return verdict
        finally:
            dm.close()

    def _compare_reports(self, current: EvalReport, baseline: EvalReport, wing: str) -> Verdict:
        """Compare current report against baseline."""
        severity = "none"
        details = []

        # Recall@k regression
        for k in [1, 3, 5, 10, 20]:
            curr = current.recall_at_k.get(k, 0)
            base = baseline.recall_at_k.get(k, 0)
            if base > 0:
                drop = (base - curr) / base
                if drop > self.regression_thresholds["recall_drop_pct"]:
                    severity = "critical" if severity != "critical" else "critical"
                    details.append(f"recall@{k} dropped {drop:.1%} (from {base:.2f} to {curr:.2f})")

        # MRR regression
        if baseline.mrr > 0:
            mrr_drop = (baseline.mrr - current.mrr) / baseline.mrr
            if mrr_drop > self.regression_thresholds["mrr_drop_pct"]:
                severity = "critical" if severity != "critical" else "critical"
                details.append(f"MRR dropped {mrr_drop:.1%} (from {baseline.mrr:.3f} to {current.mrr:.3f})")

        # NDCG regression
        if baseline.ndcg > 0:
            ndcg_drop = (baseline.ndcg - current.ndcg) / baseline.ndcg
            if ndcg_drop > 0.1:
                if severity == "none":
                    severity = "warning"
                details.append(f"NDCG dropped {ndcg_drop:.1%}")

        # ECE increase
        ece_increase = current.ece - baseline.ece
        if ece_increase > self.regression_thresholds["ece_increase"]:
            if severity == "none":
                severity = "warning"
            details.append(f"ECE increased {ece_increase:.3f} (from {baseline.ece:.3f} to {current.ece:.3f})")

        return Verdict(
            passed=severity == "none",
            regression_detected=severity != "none",
            severity=severity,
            details=details,
            current_report=asdict(current),
            baseline_report=asdict(baseline),
        )

    def _log_rollback(self, wing: str, tenant: str, reason: str):
        """Log rollback event."""
        state = load_judge_state(self.palace_path)
        entry = {
            "timestamp": _now_iso(),
            "wing": wing,
            "tenant": tenant,
            "reason": reason,
        }
        state.rollback_history.append(entry)
        save_judge_state(self.palace_path, state)

    def get_status(self) -> dict:
        """Get current judge status."""
        state = load_judge_state(self.palace_path)
        return {
            "running": self._running,
            "last_run": state.last_run,
            "consecutive_passes": state.consecutive_passes,
            "consecutive_failures": state.consecutive_failures,
            "last_verdict": asdict(self._last_verdict) if self._last_verdict else None,
            "rollback_history": state.rollback_history[-10:],
        }

    def run_once(self) -> Verdict:
        """Run a single verification cycle (for manual trigger)."""
        return self._run_verification_cycle()
