# SPDX-License-Identifier: MIT
"""Review command"""

from __future__ import annotations

import json

from .gitutil import (
    git_diff,
    git_diff_cached,
    git_diff_stats,
    git_dir,
    git_status_porcelain,
    run_gh,
)
from .registry import Command, CommandContext, Flag, Registry

_REVIEW_POINTS = (
    "  - Corrección del código y lógica",
    "  - Consideraciones de rendimiento",
    "  - Vulnerabilidades de seguridad",
    "  - Manejo de errores",
    "  - Cobertura de pruebas",
    "  - Nombres y legibilidad",
)


def _print_review(ctx: CommandContext) -> None:
    ctx.out.write("=== REVISIÓN ===\n")
    for point in _REVIEW_POINTS:
        ctx.out.write(point + "\n")
    ctx.out.write("=== RESUMEN ===\n")


def _print_files(ctx: CommandContext, diff: str) -> None:
    for line in diff.splitlines():
        if line.startswith("+++ b/") and line[6:] != "/dev/null":
            ctx.out.write(f"--- {line[6:]}\n")


def register_review_command(reg: Registry) -> None:
    """Registers the `dxrk review` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        wd = ctx.cwd

        if not git_dir(wd).ok:
            ctx.err.write("Error: no es un repositorio git\n")
            return 1

        if ctx.flag_bool("pr"):
            result = run_gh(wd, "pr", "view", "--json", "number,title,url,baseRefName")
            if not result.ok:
                ctx.err.write(f"Error: al obtener info del PR: {result.err.strip() or result.out.strip()}\n")
                return 1
            try:
                info = json.loads(result.out)
            except json.JSONDecodeError as exc:
                ctx.err.write(f"Error: al obtener info del PR: {exc}\n")
                return 1

            diff = run_gh(wd, "pr", "diff")
            if not diff.ok:
                ctx.err.write(f"Error: al obtener el diff del PR: {diff.err.strip() or diff.out.strip()}\n")
                return 1

            out.write(f"Detalles del PR #{info.get('number', '')}:\n{info.get('title', '')}\n\n")
            _print_files(ctx, diff.out)
            _print_review(ctx)
            return 0

        since = ctx.flag_str("since")
        if since:
            result = git_diff(wd, since)
            if not result.ok:
                ctx.err.write(f"Error: al obtener el diff: {result.err.strip() or result.out.strip()}\n")
                return 1
            files, additions, deletions = git_diff_stats(result.out)
            out.write(f"Revisando cambios desde {since}:\n")
            out.write(f"{files} archivos cambiados, {additions} inserciones(+), {deletions} eliminaciones(-)\n\n")
            _print_files(ctx, result.out)
            _print_review(ctx)
            return 0

        staged = git_diff_cached(wd)
        if not staged.ok:
            ctx.err.write(f"Error: al obtener el diff preparado: {staged.err.strip() or staged.out.strip()}\n")
            return 1
        unstaged = git_diff(wd)
        if not unstaged.ok:
            ctx.err.write(f"Error: al obtener el diff sin preparar: {unstaged.err.strip() or unstaged.out.strip()}\n")
            return 1

        status = git_status_porcelain(wd)
        has_changes = bool(status.ok and status.out.strip())

        out.write("Revisando cambios sin confirmar:\n")
        if not has_changes:
            out.write("No hay cambios para revisar.\n")
            _print_review(ctx)
            return 0

        if staged.out.strip():
            out.write("=== PREPARADOS ===\n")
            _print_files(ctx, staged.out)
        if unstaged.out.strip():
            out.write("=== SIN PREPARAR ===\n")
            _print_files(ctx, unstaged.out)

        _print_review(ctx)
        return 0

    cmd = Command(
        name="review",
        short="Revisar cambios",
        long="Revisar cambios preparados, sin preparar o de un PR según criterios de revisión.",
        flags={
            "pr": Flag("pr", is_bool=True, default=False, help="Revisar el PR actual"),
            "since": Flag("since", default="", help="Revisar cambios desde una ref"),
        },
        run=run,
    )
    reg.add_command(cmd)
