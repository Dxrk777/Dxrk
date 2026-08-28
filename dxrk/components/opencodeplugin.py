# SPDX-License-Identifier: MIT
"""OpenCode community plugin definitions — ports internal/components/opencodeplugin/.

Plugin definition metadata and installation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from dxrk.components import filemerge
from dxrk.models import OpenCodeCommunityPluginID


@dataclass
class Definition:
    id: OpenCodeCommunityPluginID
    name: str
    package_name: str
    repo_url: str
    owner: str
    repo: str
    description: str


@dataclass
class Result:
    Changed: bool = False
    Files: list[str] = field(default_factory=list)


_DEFINITIONS = [
    Definition(
        id=OpenCodeCommunityPluginID.SUB_AGENT_STATUSLINE,
        name="Sub-agent Statusline",
        package_name="opencode-subagent-statusline",
        repo_url="https://github.com/Dxrk777/sub-agent-statusline",
        owner="Dxrk777",
        repo="sub-agent-statusline",
        description="OpenCode sidebar/statusline for sub-agent activity",
    ),
    Definition(
        id=OpenCodeCommunityPluginID.SDD_MEMORY_PLUGIN,
        name="SDD Memory Manager",
        package_name="opencode-sdd-memory-manage",
        repo_url="https://github.com/Dxrk777/sdd-memory-plugin",
        owner="Dxrk777",
        repo="sdd-memory-plugin",
        description="OpenCode TUI for SDD profiles and Memory memories",
    ),
]


def definitions() -> list[Definition]:
    return list(_DEFINITIONS)


def definition_for(id: OpenCodeCommunityPluginID) -> Definition | None:
    for defn in _DEFINITIONS:
        if defn.id == id:
            return defn
    return None


def install(home_dir: str, id: OpenCodeCommunityPluginID) -> Result:
    defn = definition_for(id)
    if defn is None:
        raise ValueError(f"unknown OpenCode community plugin {id!r}")

    opencode_dir = os.path.join(home_dir, ".config", "opencode")
    os.makedirs(opencode_dir, mode=0o755, exist_ok=True)

    tui_path = os.path.join(opencode_dir, "tui.json")
    written = _ensure_tui_plugin(tui_path, defn.package_name)

    return Result(Changed=written, Files=[tui_path])


def _ensure_tui_plugin(path: str, pkg: str) -> bool:
    root: dict = {"$schema": "https://opencode.ai/tui.json"}
    try:
        with open(path) as f:
            data = f.read()
        if data.strip():
            root = json.loads(data)
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as e:
        raise ValueError(f"parse OpenCode TUI config {path!r}: {e}") from e

    plugins = _string_slice(root.get("plugin"))
    if pkg in plugins:
        return False
    plugins.append(pkg)
    root["plugin"] = plugins

    out = (json.dumps(root, indent=2) + "\n").encode("utf-8")
    wr = filemerge.write_file_atomic(path, out, 0o644)
    return wr.Changed


def _string_slice(value) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item)
    return result
