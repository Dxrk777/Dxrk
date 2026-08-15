# SPDX-License-Identifier: MIT
import os
from typing import NamedTuple

from dxrk.agents.registry import Registry
from dxrk.models import AgentID


class InstalledAgent(NamedTuple):
    id: AgentID
    config_dir: str


def discover_installed(reg: Registry, home_dir: str = "") -> list[InstalledAgent]:
    out: list[InstalledAgent] = []
    for a_id in reg.supported_agents:
        adapter = reg.get(a_id)
        if adapter is None:
            continue
        d = adapter.global_config_dir(home_dir)
        if not d:
            continue
        if os.path.isdir(d):
            out.append(InstalledAgent(id=a_id, config_dir=d))
    return out


def config_roots_for_backup(reg: Registry, home_dir: str = "") -> list[str]:
    installed = discover_installed(reg, home_dir)
    seen: set[str] = set()
    dirs: list[str] = []
    for a in installed:
        if a.config_dir not in seen:
            seen.add(a.config_dir)
            dirs.append(a.config_dir)
    return dirs
