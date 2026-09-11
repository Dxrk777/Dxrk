# SPDX-License-Identifier: MIT
"""Doctor command"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dxrk.verify import Check, run_checks

from .gitutil import detect_gh, git_dir
from .registry import Command, CommandContext, Registry


@dataclass
class DoctorReport:
    """Aggregated doctor output."""

    checks: list[str] = field(default_factory=list)

    def add(self, line: str) -> None:
        self.checks.append(line)


def run_doctor(ctx: CommandContext, report: DoctorReport | None = None) -> DoctorReport:
    """Runs all health checks and appends their output to the report."""
    if report is None:
        report = DoctorReport()

    wd = ctx.cwd

    def check_git() -> str | None:
        if not git_dir(wd).ok:
            return "no es un repositorio git"
        return None

    def check_gh() -> str | None:
        if not detect_gh():
            return "CLI gh no encontrada"
        return None

    def check_python() -> str | None:
        return None

    def check_config() -> str | None:
        path = os.path.join(os.path.expanduser("~"), ".dxrk", "config.yaml")
        if not os.path.exists(path):
            return "no hay configuración de usuario en ~/.dxrk/config.yaml"
        return None

    checks = [
        Check(id="git", description="Repositorio git disponible", run=check_git, soft=False),
        Check(id="gh", description="CLI de GitHub instalada", run=check_gh, soft=True),
        Check(id="python", description="Runtime de Python", run=check_python, soft=False),
        Check(id="config", description="Configuración presente", run=check_config, soft=True),
    ]
    result = run_checks(checks)
    for line in result.output if hasattr(result, "output") else []:
        report.add(line)
    return report


def register_doctor_command(reg: Registry) -> None:
    """Registers the `dxrk doctor` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        report = run_doctor(ctx)
        if not report.checks:
            out.write("No se ejecutó ninguna revisión.\n")
            return 0
        for line in report.checks:
            out.write(line + "\n")
        return 0

    cmd = Command(
        name="doctor",
        short="Ejecutar revisiones de estado",
        run=run,
    )
    reg.add_command(cmd)
