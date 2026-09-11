# SPDX-License-Identifier: MIT
"""Config command"""

from __future__ import annotations

import os

from dxrk.config import Config, Default, Load, Save

from .registry import Command, CommandContext, Registry


def user_config_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".dxrk", "config.yaml")


def load_user_config() -> Config:
    path = user_config_path()
    if os.path.exists(path):
        return Load(path)
    return Default()


def save_user_config(cfg: Config) -> None:
    os.makedirs(os.path.dirname(user_config_path()), mode=0o750, exist_ok=True)
    Save(user_config_path(), cfg)


def register_config_command(reg: Registry) -> None:
    """Registers the `dxrk config` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        path = user_config_path()
        if not os.path.exists(path):
            out.write(f"No se encontró el archivo de configuración en {path}\n")
            out.write("Ejecuta 'dxrk init' para crear uno.\n")
            return 0

        cfg = load_user_config()
        out.write(f"Configuración: {path}\n")
        out.write(f"Proyecto: {cfg.project.name} ({cfg.project.root})\n")
        out.write(f"Proveedor predeterminado: {cfg.project.default_provider}\n\n")
        out.write("Proveedores:\n")
        for p in cfg.providers:
            env = p.api_key_env or "-"
            out.write(f"  {p.name:<10} {p.model:<30} env={env}\n")
        if cfg.sandbox is not None:
            out.write(f"\nImagen de sandbox: {cfg.sandbox.default_image}\n")
        return 0

    cmd = Command(
        name="config",
        short="Mostrar la configuración actual",
        run=run,
    )
    reg.add_command(cmd)
