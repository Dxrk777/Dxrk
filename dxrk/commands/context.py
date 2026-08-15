# SPDX-License-Identifier: MIT
"""Context command"""

from __future__ import annotations

import os
import platform
import sys

from .registry import Command, CommandContext, Registry


def register_context_command(reg: Registry) -> None:
    """Registers the `dxrk context` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        out.write("Context\n")
        out.write("───────\n")
        out.write(f"  Working dir:  {os.path.abspath(ctx.cwd)}\n")
        out.write(f"  Platform:     {sys.platform} ({platform.machine()})\n")
        out.write(f"  Python:       {platform.python_version()}\n")
        out.write(f"  User:         {os.environ.get('USER', os.environ.get('USERNAME', 'unknown'))}\n")
        shell = os.environ.get("SHELL") or os.environ.get("COMSPEC", "unknown")
        out.write(f"  Shell:        {shell}\n")
        out.write(f"  Home:         {os.path.expanduser('~')}\n")
        term = os.environ.get("TERM") or "unknown"
        out.write(f"  Terminal:     {term}\n")
        return 0

    cmd = Command(
        name="context",
        short="Show the current execution context",
        run=run,
    )
    reg.add_command(cmd)
