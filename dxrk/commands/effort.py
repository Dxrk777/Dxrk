# SPDX-License-Identifier: MIT
"""Effort level command"""

from __future__ import annotations

from dxrk.strconst import StrMedium2

from .registry import Command, CommandContext, Registry

valid_effort_levels = ["low", StrMedium2, "high", "max", "auto"]

_EFFORT_DESCRIPTIONS = {
    "low": "Quick, straightforward implementation",
    StrMedium2: "Balanced approach with standard testing",
    "high": "Comprehensive implementation with extensive testing",
    "max": "Maximum capability with deepest reasoning",
    "auto": "Default effort level for the current model",
}


def effort_description(level: str) -> str:
    """Returns the human-readable description for an effort level."""
    return _EFFORT_DESCRIPTIONS.get(level, "")


def register_effort_command(reg: Registry) -> None:
    """Registers the `dxrk effort` command for setting the effort level."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out

        if len(ctx.args) == 0:
            out.write("Current effort level: auto\n")
            out.write("\n")
            out.write("Available levels:\n")
            for level in valid_effort_levels:
                out.write(f"  {level}\n")
            return 0

        level = ctx.args[0].strip().lower()
        if level == "unset":
            level = "auto"

        if level not in valid_effort_levels:
            ctx.err.write(
                f"Error: invalid effort level: {level}. "
                f"Valid options: {', '.join(valid_effort_levels)}\n"
            )
            return 1

        description = effort_description(level)
        out.write(f"Effort level set to {level}: {description}\n")
        return 0

    cmd = Command(
        name="effort",
        short="Set the reasoning effort level",
        long=(
            "Set the effort level for model reasoning.\n\n"
            "Effort levels:\n"
            "  low    - Quick, straightforward implementation\n"
            "  medium - Balanced approach with standard testing\n"
            "  high   - Comprehensive implementation with extensive testing\n"
            "  max    - Maximum capability with deepest reasoning\n"
            "  auto   - Use the default effort level for the current model\n\n"
            "If no level is provided, shows the current effort level."
        ),
        max_args=1,
        run=run,
    )
    reg.add_command(cmd)
