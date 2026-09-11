# SPDX-License-Identifier: MIT
"""Theme command"""

from __future__ import annotations

import json
import os

from .registry import Command, CommandContext, Registry

_THEMES = {
    "default": ("dark", "paleta azul oscuro/verde"),
    "dark": ("true", "fondo negro, texto claro"),
    "light": ("false", "fondo blanco, texto oscuro"),
    "dracula": ("true", "paleta de colores dracula"),
    "monokai": ("true", "paleta de colores monokai"),
    "nord": ("true", "paleta de colores nord"),
    "solarized": ("true", "paleta de colores solarized"),
    "github": ("false", "paleta clara github"),
    "gruvbox": ("true", "paleta de colores gruvbox"),
    "catppuccin": ("true", "paleta de colores catppuccin"),
}


def theme_state_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".dxrk", "theme.json")


def current_theme() -> str:
    try:
        with open(theme_state_path(), encoding="utf-8") as f:
            return str(json.load(f).get("theme", "default"))
    except (OSError, json.JSONDecodeError):
        return "default"


def set_current_theme(name: str) -> None:
    os.makedirs(os.path.dirname(theme_state_path()), mode=0o750, exist_ok=True)
    with open(theme_state_path(), "w", encoding="utf-8") as f:
        json.dump({"theme": name}, f)
    os.chmod(theme_state_path(), 0o600)


def register_theme_command(reg: Registry) -> None:
    """Registers the `dxrk theme` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        if not ctx.args:
            active = current_theme()
            out.write(f"Tema actual: {active}\n\n")
            out.write("NOMBRE\tOSCURO\tDESCRIPCIÓN\n")
            for name, (dark, desc) in _THEMES.items():
                marker = " *" if name == active else ""
                out.write(f"{name}{marker}\t{dark}\t{desc}\n")
            return 0

        name = ctx.args[0]
        if name not in _THEMES:
            ctx.err.write(f"Error: tema desconocido {name}\n")
            return 1
        set_current_theme(name)
        out.write(f"Tema fijado en {name}\n")
        return 0

    cmd = Command(
        name="theme",
        short="Listar o fijar el tema activo",
        max_args=1,
        run=run,
    )
    reg.add_command(cmd)
