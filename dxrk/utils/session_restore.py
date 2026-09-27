# SPDX-License-Identifier: MIT
"""Session restore, resume context, summaries, archiving, and expiration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta

from dxrk.utils.session_codec import _session_from_dict, _session_to_dict
from dxrk.utils.session_migrate import migrate_to_current
from dxrk.utils.session_model import (
    CurrentVersion,
    Message,
    RoleAssistant,
    RoleToolResult,
    RoleUser,
    Session,
    SessionError,
    SessionStatus,
    ToolCall,
    now,
)
from dxrk.utils.session_serialize import _go_quote
from dxrk.utils.session_storage import ListOpts, Storage

# ─── restore ───────────────────────────────────────────────────────────────


@dataclass
class ResumeContext:
    session: Session | None = None
    last_summary: str = ""
    pending_tools: list[ToolCall] = field(default_factory=list)
    context_window: int = 0
    token_budget: int = 0


@dataclass
class ResumeCriteria:
    max_messages_back: int = 0
    prefer_after_tool: bool = False
    max_tokens: int = 0


def restore_session(id: str, storage: Storage) -> Session:
    try:
        s = storage.load(id)
    except SessionError as e:
        raise SessionError(f"load session: {e}") from e
    if s is None or not s.id:
        raise SessionError(f"session {id!r} invalid")
    if s.version > CurrentVersion:
        raise SessionError(f"session version {s.version} exceeds current version {CurrentVersion}")
    if s.version < CurrentVersion:
        # Lazy migration for backends that hand back unmigrated payloads:
        # round-trip through the registry so v1 sessions come out canonical.
        # An unmigratable payload passes through untouched (read-any).
        try:
            migrated = migrate_to_current(json.dumps(_session_to_dict(s)))
            s = _session_from_dict(json.loads(migrated))
        except (SessionError, ValueError, TypeError):
            pass
    return s


def resume_session(s: Session) -> ResumeContext:
    pending = _collect_pending_tool_calls(s)
    summary = _build_incremental_summary(s)
    tokens = 0
    for msg in s.messages:
        tokens += msg.token_count
    return ResumeContext(
        session=s,
        last_summary=summary,
        pending_tools=pending,
        context_window=len(s.messages),
        token_budget=tokens,
    )


def create_summary(s: Session | None, max_tokens: int = 4096) -> str:
    if s is None:
        raise SessionError("session is nil")
    if max_tokens <= 0:
        max_tokens = 4096
    used = 0
    kept: list[Message] = []
    for msg in reversed(s.messages):
        t = msg.token_count
        if used + t > max_tokens:
            break
        kept.append(msg)
        used += t
    kept.reverse()
    if len(kept) < len(s.messages):
        prefix = f"Session {_go_quote(s.title)} ({len(kept)} of {len(s.messages)} messages, ~{used} tokens).\n"
    else:
        prefix = f"Session {_go_quote(s.title)} ({len(s.messages)} messages, ~{s.token_count} tokens).\n"
    return prefix + _build_message_summary(kept)


def find_resume_point(s: Session | None, criteria: ResumeCriteria) -> int:
    if s is None or not s.messages:
        raise SessionError("session is nil or empty")
    max_back = criteria.max_messages_back
    if max_back <= 0 or max_back > len(s.messages):
        max_back = len(s.messages)
    start = len(s.messages) - max_back
    if start < 0:
        start = 0
    if criteria.prefer_after_tool:
        for i in range(len(s.messages) - 1, start - 1, -1):
            if s.messages[i].tool_calls or s.messages[i].role == RoleToolResult:
                idx = i + 1
                if idx > len(s.messages):
                    idx = len(s.messages)
                return idx
    if criteria.max_tokens > 0:
        used = 0
        for i in range(len(s.messages) - 1, start - 1, -1):
            used += s.messages[i].token_count
            if used > criteria.max_tokens:
                return i + 1
    return start


def auto_archive(s: Session | None, max_age: timedelta) -> bool:
    if s is None or max_age <= timedelta(0):
        return False
    if s.status in (
        SessionStatus.Archived,
        SessionStatus.Expired,
        SessionStatus.Completed,
    ):
        return False
    if s.updated_at is None:
        return False
    return (now() - s.updated_at) > max_age


def cleanup_expired(storage: Storage, max_age: timedelta) -> int:
    try:
        sessions = storage.list(ListOpts(limit=0))
    except SessionError as e:
        raise SessionError(f"list sessions: {e}") from e
    count = 0
    for summary in sessions:
        try:
            s = storage.load(summary.id)
        except SessionError:
            continue
        if s.is_expired(max_age) and s.status in (
            SessionStatus.Active,
            SessionStatus.Paused,
        ):
            s.status = SessionStatus.Expired
            try:
                storage.save(s)
                count += 1
            except SessionError:
                pass
        elif auto_archive(s, max_age):
            s.status = SessionStatus.Archived
            try:
                storage.save(s)
                count += 1
            except SessionError:
                pass
    return count


def _collect_pending_tool_calls(s: Session) -> list[ToolCall]:
    pending: list[ToolCall] = []
    for msg in s.messages:
        for tc in msg.tool_calls:
            if tc.error or not tc.output:
                pending.append(tc)
    return pending


def _build_incremental_summary(s: Session) -> str:
    if not s.messages:
        return ""
    last = s.messages[-1]
    summary = f"Last message role: {last.role}"
    if last.role == RoleAssistant:
        if last.content:
            summary = f"Last assistant: {truncate(last.content, 200)}"
    elif last.role == RoleUser:
        summary = f"Awaiting response to: {truncate(last.content, 200)}"
    if last.tool_calls:
        summary += f" ({len(last.tool_calls)} tool calls pending)"
    return summary


def _build_message_summary(msgs: list[Message]) -> str:
    out: list[str] = []
    for msg in msgs:
        out.append(f"[{msg.role}] {truncate(msg.content, 120)}")
    return "\n".join(out) + ("\n" if out else "")


def truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


RestoreSession = restore_session
ResumeSession = resume_session
CreateSummary = create_summary
FindResumePoint = find_resume_point
AutoArchive = auto_archive
CleanupExpired = cleanup_expired
