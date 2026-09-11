# SPDX-License-Identifier: MIT
"""Keybindings command"""

from __future__ import annotations

import json

from .registry import Command, CommandContext, Registry

_KEYBINDINGS = {
    "ctrl+p": "Paleta de comandos",
    "ctrl+e": "Alternar modo de editor",
    "ctrl+r": "Reanudar sesión",
    "ctrl+t": "Selector de tema",
    "ctrl+s": "Guardar sesión",
    "ctrl+k": "Limpiar salida",
    "ctrl+n": "Nueva sesión",
    "ctrl+d": "Eliminar sesión",
    "escape": "Alternar INSERT/NORMAL en modo vim",
    "ctrl+c": "Interrumpir",
    "ctrl+l": "Limpiar pantalla",
    "ctrl+a": "Inicio de línea",
    "ctrl+e2": "Fin de línea",
}


def register_keybindings_command(reg: Registry) -> None:
    """Registers the `dxrk keybindings` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        if ctx.flag_bool("json"):
            out.write(json.dumps(_KEYBINDINGS, indent=2) + "\n")
            return 0
        out.write("TECLA\tACCIÓN\n")
        for key, action in _KEYBINDINGS.items():
            out.write(f"{key}\t{action}\n")
        return 0

    cmd = Command(
        name="keybindings",
        short="Mostrar los atajos de teclado predeterminados",
        run=run,
    )
    reg.add_command(cmd)
