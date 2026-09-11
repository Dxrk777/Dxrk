# SPDX-License-Identifier: MIT
"""Plan command"""

from __future__ import annotations

import os

from .registry import Command, CommandContext, Registry


def plan_path(wd: str) -> str:
    return os.path.join(os.path.abspath(wd), ".dxrk", "plan.md")


def _load_plan(wd: str) -> str:
    path = plan_path(wd)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _write_plan(wd: str, content: str) -> bool:
    path = plan_path(wd)
    try:
        os.makedirs(os.path.dirname(path), mode=0o750, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except OSError:
        return False


def _task_items(content: str) -> list[str]:
    items = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- [ ]"):
            items.append(stripped[5:].strip())
    return items


def register_plan_command(reg: Registry) -> None:
    """Registers the `dxrk plan` command and its subcommands."""

    def show_run(ctx: CommandContext) -> int:
        out = ctx.out
        content = _load_plan(ctx.cwd)
        if not content:
            out.write("No se encontró el archivo de plan en .dxrk/plan.md\n")
            return 0
        out.write(content)
        if not content.endswith("\n"):
            out.write("\n")
        return 0

    def add_run(ctx: CommandContext) -> int:
        out = ctx.out
        task = " ".join(ctx.args)
        content = _load_plan(ctx.cwd)
        if not content:
            content = "# Plan\n\n"
        content += f"- [ ] {task}\n"
        if not _write_plan(ctx.cwd, content):
            ctx.err.write("Error: al escribir el archivo de plan\n")
            return 1
        out.write(f"Tarea agregada: {task}\n")
        return 0

    def done_run(ctx: CommandContext) -> int:
        out = ctx.out
        try:
            index = int(ctx.args[0])
        except ValueError:
            ctx.err.write(f"Error: número de tarea inválido {ctx.args[0]}\n")
            return 1
        content = _load_plan(ctx.cwd)
        items = _task_items(content)
        if index < 1 or index > len(items):
            ctx.err.write("Error: número de tarea fuera de rango\n")
            return 1
        new_content = []
        count = 0
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- [ ]"):
                count += 1
                if count == index:
                    line = line.replace("- [ ]", "- [x]", 1)
            new_content.append(line)
        if not _write_plan(ctx.cwd, "\n".join(new_content) + "\n"):
            ctx.err.write("Error: al escribir el archivo de plan\n")
            return 1
        out.write(f"Tarea {index} marcada como terminada\n")
        return 0

    show_cmd = Command(name="plan show", short="Mostrar el plan actual", run=show_run)
    add_cmd = Command(
        name="plan add",
        short="Agregar una tarea al plan",
        min_args=1,
        run=add_run,
    )
    done_cmd = Command(
        name="plan done",
        short="Marcar una tarea del plan como terminada",
        min_args=1,
        max_args=1,
        run=done_run,
    )
    reg.add_command(show_cmd)
    reg.add_command(add_cmd)
    reg.add_command(done_cmd)
