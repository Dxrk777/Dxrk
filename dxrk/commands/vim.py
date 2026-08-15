# SPDX-License-Identifier: MIT
"""Editor mode toggle command"""

from __future__ import annotations

from .registry import Command, CommandContext, Registry


def register_vim_command(reg: Registry) -> None:
    """Registers the `dxrk vim` command for toggling editing modes."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        out.write("Editor mode toggled\n")
        out.write(
            "Use Escape to switch between INSERT and NORMAL modes when Vim mode is active.\n"
        )
        return 0

    cmd = Command(
        name="vim",
        short="Toggle between Vim and Normal editing modes",
        long=(
            "Toggle the editor input mode between Vim and Normal (readline).\n\n"
            "When Vim mode is enabled:\n"
            "  - Press Escape to toggle between INSERT and NORMAL modes\n"
            "  - Use standard Vim keybindings in NORMAL mode\n\n"
            "When Normal mode is enabled:\n"
            "  - Use standard readline keyboard bindings"
        ),
        run=run,
    )
    reg.add_command(cmd)
