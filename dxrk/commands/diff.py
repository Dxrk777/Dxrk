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
            ctx.err.write("Error: no es un repositorio git\n")
            return 1

        since = ctx.flag_str("since")
        if since:
            result = git_diff(wd, since)
        elif ctx.flag_bool("staged"):
            result = git_diff_cached(wd)
        else:
            result = git_diff(wd)

        if not result.ok:
            ctx.err.write(f"Error: al obtener el diff: {result.err.strip() or result.out.strip()}\n")
            return 1
        out.write(result.out)
        return 0

    cmd = Command(
        name="diff",
        short="Mostrar el diff de git",
        long="Mostrar los cambios en el directorio de trabajo, opcionalmente los preparados o desde una ref.",
        flags={
            "staged": Flag("staged", is_bool=True, default=False, shorthand="s", help="Mostrar los cambios preparados"),
            "since": Flag("since", default="", help="Mostrar los cambios desde una ref"),
        },
        run=run,
    )
    reg.add_command(cmd)
