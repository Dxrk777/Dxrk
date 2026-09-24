# SPDX-License-Identifier: MIT
"""Session JSON encoding with json tags and omitempty semantics."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from dxrk.utils.session_model import (
    _STATUS_BY_NAME,
    _STATUS_NAMES,
    Message,
    MessageRole,
    RoleUser,
    Session,
    SessionStatus,
    ToolCall,
    _fmt_ts,
    _from_ts,
    now,
)

# ─── JSON encoding (json tags + omitempty) ──────────────────────


def _tool_call_to_dict(tc: ToolCall) -> dict[str, Any]:
    d: dict[str, Any] = {"id": tc.id, "name": tc.name, "input": tc.input}
    if tc.output:
        d["output"] = tc.output
    if tc.duration:
        d["duration"] = tc.duration
    if tc.error:
        d["error"] = tc.error
    if tc.tokens_used:
        d["tokens_used"] = tc.tokens_used
    return d


def _tool_call_from_dict(d: dict[str, Any]) -> ToolCall:
    return ToolCall(
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        input=str(d.get("input", "")),
        output=str(d.get("output", "")),
        duration=float(d.get("duration", 0) or 0),
        error=str(d.get("error", "")),
        tokens_used=int(d.get("tokens_used", 0) or 0),
    )


def _message_to_dict(m: Message) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "timestamp": _fmt_ts(m.timestamp) if m.timestamp else _fmt_ts(now()),
    }
    if m.token_count:
        d["token_count"] = m.token_count
    if m.tool_calls:
        d["tool_calls"] = [_tool_call_to_dict(tc) for tc in m.tool_calls]
    if m.tool_result_id:
        d["tool_result_id"] = m.tool_result_id
    if m.metadata:
        d["metadata"] = dict(m.metadata)
    return d


def _parse_role(value: Any) -> MessageRole:
    v = str(value).strip() if value is not None else ""
    if v in ("user", "assistant", "system", "toolUse", "toolResult"):
        return cast(MessageRole, MessageRole(v))
    return RoleUser


def _message_from_dict(d: dict[str, Any]) -> Message:
    ts = d.get("timestamp")
    return Message(
        id=str(d.get("id", "")),
        role=_parse_role(d.get("role", RoleUser)),
        content=str(d.get("content", "")),
        timestamp=_from_ts(ts) if ts else None,
        token_count=int(d.get("token_count", 0) or 0),
        tool_calls=[_tool_call_from_dict(tc) for tc in d.get("tool_calls", []) or []],
        tool_result_id=str(d.get("tool_result_id", "")),
        metadata=dict(d.get("metadata", {}) or {}),
    )


def _session_to_dict(s: Session) -> dict[str, Any]:
    d: dict[str, Any] = {
        "version": s.version,
        "id": s.id,
        "title": s.title,
        "working_dir": s.working_dir,
        "created_at": _fmt_ts(s.created_at) if s.created_at else _fmt_ts(now()),
        "updated_at": _fmt_ts(s.updated_at) if s.updated_at else _fmt_ts(now()),
        "message_count": s.message_count,
        "token_count": s.token_count,
        "model": s.model,
        "status": int(s.status),
    }
    if s.parent_id:
        d["parent_id"] = s.parent_id
    if s.metadata:
        d["metadata"] = dict(s.metadata)
    if s.tags:
        d["tags"] = list(s.tags)
    if s.summary:
        d["summary"] = s.summary
    if s.messages:
        d["messages"] = [_message_to_dict(m) for m in s.messages]
    return d


def _session_from_dict(d: dict[str, Any]) -> Session:
    created = d.get("created_at")
    updated = d.get("updated_at")
    status_raw = d.get("status", SessionStatus.Active)
    if isinstance(status_raw, str):
        status = _STATUS_BY_NAME.get(status_raw.lower(), SessionStatus.Active)
    else:
        status = int(status_raw) if status_raw is not None else SessionStatus.Active
    return Session(
        version=int(d.get("version", 0)),
        id=str(d.get("id", "")),
        parent_id=str(d.get("parent_id", "")),
        title=str(d.get("title", "")),
        working_dir=str(d.get("working_dir", "")),
        created_at=_from_ts(created) if created else None,
        updated_at=_from_ts(updated) if updated else None,
        message_count=int(d.get("message_count", 0) or 0),
        token_count=int(d.get("token_count", 0) or 0),
        model=str(d.get("model", "")),
        status=SessionStatus(status) if status in _STATUS_NAMES else SessionStatus.Active,
        metadata=dict(d.get("metadata", {}) or {}),
        tags=list(d.get("tags", []) or []),
        summary=str(d.get("summary", "")),
        messages=[_message_from_dict(m) for m in d.get("messages", []) or []],
    )


def _index_entry_to_dict(e: dict[str, Any]) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": e["id"],
        "title": e["title"],
        "created_at": _fmt_ts(e["created_at"]),
        "updated_at": _fmt_ts(e["updated_at"]),
        "message_count": e["message_count"],
        "token_count": e["token_count"],
        "status": int(e["status"]),
    }
    if e.get("compressed"):
        d["compressed"] = True
    return d


def _index_entry_from_dict(d: dict[str, Any]) -> dict[str, Any]:
    def _ts(v: Any) -> datetime | None:
        if isinstance(v, datetime):
            return v
        return _from_ts(v) if v else None

    return {
        "id": str(d.get("id", "")),
        "title": str(d.get("title", "")),
        "created_at": _ts(d.get("created_at")),
        "updated_at": _ts(d.get("updated_at")),
        "message_count": int(d.get("message_count", 0) or 0),
        "token_count": int(d.get("token_count", 0) or 0),
        "status": d.get("status", SessionStatus.Active),
        "compressed": bool(d.get("compressed", False)),
    }
