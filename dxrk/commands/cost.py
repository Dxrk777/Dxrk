# SPDX-License-Identifier: MIT
"""Cost command"""

from __future__ import annotations

from .registry import Command, CommandContext, Registry
from .session import SessionError, load_session

# Pricing per 1M tokens (USD): (input, output)
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-opus-4-20250514": (15.0, 75.0),
    "claude-haiku-3-5": (0.80, 4.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gemini-2.0-flash": (0.10, 0.40),
    "deepseek-v4-flash": (0.20, 0.60),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> tuple[float, float, float]:
    """Returns (input_cost, output_cost, total) in USD."""
    pricing = _MODEL_PRICING.get(model, (3.0, 15.0))
    input_cost = input_tokens / 1_000_000 * pricing[0]
    output_cost = output_tokens / 1_000_000 * pricing[1]
    return input_cost, output_cost, input_cost + output_cost


def register_cost_command(reg: Registry) -> None:
    """Registers the `dxrk cost` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        session_id = ctx.args[0] if ctx.args else ""
        if not session_id:
            ctx.err.write("Error: session id required\n")
            return 1

        try:
            s = load_session(session_id)
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        input_tokens = s.token_count
        input_cost, output_cost, total = estimate_cost(s.model, input_tokens, 0)

        out.write(f"Model: {s.model}\n")
        out.write(f"Input tokens: {input_tokens}\n")
        out.write(f"Input cost: ${input_cost:.4f}\n")
        out.write(f"Output cost: ${output_cost:.4f}\n")
        out.write(f"Estimated total: ${total:.4f}\n")
        return 0

    cmd = Command(
        name="cost",
        short="Estimate token costs for a session",
        min_args=1,
        max_args=1,
        run=run,
    )
    reg.add_command(cmd)
