# SPDX-License-Identifier: MIT
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, TextIO

from dxrk.models import AgentID

__all__ = [
    "ParseUninstallFlags",
    "RunUninstall",
    "UninstallResult",
]


@dataclass
class UninstallFlags:
    agents: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    all: bool = False
    yes: bool = False


def ParseUninstallFlags(args: list[str]) -> UninstallFlags:
    from dxrk.cli.install import parse_uninstall_flags

    parsed = parse_uninstall_flags(args)
    return UninstallFlags(
        agents=parsed.agents,
        components=parsed.components,
        all=parsed.all,
        yes=parsed.yes,
    )


@dataclass
class UninstallResult:
    manifest: dict[str, Any] = field(default_factory=dict)
    backup_path: str = ""
    changed_files: list[str] = field(default_factory=list)
    removed_files: list[str] = field(default_factory=list)
    removed_directories: list[str] = field(default_factory=list)
    manual_actions: list[str] = field(default_factory=list)
    agents_removed_from_state: list[AgentID] = field(default_factory=list)


def RunUninstall(args: list[str], stdout: TextIO | None = None) -> Any:
    from dxrk.cli.install import run_uninstall

    return run_uninstall(args, stdout or sys.stdout)
