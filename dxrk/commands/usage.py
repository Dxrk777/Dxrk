# SPDX-License-Identifier: MIT
"""Usage command"""

from __future__ import annotations

from .registry import Command, CommandContext, Registry


def register_usage_command(reg: Registry) -> None:
    """Registers the `dxrk usage` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        if ctx.reg is None:
            ctx.err.write("Error: no hay registro disponible\n")
            return 1

        out.write("Uso: dxrk <comando> [flags]\n\n")
        out.write("Comandos:\n")
        for cmd in ctx.reg.commands():
            if " " in cmd.name:
                continue
            short = cmd.short or ""
            out.write(f"  {cmd.name:<22} {short}\n")
        out.write("\nSubcomandos:\n")
        for cmd in ctx.reg.commands():
            if " " in cmd.name:
                short = cmd.short or ""
                out.write(f"  {cmd.name:<22} {short}\n")
        return 0

    cmd = Command(
        name="usage",
        short="Mostrar el resumen de uso",
        run=run,
    )
    reg.add_command(cmd)
