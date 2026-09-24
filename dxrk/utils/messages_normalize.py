# SPDX-License-Identifier: MIT
"""Message normalization: merging, dedup, ordering, and token truncation."""

from __future__ import annotations

from dxrk.utils.messages_model import Content, ContentType, Message, Role


def NormalizeMessages(msgs: list[Message]) -> list[Message]:
    """Apply the standard fixups to a message slice.

    Fixes tool result ordering, deduplicates tool results, merges consecutive
    user and assistant messages, and compacts text-only contents.
    """
    if len(msgs) == 0:
        return msgs
    msgs = FixToolResultOrder(msgs)
    msgs = DeduplicateToolResults(msgs)
    msgs = MergeConsecutiveRole(msgs, Role.RoleUser)
    msgs = MergeConsecutiveRole(msgs, Role.RoleAssistant)
    msgs = CompactContent(msgs)
    return msgs


def MergeConsecutiveRole(msgs: list[Message], role: Role) -> list[Message]:
    """Merge consecutive messages with the same role into a single message.

    Contents are concatenated in order; metadata from the first message is
    kept; timestamps use the earliest.
    """
    if len(msgs) == 0:
        return msgs

    result: list[Message] = []
    current: Message | None = None

    for m in msgs:
        if m.role is role:
            if current is None:
                current = m
            else:
                current.contents.extend(m.contents)
                if m.token_count > 0:
                    current.token_count += m.token_count
                if m.timestamp < current.timestamp:
                    current.timestamp = m.timestamp
        else:
            if current is not None:
                result.append(current)
                current = None
            result.append(m)
    if current is not None:
        result.append(current)
    return result


def StripSystemMessages(msgs: list[Message]) -> list[Message]:
    """Remove all messages with RoleSystem."""
    return [m for m in msgs if m.role is not Role.RoleSystem]


def DeduplicateToolResults(msgs: list[Message]) -> list[Message]:
    """Remove duplicate tool results (same ToolUseID), keeping the first."""
    seen: set[str] = set()
    result: list[Message] = []
    for m in msgs:
        skip = False
        if m.role is Role.RoleToolResult:
            for c in m.contents:
                if (
                    c.type is ContentType.ContentToolResult
                    and c.tool_result is not None
                ):
                    if c.tool_result.tool_use_id in seen:
                        skip = True
                        break
                    seen.add(c.tool_result.tool_use_id)
        if not skip:
            result.append(m)
    return result


def FixToolResultOrder(msgs: list[Message]) -> list[Message]:
    """Move tool_results so they follow their corresponding tool_use.

    Best-effort: a tool_result found before its tool_use is moved to right
    after the tool_use.
    """
    if len(msgs) <= 1:
        return msgs

    tool_uses: dict[str, int] = {}
    tool_results: dict[str, int] = {}
    for i, m in enumerate(msgs):
        for c in m.contents:
            if c.type is ContentType.ContentToolUse and c.tool_use is not None:
                tool_uses[c.tool_use.id] = i
            if c.type is ContentType.ContentToolResult and c.tool_result is not None:
                tool_results[c.tool_result.tool_use_id] = i

    needs_reorder = any(
        result_idx < tool_uses[tool_use_id]
        for tool_use_id, result_idx in tool_results.items()
        if tool_use_id in tool_uses
    )
    if not needs_reorder:
        return msgs

    ordered = sorted(range(len(msgs)), key=lambda i: i)

    result: list[Message] = []
    pending: dict[str, Message] = {}
    for i in ordered:
        for c in msgs[i].contents:
            if c.type is ContentType.ContentToolUse and c.tool_use is not None:
                if c.tool_use.id in pending:
                    result.append(pending.pop(c.tool_use.id))
        result.append(msgs[i])
    result.extend(pending.values())
    return result


def CompactContent(msgs: list[Message]) -> list[Message]:
    """Merge consecutive text-only content blocks within each message."""
    return [_compact_message_contents(m) for m in msgs]


def _compact_message_contents(m: Message) -> Message:
    if len(m.contents) <= 1:
        return m

    text_parts: list[str] = []
    other: list[Content] = []
    for c in m.contents:
        if c.type is ContentType.ContentText and c.text != "":
            text_parts.append(c.text)
        else:
            other.append(c)

    if len(text_parts) <= 1:
        return m

    merged = Content(type=ContentType.ContentText, text="\n".join(text_parts))
    m.contents = [merged] + other
    return m


def TruncateByTokens(msgs: list[Message], max_tokens: int) -> list[Message]:
    """Keep the most recent messages that fit within the token budget.

    System messages are always preserved. Retained messages get their
    ``token_count`` set.
    """
    if len(msgs) == 0 or max_tokens <= 0:
        return []

    system_msgs = [m for m in msgs if m.role is Role.RoleSystem]
    non_system = [m for m in msgs if m.role is not Role.RoleSystem]

    system_tokens = sum(m.EstimateTokens() for m in system_msgs)

    budget = max_tokens - system_tokens
    if budget <= 0:
        return system_msgs

    result: list[Message] = []
    used = 0
    for m in reversed(non_system):
        tokens = m.EstimateTokens()
        if used + tokens > budget:
            break
        used += tokens
        result.append(m)

    result.reverse()
    return system_msgs + result


def CountTokens(msgs: list[Message]) -> int:
    """Return the total estimated token count across all messages."""
    return sum(m.EstimateTokens() for m in msgs)
