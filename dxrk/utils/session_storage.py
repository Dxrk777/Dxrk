# SPDX-License-Identifier: MIT
"""Session storage backends: file-based storage with index plus memory storage."""

from __future__ import annotations

import gzip
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from dxrk.utils.session_codec import _index_entry_from_dict, _index_entry_to_dict, _session_from_dict, _session_to_dict
from dxrk.utils.session_model import _EPOCH_UTC, Session, SessionError, SessionStatus, now

# ─── durable atomic writes ───────────────────────────────────────────


def _fsync_parent(directory: str) -> None:
    """Best-effort parent-directory fsync. Never raises.

    Portable by design: opening/fsyncing a directory fails on Windows, so
    every failure mode is swallowed — the file-level fsync above is the
    real durability guarantee.
    """
    if not directory:
        directory = "."
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _atomic_write_bytes(path: str, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically and durably. Raises OSError.

    Tmp file in the same directory + file fsync + ``os.replace`` +
    best-effort dir fsync. ``OSError`` messages are stage-tagged
    (``write temp`` / ``atomic rename``) so callers keep stable errors.
    """
    directory = os.path.dirname(path) or "."
    try:
        fd, tmp = tempfile.mkstemp(prefix=".dxrk-tmp-", dir=directory)
    except OSError as e:
        raise OSError(f"write temp: {e}") from e
    try:
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        except OSError as e:
            raise OSError(f"write temp: {e}") from e
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        try:
            os.replace(tmp, path)
        except OSError as e:
            raise OSError(f"atomic rename: {e}") from e
        _fsync_parent(directory)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _atomic_write_text(path: str, data: str) -> None:
    """Text wrapper over :func:`_atomic_write_bytes`. Raises OSError."""
    _atomic_write_bytes(path, data.encode("utf-8"))


def _atomic_write_gz_bytes(path: str, data: bytes) -> None:
    """Compress ``data`` and write ``path`` atomically. Raises OSError."""
    try:
        compressed = gzip.compress(data)
    except OSError as e:
        raise OSError(f"compress: {e}") from e
    _atomic_write_bytes(path, compressed)


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
            try:
                _atomic_write_text(self._session_path(s.id), data)
            except OSError as e:
                raise SessionError(str(e)) from e
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
        corrupt: Exception | None = None
        data: str | None = None
        try:
            with open(path, encoding="utf-8") as f:
                data = f.read()
        except FileNotFoundError:
            data = None
        except OSError as e:
            raise SessionError(f"read session: {e}") from e
        if data is not None:
            try:
                return _session_from_dict(json.loads(data))
            except (ValueError, TypeError) as e:
                # .json is torn — fall through to the .gz copy below.
                corrupt = e
        try:
            gz_data = _read_gz_file(self._compressed_path(id))
        except OSError as e:
            if corrupt is not None:
                raise SessionError(f"unmarshal session: {corrupt}") from corrupt
            raise SessionError(f"session {id!r} not found") from e
        try:
            return _session_from_dict(json.loads(gz_data))
        except (ValueError, TypeError) as e:
            raise SessionError(f"unmarshal session: {e}") from e

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
            try:
                _atomic_write_gz_bytes(self._compressed_path(id), data)
            except OSError as e:
                raise SessionError(str(e)) from e
            try:
                os.remove(src)
            except OSError:
                pass
            else:
                _fsync_parent(os.path.dirname(src) or ".")
            entry = self.index.get(id)
            if entry is not None:
                entry["compressed"] = True
                self._write_index()

    def _rebuild_index_from_disk(self) -> None:
        """Rebuild the in-memory index by scanning session files on disk.

        Unparseable files are skipped (they surface on ``load``); a
        compressed-only session (``.json.gz`` without ``.json``) is indexed
        from its ``.gz`` copy with ``compressed=True``.
        """
        rebuilt: dict[str, Any] = {}
        try:
            names = os.listdir(self.base_dir)
        except OSError:
            return
        for name in names:
            if name == ".index.json" or name.endswith(".tmp"):
                continue
            full = os.path.join(self.base_dir, name)
            if os.path.isdir(full):
                continue
            compressed = False
            if name.endswith(".json.gz"):
                sid = name[: -len(".json.gz")]
                if os.path.exists(os.path.join(self.base_dir, f"{sid}.json")):
                    continue
                try:
                    raw = _read_gz_file(full)
                except OSError:
                    continue
                compressed = True
            elif name.endswith(".json"):
                sid = name[: -len(".json")]
                try:
                    with open(full, encoding="utf-8") as f:
                        raw = f.read()
                except OSError:
                    continue
            else:
                continue
            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    continue
                s = _session_from_dict(payload)
            except (ValueError, TypeError):
                continue
            if not s.id:
                continue
            entry = _index_entry_from_dict(
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
            if compressed:
                entry["compressed"] = True
            rebuilt[s.id] = entry
        self.index = rebuilt

    def _load_index(self) -> None:
        rebuilt = False
        try:
            with open(self._index_path(), encoding="utf-8") as f:
                data = f.read()
        except OSError:
            self._rebuild_index_from_disk()
            rebuilt = True
        else:
            try:
                entries = json.loads(data)
            except ValueError:
                self._rebuild_index_from_disk()
                rebuilt = True
            else:
                if not isinstance(entries, list):
                    self._rebuild_index_from_disk()
                    rebuilt = True
                else:
                    self.index = {}
                    for e in entries:
                        if isinstance(e, dict) and e.get("id"):
                            self.index[e["id"]] = _index_entry_from_dict(e)
                    if not self.index:
                        # Valid but empty (e.g. wiped) while files exist: rescan.
                        self._rebuild_index_from_disk()
                        rebuilt = True
        if rebuilt:
            # Persist the healed index; a failure here must not break startup
            # (the in-memory rebuild is already usable, and the next startup
            # retries the rescan).
            try:
                self._write_index()
            except SessionError:
                pass

    def _write_index(self) -> None:
        entries = [_index_entry_to_dict(e) for e in self.index.values()]
        try:
            data = json.dumps(entries, indent=2)
        except (TypeError, ValueError) as e:
            raise SessionError(str(e)) from e
        try:
            _atomic_write_text(self._index_path(), data)
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
                evicted = self.order.pop(0)
                self.sessions.pop(evicted, None)

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
