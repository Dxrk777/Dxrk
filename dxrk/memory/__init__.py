# SPDX-License-Identifier: MIT
"""Agent memory persistence"""

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timezone
from enum import IntEnum
from pathlib import Path
from threading import RLock


class MemoryType(IntEnum):
    SEMANTIC = 0
    EPISODIC = 1
    PROCEDURAL = 2


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


class AgentMemory:
    """In-memory entry store persisted as JSON, indexed by project, session and type. A ``max_entries`` greater than zero
    enables least-recently-accessed eviction. ``rag`` is an optional object
    exposing ``is_enabled()`` and ``query(text, limit)``; ``vault`` is reserved
    for future encrypted storage.
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
                        entry.embedding = list(embedding)

        with self._lock:
            if self._max_entries > 0 and len(self._entries) >= self._max_entries:
                self._evict_locked()
            self._entries[entry.id] = entry
            self._by_project.setdefault(entry.project_id, []).append(entry.id)
            self._by_session.setdefault(entry.session_id, []).append(entry.id)
            self._by_type.setdefault(entry.type, []).append(entry.id)
        self._save()

    def retrieve(self, entry_id: str) -> MemoryEntry | None:
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return None
            entry.accessed_at = _now()
            entry.access_count += 1
            return entry

    def search(
        self,
        project_id: str,
        query: str,
        mem_type: MemoryType | int = 0,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        if self._rag is not None:
            enabled = getattr(self._rag, "is_enabled", lambda: False)()
            rag_query = getattr(self._rag, "query", None)
            if enabled and rag_query is not None:
                results = rag_query(query, limit)
                if results:
                    return self._filter_results(results, project_id, mem_type)
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
                return
            self._remove_from_index(self._by_project.get(entry.project_id), entry_id)
            self._remove_from_index(self._by_session.get(entry.session_id), entry_id)
            self._remove_from_index(self._by_type.get(entry.type), entry_id)
        self._save()

    def _evict_locked(self) -> None:
        oldest = min(self._entries.values(), key=lambda e: _parse_dt(e.accessed_at))
        self._entries.pop(oldest.id, None)
        self._remove_from_index(self._by_project.get(oldest.project_id), oldest.id)
        self._remove_from_index(self._by_session.get(oldest.session_id), oldest.id)
        self._remove_from_index(self._by_type.get(oldest.type), oldest.id)

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
            return MemoryStats(
                total_entries=len(self._entries),
                by_project=len(self._by_project),
                by_session=len(self._by_session),
                by_type=by_type,
            )

    def _save(self) -> None:
        if not self._path:
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
        p = Path(self._path)
        if not p.exists():
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        for raw in data:
            raw["type"] = MemoryType(raw.get("type", 0))
            e = MemoryEntry(**raw)
            self._entries[e.id] = e
            self._by_project.setdefault(e.project_id, []).append(e.id)
            self._by_session.setdefault(e.session_id, []).append(e.id)
            self._by_type.setdefault(e.type, []).append(e.id)


def top_by_importance(entries: list[MemoryEntry], limit: int) -> list[MemoryEntry]:
    if len(entries) <= limit:
        return entries
    return sorted(entries, key=lambda e: e.importance, reverse=True)[:limit]
