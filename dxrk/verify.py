# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "Check",
    "CheckResult",
    "CheckStatus",
    "PostInstallVerifier",
    "Report",
    "VerificationScenario",
    "build_report",
    "render_report",
    "run_checks",
]


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WARNING = "warning"


@dataclass
class Check:
    id: str = ""
    description: str = ""
    run: Callable[[], str | None] | None = None
    soft: bool = False


@dataclass
class CheckResult:
    id: str = ""
    description: str = ""
    status: CheckStatus = CheckStatus.SKIPPED
    error: str = ""


def run_checks(checks: list[Check]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in checks:
        result = CheckResult(id=check.id, description=check.description)
        if check.run is None:
            result.status = CheckStatus.SKIPPED
            result.error = "check not implemented"
            results.append(result)
            continue

        err = check.run()
        if err is not None:
            result.status = CheckStatus.WARNING if check.soft else CheckStatus.FAILED
            result.error = err
            results.append(result)
            continue

        result.status = CheckStatus.PASSED
        results.append(result)

    return results


_READY_MESSAGE = "You\u2019re ready. Run `claude` or `opencode` and start building."


@dataclass
class Report:
    checks: list[CheckResult] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    warnings: int = 0
    ready: bool = False
    final_note: str = ""


def build_report(results: list[CheckResult]) -> Report:
    report = Report(checks=list(results))
    for result in results:
        if result.status == CheckStatus.PASSED:
            report.passed += 1
        elif result.status == CheckStatus.FAILED:
            report.failed += 1
        elif result.status == CheckStatus.SKIPPED:
            report.skipped += 1
        elif result.status == CheckStatus.WARNING:
            report.warnings += 1

    report.ready = report.failed == 0
    if report.ready:
        report.final_note = _READY_MESSAGE
    else:
        report.final_note = "Installation completed with verification issues. Run repair on failed checks."

    return report


def render_report(report: Report) -> str:
    lines: list[str] = []
    lines.append(
        f"Verification checks: {report.passed} passed, {report.failed} failed, "
        f"{report.warnings} warnings, {report.skipped} skipped"
    )

    status_map = {
        CheckStatus.PASSED: "[ok]",
        CheckStatus.FAILED: "[!!]",
        CheckStatus.WARNING: "[??]",
        CheckStatus.SKIPPED: "[--]",
    }

    for check in report.checks:
        label = status_map.get(check.status, "[ ]")
        line = f"{label} {check.id}"
        if check.description:
            line += f" - {check.description}"
        if check.error:
            line += f" ({check.error})"
        lines.append(line)

    lines.append(report.final_note)
    return "\n".join(lines) + "\n"


class VerificationScenario:
    def __init__(self, name: str = "", checks: list[Check] | None = None) -> None:
        self.name = name
        self.checks = list(checks) if checks else []

    def run(self) -> Report:
        return build_report(run_checks(self.checks))


class PostInstallVerifier:
    def __init__(self, scenarios: list[VerificationScenario] | None = None) -> None:
        self.scenarios = list(scenarios) if scenarios else []

    def add_scenario(self, scenario: VerificationScenario) -> None:
        self.scenarios.append(scenario)

    def verify_installation(self) -> Report:
        all_results: list[CheckResult] = []
        for scenario in self.scenarios:
            all_results.extend(scenario.run().checks)
        return build_report(all_results)

    def run_all(self) -> Report:
        return self.verify_installation()
