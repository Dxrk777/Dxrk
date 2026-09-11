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
        out.write("Contexto\n")
        out.write("────────\n")
        out.write(f"  Directorio de trabajo:  {os.path.abspath(ctx.cwd)}\n")
        out.write(f"  Plataforma:             {sys.platform} ({platform.machine()})\n")
        out.write(f"  Python:                 {platform.python_version()}\n")
        out.write(f"  Usuario:                {os.environ.get('USER', os.environ.get('USERNAME', 'desconocido'))}\n")
        shell = os.environ.get("SHELL") or os.environ.get("COMSPEC", "desconocida")
        out.write(f"  Shell:                  {shell}\n")
        out.write(f"  Inicio:                 {os.path.expanduser('~')}\n")
        term = os.environ.get("TERM") or "desconocida"
        out.write(f"  Terminal:               {term}\n")
        return 0

    cmd = Command(
        name="context",
        short="Mostrar el contexto de ejecución actual",
        run=run,
    )
    reg.add_command(cmd)
