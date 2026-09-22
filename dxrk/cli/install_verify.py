# SPDX-License-Identifier: MIT
"""Minimal post-apply verification types for the install runtimes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

# ─── Minimal verify types (internal/verify pending) ──────────────────


@dataclass
class _VerifyCheck:
    id: str = ""
    description: str = ""
    soft: bool = False
    error: str = ""


@dataclass
class _VerifyReport:
    checks: list[_VerifyCheck] = field(default_factory=list)
    ready: bool = True
    final_note: str = ""


def _run_checks(checks: list[Callable[[], str | None]]) -> list[_VerifyCheck]:
    results: list[_VerifyCheck] = []
    for i, check_fn in enumerate(checks):
        cid = getattr(check_fn, "_cid", f"check:{i}")
        desc = getattr(check_fn, "_desc", "")
        soft = getattr(check_fn, "_soft", False)
        err = check_fn()
        results.append(_VerifyCheck(id=cid, description=desc, soft=soft, error=err or ""))
    return results


def _build_report(checks: list[_VerifyCheck]) -> _VerifyReport:
    ready = True
    for c in checks:
        if c.error and not c.soft:
            ready = False
    return _VerifyReport(checks=checks, ready=ready)


def _render_report(report: _VerifyReport) -> str:
    lines: list[str] = []
    for c in report.checks:
        if c.error:
            marker = "WARN" if c.soft else "FAIL"
            lines.append(f"  [{marker}] {c.id}: {c.error}")
        else:
            lines.append(f"  [PASS] {c.id}")
    if report.final_note:
        lines.append("")
        lines.append(report.final_note)
    return "\n".join(lines)
