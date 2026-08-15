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
            ctx.err.write("Error: not a git repository\n")
            return 1

        branch = git_current_branch(wd) or "(detached)"
        since = git_default_branch(wd)

        result = git_diff(wd, since)
        if not result.ok:
            ctx.err.write(
                f"Error: get diff: {result.err.strip() or result.out.strip()}\n"
            )
            return 1
        diff = result.out

        files, additions, deletions = git_diff_stats(diff)

        out.write("🔒 Security Review\n")
        out.write("==================\n")
        out.write(f"Branch: {branch}\n")
        out.write(f"Files changed: {files}\n")
        out.write(f"Additions: {additions}, Deletions: {deletions}\n\n")

        findings: list[str] = []
        for i, line in enumerate(diff.splitlines(), start=1):
            if line.startswith("+") and not line.startswith("+++"):
                for pattern in _SUSPICIOUS_PATTERNS:
                    if pattern.search(line):
                        findings.append(f"  - line {i}: possible {pattern.pattern[:40]}")
                        break

        if not findings:
            out.write("✅ No security issues detected in the changes.\n")
        else:
            out.write("Potential security concerns:\n")
            for finding in findings:
                out.write(finding + "\n")

        out.write(
            "\nNote: Review the diff against the default branch before merging.\n"
        )
        return 0

    cmd = Command(
        name="security review",
        short="Scan changes for security issues",
        long="Review the diff against the default branch for common vulnerability patterns.",
        run=run,
    )
    reg.add_command(cmd)
