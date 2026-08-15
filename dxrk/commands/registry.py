# SPDX-License-Identifier: MIT
"""Command registry and shared abstractions"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TextIO

RunFn = Callable[["CommandContext"], int]

_GO_QUOTE_CHARS = {'"': r"\"", "\\": r"\\", "\n": r"\n", "\t": r"\t", "\r": r"\r"}


def go_quote(s: str) -> str:
    """Formats a string like %q."""
    out = ['"']
    for ch in s:
        if ch in _GO_QUOTE_CHARS:
            out.append(_GO_QUOTE_CHARS[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def go_duration(seconds: float) -> str:
    """Formats a duration like time.Duration.String()."""
    secs = round(seconds)
    secs = max(secs, 0)
    hours = secs // 3600
    minutes = (secs % 3600) // 60
    sec = secs % 60
    if hours:
        return f"{hours}h{minutes}m{sec}s"
    if minutes:
        return f"{minutes}m{sec}s"
    return f"{sec}s"


@dataclass
class Flag:
    """A single command flag (mirrors pflag.Flag)."""

    name: str
    is_bool: bool = False
    default: str | bool = ""
    help: str = ""
    shorthand: str = ""


@dataclass
class CommandContext:
    """Execution context handed to every command run."""

    args: list[str] = field(default_factory=list)
    flags: dict[str, str | bool] = field(default_factory=dict)
    out: TextIO = field(default_factory=lambda: sys.stdout)
    err: TextIO = field(default_factory=lambda: sys.stderr)
    cwd: str = "."
    reg: Registry | None = None

    def flag_bool(self, name: str, default: bool = False) -> bool:
        value = self.flags.get(name, default)
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "yes", "on")

    def flag_str(self, name: str, default: str = "") -> str:
        value = self.flags.get(name, default)
        return "" if value is None else str(value)


@dataclass
class Command:
    """A single CLI command (mirrors cobra.Command)."""

    name: str
    short: str = ""
    long: str = ""
    min_args: int = 0
    max_args: int | None = None
    flags: dict[str, Flag] = field(default_factory=dict)
    run: RunFn | None = None

    def add_flag(self, flag: Flag) -> None:
        self.flags[flag.name] = flag

    def validate_args(self, args: list[str]) -> str | None:
        if len(args) < self.min_args:
            return f"requires at least {self.min_args} arg(s), received {len(args)}"
        if self.max_args is not None and len(args) > self.max_args:
            return f"accepts at most {self.max_args} arg(s), received {len(args)}"
        return None


def parse_argv(
    argv: list[str], flags: dict[str, Flag]
) -> tuple[list[str], dict[str, str | bool], str | None]:
    """Parses flags and positional args; returns (args, flags, error)."""
    positional: list[str] = []
    parsed: dict[str, str | bool] = {}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            positional.extend(argv[i + 1 :])
            break
        if tok.startswith("--"):
            body = tok[2:]
            if "=" in body:
                name, value = body.split("=", 1)
            else:
                name, value = body, None
            flag = flags.get(name)
            if flag is None:
                return [], {}, f"unknown flag: --{name}"
            if flag.is_bool:
                if value is None:
                    parsed[name] = True
                else:
                    lowered = value.lower()
                    if lowered in ("1", "true", "yes", "on"):
                        parsed[name] = True
                    elif lowered in ("0", "false", "no", "off"):
                        parsed[name] = False
                    else:
                        return [], {}, f'invalid boolean value "{value}" for --{name}'
            else:
                if value is None:
                    if i + 1 >= len(argv):
                        return [], {}, f"flag needs an argument: --{name}"
                    i += 1
                    value = argv[i]
                parsed[name] = value
        elif tok.startswith("-") and len(tok) > 1 and not tok[1].isdigit():
            short = tok[1]
            flag = next((f for f in flags.values() if f.shorthand == short), None)
            if flag is None:
                return [], {}, f"unknown shorthand flag: -{short}"
            if flag.is_bool:
                parsed[flag.name] = True
            else:
                if i + 1 >= len(argv):
                    return [], {}, f"flag needs an argument: -{short}"
                i += 1
                parsed[flag.name] = argv[i]
        else:
            positional.append(tok)
        i += 1
    return positional, parsed, None


class Registry:
    """Command registry"""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def add_command(self, cmd: Command) -> None:
        self._commands[cmd.name] = cmd

    def get_command(self, name: str) -> Command | None:
        return self._commands.get(name)

    def commands(self) -> list[Command]:
        return [self._commands[name] for name in sorted(self._commands)]

    def names(self) -> list[str]:
        return sorted(self._commands)

    def execute(
        self,
        argv: list[str],
        out: TextIO | None = None,
        err: TextIO | None = None,
        cwd: str = ".",
    ) -> int:
        if out is None:
            out = sys.stdout
        if err is None:
            err = sys.stderr
        if not argv:
            err.write("dxrk: missing command\n")
            err.write("Run 'dxrk help' for usage.\n")
            return 1

        name = argv[0]
        rest = argv[1:]
        if len(argv) >= 2 and f"{argv[0]} {argv[1]}" in self._commands:
            name = f"{argv[0]} {argv[1]}"
            rest = argv[2:]

        cmd = self._commands.get(name)
        if cmd is None:
            err.write(f"unknown command: {argv[0]}\n")
            err.write("Run 'dxrk help' for usage.\n")
            return 1

        args, flags, parse_err = parse_argv(rest, cmd.flags)
        if parse_err is not None:
            err.write(f"Error: {parse_err}\n")
            return 1
        arg_err = cmd.validate_args(args)
        if arg_err is not None:
            err.write(f"Error: {arg_err}\n")
            return 1
        if cmd.run is None:
            err.write(f"Error: command {cmd.name} is not implemented\n")
            return 1
        ctx = CommandContext(args=args, flags=flags, out=out, err=err, cwd=cwd, reg=self)
        return cmd.run(ctx)
