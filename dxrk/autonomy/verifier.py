# SPDX-License-Identifier: MIT
"""Verifier: go vet + go test with learner-driven auto-fix"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .learner import Learner, MemoryItem
from .metrics import IQMetrics
from .permissions import PermissionStore
from .updater import CmdResult, _run_cmd_raw


@dataclass
class VerifyResult:
    pass_: bool = False
    vet_output: str = ""
    test_output: str = ""
    duration: float = 0.0
    failures: int = 0


class Verifier:
    """Runs go vet + go test and optionally attempts learner-driven fixes."""

    def __init__(
        self,
        project_root: str,
        auto_fix: bool,
        learner: Learner,
        metrics: IQMetrics,
        perms: PermissionStore,
    ) -> None:
        self.project_root = project_root
        self.auto_fix = auto_fix
        self.learner = learner
        self.metrics = metrics
        self.perms = perms

    def verify(self) -> VerifyResult:
        start = time.time()
        result = VerifyResult()

        vet_out, vet_err = self._run_cmd("go", ["vet", "./..."])
        result.vet_output = vet_out.strip()
        if vet_err:
            result.failures += 1

        test_out, test_err = self._run_cmd("go", ["test", "./..."])
        result.test_output = test_out.strip()
        if test_err:
            result.failures += 1

        result.duration = time.time() - start
        result.pass_ = result.failures == 0

        self.metrics.record_test_result(result.pass_)

        if not result.pass_ and self.auto_fix:
            self._auto_fix_failures(result)

        return result

    def _auto_fix_failures(self, result: VerifyResult) -> None:
        input_ = f"vet: {result.vet_output}\ntest: {result.test_output}"
        suggestions = self.learner.suggest(input_)

        for suggestion in suggestions:
            if suggestion.success_rate <= 0.7:
                continue
            for line in suggestion.action.split("\n"):
                line = line.strip()
                if line == "" or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                self._run_cmd(parts[0], parts[1:])
            time.sleep(2)
            retry = self._run_cmd_raw("go", ["vet", "./..."])
            test_retry = self._run_cmd_raw("go", ["test", "./..."])
            fixed = not retry.err and not test_retry.err
            self.metrics.record_auto_fix(fixed)
            self.learner.record(
                MemoryItem(
                    category="auto_fix",
                    input=input_,
                    output=f"fixed={fixed}\nvet:{retry.out}\ntest:{test_retry.out}",
                    success=fixed,
                )
            )

    def _run_cmd(self, name: str, args: list[str]) -> tuple[str, bool]:
        res = self._run_cmd_raw(name, args)
        return res.out, res.err

    def _run_cmd_raw(self, name: str, args: list[str]) -> CmdResult:
        return _run_cmd_raw(self.project_root, name, args)


def NewVerifier(
    project_root: str,
    auto_fix: bool,
    learner: Learner,
    metrics: IQMetrics,
    perms: PermissionStore,
) -> Verifier:
    return Verifier(project_root, auto_fix, learner, metrics, perms)
