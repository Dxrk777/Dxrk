# SPDX-License-Identifier: MIT
"""Diff command"""

from __future__ import annotations

from .gitutil import git_diff, git_diff_cached, git_dir
from .registry import Command, CommandContext, Flag, Registry


def register_diff_command(reg: Registry) -> None:
    """Registers the `dxrk diff` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        wd = ctx.cwd

        if not git_dir(wd).ok:
            ctx.err.write("Error: not a git repository\n")
            return 1

        since = ctx.flag_str("since")
        if since:
            result = git_diff(wd, since)
        elif ctx.flag_bool("staged"):
            result = git_diff_cached(wd)
        else:
            result = git_diff(wd)

        if not result.ok:
            ctx.err.write(f"Error: get diff: {result.err.strip() or result.out.strip()}\n")
            return 1
        out.write(result.out)
        return 0

    cmd = Command(
        name="diff",
        short="Show git diff",
        long="Show working tree changes, optionally staged or since a ref.",
        flags={
            "staged": Flag("staged", is_bool=True, default=False, shorthand="s", help="Show staged changes"),
            "since": Flag("since", default="", help="Show changes since a ref"),
        },
        run=run,
    )
    reg.add_command(cmd)
