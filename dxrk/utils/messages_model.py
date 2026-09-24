# SPDX-License-Identifier: MIT
"""Conversation message primitives: roles, content blocks, and token estimates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum

# Mirrors dxrk/strconst: StrAssistant / StrSystem / StrToolUse / StrToolResult /
# StrUnknown / StrError.
_STR_ASSISTANT = "assistant"
_STR_SYSTEM = "system"
_STR_TOOL_USE = "tool_use"
_STR_TOOL_RESULT = "tool_result"
_STR_UNKNOWN = "unknown"
_STR_ERROR = "error"

_ZERO_TIME = datetime.fromtimestamp(0, tz=UTC)


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
    def _missing_(cls, value: object) -> Role:
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
