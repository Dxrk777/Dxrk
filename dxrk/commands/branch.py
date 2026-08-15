# SPDX-License-Identifier: MIT
"""Branch command"""

from __future__ import annotations

from .gitutil import git_dir, run_git
from .registry import Command, CommandContext, Flag, Registry


def register_branch_command(reg: Registry) -> None:
    """Registers the `dxrk branch` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        wd = ctx.cwd

        if not git_dir(wd).ok:
            ctx.err.write("Error: not a git repository\n")
            return 1

        if ctx.flag_bool("delete"):
            name = ctx.args[0] if ctx.args else ""
            if not name:
                ctx.err.write("Error: branch name required for delete\n")
                return 1
            flag = "-D" if ctx.flag_bool("force") else "-d"
            result = run_git(wd, "branch", flag, name)
            if not result.ok:
                ctx.err.write(
                    f"Error: delete branch: {result.err.strip() or result.out.strip()}\n"
                )
                return 1
            out.write(result.out)
            return 0

        if ctx.flag_bool("switch"):
            name = ctx.args[0] if ctx.args else ""
            if not name:
                ctx.err.write("Error: branch name required for switch\n")
                return 1
            result = run_git(wd, "checkout", name)
            if not result.ok:
                ctx.err.write(
                    f"Error: switch branch: {result.err.strip() or result.out.strip()}\n"
                )
                return 1
            out.write(result.out)
            return 0

        if ctx.flag_bool("create"):
            name = ctx.args[0] if ctx.args else ""
            if not name:
                ctx.err.write("Error: branch name required for create\n")
                return 1
            result = run_git(wd, "checkout", "-b", name)
            if not result.ok:
                ctx.err.write(
                    f"Error: create branch: {result.err.strip() or result.out.strip()}\n"
                )
                return 1
            out.write(result.out)
            return 0

        result = run_git(wd, "branch")
        if not result.ok:
            ctx.err.write(
                f"Error: list branches: {result.err.strip() or result.out.strip()}\n"
            )
            return 1
        out.write(result.out)
        return 0

    cmd = Command(
        name="branch",
        short="List, switch, create, or delete branches",
        flags={
            "list": Flag("list", is_bool=True, default=False, shorthand="l", help="List branches"),
            "switch": Flag("switch", is_bool=True, default=False, shorthand="s", help="Switch to a branch"),
            "delete": Flag("delete", is_bool=True, default=False, shorthand="d", help="Delete a branch"),
            "create": Flag("create", is_bool=True, default=False, shorthand="c", help="Create and switch to a branch"),
            "force": Flag("force", is_bool=True, default=False, help="Force delete"),
        },
        run=run,
    )
    reg.add_command(cmd)
