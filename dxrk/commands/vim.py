# SPDX-License-Identifier: MIT
"""Editor mode toggle command"""

from __future__ import annotations

from .registry import Command, CommandContext, Registry


def register_vim_command(reg: Registry) -> None:
    """Registers the `dxrk vim` command for toggling editing modes."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        out.write("Modo de editor alternado\n")
        out.write("Usa Escape para alternar entre los modos INSERT y NORMAL cuando el modo Vim está activo.\n")
        return 0

    cmd = Command(
        name="vim",
        short="Alternar entre los modos de edición Vim y Normal",
        long=(
            "Alternar el modo de entrada del editor entre Vim y Normal (readline).\n\n"
            "Cuando el modo Vim está activado:\n"
            "  - Presiona Escape para alternar entre los modos INSERT y NORMAL\n"
            "  - Usa los atajos estándar de Vim en modo NORMAL\n\n"
            "Cuando el modo Normal está activado:\n"
            "  - Usa los atajos estándar de teclado readline"
        ),
        run=run,
    )
    reg.add_command(cmd)
