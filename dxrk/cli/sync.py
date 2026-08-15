# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from dxrk.models import AgentID, Selection

__all__ = [
    "ParseSyncFlags",
    "RunSync",
    "SyncFlags",
    "SyncResult",
]


def ParseSyncFlags(args: list[str]) -> Any:
    from dxrk.cli.install import parse_sync_flags
    return parse_sync_flags(args)


def RunSync(args: list[str]) -> Any:
    from dxrk.cli.install import run_sync
    return run_sync(args)


class SyncResult:
    def __init__(
        self,
        agents: list[AgentID] | None = None,
        selection: Selection | None = None,
        plan: Any = None,
        execution: Any = None,
        verify: Any = None,
        dry_run: bool = False,
        no_op: bool = False,
        files_changed: int = 0,
    ):
        self.agents = agents or []
        self.selection = selection or Selection()
        self.plan = plan
        self.execution = execution
        self.verify = verify
        self.dry_run = dry_run
        self.no_op = no_op
        self.files_changed = files_changed


class SyncFlags:
    def __init__(
        self,
        agents: list[str] | None = None,
        skills: list[str] | None = None,
        sdd_mode: str = "",
        sdd_profile_strategy: str = "",
        strict_tdd: bool = False,
        include_permissions: bool = False,
        include_theme: bool = False,
        dry_run: bool = False,
        profiles: list[dict[str, Any]] | None = None,
    ):
        self.agents = agents or []
        self.skills = skills or []
        self.sdd_mode = sdd_mode
        self.sdd_profile_strategy = sdd_profile_strategy
        self.strict_tdd = strict_tdd
        self.include_permissions = include_permissions
        self.include_theme = include_theme
        self.dry_run = dry_run
        self.profiles = profiles or []
