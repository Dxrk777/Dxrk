# SPDX-License-Identifier: MIT
"""Agents command"""

from __future__ import annotations

import os

from .registry import Command, CommandContext, Registry

_AGENT_EXTENSIONS = (".md", ".json", ".yaml", ".yml")


def _scan_agent_dirs(wd: str) -> list[tuple[str, str, str]]:
    """Returns (name, path, description) for every discovered agent file."""
    roots = [
        os.path.join(os.path.expanduser("~"), ".dxrk", "agents"),
        os.path.join(os.path.abspath(wd), ".dxrk", "agents"),
    ]
    agents: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            full = os.path.join(root, name)
            if os.path.isdir(full):
                full = os.path.join(full, "agent.md")
                if not os.path.isfile(full):
                    continue
            if not name.lower().endswith(_AGENT_EXTENSIONS):
                continue
            key = os.path.splitext(os.path.basename(name))[0]
            if key in seen:
                continue
            seen.add(key)
            description = _read_description(full)
            agents.append((key, full, description))
    return agents


def _read_description(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("# "):
                    continue
                if stripped:
                    return stripped[:80]
    except OSError:
        pass
    return ""


def register_agents_command(reg: Registry) -> None:
    """Registers the `dxrk agents` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        agents = _scan_agent_dirs(ctx.cwd)
        if not agents:
            out.write("No agents found.\n")
            out.write("Add agent files under ~/.dxrk/agents or .dxrk/agents.\n")
            return 0
        out.write("NAME\tDESCRIPTION\tPATH\n")
        for name, path, description in agents:
            out.write(f"{name}\t{description}\t{path}\n")
        return 0

    cmd = Command(
        name="agents",
        short="List available agents",
        run=run,
    )
    reg.add_command(cmd)
