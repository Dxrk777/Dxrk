# SPDX-License-Identifier: MIT
"""Conversation search, filtering, tool-call resolution, and statistics."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dxrk.utils.messages_format import _format_duration
from dxrk.utils.messages_model import _ZERO_TIME, ContentType, Message, Role, ToolResultData, ToolUseData


@dataclass
class SearchResult:
    """a single search hit."""

    message: Message
    match_content: str
    score: float
    highlight: list[str] = field(default_factory=list)


@dataclass
class ToolCall:
    """a resolved tool invocation with context."""

    message: Message
    tool_use: ToolUseData
    result: ToolResultData | None = None
    result_msg: Message | None = None
    timestamp: datetime = _ZERO_TIME


@dataclass
class Stats:
    """aggregate statistics for a conversation."""

    total_messages: int = 0
    total_tokens: int = 0
    by_role: dict[Role, int] = field(default_factory=dict)
    avg_message_length: float = 0.0
    longest_message: int = 0
    tool_call_count: int = 0
    tool_result_count: int = 0
    error_count: int = 0
    first_message_time: datetime = _ZERO_TIME
    last_message_time: datetime = _ZERO_TIME
    avg_token_per_msg: float = 0.0

    def String(self) -> str:
        """Return a human-readable summary of the stats."""
        out = f"Messages: {self.total_messages} | Tokens: {self.total_tokens} | Avg: {self.avg_token_per_msg:.0f}/msg\n"
        for role, count in self.by_role.items():
            out += f"  {role.String()}: {count}\n"
        if self.tool_call_count > 0:
            out += f"  Tool calls: {self.tool_call_count} (errors: {self.error_count})\n"
        if self.first_message_time != _ZERO_TIME:
            duration = self.last_message_time - self.first_message_time
            rounded = timedelta(seconds=round(duration.total_seconds()))
            out += f"  Duration: {_format_duration(rounded)}\n"
        return out


def SearchMessages(msgs: list[Message], query: str) -> list[SearchResult]:
    """Perform substring search across all message content.

    Results are scored by match count and position, with highlighted
    fragments.
    """
    if query == "" or len(msgs) == 0:
        return []

    query_lower = query.lower()
    results: list[SearchResult] = []

    for m in msgs:
        text = m.TextContent()
        if text == "":
            continue

        text_lower = text.lower()
        score = 0.0
        highlights: list[str] = []

        idx = 0
        while True:
            pos = text_lower.find(query_lower, idx)
            if pos < 0:
                break
            abs_pos = pos
            score += 1.0
            if abs_pos < 10:
                score += 0.5

            start = max(0, abs_pos - 20)
            end = min(len(text), abs_pos + len(query) + 20)
            highlights.append(text[start:end])

            idx = abs_pos + len(query)

        if score > 0:
            results.append(SearchResult(message=m, match_content=text, score=score, highlight=highlights))

    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            if results[j].score > results[i].score:
                results[i], results[j] = results[j], results[i]

    return results


def FilterByRole(msgs: list[Message], role: Role) -> list[Message]:
    """Return messages matching the given role."""
    return [m for m in msgs if m.role is role]


def FilterByTime(msgs: list[Message], from_: datetime, to: datetime) -> list[Message]:
    """Return messages within the given time range (inclusive).

    A zero time on either bound leaves it open.
    """
    result: list[Message] = []
    for m in msgs:
        if (from_ == _ZERO_TIME or not (m.timestamp < from_)) and (to == _ZERO_TIME or not (m.timestamp > to)):
            result.append(m)
    return result


def FilterByTokenRange(msgs: list[Message], min_tokens: int, max_tokens: int) -> list[Message]:
    """Return messages whose estimated token count falls in [min, max].

    Use ``min_tokens=0`` or ``max_tokens=-1`` to leave a bound open.
    """
    result: list[Message] = []
    for m in msgs:
        tokens = m.EstimateTokens()
        if tokens >= min_tokens and (max_tokens < 0 or tokens <= max_tokens):
            result.append(m)
    return result


def FilterByTool(msgs: list[Message], tool_name: str) -> list[Message]:
    """Return messages containing a tool_use block with the given name.

    An empty ``tool_name`` matches any tool use.
    """
    return [m for m in msgs if m.HasToolUse(tool_name)]


def FilterByRegex(msgs: list[Message], pattern: str) -> list[Message]:
    """Return messages where any text content matches the regex pattern."""
    try:
        re_compiled = re.compile(pattern)
    except re.error:
        return []
    return [m for m in msgs if m.TextContent() != "" and re_compiled.search(m.TextContent())]


def FindToolCalls(msgs: list[Message], tool_name: str) -> list[ToolCall]:
    """Resolve tool_use and tool_result pairs into ToolCall structs.

    An empty ``tool_name`` matches all tool calls.
    """
    result_index: dict[str, Message] = {}
    for m in msgs:
        if m.role is Role.RoleToolResult:
            for c in m.contents:
                if c.type is ContentType.ContentToolResult and c.tool_result is not None:
                    result_index[c.tool_result.tool_use_id] = m

    calls: list[ToolCall] = []
    for m in msgs:
        for c in m.contents:
            if c.type is ContentType.ContentToolUse and c.tool_use is not None:
                if tool_name != "" and c.tool_use.name != tool_name:
                    continue

                tc = ToolCall(message=m, tool_use=c.tool_use, timestamp=m.timestamp)
                result_msg = result_index.get(c.tool_use.id)
                if result_msg is not None:
                    tc.result_msg = result_msg
                    for rc in result_msg.contents:
                        if (
                            rc.type is ContentType.ContentToolResult
                            and rc.tool_result is not None
                            and rc.tool_result.tool_use_id == c.tool_use.id
                        ):
                            tc.result = rc.tool_result
                            break

                calls.append(tc)
    return calls


def GetConversationStats(msgs: list[Message]) -> Stats:
    """Compute aggregate statistics for a message slice."""
    if len(msgs) == 0:
        return Stats(by_role={})

    stats = Stats(total_messages=len(msgs), by_role={})

    total_text_len = 0
    total_tokens = 0

    for m in msgs:
        stats.by_role[m.role] = stats.by_role.get(m.role, 0) + 1
        tokens = m.EstimateTokens()
        total_tokens += tokens

        text_len = len(m.TextContent())
        total_text_len += text_len
        if text_len > stats.longest_message:
            stats.longest_message = text_len

        if m.role is Role.RoleToolUse:
            stats.tool_call_count += 1
        if m.role is Role.RoleToolResult:
            stats.tool_result_count += 1
            for c in m.contents:
                if c.type is ContentType.ContentToolResult and c.tool_result is not None and c.tool_result.is_error:
                    stats.error_count += 1

        if stats.first_message_time == _ZERO_TIME or m.timestamp < stats.first_message_time:
            stats.first_message_time = m.timestamp
        if m.timestamp > stats.last_message_time:
            stats.last_message_time = m.timestamp

    stats.total_tokens = total_tokens
    stats.avg_message_length = total_text_len / len(msgs)
    stats.avg_token_per_msg = total_tokens / len(msgs)

    return stats
