# SPDX-License-Identifier: MIT
"""Conversation message primitives.

Provides message/role/content models, a fluent message builder, context-window
management with token budgeting and compaction strategies, message
normalization (merging, dedup, ordering), formatting in several output styles,
and conversation search/statistics helpers.

Concurrency mapping:

* ``time.Time`` -> ``datetime`` (UTC; zero time is ``_ZERO_TIME``)
* ``time.Duration`` -> ``datetime.timedelta``
* ``map[string]any`` -> ``dict[str, object]``

Fidelity notes (mirrored intentionally, including upstream quirks):

* ``EstimateTokens`` uses ``len(s) // 4``; the original counts *bytes*, Python counts
  characters, so multi-byte strings may estimate slightly lower.
* ``Message.EstimateTokens`` returns 1 for a message with no content.
* ``formatToolInput`` iterates maps in random order; Python keeps dict
  insertion order (deterministic output).
* ``formatVerbose`` metadata lines use dict order (map order is random).
* ``truncStr``/``TruncateMiddle`` slice the string for ``maxLen < 4`` /
  ``maxLen < 5``; the original slices bytes (can split a rune), Python slices
  characters (cannot).
* The emoji glyphs in ``format_markdown``/``FormatToolResult`` are mirrored
  verbatim from the original output strings.
* ``Compact`` with an unknown strategy raises ``ValueError`` (the original returns a
  wrapped error).
* ``GetConversationStats`` uses ``len(TextContent())``; the original counts *bytes*,
  Python counts characters, so ``longest_message``/``avg_message_length``
  may be slightly lower for multi-byte text.
* ``Role`` is an ``IntEnum`` with ``_missing_`` defaulting to ``RoleUser``,
  matching the original ``ParseRole`` fallback for unknown values.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum

# Mirrors dxrk/strconst: StrAssistant / StrSystem / StrToolUse / StrToolResult /
# StrUnknown / StrError.
_STR_ASSISTANT = "assistant"
_STR_SYSTEM = "system"
_STR_TOOL_USE = "tool_use"
_STR_TOOL_RESULT = "tool_result"
_STR_UNKNOWN = "unknown"
_STR_ERROR = "error"

_ZERO_TIME = datetime.fromtimestamp(0, tz=timezone.utc)


class Role(IntEnum):
    """the sender of a message."""

    RoleUser = 0
    RoleAssistant = 1
    RoleSystem = 2
    RoleToolUse = 3
    RoleToolResult = 4

    def String(self) -> str:
        if self is Role.RoleUser:
            return "user"
        if self is Role.RoleAssistant:
            return _STR_ASSISTANT
        if self is Role.RoleSystem:
            return _STR_SYSTEM
        if self is Role.RoleToolUse:
            return _STR_TOOL_USE
        if self is Role.RoleToolResult:
            return _STR_TOOL_RESULT
        return _STR_UNKNOWN

    @classmethod
    def _missing_(cls, value: object) -> "Role":
        return Role.RoleUser


def ParseRole(s: str) -> Role:
    """Convert a string to a Role; unknown values default to RoleUser."""
    role = s.lower()
    if role == "user":
        return Role.RoleUser
    if role == _STR_ASSISTANT:
        return Role.RoleAssistant
    if role == _STR_SYSTEM:
        return Role.RoleSystem
    if role == _STR_TOOL_USE:
        return Role.RoleToolUse
    if role == _STR_TOOL_RESULT:
        return Role.RoleToolResult
    return Role.RoleUser


class ContentType(IntEnum):
    """the kind of payload in a Content block."""

    ContentText = 0
    ContentImage = 1
    ContentToolUse = 2
    ContentToolResult = 3

    def String(self) -> str:
        if self is ContentType.ContentText:
            return "text"
        if self is ContentType.ContentImage:
            return "image"
        if self is ContentType.ContentToolUse:
            return _STR_TOOL_USE
        if self is ContentType.ContentToolResult:
            return _STR_TOOL_RESULT
        return _STR_UNKNOWN


@dataclass
class ImageData:
    """an image payload."""

    source: str = "base64"  # "base64" or "url"
    media_type: str = ""  # e.g. "image/png", "image/jpeg"
    data: str = ""  # base64 data or URL


@dataclass
class ToolUseData:
    """a tool invocation by the assistant."""

    id: str = ""
    name: str = ""
    input: dict[str, object] = field(default_factory=dict)


@dataclass
class ToolResultData:
    """the result returned by a tool."""

    tool_use_id: str = ""
    content: str = ""
    is_error: bool = False
    duration: timedelta = timedelta(0)


@dataclass
class Content:
    """a single block within a message."""

    type: ContentType = ContentType.ContentText
    text: str = ""
    image: ImageData | None = None
    tool_use: ToolUseData | None = None
    tool_result: ToolResultData | None = None


@dataclass
class Message:
    """a single conversation turn."""

    id: str = ""
    role: Role = Role.RoleUser
    contents: list[Content] = field(default_factory=list)
    timestamp: datetime = _ZERO_TIME
    token_count: int = 0
    model: str = ""
    stop_reason: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def EstimateTokens(self) -> int:
        """Return the token count for this message.

        If ``token_count`` is set it is returned directly; otherwise a rough
        estimate (characters / 4) is computed from all text content.
        """
        if self.token_count > 0:
            return self.token_count
        total = 0
        for c in self.contents:
            if c.type is ContentType.ContentText:
                total += EstimateTokens(c.text)
            elif c.type is ContentType.ContentToolUse:
                if c.tool_use is not None:
                    total += EstimateTokens(c.tool_use.id)
                    total += EstimateTokens(c.tool_use.name)
                    for k, v in c.tool_use.input.items():
                        total += EstimateTokens(k)
                        total += EstimateTokens(str(v))
            elif c.type is ContentType.ContentToolResult:
                if c.tool_result is not None:
                    total += EstimateTokens(c.tool_result.content)
        if total == 0:
            return 1
        return total

    def HasToolUse(self, name: str) -> bool:
        """Return True if the message contains a tool_use block with ``name``.

        An empty ``name`` matches any tool use.
        """
        for c in self.contents:
            if c.type is ContentType.ContentToolUse and c.tool_use is not None:
                if name == "" or c.tool_use.name == name:
                    return True
        return False

    def TextContent(self) -> str:
        """Return the concatenated text of all text content blocks."""
        parts: list[str] = []
        for c in self.contents:
            if c.type is ContentType.ContentText and c.text != "":
                parts.append(c.text)
        return "\n".join(parts)


def EstimateTokens(s: str) -> int:
    """Return a rough token count for a string: len(s)/4, minimum 1."""
    n = len(s)
    if n == 0:
        return 0
    tokens = n // 4
    if tokens == 0:
        return 1
    return tokens


class MessageBuilder:
    """a fluent API for building messages."""

    def __init__(self, msg: Message) -> None:
        self.msg = msg

    def WithID(self, id: str) -> "MessageBuilder":
        self.msg.id = id
        return self

    def WithTimestamp(self, ts: datetime) -> "MessageBuilder":
        self.msg.timestamp = ts
        return self

    def WithModel(self, model: str) -> "MessageBuilder":
        self.msg.model = model
        return self

    def WithTokenCount(self, n: int) -> "MessageBuilder":
        self.msg.token_count = n
        return self

    def WithStopReason(self, reason: str) -> "MessageBuilder":
        self.msg.stop_reason = reason
        return self

    def WithMetadata(self, key: str, value: object) -> "MessageBuilder":
        self.msg.metadata[key] = value
        return self

    def Text(self, text: str) -> "MessageBuilder":
        self.msg.contents.append(Content(type=ContentType.ContentText, text=text))
        return self

    def Image(self, media_type: str, data: str) -> "MessageBuilder":
        self.msg.contents.append(
            Content(
                type=ContentType.ContentImage,
                image=ImageData(source="base64", media_type=media_type, data=data),
            )
        )
        return self

    def ImageURL(self, url: str, media_type: str) -> "MessageBuilder":
        self.msg.contents.append(
            Content(
                type=ContentType.ContentImage,
                image=ImageData(source="url", media_type=media_type, data=url),
            )
        )
        return self

    def ToolUse(
        self, id: str, name: str, input: dict[str, object] | None = None
    ) -> "MessageBuilder":
        data = input if input is not None else {}
        self.msg.contents.append(
            Content(
                type=ContentType.ContentToolUse,
                tool_use=ToolUseData(id=id, name=name, input=data),
            )
        )
        return self

    def ToolResult(
        self, tool_use_id: str, content: str, is_error: bool
    ) -> "MessageBuilder":
        self.msg.contents.append(
            Content(
                type=ContentType.ContentToolResult,
                tool_result=ToolResultData(
                    tool_use_id=tool_use_id, content=content, is_error=is_error
                ),
            )
        )
        return self

    def Build(self) -> Message:
        return self.msg


def NewMessage(role: Role) -> MessageBuilder:
    """Start building a message with the given role."""
    return MessageBuilder(
        Message(
            role=role,
            timestamp=datetime.now(timezone.utc),
            contents=[],
            metadata={},
        )
    )


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


class CompactStrategy(IntEnum):
    """how messages are selected for removal."""

    CompactOldest = 0
    CompactToolResults = 1
    CompactByImportance = 2
    CompactRecursive = 3


@dataclass
class MessageScore:
    """a message and its compaction score."""

    message: Message
    score: float
    reason: str


def ScoreMessages(msgs: list[Message]) -> list[MessageScore]:
    """Rank messages by importance for compaction decisions.

    Scoring factors: recency (newer = higher), role priority
    (user > system > assistant > tool), tool error status (errors kept
    longer), and content size (large tool results penalized).
    """
    if len(msgs) == 0:
        return []
    scores: list[MessageScore] = []
    now = msgs[-1].timestamp

    role_base = {
        Role.RoleUser: 100,
        Role.RoleSystem: 90,
        Role.RoleAssistant: 70,
        Role.RoleToolUse: 50,
        Role.RoleToolResult: 30,
    }

    for i, m in enumerate(msgs):
        score: float = role_base.get(m.role, 40)

        if now != _ZERO_TIME and m.timestamp != _ZERO_TIME:
            age = (now - m.timestamp).total_seconds() / 60.0
            recency_bonus = 50.0 / (1.0 + age / 30.0)
            score += recency_bonus

        token_size = m.EstimateTokens()
        if token_size > 500:
            score -= (token_size - 500) / 100.0

        if m.role is Role.RoleToolResult:
            for c in m.contents:
                if (
                    c.type is ContentType.ContentToolResult
                    and c.tool_result is not None
                    and c.tool_result.is_error
                ):
                    score += 20

        if i == 0 or i == len(msgs) - 1:
            score += 30

        scores.append(
            MessageScore(
                message=m,
                score=score,
                reason=f"role={m.role.String()} tokens={token_size}",
            )
        )
    return scores


class WindowFullError(Exception):
    """the context window cannot accept more."""


class NoMessagesError(Exception):
    """compaction on an empty window."""


@dataclass
class ContextWindow:
    """messages within a token budget."""

    messages: list[Message] = field(default_factory=list)
    token_count: int = 0
    max_tokens: int = 0
    system_prompt: str = ""
    truncated: bool = False

    def SetSystemPrompt(self, prompt: str) -> None:
        """Set the system prompt, counting its tokens toward the budget."""
        self.system_prompt = prompt
        self._recount_tokens()

    def AddMessage(self, msg: Message) -> None:
        """Add a message, auto-dropping older messages on overflow."""
        tokens = msg.EstimateTokens()
        system_tokens = EstimateTokens(self.system_prompt)

        if tokens + system_tokens > self.max_tokens:
            raise WindowFullError(
                f"context window full: message ({tokens} tokens) exceeds "
                f"window budget ({self.max_tokens} tokens)"
            )

        self.messages.append(msg)
        self.token_count += tokens

        while (
            self.token_count + system_tokens > self.max_tokens
            and len(self.messages) > 1
        ):
            self._drop_oldest()
            self.truncated = True

    def _drop_oldest(self) -> None:
        for i, m in enumerate(self.messages):
            if m.role is not Role.RoleSystem:
                self.token_count -= m.EstimateTokens()
                del self.messages[i]
                return
        if len(self.messages) > 0:
            self.token_count -= self.messages[0].EstimateTokens()
            del self.messages[0]

    def GetMessages(self) -> list[Message]:
        """Return the current window contents (a copy)."""
        return list(self.messages)

    def RemainingTokens(self) -> int:
        """Return how many tokens are left in the budget."""
        system_tokens = EstimateTokens(self.system_prompt)
        remaining = self.max_tokens - self.token_count - system_tokens
        if remaining < 0:
            return 0
        return remaining

    def NeedsCompaction(self) -> bool:
        """Return True if the window is above 80% capacity."""
        system_tokens = EstimateTokens(self.system_prompt)
        used = self.token_count + system_tokens
        return float(used) >= float(self.max_tokens) * 0.8

    def Compact(self, strategy: CompactStrategy) -> None:
        """Reduce the window contents using the specified strategy."""
        if len(self.messages) == 0:
            raise NoMessagesError("no messages to compact")

        if strategy is CompactStrategy.CompactOldest:
            self._compact_oldest()
        elif strategy is CompactStrategy.CompactToolResults:
            self._compact_tool_results()
        elif strategy is CompactStrategy.CompactByImportance:
            self._compact_by_importance()
        elif strategy is CompactStrategy.CompactRecursive:
            self._compact_recursive()
        else:
            raise ValueError(f"unknown compact strategy: {int(strategy)}")

        self._recount_tokens()

    def _compact_oldest(self) -> None:
        system_tokens = EstimateTokens(self.system_prompt)
        target = self.max_tokens // 2

        while self.token_count + system_tokens > target and len(self.messages) > 2:
            self._drop_oldest()
            self.truncated = True

    def _compact_tool_results(self) -> None:
        i = 0
        while i < len(self.messages):
            m = self.messages[i]
            if m.role is Role.RoleToolResult:
                self.token_count -= m.EstimateTokens()
                del self.messages[i]
                self.truncated = True
            else:
                i += 1

    def _compact_by_importance(self) -> None:
        system_tokens = EstimateTokens(self.system_prompt)
        target = self.max_tokens // 2

        scores = sorted(ScoreMessages(self.messages), key=lambda s: s.score)
        for s in scores:
            if self.token_count + system_tokens <= target:
                break
            for i, m in enumerate(self.messages):
                if m.id == s.message.id or (
                    m.timestamp == s.message.timestamp and m.role is s.message.role
                ):
                    self.token_count -= m.EstimateTokens()
                    del self.messages[i]
                    self.truncated = True
                    break

    def _compact_recursive(self) -> None:
        max_iters = 10
        for _ in range(max_iters):
            if not self.NeedsCompaction():
                break
            scores = ScoreMessages(self.messages)
            if len(scores) == 0:
                break

            min_score = min(scores, key=lambda s: s.score)
            target = min_score.message
            for i, m in enumerate(self.messages):
                if m.timestamp == target.timestamp and m.role is target.role:
                    self.token_count -= m.EstimateTokens()
                    del self.messages[i]
                    self.truncated = True
                    break

    def _recount_tokens(self) -> None:
        self.token_count = 0
        for m in self.messages:
            self.token_count += m.EstimateTokens()


def NewContextWindow(max_tokens: int) -> ContextWindow:
    """Create a window with the given maximum token budget."""
    return ContextWindow(max_tokens=max_tokens)


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
        out = (
            f"Messages: {self.total_messages} | Tokens: {self.total_tokens} | "
            f"Avg: {self.avg_token_per_msg:.0f}/msg\n"
        )
        for role, count in self.by_role.items():
            out += f"  {role.String()}: {count}\n"
        if self.tool_call_count > 0:
            out += (
                f"  Tool calls: {self.tool_call_count} (errors: {self.error_count})\n"
            )
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
            results.append(
                SearchResult(
                    message=m, match_content=text, score=score, highlight=highlights
                )
            )

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
        if (from_ == _ZERO_TIME or not (m.timestamp < from_)) and (
            to == _ZERO_TIME or not (m.timestamp > to)
        ):
            result.append(m)
    return result


def FilterByTokenRange(
    msgs: list[Message], min_tokens: int, max_tokens: int
) -> list[Message]:
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
    return [
        m for m in msgs if m.TextContent() != "" and re_compiled.search(m.TextContent())
    ]


def FindToolCalls(msgs: list[Message], tool_name: str) -> list[ToolCall]:
    """Resolve tool_use and tool_result pairs into ToolCall structs.

    An empty ``tool_name`` matches all tool calls.
    """
    result_index: dict[str, Message] = {}
    for m in msgs:
        if m.role is Role.RoleToolResult:
            for c in m.contents:
                if (
                    c.type is ContentType.ContentToolResult
                    and c.tool_result is not None
                ):
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
                if (
                    c.type is ContentType.ContentToolResult
                    and c.tool_result is not None
                    and c.tool_result.is_error
                ):
                    stats.error_count += 1

        if (
            stats.first_message_time == _ZERO_TIME
            or m.timestamp < stats.first_message_time
        ):
            stats.first_message_time = m.timestamp
        if m.timestamp > stats.last_message_time:
            stats.last_message_time = m.timestamp

    stats.total_tokens = total_tokens
    stats.avg_message_length = total_text_len / len(msgs)
    stats.avg_token_per_msg = total_tokens / len(msgs)

    return stats
