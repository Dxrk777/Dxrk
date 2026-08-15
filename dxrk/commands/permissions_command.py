# SPDX-License-Identifier: MIT
"""Permissions command"""

from __future__ import annotations

from dxrk.config import SandboxConfig

from .config import load_user_config, save_user_config
from .registry import Command, CommandContext, Registry


def register_permissions_command(reg: Registry) -> None:
    """Registers the `dxrk permissions` command and its subcommands."""

    def show_run(ctx: CommandContext) -> int:
        out = ctx.out
        cfg = load_user_config()
        if cfg.sandbox is None:
            out.write("No sandbox configuration found.\n")
            return 0
        sb = cfg.sandbox
        out.write(f"Sandbox Image:  {sb.default_image}\n")
        out.write(f"Memory Limit:   {sb.memory_limit}\n")
        out.write(f"CPU Limit:      {sb.cpu_limit}\n")
        out.write(f"Timeout:        {sb.timeout_sec}s\n")
        out.write(f"Max Containers: {sb.max_containers}\n")
        return 0

    def reset_run(ctx: CommandContext) -> int:
        out = ctx.out
        cfg = load_user_config()
        cfg.sandbox = SandboxConfig()
        save_user_config(cfg)
        out.write("Permission rules reset to defaults\n")
        return 0

    show_cmd = Command(name="permissions", short="Show sandbox permission rules", run=show_run)
    reset_cmd = Command(name="permissions reset", short="Reset permission rules to defaults", run=reset_run)
    reg.add_command(show_cmd)
    reg.add_command(reset_cmd)
