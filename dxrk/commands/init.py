# SPDX-License-Identifier: MIT
"""Init command"""

from __future__ import annotations

import os

from dxrk.config import Default, Save

from .registry import Command, CommandContext, Registry


def register_init_command(reg: Registry) -> None:
    """Registers the `dxrk init` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        wd = ctx.cwd
        dxrk_dir = os.path.join(os.path.abspath(wd), ".dxrk")

        try:
            os.makedirs(dxrk_dir, mode=0o750, exist_ok=True)
        except OSError as exc:
            ctx.err.write(f"Error: al crear el directorio .dxrk: {exc}\n")
            return 1

        config_path = os.path.join(dxrk_dir, "config.json")
        if os.path.exists(config_path):
            out.write("Dxrk ya está inicializado en este directorio.\n")
            out.write(f"Configuración: {config_path}\n")
            return 0

        cfg = Default()
        try:
            Save(config_path, cfg)
        except OSError as exc:
            ctx.err.write(f"Error: al escribir la configuración: {exc}\n")
            return 1

        try:
            os.makedirs(os.path.join(dxrk_dir, "memory"), mode=0o750, exist_ok=True)
        except OSError as exc:
            ctx.err.write(f"Error: al crear el directorio memory: {exc}\n")
            return 1

        out.write(f"Dxrk inicializado en {os.path.abspath(wd)}\n")
        out.write(f"Configuración: {config_path}\n")
        return 0

    cmd = Command(
        name="init",
        short="Inicializar Dxrk en el directorio actual",
        run=run,
    )
    reg.add_command(cmd)
