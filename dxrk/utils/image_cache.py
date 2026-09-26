# SPDX-License-Identifier: MIT
"""Size-bounded, time-expiring LRU image cache."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from dxrk.utils.image_format import Format
from dxrk.utils.image_format import _coerce_format as _coerce_format


@dataclass
class CacheEntry:
    """A cached image entry. Mirrors image.CacheEntry."""

    data: bytes
    format: Format
    width: int
    height: int
    created_at: datetime
    accessed_at: datetime
    access_count: int


@dataclass
class CacheStats:
    """Image cache statistics. Mirrors image.CacheStats."""

    entry_count: int
    total_size: int
    max_size: int
    max_age: timedelta


class ImageCache:
    """A size-bounded, time-expiring image cache. Mirrors image.ImageCache."""

    def __init__(self, max_size: int = 100, max_age: timedelta | None = None) -> None:
        if max_size <= 0:
            max_size = 100
        if max_age is None or max_age <= timedelta(0):
            max_age = timedelta(hours=24)
        self._entries: dict[str, CacheEntry] = {}
        self._mu = threading.RLock()
        self._max_size = max_size
        self._max_age = max_age
        self._current_size = 0

    def get(self, key: str) -> tuple[bytes | None, Format, int, int, bool]:
        """Return the cached entry for key as (data, format, width, height, ok).

        Expired entries are treated as misses (not removed).
        """
        with self._mu:
            entry = self._entries.get(key)
            if entry is None:
                return None, Format.UNKNOWN, 0, 0, False

            if datetime.now() - entry.created_at > self._max_age:  # noqa: DTZ005 - naive local clock
                return None, Format.UNKNOWN, 0, 0, False

            entry.accessed_at = datetime.now()  # noqa: DTZ005 - naive local clock
            entry.access_count += 1
            return entry.data, entry.format, entry.width, entry.height, True

    def set(self, key: str, data: bytes, format: Format | int, width: int, height: int) -> None:
        """Store an entry, evicting the least-recently-used entry when full."""
        with self._mu:
            if len(self._entries) >= self._max_size:
                self._evict_lru()

            self._entries[key] = CacheEntry(
                data=data,
                format=_coerce_format(format),
                width=width,
                height=height,
                created_at=datetime.now(),  # noqa: DTZ005 - naive local clock
                accessed_at=datetime.now(),  # noqa: DTZ005 - naive local clock
                access_count=1,
            )
            self._current_size += len(data)

    def delete(self, key: str) -> bool:
        """Delete an entry; returns True if it existed."""
        with self._mu:
            entry = self._entries.get(key)
            if entry is None:
                return False
            self._current_size -= len(entry.data)
            del self._entries[key]
            return True

    def clear(self) -> None:
        """Remove all entries."""
        with self._mu:
            self._entries = {}
            self._current_size = 0

    def _evict_lru(self) -> None:
        """Evict the entry with the oldest AccessedAt."""
        oldest_key = ""
        oldest_time: datetime | None = None
        for key, entry in self._entries.items():
            if oldest_key == "" or oldest_time is None or entry.accessed_at < oldest_time:
                oldest_key = key
                oldest_time = entry.accessed_at
        if oldest_key != "":
            self._current_size -= len(self._entries[oldest_key].data)
            del self._entries[oldest_key]

    def stats(self) -> CacheStats:
        """Return cache statistics."""
        with self._mu:
            return CacheStats(
                entry_count=len(self._entries),
                total_size=self._current_size,
                max_size=self._max_size,
                max_age=self._max_age,
            )

    def keys(self) -> list[str]:
        """Return all cached keys."""
        with self._mu:
            return list(self._entries.keys())

    def prune_expired(self) -> int:
        """Remove expired entries; returns the number removed."""
        with self._mu:
            now = datetime.now()  # noqa: DTZ005 - naive local clock
            count = 0
            for key, entry in list(self._entries.items()):
                if now - entry.created_at > self._max_age:
                    self._current_size -= len(entry.data)
                    del self._entries[key]
                    count += 1
            return count
