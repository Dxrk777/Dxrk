# SPDX-License-Identifier: MIT
"""Session statistics command"""

from __future__ import annotations

from dataclasses import dataclass, field

from dxrk.utils.session import now

from .registry import Command, CommandContext, Registry, go_duration


@dataclass
class SessionStats:
    """Aggregated statistics for the current session."""

    started_at: float = field(default_factory=lambda: now().timestamp())
    messages: int = 0
    tool_calls: int = 0
    tokens_used: int = 0
    model: str = ""


current_session: SessionStats | None = None


def record_message() -> None:
    """Increments the message counter for the current session."""
    if current_session is not None:
        current_session.messages += 1


def record_tool_call() -> None:
    """Increments the tool call counter for the current session."""
    if current_session is not None:
        current_session.tool_calls += 1


def record_tokens(tokens: int) -> None:
    """Accumulates token usage for the current session."""
    if current_session is not None:
        current_session.tokens_used += tokens


def set_model(model: str) -> None:
    """Records the model used for the current session."""
    if current_session is not None:
        current_session.model = model


def model_or_none(model: str) -> str:
    """Returns '(none)' for an empty model name."""
    return model if model else "(none)"


def format_tokens(tokens: int) -> str:
    """Formats a token count with K/M suffixes."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


def run_stats(ctx: CommandContext, s: SessionStats) -> int:
    """Prints the session statistics table."""
    err = ctx.err
    started = now()
    elapsed = started.timestamp() - s.started_at
    err.write("Session Statistics\n")
    err.write("──────────────────\n")
    err.write(f"  Started:      {started.strftime('%Y-%m-%d %H:%M:%S')}\n")
    err.write(f"  Duration:     {go_duration(elapsed)}\n")
    err.write(f"  Model:        {model_or_none(s.model)}\n")
    err.write(f"  Messages:     {s.messages}\n")
    err.write(f"  Tool calls:   {s.tool_calls}\n")
    err.write(f"  Tokens used:  {format_tokens(s.tokens_used)}\n")
    return 0


def register_stats_command(reg: Registry) -> None:
    """Registers the `dxrk stats` command."""

    def run(ctx: CommandContext) -> int:
        s = current_session if current_session is not None else SessionStats()
        return run_stats(ctx, s)

    cmd = Command(
        name="stats",
        short="Show session statistics",
        run=run,
    )
    reg.add_command(cmd)
