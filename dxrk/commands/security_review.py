# SPDX-License-Identifier: MIT
"""Security review command"""

from __future__ import annotations

import re

from .gitutil import (
    git_current_branch,
    git_default_branch,
    git_diff,
    git_diff_stats,
    git_dir,
)
from .registry import Command, CommandContext, Registry

_SUSPICIOUS_PATTERNS = (
    re.compile(r"(?i)api[_-]?key\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
    re.compile(r"(?i)secret\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
    re.compile(r"(?i)password\s*[=:]\s*['\"][^'\"]{6,}['\"]"),
    re.compile(r"BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(r"(?i)aws_access_key_id"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}"),
    re.compile(r"eval\s*\(\s*(?:exec|system|shell)\s*\("),
    re.compile(r"(?i)\bexec\s*\(\s*['\"]"),
)


def register_security_review_command(reg: Registry) -> None:
    """Registers the `dxrk security review` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        wd = ctx.cwd

        if not git_dir(wd).ok:
            ctx.err.write("Error: no es un repositorio git\n")
            return 1

        branch = git_current_branch(wd) or "(detached)"
        since = git_default_branch(wd)

        result = git_diff(wd, since)
        if not result.ok:
            ctx.err.write(f"Error: al obtener el diff: {result.err.strip() or result.out.strip()}\n")
            return 1
        diff = result.out

        files, additions, deletions = git_diff_stats(diff)

        out.write("🔒 Revisión de seguridad\n")
        out.write("========================\n")
        out.write(f"Rama: {branch}\n")
        out.write(f"Archivos cambiados: {files}\n")
        out.write(f"Adiciones: {additions}, Eliminaciones: {deletions}\n\n")

        findings: list[str] = []
        for i, line in enumerate(diff.splitlines(), start=1):
            if line.startswith("+") and not line.startswith("+++"):
                for pattern in _SUSPICIOUS_PATTERNS:
                    if pattern.search(line):
                        findings.append(f"  - línea {i}: posible {pattern.pattern[:40]}")
                        break

        if not findings:
            out.write("✅ No se detectaron problemas de seguridad en los cambios.\n")
        else:
            out.write("Posibles problemas de seguridad:\n")
            for finding in findings:
                out.write(finding + "\n")

        out.write("\nNota: revisa el diff contra la rama predeterminada antes de fusionar.\n")
        return 0

    cmd = Command(
        name="security review",
        short="Analizar los cambios en busca de problemas de seguridad",
        long="Revisar el diff contra la rama predeterminada para patrones comunes de vulnerabilidad.",
        run=run,
    )
    reg.add_command(cmd)
