# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dxrk.models import AgentID, ComponentID

__all__ = [
    "DryRunMode",
    "build_dryrun_report",
]


@dataclass
class DryRunMode:
    agents: list[AgentID] = field(default_factory=list)
    unsupported_agents: list[AgentID] = field(default_factory=list)
    persona: str = ""
    preset: str = ""
    sdd_mode: str = ""
    components: list[ComponentID] = field(default_factory=list)
    added_dependencies: list[ComponentID] = field(default_factory=list)
    os_name: str = ""
    linux_distro: str = ""
    package_manager: str = ""
    supported: bool = False
    prepare_steps: int = 0
    apply_steps: int = 0


def build_dryrun_report(result: Any) -> str:
    from dxrk.cli.install import render_dry_run

    return render_dry_run(result)
