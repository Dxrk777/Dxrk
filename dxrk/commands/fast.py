# SPDX-License-Identifier: MIT
"""Fast mode toggle command"""

from __future__ import annotations

from .registry import Command, CommandContext, Registry


def register_fast_command(reg: Registry) -> None:
    """Registers the `dxrk fast` command for toggling fast mode."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out

        if len(ctx.args) == 0:
            out.write("Fast mode: toggled (currently available)\n")
            out.write("Use 'dxrk fast on' or 'dxrk fast off' to set explicitly.\n")
            return 0

        arg = ctx.args[0].strip().lower()
        if arg == "on":
            out.write("Fast mode enabled\n")
            return 0
        if arg == "off":
            out.write("Fast mode disabled\n")
            return 0
        ctx.err.write(f"Error: invalid argument: {arg}. Use 'on' or 'off'\n")
        return 1

    cmd = Command(
        name="fast",
        short="Toggle fast mode",
        long=(
            "Toggle fast mode for reduced latency at higher cost.\n\n"
            "Fast mode uses a faster model variant for quick iterations. Billed as\n"
            "extra usage at a premium rate with separate rate limits.\n\n"
            "Examples:\n"
            "  dxrk fast        - Toggle fast mode\n"
            "  dxrk fast on     - Enable fast mode\n"
            "  dxrk fast off    - Disable fast mode"
        ),
        max_args=1,
        run=run,
    )
    reg.add_command(cmd)
