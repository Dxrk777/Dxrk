# SPDX-License-Identifier: MIT
"""Backend registry — stdlib only."""

from __future__ import annotations

from .base import (
    BackendClosedError,
    BackendError,
    BaseBackend,
    BaseCollection,
    CollectionNotInitializedError,
    DimensionMismatchError,
    EmbedderIdentityMismatchError,
    GetResult,
    HealthStatus,
    PalaceNotFoundError,
    PalaceRef,
    QueryResult,
    UnsupportedFilterError,
)
from .sqlite import DB_FILENAME, DEFAULT_COLLECTION, SqliteBackend, SqliteCollection

_REGISTRY: dict[str, type[BaseBackend]] = {
    "sqlite": SqliteBackend,
}

DEFAULT_BACKEND = "sqlite"


def get_backend(name: str = DEFAULT_BACKEND) -> BaseBackend:
    try:
        cls = _REGISTRY[name]
    except KeyError as e:
        raise BackendError(f"unknown backend: {name}") from e
    return cls()


def register_backend(name: str, cls: type[BaseBackend]) -> None:
    _REGISTRY[name] = cls


__all__ = [
    "BaseBackend",
    "BaseCollection",
    "BackendError",
    "BackendClosedError",
    "CollectionNotInitializedError",
    "DB_FILENAME",
    "DEFAULT_BACKEND",
    "DEFAULT_COLLECTION",
    "DimensionMismatchError",
    "EmbedderIdentityMismatchError",
    "GetResult",
    "HealthStatus",
    "PalaceNotFoundError",
    "PalaceRef",
    "QueryResult",
    "SqliteBackend",
    "SqliteCollection",
    "UnsupportedFilterError",
    "get_backend",
    "register_backend",
]
