# SPDX-License-Identifier: MIT
"""External judge: isolated verification without silent auto-fix.

The autonomy-loop verifier used to live inside ``dxrk/autonomy/`` coupled
to the learner, metrics and updater subsystems. As an external judge it
only *observes*: it runs explicit check commands in ``project_root`` and
reports. Fixing is never silent — ``auto_fix`` defaults to ``False`` and
even when enabled it only invokes an explicitly provided ``fix_fn``
(callers wire their own remediation); without one the failure is merely
reported.

stdlib only, no imports from ``dxrk.autonomy``.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field


@dataclass
class VerifyResult:
    pass_: bool = False
    outputs: dict[str, str] = field(default_factory=dict)
    duration: float = 0.0
    failures: int = 0
    auto_fix_attempted: bool = False


FixFn = Callable[[tuple[str, ...]], None]


class Verifier:
    """Runs explicit check commands and reports; never fixes silently."""

    def __init__(
        self,
        project_root: str,
        auto_fix: bool = False,
        fix_fn: FixFn | None = None,
        commands: Sequence[Sequence[str]] | None = None,
    ) -> None:
        self.project_root = project_root
        self.auto_fix = bool(auto_fix)
        self.fix_fn = fix_fn
        self.commands: tuple[tuple[str, ...], ...] = tuple(tuple(c) for c in (commands or ()))

    @staticmethod
    def auto_fix_default() -> bool:
        """Auto-fix ships default-off; callers opt in explicitly."""
        return False

    def verify(self) -> VerifyResult:
        start = time.time()
        result = VerifyResult()
        for cmd in self.commands:
            out, failed = self._run_cmd(cmd)
            result.outputs[" ".join(cmd)] = out
            if failed:
                result.failures += 1
        result.duration = time.time() - start
        result.pass_ = result.failures == 0
        if not result.pass_ and self.auto_fix and self.fix_fn is not None:
            result.auto_fix_attempted = True
            for cmd in self.commands:
                self.fix_fn(cmd)
            retry = self.verify_once()
            result.outputs.update(retry.outputs)
            result.failures = retry.failures
            result.pass_ = retry.pass_
            result.duration = time.time() - start
        return result

    def verify_once(self) -> VerifyResult:
        """Single check pass without any fix attempt (no recursion)."""
        start = time.time()
        result = VerifyResult()
        for cmd in self.commands:
            out, failed = self._run_cmd(cmd)
            result.outputs[" ".join(cmd)] = out
            if failed:
                result.failures += 1
        result.duration = time.time() - start
        result.pass_ = result.failures == 0
        return result

    def _run_cmd(self, cmd: tuple[str, ...]) -> tuple[str, bool]:
        try:
            proc = subprocess.run(
                list(cmd),
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (OSError, ValueError):
            return "", True
        except Exception:  # defensive: a judge never crashes the caller
            return "", True
        text = (proc.stdout or "") + (proc.stderr or "")
        return text.strip(), proc.returncode != 0


def NewVerifier(
    project_root: str,
    auto_fix: bool = False,
    fix_fn: FixFn | None = None,
    commands: Sequence[Sequence[str]] | None = None,
) -> Verifier:
    return Verifier(project_root, auto_fix=auto_fix, fix_fn=fix_fn, commands=commands)
