# SPDX-License-Identifier: MIT
"""Theme command"""

from __future__ import annotations

import json
import os

from .registry import Command, CommandContext, Registry

_THEMES = {
    "default": ("dark", "dark blue/green palette"),
    "dark": ("true", "black background, light text"),
    "light": ("false", "white background, dark text"),
    "dracula": ("true", "dracula color palette"),
    "monokai": ("true", "monokai color palette"),
    "nord": ("true", "nord color palette"),
    "solarized": ("true", "solarized color palette"),
    "github": ("false", "github light palette"),
    "gruvbox": ("true", "gruvbox color palette"),
    "catppuccin": ("true", "catppuccin color palette"),
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
            out.write(f"Current theme: {active}\n\n")
            out.write("NAME\tDARK\tDESCRIPTION\n")
            for name, (dark, desc) in _THEMES.items():
                marker = " *" if name == active else ""
                out.write(f"{name}{marker}\t{dark}\t{desc}\n")
            return 0

        name = ctx.args[0]
        if name not in _THEMES:
            ctx.err.write(f"Error: unknown theme {name}\n")
            return 1
        set_current_theme(name)
        out.write(f"Theme set to {name}\n")
        return 0

    cmd = Command(
        name="theme",
        short="List or set the active theme",
        max_args=1,
        run=run,
    )
    reg.add_command(cmd)
