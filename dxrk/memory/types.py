# SPDX-License-Identifier: MIT
"""Enriched memory types for DxrkMemory 2.0.

Keeps backward compatibility with the original 3-value MemoryType
(SEMANTIC=0, EPISODIC=1, PROCEDURAL=2) while exposing palace-native
records (DrawerRecord, ClosetRecord) used by the wings/rooms/drawers
hierarchy.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import IntEnum


class MemoryType(IntEnum):
    """Stable IntEnum — 0,1,2 are the legacy values that must not change."""

    SEMANTIC = 0
    EPISODIC = 1
    PROCEDURAL = 2
    # Additive extensions (optional, never break legacy wire format)
    TECHNICAL = 3
    PERSONAL = 4


@dataclass
class MemoryEntry:
    """Mutable entry used by AgentMemory public API (JSON compat)."""

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
    # Enriched palace fields (additive, default empty so old JSON still loads)
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


def top_by_importance(entries: list[MemoryEntry], limit: int) -> list[MemoryEntry]:
    """Return top-N entries sorted by importance descending."""
    if len(entries) <= limit:
        return entries
    return sorted(entries, key=lambda e: e.importance, reverse=True)[:limit]


@dataclass(frozen=True, slots=True)
class DrawerRecord:
    """Immutable palace drawer — verbatim chunk."""

    drawer_id: str
    wing: str
    room: str
    content: str
    source_file: str
    chunk_index: int
    palace_path: str
    hall: str = "general"
    entities: str = ""
    filed_at: str = ""
    normalize_version: int = 2

    @staticmethod
    def make_id(wing: str, room: str, source_file: str, chunk_index: int) -> str:
        h = hashlib.sha256(f"{source_file}{chunk_index}".encode()).hexdigest()[:24]
        return f"drawer_{wing}_{room}_{h}"


@dataclass(frozen=True, slots=True)
class ClosetRecord:
    """Immutable closet — compact AAAK pointer to drawers."""

    closet_id: str
    wing: str
    room: str
    source_file: str
    content: str
    drawer_ids: tuple[str, ...]
    palace_path: str
    filed_at: str = ""
    normalize_version: int = 2

    @staticmethod
    def make_base_id(wing: str, room: str, source_file: str) -> str:
        h = hashlib.sha256(source_file.encode()).hexdigest()[:24]
        return f"closet_{wing}_{room}_{h}"
