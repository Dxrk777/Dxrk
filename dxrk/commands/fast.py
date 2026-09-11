# SPDX-License-Identifier: MIT
"""Fast mode toggle command"""

from __future__ import annotations

from .registry import Command, CommandContext, Registry


def register_fast_command(reg: Registry) -> None:
    """Registers the `dxrk fast` command for toggling fast mode."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out

        if len(ctx.args) == 0:
            out.write("Modo rápido: alternado (disponible actualmente)\n")
            out.write("Usa 'dxrk fast on' o 'dxrk fast off' para fijarlo explícitamente.\n")
            return 0

        arg = ctx.args[0].strip().lower()
        if arg == "on":
            out.write("Modo rápido activado\n")
            return 0
        if arg == "off":
            out.write("Modo rápido desactivado\n")
            return 0
        ctx.err.write(f"Error: argumento inválido: {arg}. Usa 'on' o 'off'\n")
        return 1

    cmd = Command(
        name="fast",
        short="Alternar el modo rápido",
        long=(
            "Alternar el modo rápido para menor latencia a mayor costo.\n\n"
            "El modo rápido usa una variante más veloz del modelo para iteraciones rápidas. Se factura\n"
            "como uso adicional con una tarifa mayor y límites separados.\n\n"
            "Ejemplos:\n"
            "  dxrk fast        - Alternar el modo rápido\n"
            "  dxrk fast on     - Activar el modo rápido\n"
            "  dxrk fast off    - Desactivar el modo rápido"
        ),
        max_args=1,
        run=run,
    )
    reg.add_command(cmd)
