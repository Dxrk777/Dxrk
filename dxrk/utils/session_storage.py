# SPDX-License-Identifier: MIT
"""Session storage backends: file-based storage with index plus memory storage."""

from __future__ import annotations

import gzip
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from dxrk.utils.session_codec import _index_entry_from_dict, _index_entry_to_dict, _session_from_dict, _session_to_dict
from dxrk.utils.session_model import _EPOCH_UTC, Session, SessionError, SessionStatus, now

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
            if opts.search_query and opts.search_query.lower() not in e["title"].lower():
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
                    key=lambda e: e["updated_at"] if e["updated_at"] is not None else _EPOCH_UTC,
                    reverse=not asc,
                )
            else:
                filtered.sort(
                    key=lambda e: e["created_at"] if e["created_at"] is not None else _EPOCH_UTC,
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
                if opts.search_query and opts.search_query.lower() not in s.title.lower():
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
                    key=lambda sm: sm.created_at if sm.created_at is not None else _EPOCH_UTC,
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
