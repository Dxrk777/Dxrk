# SPDX-License-Identifier: MIT
"""Autonomy orchestrator: self-update, self-verify, self-learn loop"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict
from typing import Callable, Optional

from dxrk.config import AutonomyConfig

from .evolution import NewEvolutionEngine
from .learner import MemoryItem, NewLearner
from .metrics import IQSnapshot, NewIQMetrics
from .permissions import NewPermissionStore
from .updater import NewUpdater
from .verifier import NewVerifier

logger = logging.getLogger(__name__)

RequestFn = Callable[[str, str], tuple[bool, Optional[str]]]


class Autonomy:
    """Runs periodic self-update, self-verify and self-learn cycles."""

    def __init__(
        self,
        cfg: AutonomyConfig,
        project_root: str,
        request_fn: Optional[RequestFn] = None,
    ) -> None:
        self.config = cfg
        self.project_root = project_root
        self.permissions = NewPermissionStore(cfg.capabilities, cfg.ask_before)
        if request_fn is not None:
            self.permissions.set_request_handler(request_fn)

        self.ctx = threading.Event()
        self._running = False
        self.iq_history: list[IQSnapshot] = []
        self.start_time = time.time()
        self._thread: Optional[threading.Thread] = None

        learn_dir = os.path.join(project_root, cfg.learn_dir)
        os.makedirs(learn_dir, mode=0o750, exist_ok=True)

        self.learner = NewLearner(
            os.path.join(project_root, cfg.memories_file), cfg.max_memory_items
        )
        self.metrics = NewIQMetrics(os.path.join(project_root, cfg.iq_metrics_file))
        self.updater = NewUpdater(project_root, cfg.interval_sec, self.permissions)
        self.verifier = NewVerifier(
            project_root, cfg.auto_fix, self.learner, self.metrics, self.permissions
        )
        self.evolution = None
        if cfg.evolution:
            self.evolution = NewEvolutionEngine(
                os.path.join(learn_dir, "evolution.json"), self.learner, self.metrics
            )

    def start(self) -> None:
        cfg = self.config
        if not cfg.enabled or self._running:
            return
        logger.info(
            "autonomy starting (interval=%ds, update=%v, verify=%v, learn=%v, evolution=%v)",
            cfg.interval_sec,
            cfg.self_update,
            cfg.self_verify,
            cfg.self_learn,
            cfg.evolution,
        )
        self._running = True

        if cfg.self_update:
            result = self.updater.check(True)
            if result.updated:
                logger.info(
                    "self-update: %s -> %s (%d changes)",
                    result.before,
                    result.after,
                    result.changes,
                )
            elif result.error:
                logger.info("self-update check: %s", result.error)

        if cfg.self_verify:
            verify_result = self.verifier.verify()
            logger.info(
                "verify: pass=%v failures=%d duration=%v",
                verify_result.pass_,
                verify_result.failures,
                verify_result.duration,
            )
            if not verify_result.pass_:
                self._save_result("verify-fail", verify_result)

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        cfg = self.config
        try:
            while not self.ctx.wait(cfg.interval_sec):
                self._tick()
        finally:
            self._running = False

    def _tick(self) -> None:
        cfg = self.config
        if cfg.self_update:
            result = self.updater.check(False)
            if result.updated:
                logger.info(
                    "auto-updated: %s -> %s (%d changes)",
                    result.before,
                    result.after,
                    result.changes,
                )

        if cfg.self_verify:
            verify_result = self.verifier.verify()
            if not verify_result.pass_:
                logger.info("verify failed (%d failures)", verify_result.failures)
                self._save_result("verify-fail", verify_result)

        if cfg.evolution and self.evolution is not None:
            best = self.evolution.evolve()
            logger.info(
                "evolution: gen=%d pop=%d best_score=%.1f",
                best.generations,
                len(self.evolution.population()),
                best.score,
            )

        if cfg.self_learn:
            self._report_iq()

    def _report_iq(self) -> None:
        snapshot = self.metrics.score()
        self.iq_history.append(snapshot)
        every = self.config.iq_report_every
        if every > 0 and len(self.iq_history) % every == 0:
            logger.info(
                "=== IQ REPORT ===\n"
                "success_rate:        %s\n"
                "error_reduction:     %s\n"
                "token_efficiency:    %s\n"
                "latency_p50:         %s\n"
                "test_pass_rate:      %s\n"
                "auto_fix_rate:       %s\n"
                "evolution_score:     %s\n"
                "OVERALL IQ:          %s\n"
                "turns_completed:     %d\n"
                "errors_fixed:        %d\n"
                "=================",
                snapshot.success_rate,
                snapshot.error_reduction,
                snapshot.token_efficiency,
                snapshot.latency_p50,
                snapshot.test_pass_rate,
                snapshot.auto_fix_rate,
                snapshot.evolution_score,
                snapshot.overall_iq,
                snapshot.turns_completed,
                snapshot.errors_fixed,
            )

    def record_turn(self, success: bool, tokens: int, latency_ms: float) -> None:
        self.metrics.record_turn(success, tokens, latency_ms)
        self.learner.record(
            MemoryItem(
                category="turn",
                success=success,
                tokens=tokens,
                latency_ms=latency_ms,
            )
        )

    def stop(self) -> None:
        self.ctx.set()
        self._running = False
        logger.info("autonomy stopped")

    def running(self) -> bool:
        return self._running

    def current_iq(self) -> IQSnapshot:
        return self.metrics.score()

    def _save_result(self, name: str, data) -> None:
        directory = os.path.dirname(
            os.path.join(self.project_root, self.config.memories_file)
        )
        results_dir = os.path.join(directory, "results")
        try:
            os.makedirs(results_dir, mode=0o750, exist_ok=True)
        except OSError as exc:
            logger.info("[autonomy] failed to create results dir: %s", exc)
            return
        path = os.path.join(results_dir, f"{name}-{int(time.time())}.json")
        try:
            payload = asdict(data) if hasattr(data, "__dataclass_fields__") else data
            content = json.dumps(payload, indent=2)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
        except (TypeError, OSError) as exc:
            logger.info("[autonomy] failed to save result: %s", exc)


def New(
    cfg: AutonomyConfig,
    project_root: str,
    request_fn: Optional[RequestFn] = None,
) -> Autonomy:
    return Autonomy(cfg, project_root, request_fn)
