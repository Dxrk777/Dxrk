# SPDX-License-Identifier: MIT
"""Hooks command"""

from __future__ import annotations

import json
import os

from .registry import Command, CommandContext, Registry, go_quote

HOOK_EVENTS = (
    "pre-commit",
    "post-commit",
    "pre-push",
    "pre-agent",
    "post-agent",
    "pre-tool",
    "post-tool",
    "session-start",
    "session-end",
)


def hooks_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".config", "dxrk", "hooks.json")


def load_hooks() -> list[dict[str, str | bool]]:
    path = hooks_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def save_hooks(hooks: list[dict[str, str | bool]]) -> bool:
    path = hooks_path()
    try:
        os.makedirs(os.path.dirname(path), mode=0o750, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(hooks, f, indent=2)
        return True
    except OSError:
        return False


def register_hooks_command(reg: Registry) -> None:
    """Registers the `dxrk hooks` command and its subcommands."""

    def list_run(ctx: CommandContext) -> int:
        out = ctx.out
        hooks = load_hooks()
        if not hooks:
            out.write("No hooks configured.\n")
            return 0
        out.write("NAME\tEVENT\tCOMMAND\tENABLED\n")
        for h in hooks:
            out.write(
                f"{h.get('name', '')}\t{h.get('event', '')}\t{h.get('command', '')}\t"
                f"{str(h.get('enabled', True)).lower()}\n"
            )
        return 0

    def add_run(ctx: CommandContext) -> int:
        out = ctx.out
        name = ctx.args[0]
        event = ctx.args[1]
        command = ctx.args[2]

        if event not in HOOK_EVENTS:
            ctx.err.write(f"Error: invalid event {go_quote(event)}\n")
            return 1

        hooks = load_hooks()
        for h in hooks:
            if h.get("name") == name:
                ctx.err.write(f"Error: hook {go_quote(name)} already exists\n")
                return 1

        hooks.append(
            {
                "name": name,
                "event": event,
                "command": command,
                "enabled": True,
            }
        )
        if not save_hooks(hooks):
            ctx.err.write("Error: write hooks config\n")
            return 1
        out.write(f"Added hook {go_quote(name)} ({event})\n")
        return 0

    def remove_run(ctx: CommandContext) -> int:
        out = ctx.out
        name = ctx.args[0]
        hooks = load_hooks()
        remaining = [h for h in hooks if h.get("name") != name]
        if len(remaining) == len(hooks):
            ctx.err.write(f"Error: hook {go_quote(name)} not found\n")
            return 1
        if not save_hooks(remaining):
            ctx.err.write("Error: write hooks config\n")
            return 1
        out.write(f"Removed hook {go_quote(name)}\n")
        return 0

    list_cmd = Command(name="hooks list", short="List configured hooks", run=list_run)
    add_cmd = Command(
        name="hooks add",
        short="Add a hook",
        min_args=3,
        max_args=3,
        run=add_run,
    )
    remove_cmd = Command(
        name="hooks remove",
        short="Remove a hook",
        min_args=1,
        max_args=1,
        run=remove_run,
    )
    reg.add_command(list_cmd)
    reg.add_command(add_cmd)
    reg.add_command(remove_cmd)
