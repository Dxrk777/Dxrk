# SPDX-License-Identifier: MIT
"""Message rendering in several output styles plus small text helpers."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from enum import IntEnum

from dxrk.utils.messages_model import _STR_ERROR, ContentType, Message, ToolResultData


class FormatStyle(IntEnum):
    """output style of FormatMessage."""

    Plain = 0
    Markdown = 1
    Rich = 2
    Compact = 3
    Verbose = 4


def FormatMessage(msg: Message, format: FormatStyle) -> str:
    """Render a Message according to the given style."""
    if format is FormatStyle.Markdown:
        return _format_markdown(msg)
    if format is FormatStyle.Rich:
        return _format_rich(msg)
    if format is FormatStyle.Compact:
        return _format_compact(msg)
    if format is FormatStyle.Verbose:
        return _format_verbose(msg)
    return _format_plain(msg)


def _format_plain(msg: Message) -> str:
    return f"[{msg.role.String()}] {msg.TextContent()}"


def _format_markdown(msg: Message) -> str:
    out = f"**{msg.role.String().upper()}**\n\n"
    for c in msg.contents:
        if c.type is ContentType.ContentText:
            out += f"{c.text}\n"
        elif c.type is ContentType.ContentImage:
            if c.image is not None:
                out += f"[Image: {c.image.media_type}]\n"
        elif c.type is ContentType.ContentToolUse:
            if c.tool_use is not None:
                out += f"🔧 tool_use: {c.tool_use.name}(```json\n"
                out += f"{_format_tool_input(c.tool_use.input)}\n```)  \n"
        elif c.type is ContentType.ContentToolResult:
            if c.tool_result is not None:
                prefix = "✅"
                if c.tool_result.is_error:
                    prefix = "❌"
                out += f"{prefix} {_trunc_str(c.tool_result.content, 200)}\n"
    return out


def _format_rich(msg: Message) -> str:
    ts = msg.timestamp.strftime("%H:%M:%S")
    out = f"[{ts}] {msg.role.String()}: "
    parts: list[str] = []
    for c in msg.contents:
        if c.type is ContentType.ContentText:
            parts.append(c.text)
        elif c.type is ContentType.ContentImage:
            parts.append("[image]")
        elif c.type is ContentType.ContentToolUse:
            if c.tool_use is not None:
                parts.append(f"→ {c.tool_use.name}")
        elif c.type is ContentType.ContentToolResult:
            if c.tool_result is not None:
                status = "ok"
                if c.tool_result.is_error:
                    status = _STR_ERROR
                parts.append(f"← {status}")
    out += " | ".join(parts)
    if msg.stop_reason != "":
        out += f" [{msg.stop_reason}]"
    return out


def _format_compact(msg: Message) -> str:
    role = msg.role.String()[0]
    text = _trunc_str(msg.TextContent(), 80)
    return f"{role}: {text}"


def _format_verbose(msg: Message) -> str:
    out = f"Message ID:    {msg.id}\n"
    out += f"Role:          {msg.role.String()}\n"
    out += f"Timestamp:     {msg.timestamp.isoformat()}\n"
    out += f"Model:         {msg.model}\n"
    out += f"Tokens:        {msg.token_count}\n"
    out += f"Stop Reason:   {msg.stop_reason}\n"
    out += f"Contents ({len(msg.contents)}):\n"
    for i, c in enumerate(msg.contents):
        out += f"  [{i}] Type: {c.type.String()}\n"
        if c.type is ContentType.ContentText:
            out += f"       Text: {_trunc_str(c.text, 120)}\n"
        elif c.type is ContentType.ContentImage:
            if c.image is not None:
                out += f"       Image: {c.image.media_type} ({c.image.source})\n"
        elif c.type is ContentType.ContentToolUse:
            if c.tool_use is not None:
                out += f"       Tool: {c.tool_use.name} (id={c.tool_use.id})\n"
                out += f"       Input: {_trunc_str(_format_tool_input(c.tool_use.input), 200)}\n"
        elif c.type is ContentType.ContentToolResult:
            if c.tool_result is not None:
                out += f"       Result: tool_use_id={c.tool_result.tool_use_id} error={c.tool_result.is_error}\n"
                out += f"       Content: {_trunc_str(c.tool_result.content, 200)}\n"
    if len(msg.metadata) > 0:
        out += "Metadata:\n"
        for k, v in msg.metadata.items():
            out += f"  {k}: {v}\n"
    return out


def _format_tool_input(input: dict[str, object]) -> str:
    if len(input) == 0:
        return "{}"
    parts: list[str] = []
    for k, v in input.items():
        parts.append(f"{json.dumps(k)}: {json.dumps(str(v))}")
    return "{" + ", ".join(parts) + "}"


def FormatToolUse(name: str, input: dict[str, object]) -> str:
    """Format a tool call for display."""
    return f"→ {name}({_format_tool_input(input)})"


def FormatToolResult(result: ToolResultData) -> str:
    """Format a tool result for display."""
    prefix = "✓"
    if result.is_error:
        prefix = "✗"
    content = _trunc_str(result.content, 100)
    dur = ""
    if result.duration > timedelta(0):
        dur = f" [{_round_ms(result.duration)}]"
    return f"{prefix} {content}{dur}"


def FormatError(err: Exception | None) -> str:
    """Format an error message with context."""
    if err is None:
        return ""
    return f"Error: {err}"


def FormatProgress(tool: str, elapsed: timedelta) -> str:
    """Return a progress indicator string."""
    sec = elapsed.total_seconds()
    dots = int(sec) % 4
    pending = "." * (dots + 1)
    return f"  {tool}{pending} {_round_ms(elapsed)}"


def FormatDiff(before: str, after: str) -> str:
    """Produce a simple before/after comparison."""
    return f"--- before\n{before}\n+++ after\n{after}"


def TruncateMiddle(s: str, max_len: int) -> str:
    """Truncate a string to ``max_len`` characters, ellipsis in the middle."""
    rune_len = len(s)
    if rune_len <= max_len:
        return s
    if max_len < 5:
        return s[:max_len]
    half = (max_len - 3) // 2
    start = s[:half]
    end = s[-half:]
    return start + "..." + end


def WrapCode(code: str, lang: str) -> str:
    """Wrap text in a markdown code block."""
    return f"```{lang}\n{code}\n```"


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def StripANSI(s: str) -> str:
    """Remove ANSI escape codes from a string."""
    return _ANSI_RE.sub("", s)


def WordCount(s: str) -> int:
    """Return the number of words in s."""
    return len(s.split())


def CharCount(s: str) -> int:
    """Return the character count of s."""
    return len(s)


def _trunc_str(s: str, max_len: int) -> str:
    """Truncate s to ``max_len`` characters with a "..." suffix."""
    rune_len = len(s)
    if rune_len <= max_len:
        return s
    if max_len < 4:
        return s[:max_len]
    return s[: max_len - 3] + "..."


def _round_ms(d: timedelta) -> timedelta:
    """Round a duration to whole milliseconds."""
    us = round(d.total_seconds() * 1_000_000 / 1000) * 1000
    return timedelta(microseconds=us)


def _format_duration(d: timedelta) -> str:
    """Format a duration (e.g. "1m30s", "45s", "500ms")."""
    total_us = d // timedelta(microseconds=1)
    if total_us == 0:
        return "0s"
    hours = total_us // 3_600_000_000
    minutes = (total_us % 3_600_000_000) // 60_000_000
    seconds_us = total_us % 60_000_000
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds_us == 0 and not parts:
        return "0s"
    if seconds_us == 0:
        return "".join(parts)
    if seconds_us < 1_000_000:
        if seconds_us % 1000 == 0:
            parts.append(f"{seconds_us // 1000}ms")
        else:
            parts.append(f"{seconds_us}µs")
    else:
        seconds = seconds_us / 1_000_000
        if seconds == int(seconds):
            parts.append(f"{int(seconds)}s")
        else:
            parts.append(f"{seconds:g}s")
    return "".join(parts)
