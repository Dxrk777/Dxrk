# SPDX-License-Identifier: MIT
"""Storage backend contract — DxrkMemory stdlib backend."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BackendError(Exception):
    """Base class for every storage-backend error."""


class PalaceNotFoundError(BackendError, FileNotFoundError):
    """Raised when get_collection(create=False) is called on a missing palace."""


class CollectionNotInitializedError(PalaceNotFoundError):
    """Palace exists but requested collection has never been created."""


class BackendClosedError(BackendError):
    """Backend method called after close()."""


class UnsupportedFilterError(BackendError):
    """Where-clause uses an operator the backend does not implement."""


class DimensionMismatchError(BackendError):
    """Embedding dimension mismatch on write."""


class EmbedderIdentityMismatchError(BackendError):
    """Stored embedder model name differs from current one."""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PalaceRef:
    """Handle to a palace consumed by backends."""

    id: str
    local_path: str | None = None
    namespace: str | None = None


@dataclass(frozen=True, slots=True)
class HealthStatus:
    ok: bool
    detail: str = ""

    @classmethod
    def healthy(cls, detail: str = "") -> HealthStatus:
        return cls(ok=True, detail=detail)

    @classmethod
    def unhealthy(cls, detail: str) -> HealthStatus:
        return cls(ok=False, detail=detail)


_TYPED_RESULT_FIELDS: tuple[str, ...] = ("ids", "documents", "metadatas", "distances", "embeddings")


class _DictCompatMixin:
    """Transitional dict-protocol shim — prefers attribute access."""

    def __getitem__(self, key: str) -> object:
        if key in _TYPED_RESULT_FIELDS:
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: object = None) -> object:
        if key in _TYPED_RESULT_FIELDS:
            val = getattr(self, key, default)
            return default if val is None else val
        return default

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in _TYPED_RESULT_FIELDS and getattr(self, key, None) is not None


@dataclass(frozen=True, slots=True)
class QueryResult(_DictCompatMixin):
    """Typed return from BaseCollection.query."""

    ids: list[list[str]]
    documents: list[list[str]]
    metadatas: list[list[dict[str, object]]]
    distances: list[list[float]]
    embeddings: list[list[list[float]]] | None = None

    @classmethod
    def empty(cls, num_queries: int = 1, embeddings_requested: bool = False) -> QueryResult:
        return cls(
            ids=[[] for _ in range(num_queries)],
            documents=[[] for _ in range(num_queries)],
            metadatas=[[] for _ in range(num_queries)],
            distances=[[] for _ in range(num_queries)],
            embeddings=[[] for _ in range(num_queries)] if embeddings_requested else None,  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class GetResult(_DictCompatMixin):
    """Typed return from BaseCollection.get."""

    ids: list[str]
    documents: list[str]
    metadatas: list[dict[str, object]]
    embeddings: list[list[float]] | None = None

    @classmethod
    def empty(cls) -> GetResult:
        return cls(ids=[], documents=[], metadatas=[], embeddings=None)


# ---------------------------------------------------------------------------
# Collection contract
# ---------------------------------------------------------------------------


class BaseCollection(ABC):
    """Per-collection read/write surface every backend must implement."""

    @abstractmethod
    def add(
        self,
        *,
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, object]] | None = None,
        embeddings: list[list[float]] | None = None,
    ) -> None: ...

    @abstractmethod
    def upsert(
        self,
        *,
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, object]] | None = None,
        embeddings: list[list[float]] | None = None,
    ) -> None: ...

    @abstractmethod
    def query(
        self,
        *,
        query_texts: list[str] | None = None,
        query_embeddings: list[list[float]] | None = None,
        n_results: int = 10,
        where: dict[str, object] | None = None,
        where_document: dict[str, object] | None = None,
        include: list[str] | None = None,
    ) -> QueryResult: ...

    @abstractmethod
    def get(
        self,
        *,
        ids: list[str] | None = None,
        where: dict[str, object] | None = None,
        where_document: dict[str, object] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        include: list[str] | None = None,
    ) -> GetResult: ...

    @abstractmethod
    def delete(
        self,
        *,
        ids: list[str] | None = None,
        where: dict[str, object] | None = None,
    ) -> None: ...

    @abstractmethod
    def count(self) -> int: ...

    def estimated_count(self) -> int:
        return self.count()

    def close(self) -> None:
        return None

    def health(self) -> HealthStatus:
        return HealthStatus.healthy()

    def update(
        self,
        *,
        ids: list[str],
        documents: list[str] | None = None,
        metadatas: list[dict[str, object]] | None = None,
        embeddings: list[list[float]] | None = None,
    ) -> None:
        """Default non-atomic update: get + merge + upsert."""
        if documents is None and metadatas is None and embeddings is None:
            raise ValueError("update requires at least one of documents, metadatas, embeddings")
        n = len(ids)
        for label, value in (
            ("documents", documents),
            ("metadatas", metadatas),
            ("embeddings", embeddings),
        ):
            if value is not None and len(value) != n:
                raise ValueError(f"{label} length {len(value)} does not match ids length {n}")
        existing = self.get(ids=ids, include=["documents", "metadatas"])
        by_id: dict[str, tuple[str, dict[str, object]]] = {
            rid: (existing.documents[i], existing.metadatas[i]) for i, rid in enumerate(existing.ids)
        }
        merged_docs: list[str] = []
        merged_metas: list[dict[str, object]] = []
        for i, rid in enumerate(ids):
            prev_doc, prev_meta = by_id.get(rid, ("", {}))
            merged_docs.append(documents[i] if documents is not None else prev_doc)
            new_meta: dict[str, object] = dict(prev_meta or {})
            if metadatas is not None:
                new_meta.update(metadatas[i] or {})
            merged_metas.append(new_meta)
        self.upsert(documents=merged_docs, ids=list(ids), metadatas=merged_metas, embeddings=embeddings)


# ---------------------------------------------------------------------------
# Backend contract
# ---------------------------------------------------------------------------


class BaseBackend(ABC):
    """Long-lived factory serving many palaces."""

    name: ClassVar[str]
    spec_version: ClassVar[str] = "1.0"
    capabilities: ClassVar[frozenset[str]] = frozenset()

    @abstractmethod
    def get_collection(
        self,
        *,
        palace: PalaceRef,
        collection_name: str,
        create: bool = False,
        options: dict[str, object] | None = None,
    ) -> BaseCollection: ...

    def close_palace(self, palace: PalaceRef) -> None:
        return None

    def close(self) -> None:
        return None

    def health(self, palace: PalaceRef | None = None) -> HealthStatus:
        return HealthStatus.healthy()

    @classmethod
    def detect(cls, path: str) -> bool:  # pragma: no cover - default hook
        return False


# ---------------------------------------------------------------------------
# Include spec
# ---------------------------------------------------------------------------

_VALID_INCLUDE_KEYS: frozenset[str] = frozenset({"documents", "metadatas", "distances", "embeddings"})


@dataclass(slots=True)
class _IncludeSpec:
    """Resolve include= parameter with spec-mandated defaults."""

    documents: bool = True
    metadatas: bool = True
    distances: bool = True
    embeddings: bool = False

    @classmethod
    def resolve(cls, include: list[str] | None, *, default_distances: bool = True) -> _IncludeSpec:
        if include is None:
            return cls(documents=True, metadatas=True, distances=default_distances, embeddings=False)
        keys: set[str] = {k for k in include if k in _VALID_INCLUDE_KEYS}
        return cls(
            documents="documents" in keys,
            metadatas="metadatas" in keys,
            distances="distances" in keys,
            embeddings="embeddings" in keys,
        )
