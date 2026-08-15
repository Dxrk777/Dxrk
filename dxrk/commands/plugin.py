# SPDX-License-Identifier: MIT
"""Plugin command"""

from __future__ import annotations

import json
import os

from .registry import Command, CommandContext, Registry


def plugins_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".dxrk", "plugins")


def list_plugins() -> list[tuple[str, str, str]]:
    """Returns (name, version, path) for every installed plugin."""
    root = plugins_dir()
    if not os.path.isdir(root):
        return []
    plugins: list[tuple[str, str, str]] = []
    for name in sorted(os.listdir(root)):
        dir_path = os.path.join(root, name)
        if not os.path.isdir(dir_path):
            continue
        manifest = os.path.join(dir_path, "manifest.json")
        version = ""
        try:
            with open(manifest, encoding="utf-8") as f:
                data = json.load(f)
            version = str(data.get("version", ""))
        except (OSError, json.JSONDecodeError):
            pass
        plugins.append((name, version, dir_path))
    return plugins


def register_plugin_command(reg: Registry) -> None:
    """Registers the `dxrk plugin` command and its subcommands."""

    def list_run(ctx: CommandContext) -> int:
        out = ctx.out
        plugins = list_plugins()
        if not plugins:
            out.write("No plugins found.\n")
            out.write(f"Install plugins under {plugins_dir()}\n")
            return 0
        out.write("NAME\tVERSION\tPATH\n")
        for name, version, path in plugins:
            out.write(f"{name}\t{version}\t{path}\n")
        return 0

    def add_run(ctx: CommandContext) -> int:
        out = ctx.out
        name = ctx.args[0]
        root = plugins_dir()
        dir_path = os.path.join(root, name)
        try:
            os.makedirs(dir_path, mode=0o750, exist_ok=True)
            manifest = os.path.join(dir_path, "manifest.json")
            if not os.path.exists(manifest):
                with open(manifest, "w", encoding="utf-8") as f:
                    json.dump({"name": name, "version": "0.1.0"}, f, indent=2)
        except OSError as exc:
            ctx.err.write(f"Error: install plugin: {exc}\n")
            return 1
        out.write(f"Installed plugin {name}\n")
        return 0

    def remove_run(ctx: CommandContext) -> int:
        out = ctx.out
        name = ctx.args[0]
        dir_path = os.path.join(plugins_dir(), name)
        if not os.path.isdir(dir_path):
            ctx.err.write(f"Error: plugin {name} not found\n")
            return 1
        try:
            import shutil

            shutil.rmtree(dir_path)
        except OSError as exc:
            ctx.err.write(f"Error: remove plugin: {exc}\n")
            return 1
        out.write(f"Removed plugin {name}\n")
        return 0

    list_cmd = Command(name="plugin list", short="List installed plugins", run=list_run)
    add_cmd = Command(name="plugin add", short="Install a plugin", min_args=1, max_args=1, run=add_run)
    remove_cmd = Command(name="plugin remove", short="Remove a plugin", min_args=1, max_args=1, run=remove_run)
    reg.add_command(list_cmd)
    reg.add_command(add_cmd)
    reg.add_command(remove_cmd)
