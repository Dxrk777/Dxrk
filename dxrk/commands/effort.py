# SPDX-License-Identifier: MIT
"""Effort level command"""

from __future__ import annotations

from dxrk.strconst import StrMedium2

from .registry import Command, CommandContext, Registry

valid_effort_levels = ["low", StrMedium2, "high", "max", "auto"]

_EFFORT_DESCRIPTIONS = {
    "low": "Implementación rápida y directa",
    StrMedium2: "Enfoque equilibrado con pruebas estándar",
    "high": "Implementación completa con pruebas extensas",
    "max": "Capacidad máxima con el razonamiento más profundo",
    "auto": "Nivel de esfuerzo predeterminado del modelo actual",
}


def effort_description(level: str) -> str:
    """Returns the human-readable description for an effort level."""
    return _EFFORT_DESCRIPTIONS.get(level, "")


def register_effort_command(reg: Registry) -> None:
    """Registers the `dxrk effort` command for setting the effort level."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out

        if len(ctx.args) == 0:
            out.write("Nivel de esfuerzo actual: auto\n")
            out.write("\n")
            out.write("Niveles disponibles:\n")
            for level in valid_effort_levels:
                out.write(f"  {level}\n")
            return 0

        level = ctx.args[0].strip().lower()
        if level == "unset":
            level = "auto"

        if level not in valid_effort_levels:
            ctx.err.write(
                f"Error: nivel de esfuerzo inválido: {level}. Opciones válidas: {', '.join(valid_effort_levels)}\n"
            )
            return 1

        description = effort_description(level)
        out.write(f"Nivel de esfuerzo fijado en {level}: {description}\n")
        return 0

    cmd = Command(
        name="effort",
        short="Fijar el nivel de esfuerzo de razonamiento",
        long=(
            "Fijar el nivel de esfuerzo para el razonamiento del modelo.\n\n"
            "Niveles de esfuerzo:\n"
            "  low    - Implementación rápida y directa\n"
            "  medium - Enfoque equilibrado con pruebas estándar\n"
            "  high   - Implementación completa con pruebas extensas\n"
            "  max    - Capacidad máxima con el razonamiento más profundo\n"
            "  auto   - Usar el nivel de esfuerzo predeterminado del modelo actual\n\n"
            "Si no se indica un nivel, muestra el nivel de esfuerzo actual."
        ),
        max_args=1,
        run=run,
    )
    reg.add_command(cmd)
