# SPDX-License-Identifier: MIT
"""Embedded assets access"""

from __future__ import annotations

import os

_ASSETS_ROOT = os.path.join(os.path.dirname(__file__), "..", "assets")


def _asset_path(path: str) -> str:
    return os.path.normpath(os.path.join(_ASSETS_ROOT, path))


def read(path: str, root: str | None = None) -> str | None:
    """Read an embedded asset file. Returns None if not found."""
    base = root or _ASSETS_ROOT
    full = os.path.normpath(os.path.join(base, path))
    if not full.startswith(os.path.normpath(base)):
        return None
    try:
        with open(full) as f:
            return f.read()
    except FileNotFoundError:
        return None


def must_read(path: str, root: str | None = None) -> str:
    """Read an embedded asset file or raise."""
    content = read(path, root)
    if content is None:
        raise FileNotFoundError(f"assets: {path} not found")
    return content


def sdd_commands_asset_dir(agent_id: str) -> str:
    from dxrk.models import AgentID
    if agent_id == AgentID.CLAUDE_CODE:
        return "claude/commands"
    return "opencode/commands"
