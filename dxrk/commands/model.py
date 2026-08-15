# SPDX-License-Identifier: MIT
"""Model command"""

from __future__ import annotations

from .config import load_user_config, save_user_config
from .registry import Command, CommandContext, Registry


def register_model_command(reg: Registry) -> None:
    """Registers the `dxrk model` command."""

    def list_run(ctx: CommandContext) -> int:
        out = ctx.out
        cfg = load_user_config()
        out.write("Available models:\n")
        for p in cfg.providers:
            marker = " *" if p.name == cfg.project.default_provider else ""
            out.write(f"  {p.name:<10} {p.model}{marker}\n")
        return 0

    def current_run(ctx: CommandContext) -> int:
        out = ctx.out
        cfg = load_user_config()
        for p in cfg.providers:
            if p.name == cfg.project.default_provider:
                out.write(f"{p.model}\n")
                return 0
        out.write("(none)\n")
        return 0

    def set_run(ctx: CommandContext) -> int:
        out = ctx.out
        provider = ctx.args[0]
        model_name = ctx.args[1]
        cfg = load_user_config()
        found = False
        for p in cfg.providers:
            if p.name == provider:
                p.model = model_name
                found = True
                break
        if not found:
            ctx.err.write(f"Error: provider {provider} not found\n")
            return 1
        save_user_config(cfg)
        out.write(f"Set model for {provider} to {model_name}\n")
        return 0

    list_cmd = Command(name="model list", short="List available models", run=list_run)
    current_cmd = Command(name="model current", short="Show the current model", run=current_run)
    set_cmd = Command(
        name="model set",
        short="Set the model for a provider",
        min_args=2,
        max_args=2,
        run=set_run,
    )
    reg.add_command(list_cmd)
    reg.add_command(current_cmd)
    reg.add_command(set_cmd)
