# SPDX-License-Identifier: MIT
"""Session model: canonical session/message types, IDs, and time helpers."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import cast

CurrentVersion = 2


class SessionError(Exception):
    pass


class SessionStatus(IntEnum):
    Active = 0
    Paused = 1
    Completed = 2
    Archived = 3
    Expired = 4

    def __str__(self) -> str:
        names = {0: "active", 1: "paused", 2: "completed", 3: "archived", 4: "expired"}
        return names.get(int(self), "unknown")

    def go_string(self) -> str:
        return str(self)


_STATUS_NAMES = {0: "active", 1: "paused", 2: "completed", 3: "archived", 4: "expired"}
_STATUS_BY_NAME = {name: value for value, name in _STATUS_NAMES.items()}

_EPOCH_UTC = datetime.min.replace(tzinfo=UTC)


class MessageRole(str):
    User = "user"
    Assistant = "assistant"
    System = "system"
    ToolUse = "toolUse"
    ToolResult = "toolResult"


RoleUser: MessageRole = cast(MessageRole, MessageRole.User)
RoleAssistant: MessageRole = cast(MessageRole, MessageRole.Assistant)
RoleSystem: MessageRole = cast(MessageRole, MessageRole.System)
RoleToolUse: MessageRole = cast(MessageRole, MessageRole.ToolUse)
RoleToolResult: MessageRole = cast(MessageRole, MessageRole.ToolResult)


@dataclass
class ToolCall:
    id: str = ""
    name: str = ""
    input: str = ""
    output: str = ""
    duration: float = 0.0
    error: str = ""
    tokens_used: int = 0


@dataclass
class Message:
    id: str = ""
    role: MessageRole = RoleUser
    content: str = ""
    timestamp: datetime | None = None
    token_count: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_result_id: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class Session:
    version: int = CurrentVersion
    id: str = ""
    parent_id: str = ""
    title: str = ""
    working_dir: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    message_count: int = 0
    token_count: int = 0
    model: str = ""
    status: SessionStatus = SessionStatus.Active
    metadata: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    messages: list[Message] = field(default_factory=list)

    def add_message(self, msg: Message) -> None:
        if not msg.id:
            msg.id = generate_id()
        if msg.timestamp is None:
            msg.timestamp = now()
        if msg.token_count == 0:
            msg.token_count = estimate_tokens(msg.content)
        self.messages.append(msg)
        self.message_count = len(self.messages)
        self.token_count += msg.token_count
        self.updated_at = now()

    def get_messages(self) -> list[Message]:
        return list(self.messages)

    def last_message(self) -> Message | None:
        if not self.messages:
            return None
        return self.messages[-1]

    def duration(self) -> timedelta:
        if self.updated_at is None or self.created_at is None:
            return timedelta(0)
        return self.updated_at - self.created_at

    def is_expired(self, max_age: timedelta) -> bool:
        if max_age <= timedelta(0) or self.updated_at is None:
            return False
        return (now() - self.updated_at) > max_age

    def estimate_tokens(self) -> int:
        total = 0
        for msg in self.messages:
            total += msg.token_count
        self.token_count = total
        return total


@dataclass
class SessionOpts:
    title: str = ""
    working_dir: str = ""
    model: str = ""
    max_messages: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


def new_session(opts: SessionOpts | None = None) -> Session:
    opts = opts or SessionOpts()
    now_ts = now()
    s = Session(
        version=CurrentVersion,
        id=generate_id(),
        title=opts.title,
        working_dir=opts.working_dir,
        created_at=now_ts,
        updated_at=now_ts,
        model=opts.model,
        status=SessionStatus.Active,
        metadata=dict(opts.metadata),
    )
    if not s.title:
        s.title = "Untitled Session"
    return s


NewSession = new_session


def generate_id() -> str:
    return secrets.token_hex(16)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    words = len(text.split())
    chars = len(text)
    tw = words * 4 // 3
    tc = chars // 4
    return tw if tw > tc else tc


# ─── time helpers ──────────────────────────────────────────────────────────


def now() -> datetime:
    return datetime.now(UTC)


def _fmt_ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    frac = ""
    if dt.microsecond:
        frac = f".{dt.microsecond:06d}".rstrip("0")
    off = dt.strftime("%z")
    if off in ("", "+0000"):
        suffix = "Z"
    else:
        suffix = f"{off[:3]}:{off[3:]}"
    return base + frac + suffix


def _fmt_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    off = dt.strftime("%z")
    if off in ("", "+0000"):
        return base + "Z"
    return base + off


def _from_ts(text: str) -> datetime:
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)
