# SPDX-License-Identifier: MIT
"""MCP command"""

from __future__ import annotations

import json
import os

from .registry import Command, CommandContext, Flag, Registry


def mcp_state_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".dxrk", "mcp.json")


def load_mcp_state() -> dict[str, dict]:
    try:
        with open(mcp_state_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data.get("servers", {}) if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_mcp_state(servers: dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(mcp_state_path()), mode=0o750, exist_ok=True)
    with open(mcp_state_path(), "w", encoding="utf-8") as f:
        json.dump({"servers": servers}, f, indent=2)
    os.chmod(mcp_state_path(), 0o600)


def register_mcp_command(reg: Registry) -> None:
    """Registers the `dxrk mcp` command and its subcommands."""

    def list_run(ctx: CommandContext) -> int:
        out = ctx.out
        servers = load_mcp_state()
        if not servers:
            out.write("No MCP servers configured.\n")
            return 0
        out.write("NAME\tSTATUS\tCOMMAND\n")
        for name, info in sorted(servers.items()):
            out.write(
                f"{name}\t{info.get('status', 'configured')}\t{info.get('command', '')}\n"
            )
        return 0

    def add_run(ctx: CommandContext) -> int:
        out = ctx.out
        name = ctx.args[0]
        command = ctx.args[1] if len(ctx.args) > 1 else ctx.flag_str("command")
        if not command:
            ctx.err.write("Error: command required (argument or --command)\n")
            return 1
        servers = load_mcp_state()
        servers[name] = {"command": command, "status": "configured"}
        save_mcp_state(servers)
        out.write(f"Added MCP server {name}\n")
        return 0

    def remove_run(ctx: CommandContext) -> int:
        out = ctx.out
        name = ctx.args[0]
        servers = load_mcp_state()
        if name not in servers:
            ctx.err.write(f"Error: MCP server {name} not found\n")
            return 1
        del servers[name]
        save_mcp_state(servers)
        out.write(f"Removed MCP server {name}\n")
        return 0

    list_cmd = Command(name="mcp list", short="List configured MCP servers", run=list_run)
    add_cmd = Command(
        name="mcp add",
        short="Add an MCP server",
        min_args=1,
        max_args=1,
        flags={
            "command": Flag("command", default="", help="Server command"),
        },
        run=add_run,
    )
    remove_cmd = Command(name="mcp remove", short="Remove an MCP server", min_args=1, max_args=1, run=remove_run)
    reg.add_command(list_cmd)
    reg.add_command(add_cmd)
    reg.add_command(remove_cmd)
