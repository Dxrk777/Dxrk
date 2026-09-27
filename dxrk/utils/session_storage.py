# SPDX-License-Identifier: MIT
"""Session storage backends: file-based storage with index, memory storage,
and an opt-in SQLite/WAL store implementing the same ``Storage`` protocol."""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from dxrk.utils.session_codec import _index_entry_from_dict, _index_entry_to_dict, _session_from_dict, _session_to_dict
from dxrk.utils.session_migrate import migrate_to_current
from dxrk.utils.session_model import _EPOCH_UTC, Session, SessionError, SessionStatus, _fmt_ts, _from_ts, now

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


def _migrated_or_raw(raw: str) -> str:
    """Run ``raw`` through the migration registry, passing it through on failure.

    Unknown layouts (e.g. version-less files predating the registry) stay
    readable; genuine v1 payloads come out canonical (v2).
    """
    try:
        return migrate_to_current(raw)
    except SessionError:
        return raw


def _parse_session_payload(raw: str) -> Session:
    try:
        payload = json.loads(_migrated_or_raw(raw))
    except (ValueError, TypeError) as e:
        raise SessionError(f"unmarshal session: {e}") from e
    if not isinstance(payload, dict):
        raise SessionError("unmarshal session: expected object")
    return _session_from_dict(payload)


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


def _validate_session_id(base_dir: str, id: str) -> str:
    """Resolve ``id`` to a session file path, rejecting path traversal.

    Shared by every disk-backed store so sanitization semantics stay
    identical. Raises SessionError for empty ids, absolute paths,
    separators, NUL bytes, ``..`` components, or anything resolving
    outside ``base_dir``. Session ids are generated internally (hex);
    anything else never names a real session file.
    """
    if not id or id in (".", ".."):
        raise SessionError(f"invalid session id: {id!r}")
    if os.path.isabs(id) or "/" in id or "\\" in id or "\x00" in id:
        raise SessionError(f"invalid session id: {id!r}")
    full = os.path.realpath(os.path.join(base_dir, f"{id}.json"))
    base = os.path.realpath(base_dir)
    if full != base and not full.startswith(base + os.sep):
        raise SessionError(f"invalid session id: {id!r}")
    return full


def _summaries_from_entries(entries: list[dict[str, Any]], opts: ListOpts | None = None) -> list[SessionSummary]:
    """Filter/sort/paginate raw index entries into ``SessionSummary`` items.

    Shared by every index-backed store (FileStorage, SQLiteSessionStorage)
    so ``list`` semantics are identical by construction. Entries carry the
    ``_index_entry_from_dict`` shape (id/title/created_at/updated_at/
    message_count/token_count/status); payloads are never consulted.
    """
    opts = opts or ListOpts()
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

    def _validate_session_id(self, id: str) -> str:
        """Resolve ``id`` to a session file path, rejecting path traversal.

        Delegates to the shared :func:`_validate_session_id` helper so all
        disk-backed stores enforce identical sanitization.
        """
        return _validate_session_id(self.base_dir, id)

    def _session_path(self, id: str) -> str:
        return self._validate_session_id(id)

    def _compressed_path(self, id: str) -> str:
        return self._validate_session_id(id) + ".gz"

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
        corrupt: SessionError | None = None
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
                return _parse_session_payload(data)
            except SessionError as e:
                # .json is torn — fall through to the .gz copy below.
                corrupt = e
        try:
            gz_data = _read_gz_file(self._compressed_path(id))
        except OSError as e:
            if corrupt is not None:
                raise corrupt from corrupt
            raise SessionError(f"session {id!r} not found") from e
        return _parse_session_payload(gz_data)

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
        with self.mu:
            entries = list(self.index.values())
        return _summaries_from_entries(entries, opts)

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
                payload = json.loads(_migrated_or_raw(raw))
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


# ─── sqlite/wal storage (opt-in) ─────────────────────────────────────────


SESSION_BACKEND_ENV_VAR = "DXRK_SESSION_BACKEND"

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 2,
    title TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    status INTEGER NOT NULL DEFAULT 0,
    message_count INTEGER NOT NULL DEFAULT 0,
    token_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_model ON sessions(model);
"""


def _sqlite_ts(value: Any) -> datetime | None:
    try:
        return _from_ts(value) if value else None
    except (ValueError, TypeError):
        return None


class SQLiteSessionStorage:
    """Opt-in SQLite/WAL session store implementing the ``Storage`` protocol.

    Same semantics as :class:`FileStorage` (save/load/delete/exists/list,
    SessionError contract, id sanitization, migration-on-load): ``list`` is
    served from indexed columns via the shared ``_summaries_from_entries``
    helper, so filtering/sorting/pagination behave identically by
    construction and payloads are never parsed for listing.

    Opt-in only — the JSON dir stays the default backend. Select it either
    explicitly (``SQLiteSessionStorage(base_dir)``) or via the
    ``DXRK_SESSION_BACKEND=sqlite`` environment variable with
    :func:`open_session_storage`.

    Layout: one ``sessions.db`` file in ``base_dir`` (mode 0600), WAL
    journal, ``busy_timeout=5000``. Each save is a single upsert
    transaction (atomic). ``load`` parses the stored payload through the
    migration registry, so registry versions migrate lazily exactly like
    the file backend.

    PINNED DIFFERENCE vs FileStorage: a row whose payload is corrupt (only
    possible via external tampering — saves always write valid JSON) still
    appears in ``list`` (columns are the source of truth for listing)
    while ``load`` raises SessionError. FileStorage instead drops torn
    files from a rebuilt index. See
    ``tests/test_session_phase03_sqlite.py::test_pinned_difference_corrupt_visibility``.

    Deliberately NOT ported: ``compress_session`` (payloads live inline in
    the db; there is no ``.json``/``.json.gz`` duality) and the CLI-level
    ``.quarantine/`` directory (a CLI concern in ``commands/session.py``,
    not a store concern).
    """

    DB_FILENAME = "sessions.db"

    def __init__(self, base_dir: str = "") -> None:
        if not base_dir:
            base_dir = os.path.join(os.path.expanduser("~"), ".dxrk", "sessions")
        self.base_dir = base_dir
        self.mu = threading.RLock()
        os.makedirs(base_dir, mode=0o700, exist_ok=True)
        self.db_path = os.path.join(base_dir, self.DB_FILENAME)
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        except sqlite3.Error as e:
            raise SessionError(f"open sqlite store: {e}") from e
        try:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.executescript(_SQLITE_SCHEMA)
            self._conn.commit()
        except sqlite3.Error as e:
            self._conn.close()
            raise SessionError(f"init sqlite store: {e}") from e
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def save(self, s: Session) -> None:
        _validate_session_id(self.base_dir, s.id)
        with self.mu:
            s.updated_at = now()
            try:
                data = json.dumps(_session_to_dict(s), indent=2)
            except (TypeError, ValueError) as e:
                raise SessionError(f"marshal session: {e}") from e
            self._upsert_row(s, data)

    def _upsert_row(self, s: Session, payload: str) -> None:
        """Insert or replace the row for ``s`` without touching timestamps.

        Public ``save`` always refreshes ``updated_at`` first; the
        JSON-dir importer calls this directly to preserve original
        timestamps. Raises SessionError on sqlite failures.
        """
        try:
            tags = json.dumps(list(s.tags))
        except (TypeError, ValueError) as e:
            raise SessionError(f"marshal session: {e}") from e
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO sessions "
                    "(id, payload, version, title, model, status, message_count,"
                    " token_count, created_at, updated_at, tags) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "payload=excluded.payload, version=excluded.version, title=excluded.title,"
                    " model=excluded.model, status=excluded.status,"
                    " message_count=excluded.message_count, token_count=excluded.token_count,"
                    " created_at=excluded.created_at, updated_at=excluded.updated_at,"
                    " tags=excluded.tags",
                    (
                        s.id,
                        payload,
                        s.version,
                        s.title,
                        s.model,
                        int(s.status),
                        s.message_count,
                        s.token_count,
                        _fmt_ts(s.created_at) if s.created_at else "",
                        _fmt_ts(s.updated_at) if s.updated_at else "",
                        tags,
                    ),
                )
        except sqlite3.Error as e:
            raise SessionError(f"save session: {e}") from e

    def load(self, id: str) -> Session:
        _validate_session_id(self.base_dir, id)
        with self.mu:
            try:
                row = self._conn.execute("SELECT payload FROM sessions WHERE id = ?", (id,)).fetchone()
            except sqlite3.Error as e:
                raise SessionError(f"read session: {e}") from e
        if row is None:
            raise SessionError(f"session {id!r} not found")
        return _parse_session_payload(str(row[0]))

    def delete(self, id: str) -> None:
        _validate_session_id(self.base_dir, id)
        with self.mu:
            try:
                with self._conn:
                    self._conn.execute("DELETE FROM sessions WHERE id = ?", (id,))
            except sqlite3.Error as e:
                raise SessionError(f"delete session: {e}") from e

    def exists(self, id: str) -> bool:
        _validate_session_id(self.base_dir, id)
        with self.mu:
            try:
                row = self._conn.execute("SELECT 1 FROM sessions WHERE id = ?", (id,)).fetchone()
            except sqlite3.Error as e:
                raise SessionError(f"read session: {e}") from e
        return row is not None

    def list(self, opts: ListOpts | None = None) -> list[SessionSummary]:
        # Indexed columns only — the payload is never selected, let alone
        # parsed, so listing is O(rows) without per-session JSON work.
        with self.mu:
            try:
                rows = self._conn.execute(
                    "SELECT id, title, created_at, updated_at, message_count, token_count, status FROM sessions"
                ).fetchall()
            except sqlite3.Error as e:
                raise SessionError(f"list sessions: {e}") from e
        entries: list[dict[str, Any]] = [
            {
                "id": str(r[0]),
                "title": str(r[1]),
                "created_at": _sqlite_ts(r[2]),
                "updated_at": _sqlite_ts(r[3]),
                "message_count": int(r[4] or 0),
                "token_count": int(r[5] or 0),
                "status": self._status_from_row(r[6]),
                "compressed": False,
            }
            for r in rows
        ]
        return _summaries_from_entries(entries, opts)

    @staticmethod
    def _status_from_row(value: Any) -> SessionStatus:
        try:
            return SessionStatus(int(value))
        except (ValueError, TypeError):
            return SessionStatus.Active

    def close(self) -> None:
        with self.mu:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    Save = save
    Load = load
    Delete = delete
    List = list
    Exists = exists
    Close = close


NewSQLiteSessionStorage = SQLiteSessionStorage


def open_session_storage(base_dir: str = "") -> FileStorage | SQLiteSessionStorage:
    """Return the session store selected by the environment (default: file).

    The JSON dir (FileStorage) stays the default backend. Set
    ``DXRK_SESSION_BACKEND=sqlite`` to opt into the SQLite/WAL store.
    Unknown values fall back to FileStorage.
    """
    if os.environ.get(SESSION_BACKEND_ENV_VAR, "").strip().lower() == "sqlite":
        return SQLiteSessionStorage(base_dir)
    return FileStorage(base_dir)


@dataclass
class JsonToSqliteResult:
    imported: int = 0
    skipped: int = 0
    skipped_ids: list[str] = field(default_factory=list)


def migrate_json_dir_to_sqlite(source: FileStorage | str, target: SQLiteSessionStorage) -> JsonToSqliteResult:
    """One-shot import of a JSON session dir into a SQLite store.

    Reads ``*.json`` plus compressed-only ``*.json.gz`` sessions through
    ``FileStorage.load`` (so ``.gz`` fallback and registry migration
    apply), then upserts each row preserving the original
    ``created_at``/``updated_at`` timestamps. Unparseable files are
    skipped and reported in ``skipped_ids`` (mirroring the index-rebuild
    skip policy). Idempotent: re-running upserts the same rows.
    Raises SessionError when the source dir is unreadable.
    """
    if isinstance(source, str):
        file_store = FileStorage(source)
        src_dir = source
    else:
        file_store = source
        src_dir = source.base_dir
    result = JsonToSqliteResult()
    try:
        names = sorted(os.listdir(src_dir))
    except OSError as e:
        raise SessionError(f"read session dir: {e}") from e
    seen: set[str] = set()
    for name in names:
        if name == ".index.json" or name.endswith(".tmp"):
            continue
        full = os.path.join(src_dir, name)
        if os.path.isdir(full):
            continue
        sid: str | None = None
        if name.endswith(".json.gz"):
            sid = name[: -len(".json.gz")]
            if os.path.exists(os.path.join(src_dir, f"{sid}.json")):
                continue
        elif name.endswith(".json"):
            sid = name[: -len(".json")]
        else:
            continue
        if not sid or sid in seen:
            continue
        seen.add(sid)
        try:
            s = file_store.load(sid)
        except SessionError:
            result.skipped += 1
            result.skipped_ids.append(sid)
            continue
        try:
            payload = json.dumps(_session_to_dict(s), indent=2)
        except (TypeError, ValueError) as e:
            raise SessionError(f"marshal session: {e}") from e
        target._upsert_row(s, payload)
        result.imported += 1
    return result


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
