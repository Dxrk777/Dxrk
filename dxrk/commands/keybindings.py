# SPDX-License-Identifier: MIT
"""Keybindings command"""

from __future__ import annotations

import json

from .registry import Command, CommandContext, Registry

_KEYBINDINGS = {
    "ctrl+p": "Command palette",
    "ctrl+e": "Editor mode toggle",
    "ctrl+r": "Resume session",
    "ctrl+t": "Theme picker",
    "ctrl+s": "Save session",
    "ctrl+k": "Clear output",
    "ctrl+n": "New session",
    "ctrl+d": "Delete session",
    "escape": "Switch INSERT/NORMAL in vim mode",
    "ctrl+c": "Interrupt",
    "ctrl+l": "Clear screen",
    "ctrl+a": "Beginning of line",
    "ctrl+e2": "End of line",
}


def register_keybindings_command(reg: Registry) -> None:
    """Registers the `dxrk keybindings` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        if ctx.flag_bool("json"):
            out.write(json.dumps(_KEYBINDINGS, indent=2) + "\n")
            return 0
        out.write("KEY\tACTION\n")
        for key, action in _KEYBINDINGS.items():
            out.write(f"{key}\t{action}\n")
        return 0

    cmd = Command(
        name="keybindings",
        short="Show the default keybindings",
        run=run,
    )
    reg.add_command(cmd)
