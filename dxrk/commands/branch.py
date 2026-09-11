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
            ctx.err.write("Error: no es un repositorio git\n")
            return 1

        if ctx.flag_bool("delete"):
            name = ctx.args[0] if ctx.args else ""
            if not name:
                ctx.err.write("Error: se requiere el nombre de la rama para eliminar\n")
                return 1
            flag = "-D" if ctx.flag_bool("force") else "-d"
            result = run_git(wd, "branch", flag, name)
            if not result.ok:
                ctx.err.write(f"Error: al eliminar la rama: {result.err.strip() or result.out.strip()}\n")
                return 1
            out.write(result.out)
            return 0

        if ctx.flag_bool("switch"):
            name = ctx.args[0] if ctx.args else ""
            if not name:
                ctx.err.write("Error: se requiere el nombre de la rama para cambiar\n")
                return 1
            result = run_git(wd, "checkout", name)
            if not result.ok:
                ctx.err.write(f"Error: al cambiar de rama: {result.err.strip() or result.out.strip()}\n")
                return 1
            out.write(result.out)
            return 0

        if ctx.flag_bool("create"):
            name = ctx.args[0] if ctx.args else ""
            if not name:
                ctx.err.write("Error: se requiere el nombre de la rama para crear\n")
                return 1
            result = run_git(wd, "checkout", "-b", name)
            if not result.ok:
                ctx.err.write(f"Error: al crear la rama: {result.err.strip() or result.out.strip()}\n")
                return 1
            out.write(result.out)
            return 0

        result = run_git(wd, "branch")
        if not result.ok:
            ctx.err.write(f"Error: al listar las ramas: {result.err.strip() or result.out.strip()}\n")
            return 1
        out.write(result.out)
        return 0

    cmd = Command(
        name="branch",
        short="Listar, cambiar, crear o eliminar ramas",
        flags={
            "list": Flag("list", is_bool=True, default=False, shorthand="l", help="Listar las ramas"),
            "switch": Flag("switch", is_bool=True, default=False, shorthand="s", help="Cambiar a una rama"),
            "delete": Flag("delete", is_bool=True, default=False, shorthand="d", help="Eliminar una rama"),
            "create": Flag(
                "create", is_bool=True, default=False, shorthand="c", help="Crear una rama y cambiar a ella"
            ),
            "force": Flag("force", is_bool=True, default=False, help="Forzar la eliminación"),
        },
        run=run,
    )
    reg.add_command(cmd)
