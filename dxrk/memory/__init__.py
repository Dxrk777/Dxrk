# SPDX-License-Identifier: MIT
"""Agent memory persistence — facade keeping AgentMemory compat while delegating to SqliteBackend when palace path is used."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from threading import RLock

# Re-export enriched types
from .types import MemoryType as _MemoryTypeBase  # noqa: F401 (expose)


# Keep local IntEnum with 3 legacy values for strict backward compat (tests compare MemoryType(0) etc.)
class MemoryType(IntEnum):
    SEMANTIC = 0
    EPISODIC = 1
    PROCEDURAL = 2
    # additive extensions (optional)
    TECHNICAL = 3
    PERSONAL = 4


@dataclass
class MemoryEntry:
    id: str = ""
    type: MemoryType = MemoryType.SEMANTIC
    content: str = ""
    metadata: dict[str, str] | None = None
    embedding: list[float] | None = None
    created_at: str = ""
    accessed_at: str = ""
    access_count: int = 0
    importance: float = 0.0
    project_id: str = ""
    session_id: str = ""
    # enriched additive fields (default so old JSON still loads)
    title: str = ""
    scope: str = ""
    topic_key: str = ""
    wing: str = ""
    room: str = ""
    drawer_id: str = ""
    palace_path: str = ""


@dataclass
class MemoryStats:
    total_entries: int = 0
    by_project: int = 0
    by_session: int = 0
    by_type: dict[MemoryType, int] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.fromtimestamp(0, tz=UTC)


def _is_sqlite_path(path: str | Path | None) -> bool:
    if not path:
        return False
    s = str(path).strip()
    if not s:
        return False
    low = s.lower()
    if low.endswith(".json"):
        return False
    return True


def top_by_importance(entries: list[MemoryEntry], limit: int) -> list[MemoryEntry]:
    if len(entries) <= limit:
        return entries
    return sorted(entries, key=lambda e: e.importance, reverse=True)[:limit]


class AgentMemory:
    """In-memory entry store persisted as JSON, indexed by project, session and type.

    When ``path`` points to a sqlite palace (directory or .db file) the store
    additionally delegates to :class:`dxrk.memory.backend.sqlite.SqliteBackend`
    (hybrid BM25). JSON path remains the backward-compat fallback used by tests.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        max_entries: int = 0,
        rag: object | None = None,
        vault: object | None = None,
    ) -> None:
        self._lock = RLock()
        self._entries: dict[str, MemoryEntry] = {}
        self._by_project: dict[str, list[str]] = {}
        self._by_session: dict[str, list[str]] = {}
        self._by_type: dict[MemoryType, list[str]] = {}
        self._rag = rag
        self._vault = vault
        self._path = str(path) if path else ""
        self._max_entries = max_entries
        self._use_sqlite = _is_sqlite_path(path)
        self._palace: object | None = None
        self._palace_collection: object | None = None
        if self._use_sqlite:
            try:
                from .palace import Palace

                # path is palace dir or db file
                palace_dir = str(path) if path else ""
                # if path is a file ending .db, use its parent dir
                p = Path(palace_dir).expanduser()
                if p.is_file() or p.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
                    palace_dir = str(p.parent)
                pal = Palace(palace_dir)
                self._palace = pal
                # ensure palace dir exists
                Path(palace_dir).mkdir(parents=True, exist_ok=True)
                try:
                    Path(palace_dir).chmod(0o750)
                except OSError:
                    pass
                pal.init()
                self._palace_collection = pal._collection(create=True)  # type: ignore
            except Exception:
                # fall back to JSON if palace init fails
                self._use_sqlite = False
                self._palace = None
                self._palace_collection = None
        self._load()

    def store(self, entry: MemoryEntry) -> None:
        if not entry.id:
            entry.id = f"mem-{time.time_ns()}"
        entry.created_at = _now()
        entry.accessed_at = entry.created_at

        if entry.content and self._rag is not None:
            enabled = getattr(self._rag, "is_enabled", lambda: False)()
            query = getattr(self._rag, "query", None)
            if enabled and query is not None:
                results = query(entry.content, 1)
                if results:
                    rec = getattr(results[0], "record", results[0])
                    embedding = getattr(rec, "embedding", None)
                    if embedding is not None:
                        entry.embedding = list(embedding)  # type: ignore[arg-type]

        with self._lock:
            if self._max_entries > 0 and len(self._entries) >= self._max_entries:
                self._evict_locked()
            self._entries[entry.id] = entry
            self._by_project.setdefault(entry.project_id, []).append(entry.id)
            self._by_session.setdefault(entry.session_id, []).append(entry.id)
            self._by_type.setdefault(entry.type, []).append(entry.id)
            # also persist to sqlite palace if enabled (palace is source of truth, dict is LRU cache)
            if self._use_sqlite and self._palace is not None:
                try:
                    wing = entry.project_id or entry.wing or "default"
                    room = entry.session_id or entry.room or "general"
                    meta: dict[str, object] = {
                        "wing": wing,
                        "room": room,
                        "source_file": entry.palace_path or entry.id,
                        "chunk_index": 0,
                        "importance": entry.importance,
                        "project_id": entry.project_id,
                        "session_id": entry.session_id,
                        "type": int(entry.type),
                        "mem_type": int(entry.type),
                        "filed_at": entry.created_at,
                    }
                    if entry.metadata:
                        meta.update(entry.metadata)  # type: ignore[arg-type]
                    self._palace_collection.upsert(documents=[entry.content], ids=[entry.id], metadatas=[meta])  # type: ignore
                except Exception:
                    pass
        self._save()

    def retrieve(self, entry_id: str) -> MemoryEntry | None:
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is not None:
                entry.accessed_at = _now()
                entry.access_count += 1
                return entry
            if self._use_sqlite and self._palace_collection is not None:
                try:
                    res = self._palace_collection.get(ids=[entry_id], include=["documents", "metadatas"])  # type: ignore
                    if res.ids:
                        doc = res.documents[0] if res.documents else ""
                        meta = res.metadatas[0] if res.metadatas else {}
                        if not isinstance(meta, dict):
                            meta = {}
                        project_id = str(meta.get("project_id") or meta.get("wing") or "")
                        session_id = str(meta.get("session_id") or meta.get("room") or "")
                        type_val = meta.get("type")
                        if type_val is None:
                            type_val = meta.get("mem_type")
                        try:
                            mem_type = MemoryType(int(type_val)) if type_val is not None else MemoryType.SEMANTIC
                        except (ValueError, TypeError):
                            mem_type = MemoryType.SEMANTIC
                        try:
                            importance = float(meta.get("importance") or 0)
                        except (TypeError, ValueError):
                            importance = 0.0
                        core_keys = {
                            "wing",
                            "room",
                            "source_file",
                            "chunk_index",
                            "importance",
                            "project_id",
                            "session_id",
                            "type",
                            "mem_type",
                            "filed_at",
                            "entities",
                            "hall",
                            "normalize_version",
                            "added_by",
                            "source_mtime",
                            "chunk_total",
                        }
                        user_meta = {k: str(v) for k, v in meta.items() if k not in core_keys}
                        e = MemoryEntry(
                            id=entry_id,
                            type=mem_type,
                            content=doc or "",
                            metadata=user_meta or None,
                            project_id=project_id,
                            session_id=session_id,
                            importance=importance,
                            wing=str(meta.get("wing") or ""),
                            room=str(meta.get("room") or ""),
                            palace_path=str(meta.get("source_file") or ""),
                            created_at=str(meta.get("filed_at") or ""),
                            accessed_at=_now(),
                            access_count=1,
                        )
                        # populate LRU cache and indexes
                        self._entries[entry_id] = e
                        self._by_project.setdefault(e.project_id, []).append(e.id)
                        self._by_session.setdefault(e.session_id, []).append(e.id)
                        self._by_type.setdefault(e.type, []).append(e.id)
                        return e
                except Exception:
                    pass
                return None
            return None

    def search(
        self,
        project_id: str,
        query: str,
        mem_type: MemoryType | int = 0,
        limit: int = 10,
        since: str | None = None,
        before: str | None = None,
    ) -> list[MemoryEntry]:
        if self._rag is not None:
            enabled = getattr(self._rag, "is_enabled", lambda: False)()
            rag_query = getattr(self._rag, "query", None)
            if enabled and rag_query is not None:
                results = rag_query(query, limit)
                if results:
                    return self._filter_results(results, project_id, mem_type)
        # palace (sqlite) search — source of truth, dict is LRU cache
        if self._use_sqlite and self._palace_collection is not None and query:
            try:
                from .date_window import filed_at_in_window, parse_window
                from .search import build_where_filter

                try:
                    since_dt, before_dt = parse_window(since, before)
                except ValueError:
                    raise
                date_active = since_dt is not None or before_dt is not None

                where = build_where_filter(project_id if project_id else None, None)
                where_filter = where or None

                needs_post_filter = bool(mem_type and int(mem_type) != 0) or date_active
                if date_active:
                    fetch_n = max(min(limit * 15, 500), limit) if limit else 10
                elif needs_post_filter:
                    fetch_n = limit * 3
                else:
                    fetch_n = limit

                qres = self._palace_collection.query(  # type: ignore[attr-defined]
                    query_texts=[query],
                    n_results=fetch_n,
                    where=where_filter,
                    include=["documents", "metadatas", "distances"],
                )
                try:
                    ids = qres.ids[0] if qres.ids else []  # type: ignore[attr-defined]
                    docs = qres.documents[0] if qres.documents else []  # type: ignore[attr-defined]
                    metas = qres.metadatas[0] if qres.metadatas else []  # type: ignore[attr-defined]
                    dists = qres.distances[0] if qres.distances else []  # type: ignore[attr-defined]
                except (IndexError, AttributeError):
                    ids, docs, metas, dists = [], [], [], []

                out: list[MemoryEntry] = []
                with self._lock:
                    for rid, doc, meta, dist in zip(ids, docs, metas, dists):
                        if not isinstance(meta, dict):
                            meta = {}
                        if query and query.lower() not in str(doc or "").lower():
                            continue
                        if date_active and not filed_at_in_window(meta.get("filed_at"), since_dt, before_dt):
                            continue
                        if mem_type and int(mem_type) != 0:
                            type_val = meta.get("type")
                            if type_val is None:
                                type_val = meta.get("mem_type")
                            try:
                                mt = int(type_val) if type_val is not None else 0
                            except (TypeError, ValueError):
                                mt = 0
                            if mt != int(mem_type):
                                continue
                        project_id_val = str(meta.get("project_id") or meta.get("wing") or "")
                        session_id_val = str(meta.get("session_id") or meta.get("room") or "")
                        type_val2 = meta.get("type")
                        if type_val2 is None:
                            type_val2 = meta.get("mem_type")
                        try:
                            mtype = MemoryType(int(type_val2)) if type_val2 is not None else MemoryType.SEMANTIC
                        except (ValueError, TypeError):
                            mtype = MemoryType.SEMANTIC
                        try:
                            imp = float(meta.get("importance") or 0)
                        except (TypeError, ValueError):
                            imp = 0.0
                        similarity = 0.0
                        try:
                            if dist is not None:
                                similarity = max(0.0, 1.0 - float(dist))
                        except (TypeError, ValueError):
                            similarity = 0.0
                        final_importance = imp if imp != 0 else similarity
                        core_keys = {
                            "wing",
                            "room",
                            "source_file",
                            "chunk_index",
                            "importance",
                            "project_id",
                            "session_id",
                            "type",
                            "mem_type",
                            "filed_at",
                            "entities",
                            "hall",
                            "normalize_version",
                            "added_by",
                            "source_mtime",
                            "chunk_total",
                        }
                        user_meta = {k: str(v) for k, v in meta.items() if k not in core_keys}
                        e = MemoryEntry(
                            id=rid,
                            type=mtype,
                            content=str(doc or ""),
                            metadata=user_meta or None,
                            project_id=project_id_val,
                            session_id=session_id_val,
                            importance=final_importance,
                            wing=str(meta.get("wing") or ""),
                            room=str(meta.get("room") or ""),
                            palace_path=str(meta.get("source_file") or ""),
                            created_at=str(meta.get("filed_at") or ""),
                            accessed_at=str(meta.get("filed_at") or ""),
                        )
                        if rid not in self._entries:
                            self._entries[rid] = e
                            self._by_project.setdefault(e.project_id, []).append(rid)
                            self._by_session.setdefault(e.session_id, []).append(rid)
                            self._by_type.setdefault(e.type, []).append(rid)
                        out.append(e)
                        if len(out) >= limit:
                            break
                if out:
                    return top_by_importance(out, limit)
            except ValueError:
                raise
            except Exception:
                pass
        # empty query in palace mode — list via get with where filter (palace is source of truth, dict is cache)
        if self._use_sqlite and self._palace_collection is not None and not query:
            try:
                from .date_window import filed_at_in_window, parse_window
                from .search import build_where_filter

                try:
                    since_dt, before_dt = parse_window(since, before)
                except ValueError:
                    raise
                date_active = since_dt is not None or before_dt is not None
                where = build_where_filter(project_id if project_id else None, None)
                where_filter = where or None
                needs_post = bool(mem_type and int(mem_type) != 0) or date_active
                fetch_lim = limit * 3 if needs_post else limit
                if not fetch_lim:
                    fetch_lim = 10
                got = self._palace_collection.get(  # type: ignore[attr-defined]
                    where=where_filter, include=["documents", "metadatas"], limit=fetch_lim
                )
                out2: list[MemoryEntry] = []
                with self._lock:
                    for rid, doc, meta in zip(got.ids, got.documents, got.metadatas):
                        if not isinstance(meta, dict):
                            meta = {}
                        if date_active and not filed_at_in_window(meta.get("filed_at"), since_dt, before_dt):
                            continue
                        if mem_type and int(mem_type) != 0:
                            type_val = meta.get("type")
                            if type_val is None:
                                type_val = meta.get("mem_type")
                            try:
                                mt = int(type_val) if type_val is not None else 0
                            except (TypeError, ValueError):
                                mt = 0
                            if mt != int(mem_type):
                                continue
                        project_id_val = str(meta.get("project_id") or meta.get("wing") or "")
                        session_id_val = str(meta.get("session_id") or meta.get("room") or "")
                        type_val2 = meta.get("type")
                        if type_val2 is None:
                            type_val2 = meta.get("mem_type")
                        try:
                            mtype = MemoryType(int(type_val2)) if type_val2 is not None else MemoryType.SEMANTIC
                        except (ValueError, TypeError):
                            mtype = MemoryType.SEMANTIC
                        try:
                            imp = float(meta.get("importance") or 0)
                        except (TypeError, ValueError):
                            imp = 0.0
                        core_keys = {
                            "wing",
                            "room",
                            "source_file",
                            "chunk_index",
                            "importance",
                            "project_id",
                            "session_id",
                            "type",
                            "mem_type",
                            "filed_at",
                            "entities",
                            "hall",
                            "normalize_version",
                            "added_by",
                            "source_mtime",
                            "chunk_total",
                        }
                        user_meta = {k: str(v) for k, v in meta.items() if k not in core_keys}
                        e = MemoryEntry(
                            id=rid,
                            type=mtype,
                            content=str(doc or ""),
                            metadata=user_meta or None,
                            project_id=project_id_val,
                            session_id=session_id_val,
                            importance=imp,
                            wing=str(meta.get("wing") or ""),
                            room=str(meta.get("room") or ""),
                            palace_path=str(meta.get("source_file") or ""),
                            created_at=str(meta.get("filed_at") or ""),
                            accessed_at=str(meta.get("filed_at") or ""),
                        )
                        if rid not in self._entries:
                            self._entries[rid] = e
                            self._by_project.setdefault(e.project_id, []).append(rid)
                            self._by_session.setdefault(e.session_id, []).append(rid)
                            self._by_type.setdefault(e.type, []).append(rid)
                        out2.append(e)
                        if len(out2) >= limit:
                            break
                if out2:
                    return top_by_importance(out2, limit)
            except ValueError:
                raise
            except Exception:
                pass
        return self._search_local(project_id, query, mem_type, limit)

    def _filter_results(
        self,
        results: list[object],
        project_id: str,
        mem_type: MemoryType | int,
    ) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        with self._lock:
            for r in results:
                rec = getattr(r, "record", r)
                entry = self._entries.get(getattr(rec, "id", ""))
                if entry is None:
                    continue
                if project_id and entry.project_id != project_id:
                    continue
                if mem_type and entry.type != mem_type:
                    continue
                entries.append(entry)
        return entries

    def _search_local(
        self,
        project_id: str,
        query: str,
        mem_type: MemoryType | int,
        limit: int,
    ) -> list[MemoryEntry]:
        with self._lock:
            candidates: list[MemoryEntry] = []
            for e in self._entries.values():
                if project_id and e.project_id != project_id:
                    continue
                if mem_type and e.type != mem_type:
                    continue
                if query and query.lower() not in e.content.lower():
                    continue
                candidates.append(e)
        return top_by_importance(candidates, limit)

    def get_by_project(self, project_id: str) -> list[MemoryEntry]:
        with self._lock:
            return self._resolve(self._by_project.get(project_id, []))

    def get_by_session(self, session_id: str) -> list[MemoryEntry]:
        with self._lock:
            return self._resolve(self._by_session.get(session_id, []))

    def get_by_type(self, mem_type: MemoryType | int) -> list[MemoryEntry]:
        with self._lock:
            return self._resolve(self._by_type.get(MemoryType(mem_type), []))

    def _resolve(self, ids: list[str]) -> list[MemoryEntry]:
        return [e for i in ids if (e := self._entries.get(i)) is not None]

    def delete(self, entry_id: str) -> None:
        with self._lock:
            entry = self._entries.pop(entry_id, None)
            if entry is None:
                # try sqlite delete even if not in dict
                if self._use_sqlite and self._palace_collection is not None:
                    try:
                        self._palace_collection.delete(ids=[entry_id])  # type: ignore
                    except Exception:
                        pass
                return
            self._remove_from_index(self._by_project.get(entry.project_id), entry_id)
            self._remove_from_index(self._by_session.get(entry.session_id), entry_id)
            self._remove_from_index(self._by_type.get(entry.type), entry_id)
            if self._use_sqlite and self._palace_collection is not None:
                try:
                    self._palace_collection.delete(ids=[entry_id])  # type: ignore
                except Exception:
                    pass
        self._save()

    def _evict_locked(self) -> None:
        oldest = min(self._entries.values(), key=lambda e: _parse_dt(e.accessed_at))
        self._entries.pop(oldest.id, None)
        self._remove_from_index(self._by_project.get(oldest.project_id), oldest.id)
        self._remove_from_index(self._by_session.get(oldest.session_id), oldest.id)
        self._remove_from_index(self._by_type.get(oldest.type), oldest.id)
        if self._use_sqlite and self._palace_collection is not None:
            try:
                self._palace_collection.delete(ids=[oldest.id])  # type: ignore
            except Exception:
                pass

    @staticmethod
    def _remove_from_index(slice_: list[str] | None, entry_id: str) -> None:
        if slice_ is None:
            return
        try:
            slice_.remove(entry_id)
        except ValueError:
            pass

    def stats(self) -> MemoryStats:
        with self._lock:
            by_type: dict[MemoryType, int] = {}
            for e in self._entries.values():
                by_type[e.type] = by_type.get(e.type, 0) + 1
            if self._use_sqlite and self._palace_collection is not None:
                try:
                    palace_count = self._palace_collection.count()  # type: ignore
                    # try palace distribution for fidelity, fallback to dict
                    try:
                        got = self._palace_collection.get(include=["metadatas"], limit=5000)  # type: ignore
                        pal_by_type: dict[MemoryType, int] = {}
                        pal_wings: set[str] = set()
                        pal_rooms: set[str] = set()
                        for m in got.metadatas:
                            if not isinstance(m, dict):
                                continue
                            tv = m.get("type")
                            if tv is None:
                                tv = m.get("mem_type")
                            try:
                                mt = MemoryType(int(tv)) if tv is not None else MemoryType.SEMANTIC
                            except (ValueError, TypeError):
                                mt = MemoryType.SEMANTIC
                            pal_by_type[mt] = pal_by_type.get(mt, 0) + 1
                            wing = m.get("wing") or m.get("project_id")
                            if isinstance(wing, str) and wing:
                                pal_wings.add(wing)
                            room = m.get("room") or m.get("session_id")
                            if isinstance(room, str) and room:
                                pal_rooms.add(room)
                        if got.ids:
                            pal_by_type_final = pal_by_type or by_type
                            by_project = len(pal_wings) if pal_wings else len(self._by_project)
                            by_session = len(pal_rooms) if pal_rooms else len(self._by_session)
                            return MemoryStats(
                                total_entries=palace_count,
                                by_project=by_project,
                                by_session=by_session,
                                by_type=pal_by_type_final,
                            )
                    except Exception:
                        pass
                    return MemoryStats(
                        total_entries=palace_count,
                        by_project=len(self._by_project),
                        by_session=len(self._by_session),
                        by_type=by_type,
                    )
                except Exception:
                    pass
            return MemoryStats(
                total_entries=len(self._entries),
                by_project=len(self._by_project),
                by_session=len(self._by_session),
                by_type=by_type,
            )

    def _save(self) -> None:
        if not self._path:
            return
        if self._use_sqlite:
            return
        with self._lock:
            data = [asdict(e) for e in self._entries.values()]
        p = Path(self._path)
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        p.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        p.chmod(0o600)

    def _load(self) -> None:
        if not self._path:
            return
        if self._use_sqlite:
            return
        p = Path(self._path)
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for raw in data:
            try:
                raw["type"] = MemoryType(raw.get("type", 0))
            except ValueError:
                raw["type"] = MemoryType.SEMANTIC
            # filter unknown keys for forward compat (extra enriched fields)
            allowed = {k for k in MemoryEntry.__dataclass_fields__}
            filtered = {k: v for k, v in raw.items() if k in allowed}
            e = MemoryEntry(**filtered)  # type: ignore[arg-type]
            self._entries[e.id] = e
            self._by_project.setdefault(e.project_id, []).append(e.id)
            self._by_session.setdefault(e.session_id, []).append(e.id)
            self._by_type.setdefault(e.type, []).append(e.id)


# Re-export palace / backend symbols for facade
try:
    from .backend import PalaceRef  # noqa: F401
    from .backend.base import HealthStatus  # noqa: F401
    from .date_window import filed_at_in_window, parse_date_bound, parse_window  # noqa: F401
    from .dialect import Dialect  # noqa: F401
    from .entity_detector import classify_entity, extract_candidates, score_entity  # noqa: F401
    from .graph import KnowledgeGraph  # noqa: F401
    from .layers import Layer0, Layer1, Layer2, Layer3, MemoryStack  # noqa: F401
    from .miner import GitignoreMatcher, scan_project  # noqa: F401
    from .miner import chunk_text as palace_chunk_text
    from .palace import DxrkMemory, DxrkPalace, Palace, reap_stale_dxrk_locks, reap_stale_mine_locks  # noqa: F401
    from .search import hybrid_search, sanitize_query  # noqa: F401
except Exception:
    pass

__all__ = [
    "AgentMemory",
    "MemoryEntry",
    "MemoryType",
    "MemoryStats",
    "top_by_importance",
    "DxrkMemory",
    "Palace",
    "DxrkPalace",
    "PalaceRef",
    "HealthStatus",
    "KnowledgeGraph",
    "hybrid_search",
    "Dialect",
    "MemoryStack",
]
