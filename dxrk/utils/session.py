# SPDX-License-Identifier: MIT
"""Session utils

Session persistence, serialization, restore, and management utilities:
a canonical session model, pluggable storage backends, JSON/Markdown/HTML/XML
serialization, and a version migration framework.
"""

from __future__ import annotations

import gzip
import json
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Any, Protocol, cast

__all__ = [
    "CurrentVersion",
    "SessionStatus",
    "MessageRole",
    "Session",
    "Message",
    "ToolCall",
    "SessionOpts",
    "SessionError",
    "Storage",
    "SessionSummary",
    "ListOpts",
    "FileStorage",
    "MemoryStorage",
    "Serialize",
    "Deserialize",
    "ExportJSON",
    "ImportJSON",
    "CompactJSON",
    "ExportMarkdown",
    "ExportHTML",
    "ExportXML",
    "ResumeContext",
    "ResumeCriteria",
    "RestoreSession",
    "ResumeSession",
    "CreateSummary",
    "FindResumePoint",
    "AutoArchive",
    "CleanupExpired",
    "RegisterMigration",
    "MigrateSession",
    "ListMigrations",
    "HasMigration",
    "DetectVersion",
    "MigrateToCurrent",
]

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

_EPOCH_UTC = datetime.min.replace(tzinfo=timezone.utc)


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
    return datetime.now(timezone.utc)


def _fmt_ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
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
        dt = dt.replace(tzinfo=timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    off = dt.strftime("%z")
    if off in ("", "+0000"):
        return base + "Z"
    return base + off


def _from_ts(text: str) -> datetime:
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


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
        status=SessionStatus(status)
        if status in _STATUS_NAMES
        else SessionStatus.Active,
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
    return {
        "id": str(d.get("id", "")),
        "title": str(d.get("title", "")),
        "created_at": _from_ts(d["created_at"]) if d.get("created_at") else None,
        "updated_at": _from_ts(d["updated_at"]) if d.get("updated_at") else None,
        "message_count": int(d.get("message_count", 0) or 0),
        "token_count": int(d.get("token_count", 0) or 0),
        "status": d.get("status", SessionStatus.Active),
        "compressed": bool(d.get("compressed", False)),
    }


# ─── storage ───────────────────────────────────────────────────────────────


@dataclass
class SessionSummary:
    id: str = ""
    title: str = ""
    created_at: datetime | None = None
    message_count: int = 0
    token_count: int = 0
    status: SessionStatus = SessionStatus.Active


@dataclass
class ListOpts:
    limit: int = 0
    offset: int = 0
    status: int = -1
    sort_by: str = ""
    sort_dir: str = ""
    after: datetime | None = None
    before: datetime | None = None
    search_query: str = ""


class Storage(Protocol):
    def save(self, session: Session) -> None: ...
    def load(self, id: str) -> Session: ...
    def delete(self, id: str) -> None: ...
    def list(self, opts: ListOpts | None = None) -> list[SessionSummary]: ...
    def exists(self, id: str) -> bool: ...


def _cmp_int(a: int, b: int, asc: bool) -> bool:
    return a < b if asc else a > b


def _cmp_time(a: datetime, b: datetime, asc: bool) -> bool:
    return a < b if asc else a > b


class FileStorage:
    def __init__(self, base_dir: str = "") -> None:
        if not base_dir:
            base_dir = os.path.join(os.path.expanduser("~"), ".dxrk", "sessions")
        self.base_dir = base_dir
        self.mu = threading.RLock()
        self.index: dict[str, Any] = {}
        os.makedirs(base_dir, mode=0o700, exist_ok=True)
        self._load_index()

    def _session_path(self, id: str) -> str:
        return os.path.join(self.base_dir, f"{id}.json")

    def _compressed_path(self, id: str) -> str:
        return os.path.join(self.base_dir, f"{id}.json.gz")

    def _index_path(self) -> str:
        return os.path.join(self.base_dir, ".index.json")

    def save(self, s: Session) -> None:
        with self.mu:
            s.updated_at = now()
            try:
                data = json.dumps(_session_to_dict(s), indent=2)
            except (TypeError, ValueError) as e:
                raise SessionError(f"marshal session: {e}") from e
            target = self._session_path(s.id)
            tmp = target + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(data)
            except OSError as e:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise SessionError(f"write temp: {e}") from e
            try:
                os.replace(tmp, target)
            except OSError as e:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise SessionError(f"atomic rename: {e}") from e
            self.index[s.id] = _index_entry_from_dict(
                {
                    "id": s.id,
                    "title": s.title,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                    "message_count": s.message_count,
                    "token_count": s.token_count,
                    "status": s.status,
                }
            )
            self._write_index()

    def load(self, id: str) -> Session:
        with self.mu:
            _ = self.index.get(id)
        path = self._session_path(id)
        try:
            with open(path, encoding="utf-8") as f:
                data = f.read()
        except FileNotFoundError:
            try:
                data = _read_gz_file(self._compressed_path(id))
            except OSError as e:
                raise SessionError(f"session {id!r} not found") from e
        except OSError as e:
            raise SessionError(f"read session: {e}") from e
        try:
            s = _session_from_dict(json.loads(data))
        except (ValueError, TypeError) as e:
            raise SessionError(f"unmarshal session: {e}") from e
        return s

    def delete(self, id: str) -> None:
        with self.mu:
            try:
                os.remove(self._session_path(id))
            except OSError:
                pass
            try:
                os.remove(self._compressed_path(id))
            except OSError:
                pass
            self.index.pop(id, None)
            self._write_index()

    def exists(self, id: str) -> bool:
        with self.mu:
            if id in self.index:
                return True
        if os.path.exists(self._session_path(id)):
            return True
        return os.path.exists(self._compressed_path(id))

    def list(self, opts: ListOpts | None = None) -> list[SessionSummary]:
        opts = opts or ListOpts()
        with self.mu:
            entries = list(self.index.values())
        filtered: list[Any] = []
        for e in entries:
            if opts.status >= 0 and int(e["status"]) != opts.status:
                continue
            if opts.after is not None and e["created_at"] < opts.after:
                continue
            if opts.before is not None and e["created_at"] > opts.before:
                continue
            if (
                opts.search_query
                and opts.search_query.lower() not in e["title"].lower()
            ):
                continue
            filtered.append(e)

        asc = opts.sort_dir == "asc"
        key = opts.sort_by
        if key == "token_count":
            filtered.sort(key=lambda e: e["token_count"], reverse=not asc)
        elif key == "message_count":
            filtered.sort(key=lambda e: e["message_count"], reverse=not asc)
        else:
            if key == "updated_at":
                filtered.sort(
                    key=lambda e: (
                        e["updated_at"] if e["updated_at"] is not None else _EPOCH_UTC
                    ),
                    reverse=not asc,
                )
            else:
                filtered.sort(
                    key=lambda e: (
                        e["created_at"] if e["created_at"] is not None else _EPOCH_UTC
                    ),
                    reverse=not asc,
                )

        if opts.offset > 0:
            if opts.offset >= len(filtered):
                return []
            filtered = filtered[opts.offset :]
        if opts.limit > 0 and opts.limit < len(filtered):
            filtered = filtered[: opts.limit]

        result: list[SessionSummary] = []
        for e in filtered:
            result.append(
                SessionSummary(
                    id=e["id"],
                    title=e["title"],
                    created_at=e["created_at"],
                    message_count=e["message_count"],
                    token_count=e["token_count"],
                    status=e["status"],
                )
            )
        return result

    def compress_session(self, id: str) -> None:
        with self.mu:
            src = self._session_path(id)
            try:
                with open(src, "rb") as f:
                    data = f.read()
            except OSError as e:
                raise SessionError(str(e)) from e
            dst = self._compressed_path(id)
            try:
                with gzip.open(dst, "wb") as gz:
                    gz.write(data)
            except OSError as e:
                raise SessionError(str(e)) from e
            try:
                os.remove(src)
            except OSError:
                pass
            entry = self.index.get(id)
            if entry is not None:
                entry["compressed"] = True
                self._write_index()

    def _load_index(self) -> None:
        try:
            with open(self._index_path(), encoding="utf-8") as f:
                data = f.read()
        except OSError:
            return
        try:
            entries = json.loads(data)
        except ValueError:
            return
        self.index = {}
        for e in entries:
            if isinstance(e, dict) and e.get("id"):
                self.index[e["id"]] = _index_entry_from_dict(e)

    def _write_index(self) -> None:
        entries = [_index_entry_to_dict(e) for e in self.index.values()]
        try:
            data = json.dumps(entries, indent=2)
            with open(self._index_path(), "w", encoding="utf-8") as f:
                f.write(data)
        except OSError as e:
            raise SessionError(str(e)) from e

    Save = save
    Load = load
    Delete = delete
    List = list
    Exists = exists
    CompressSession = compress_session


NewFileStorage = FileStorage


def _read_gz_file(path: str) -> str:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return f.read()


class MemoryStorage:
    def __init__(self, max_sessions: int = 0) -> None:
        self.mu = threading.RLock()
        self.sessions: dict[str, Session] = {}
        self.order: list[str] = []
        self.max_sessions = max_sessions

    def save(self, s: Session) -> None:
        with self.mu:
            if s.id not in self.sessions:
                self.order.append(s.id)
            self.sessions[s.id] = s
            while self.max_sessions > 0 and len(self.order) > self.max_sessions:
                self.order = self.order[1:]
                self.sessions.pop(self.order[0], None)

    def load(self, id: str) -> Session:
        with self.mu:
            s = self.sessions.get(id)
            if s is None:
                raise SessionError(f"session {id!r} not found")
            return s

    def delete(self, id: str) -> None:
        with self.mu:
            if id not in self.sessions:
                raise SessionError(f"session {id!r} not found")
            self.sessions.pop(id, None)
            for i, oid in enumerate(self.order):
                if oid == id:
                    self.order = self.order[:i] + self.order[i + 1 :]
                    break

    def list(self, opts: ListOpts | None = None) -> list[SessionSummary]:
        opts = opts or ListOpts()
        with self.mu:
            result: list[SessionSummary] = []
            for s in self.sessions.values():
                if opts.status >= 0 and int(s.status) != opts.status:
                    continue
                if (
                    opts.search_query
                    and opts.search_query.lower() not in s.title.lower()
                ):
                    continue
                result.append(
                    SessionSummary(
                        id=s.id,
                        title=s.title,
                        created_at=s.created_at,
                        message_count=s.message_count,
                        token_count=s.token_count,
                        status=s.status,
                    )
                )
            key = opts.sort_by
            if key == "token_count":
                result.sort(key=lambda sm: sm.token_count, reverse=True)
            elif key == "message_count":
                result.sort(key=lambda sm: sm.message_count, reverse=True)
            else:
                result.sort(
                    key=lambda sm: (
                        sm.created_at if sm.created_at is not None else _EPOCH_UTC
                    ),
                    reverse=True,
                )
            if opts.offset > 0 and opts.offset < len(result):
                result = result[opts.offset :]
            if opts.limit > 0 and opts.limit < len(result):
                result = result[: opts.limit]
            return result

    def exists(self, id: str) -> bool:
        with self.mu:
            return id in self.sessions

    Save = save
    Load = load
    Delete = delete
    List = list
    Exists = exists


NewMemoryStorage = MemoryStorage


# ─── serialization ─────────────────────────────────────────────────────────


class Format:
    JSON = 0
    Markdown = 1
    HTML = 2
    XML = 3


_GO_QUOTE_CHARS = {'"': r"\"", "\\": r"\\", "\n": r"\n", "\t": r"\t", "\r": r"\r"}


def _go_quote(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in _GO_QUOTE_CHARS:
            out.append(_GO_QUOTE_CHARS[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def serialize(s: Session, format: int) -> str:
    if format == Format.JSON:
        return export_json(s)
    if format == Format.Markdown:
        return export_markdown(s)
    if format == Format.HTML:
        return export_html(s)
    if format == Format.XML:
        return export_xml(s)
    raise SessionError(f"unsupported format: {format}")


def deserialize(data: str, format: int) -> Session:
    if format != Format.JSON:
        raise SessionError("deserialize only supports JSON")
    return import_json(data)


def export_json(s: Session) -> str:
    return json.dumps(_session_to_dict(s), indent=2)


def import_json(data: str) -> Session:
    try:
        return _session_from_dict(json.loads(data))
    except (ValueError, TypeError) as e:
        raise SessionError(f"unmarshal session: {e}") from e


def compact_json(data: str) -> str:
    try:
        s = _session_from_dict(json.loads(data))
    except (ValueError, TypeError) as e:
        raise SessionError(str(e)) from e
    s.messages = []
    s.summary = ""
    return json.dumps(_session_to_dict(s), indent=2)


def _title_english(s: str) -> str:
    return " ".join(word.capitalize() for word in s.split())


def export_markdown(s: Session) -> str:
    lines: list[str] = []
    lines.append("---")
    lines.append(f"session_id: {s.id}")
    if s.parent_id:
        lines.append(f"parent_id: {s.parent_id}")
    lines.append(f"title: {_go_quote(s.title)}")
    lines.append(f"model: {s.model}")
    lines.append(f"created_at: {_fmt_rfc3339(s.created_at) if s.created_at else ''}")
    lines.append(f"updated_at: {_fmt_rfc3339(s.updated_at) if s.updated_at else ''}")
    lines.append(f"status: {s.status}")
    lines.append(f"messages: {s.message_count}")
    lines.append(f"tokens: {s.token_count}")
    if s.tags:
        lines.append(f"tags: [{', '.join(s.tags)}]")
    lines.append("---")
    lines.append("")
    lines.append(f"# {s.title}")
    lines.append("")
    if s.summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(s.summary)
        lines.append("")
    for msg in s.messages:
        lines.append(f"### {_title_english(str(msg.role))}")
        ts = msg.timestamp.strftime("%Y-%m-%d %H:%M:%S") if msg.timestamp else ""
        lines.append(f"*{ts}*")
        lines.append("")
        if msg.content:
            if msg.role == RoleAssistant:
                lines.append("```")
                lines.append(msg.content)
                lines.append("```")
                lines.append("")
            else:
                lines.append(msg.content)
                lines.append("")
        for tc in msg.tool_calls:
            lines.append(f"**Tool: {tc.name}**")
            if tc.input:
                lines.append(f"Input: `{tc.input}`")
            if tc.output:
                lines.append(f"Output: `{tc.output}`")
            if tc.error:
                lines.append(f"Error: `{tc.error}`")
            lines.append("")
    return "\n".join(lines)


def export_html(s: Session) -> str:
    lines: list[str] = []
    lines.append("<!DOCTYPE html>")
    lines.append('<html lang="en"><head><meta charset="utf-8">')
    lines.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    lines.append(f"<title>{html_escape(s.title)}</title>")
    lines.append(
        "<style>body{font-family:system-ui,sans-serif;max-width:800px;margin:0 auto;padding:2rem;line-height:1.6}"
    )
    lines.append("h1{border-bottom:2px solid #333;padding-bottom:.5rem}")
    lines.append(
        ".msg{margin:1.5rem 0;padding:1rem;border-radius:8px;border-left:4px solid #ccc}"
    )
    lines.append(".msg-user{background:#f0f7ff;border-color:#4a9eff}")
    lines.append(".msg-assistant{background:#f5fff0;border-color:#4aff4a}")
    lines.append(".msg-system{background:#fff8f0;border-color:#ffaa4a}")
    lines.append(".role{font-weight:bold;text-transform:capitalize}")
    lines.append(".time{color:#888;font-size:.85em}")
    lines.append(
        "pre{background:#f4f4f4;padding:1rem;overflow-x:auto;border-radius:4px}"
    )
    lines.append(
        "code{background:#f4f4f4;padding:.15em .3em;border-radius:3px;font-size:.9em}"
    )
    lines.append("</style></head><body>")
    lines.append("")
    lines.append(f"<h1>{html_escape(s.title)}</h1>")
    lines.append(
        f"<p><strong>Model:</strong> {html_escape(s.model)} &mdash; <strong>Messages:</strong> "
        f"{s.message_count} &mdash; <strong>Tokens:</strong> {s.token_count}</p>"
    )
    created = _fmt_rfc3339(s.created_at) if s.created_at else ""
    updated = _fmt_rfc3339(s.updated_at) if s.updated_at else ""
    lines.append(
        f"<p><em>Created: {created} &mdash; Updated: {updated} &mdash; Status: {s.status}</em></p>"
    )
    lines.append("")
    if s.summary:
        lines.append(f"<h2>Summary</h2><div>{html_escape(s.summary)}</div>")
    for msg in s.messages:
        lines.append(f'<div class="msg msg-{msg.role}">')
        ts = _fmt_rfc3339(msg.timestamp) if msg.timestamp else ""
        lines.append(
            f'<span class="role">{html_escape(str(msg.role))}</span> '
            f'<span class="time">{ts}</span>'
        )
        if msg.content:
            lines.append(f"<pre><code>{html_escape(msg.content)}</code></pre>")
        for tc in msg.tool_calls:
            err = f" <em>(error: {html_escape(tc.error)})</em>" if tc.error else ""
            lines.append(
                f'<div class="tool-call"><strong>Tool: {html_escape(tc.name)}</strong>{err}</div>'
            )
        lines.append("</div>")
    lines.append("</body></html>")
    return "\n".join(lines)


def html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&#34;")
        .replace("'", "&#39;")
    )


def xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def export_xml(s: Session) -> str:
    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append("<session>")
    lines.append(f"  <id>{xml_escape(s.id)}</id>")
    lines.append(f"  <title>{xml_escape(s.title)}</title>")
    lines.append(f"  <model>{xml_escape(s.model)}</model>")
    lines.append(f"  <status>{s.status}</status>")
    lines.append(
        f"  <created_at>{_fmt_rfc3339(s.created_at) if s.created_at else ''}</created_at>"
    )
    lines.append(
        f"  <updated_at>{_fmt_rfc3339(s.updated_at) if s.updated_at else ''}</updated_at>"
    )
    lines.append(f"  <message_count>{s.message_count}</message_count>")
    lines.append(f"  <token_count>{s.token_count}</token_count>")
    if s.summary:
        lines.append(f"  <summary>{xml_escape(s.summary)}</summary>")
    lines.append("  <messages>")
    for msg in s.messages:
        lines.append("    <message>")
        ts = _fmt_rfc3339(msg.timestamp) if msg.timestamp else ""
        lines.append(f"      <id>{xml_escape(msg.id)}</id>")
        lines.append(f"      <role>{msg.role}</role>")
        lines.append(f"      <timestamp>{ts}</timestamp>")
        if msg.content:
            lines.append(f"      <content>{xml_escape(msg.content)}</content>")
        for tc in msg.tool_calls:
            lines.append(f"      <tool_call>")
            lines.append(f"        <name>{xml_escape(tc.name)}</name>")
            lines.append(f"        <input>{xml_escape(tc.input)}</input>")
            if tc.output:
                lines.append(f"        <output>{xml_escape(tc.output)}</output>")
            lines.append("      </tool_call>")
        lines.append("    </message>")
    lines.append("  </messages>")
    lines.append("</session>")
    return "\n".join(lines)


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
        raise SessionError(
            f"session version {s.version} exceeds current version {CurrentVersion}"
        )
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
        prefix = (
            f"Session {_go_quote(s.title)} ({len(kept)} of {len(s.messages)} messages, "
            f"~{used} tokens).\n"
        )
    else:
        prefix = (
            f"Session {_go_quote(s.title)} ({len(s.messages)} messages, "
            f"~{s.token_count} tokens).\n"
        )
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


# ─── migration ─────────────────────────────────────────────────────────────


MigrationFunc = Any

_migrations_mu = threading.Lock()
_migrations: list[tuple[int, int, MigrationFunc]] = []
_migrations_built = False


def register_migration(from_version: int, to_version: int, fn: MigrationFunc) -> None:
    with _migrations_mu:
        for m in _migrations:
            if m[0] == from_version and m[1] == to_version:
                return
        _migrations.append((from_version, to_version, fn))


def migrate_session(data: str, from_version: int, to_version: int) -> str:
    if from_version == to_version:
        return data
    if from_version > to_version:
        raise SessionError(
            f"downgrade migrations not supported: {from_version} -> {to_version}"
        )
    current = from_version
    current_data = data
    while current < to_version:
        fn = find_migration(current, current + 1)
        if fn is None:
            raise SessionError(f"no migration from version {current} to {current + 1}")
        try:
            current_data = fn(current_data)
        except SessionError as e:
            raise SessionError(
                f"migration {current} -> {current + 1} failed: {e}"
            ) from e
        try:
            probe = json.loads(current_data)
            probe_version = (
                int(probe.get("version", 0) or 0) if isinstance(probe, dict) else 0
            )
        except ValueError:
            probe_version = current
        if probe_version > current:
            current = probe_version
        else:
            current += 1
    return current_data


def find_migration(from_version: int, to_version: int) -> MigrationFunc | None:
    with _migrations_mu:
        for m in _migrations:
            if m[0] == from_version and m[1] == to_version:
                return m[2]
    return None


def _build_migrations() -> None:
    global _migrations_built
    with _migrations_mu:
        if _migrations_built:
            return
        _migrations_built = True

        def v1_to_v2(data: str) -> str:
            try:
                raw = json.loads(data)
            except ValueError as e:
                raise SessionError(f"unmarshal v1: {e}") from e
            if not isinstance(raw, dict):
                raise SessionError("unmarshal v1: expected object")
            raw["version"] = 2
            if "messages" not in raw:
                raw["messages"] = []
            status = raw.get("status")
            if isinstance(status, (int, float)) and not isinstance(status, bool):
                names = {
                    0: "active",
                    1: "paused",
                    2: "completed",
                    3: "archived",
                    4: "expired",
                }
                raw["status"] = names.get(int(status), "active")
            return json.dumps(raw, indent=2)

        _migrations.append((1, 2, v1_to_v2))


def list_migrations() -> list[str]:
    with _migrations_mu:
        paths = [f"{m[0]} -> {m[1]}" for m in _migrations]
    return sorted(paths)


def has_migration(from_version: int, to_version: int) -> bool:
    return find_migration(from_version, to_version) is not None


def detect_version(data: str) -> int:
    try:
        probe = json.loads(data)
        version = int(probe.get("version", 0) or 0) if isinstance(probe, dict) else 0
    except (ValueError, TypeError) as e:
        raise SessionError(f"detect version: {e}") from e
    return version


def migrate_to_current(data: str) -> str:
    v = detect_version(data)
    return migrate_session(data, v, CurrentVersion)


_build_migrations()


Serialize = serialize
Deserialize = deserialize
ExportJSON = export_json
ImportJSON = import_json
CompactJSON = compact_json
ExportMarkdown = export_markdown
ExportHTML = export_html
ExportXML = export_xml
RestoreSession = restore_session
ResumeSession = resume_session
CreateSummary = create_summary
FindResumePoint = find_resume_point
AutoArchive = auto_archive
CleanupExpired = cleanup_expired
RegisterMigration = register_migration
MigrateSession = migrate_session
ListMigrations = list_migrations
HasMigration = has_migration
DetectVersion = detect_version
MigrateToCurrent = migrate_to_current
