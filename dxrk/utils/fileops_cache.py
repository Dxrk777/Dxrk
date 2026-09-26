# SPDX-License-Identifier: MIT
"""Thread-safe LRU file-content cache with TTL and modification watchers."""

from __future__ import annotations

import fnmatch
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dxrk.utils.fileops_errors import FileopsError

_WATCH_INTERVAL = 5.0


@dataclass
class CacheEntry:
    """A single cached file. Mirrors fileops.CacheEntry."""

    path: str = ""
    content: str = ""
    size: int = 0
    mod_time: datetime = field(default_factory=datetime.now)
    expiry: datetime = field(default_factory=datetime.now)


@dataclass
class CacheStats:
    """Reports cache performance. Mirrors fileops.CacheStats."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    entries: int = 0
    hit_rate: float = 0.0
    size_bytes: int = 0


class FileCache:
    """A thread-safe LRU file content cache with TTL expiration. Mirrors FileCache."""

    def __init__(self, max_entries: int, ttl: timedelta | None) -> None:
        if max_entries < 1:
            max_entries = 256
        self._mu = threading.RLock()
        self._entries: dict[str, CacheEntry] = {}
        self._order: list[str] = []
        self._max_entries = max_entries
        self._ttl = ttl
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._watchers: dict[str, list[Callable[[str], None]]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def Get(self, path: str) -> tuple[str, bool]:
        """Return cached content for path if present and not expired. Mirrors Get."""
        with self._mu:
            entry = self._entries.get(path)
            if entry is None:
                self._misses += 1
                return "", False
            if datetime.now() > entry.expiry:
                self._remove_locked(path)
                self._misses += 1
                return "", False
            self._touch_locked(path)
            self._hits += 1
            return entry.content, True

    def Set(self, path: str, content: str) -> None:
        """Cache content for path. Mirrors fileops.FileCache.Set."""
        with self._mu:
            info = None
            try:
                info = os.stat(path)
            except OSError:
                pass
            if info is not None:
                mod_time = datetime.fromtimestamp(info.st_mtime)
                size = info.st_size
            else:
                mod_time = datetime.now()
                size = 0
            entry = CacheEntry(
                path=path,
                content=content,
                size=size,
                mod_time=mod_time,
                expiry=(datetime.now() + self._ttl if self._ttl is not None else datetime.max),
            )
            if path in self._entries:
                self._entries[path] = entry
                self._touch_locked(path)
                return
            while len(self._entries) >= self._max_entries:
                self._evict_oldest_locked()
            self._entries[path] = entry
            self._order.append(path)

    def Invalidate(self, path: str) -> None:
        """Remove a single entry from the cache. Mirrors Invalidate."""
        with self._mu:
            self._remove_locked(path)

    def InvalidateAll(self) -> None:
        """Clear the entire cache. Mirrors InvalidateAll."""
        with self._mu:
            self._entries = {}
            self._order = []

    def InvalidatePattern(self, pattern: str) -> None:
        """Remove entries whose path base name matches the glob pattern. Mirrors InvalidatePattern."""
        with self._mu:
            matched = [p for p in self._entries if fnmatch.fnmatchcase(os.path.basename(p), pattern)]
            for p in matched:
                self._remove_locked(p)

    def InvalidatePrefix(self, prefix: str) -> None:
        """Remove all entries whose path starts with prefix. Mirrors InvalidatePrefix."""
        with self._mu:
            matched = [p for p in self._entries if p.startswith(prefix)]
            for p in matched:
                self._remove_locked(p)

    def Watch(self, path: str, callback: Callable[[str], None]) -> None:
        """Register a callback that fires when path is detected as modified. Mirrors Watch."""
        with self._mu:
            self._watchers.setdefault(path, []).append(callback)

    def Stats(self) -> CacheStats:
        """Return current cache statistics. Mirrors fileops.Stats."""
        with self._mu:
            total_size = sum(e.size for e in self._entries.values())
            total = self._hits + self._misses
            rate = 0.0
            if total > 0:
                rate = self._hits / total
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                entries=len(self._entries),
                hit_rate=rate,
                size_bytes=total_size,
            )

    def Close(self) -> None:
        """Stop the background watcher thread. Mirrors fileops.Close."""
        self._stop.set()

    def GetOrLoad(
        self, path: str, loader: Callable[[str], str | tuple[str, FileopsError | None]]
    ) -> tuple[str, FileopsError | None]:
        """Return cached content or load it via loader, caching the result. Mirrors GetOrLoad."""
        content, ok = self.Get(path)
        if ok:
            return content, None
        result = loader(path)
        if isinstance(result, tuple):
            content, err = result
        else:
            content, err = result, None
        if err is not None:
            return "", err
        self.Set(path, content)
        return content, None

    def Paths(self) -> list[str]:
        """Return all currently cached file paths. Mirrors fileops.Paths."""
        with self._mu:
            return list(self._order)

    def Size(self) -> int:
        """Return the number of entries in the cache. Mirrors fileops.Size."""
        with self._mu:
            return len(self._entries)

    def Contains(self, path: str) -> bool:
        """Report whether path is currently cached and not expired. Mirrors Contains."""
        with self._mu:
            entry = self._entries.get(path)
            if entry is None:
                return False
            return datetime.now() <= entry.expiry

    def Keys(self) -> list[str]:
        """Return all cached keys (alias for Paths). Mirrors fileops.Keys."""
        return self.Paths()

    def _touch_locked(self, path: str) -> None:
        for i, p in enumerate(self._order):
            if p == path:
                self._order.pop(i)
                self._order.append(path)
                return

    def _remove_locked(self, path: str) -> None:
        self._entries.pop(path, None)
        for i, p in enumerate(self._order):
            if p == path:
                self._order.pop(i)
                return

    def _evict_oldest_locked(self) -> None:
        if len(self._order) == 0:
            return
        oldest = self._order.pop(0)
        self._entries.pop(oldest, None)
        self._evictions += 1

    def _watch_loop(self) -> None:
        while not self._stop.wait(_WATCH_INTERVAL):
            self._poll_watchers()

    def _poll_watchers(self) -> None:
        with self._mu:
            paths = list(self._watchers)
            cbs = {p: list(fns) for p, fns in self._watchers.items()}
        for p in paths:
            try:
                info = os.stat(p)
            except OSError:
                continue
            with self._mu:
                entry = self._entries.get(p)
            if entry is not None and datetime.fromtimestamp(info.st_mtime) > entry.mod_time:
                with self._mu:
                    self._remove_locked(p)
                for cb in cbs.get(p, []):
                    cb(p)


def NewFileCache(max_entries: int, ttl: timedelta | None) -> FileCache:
    """Create a cache holding at most max_entries entries for the given TTL. Mirrors NewFileCache."""
    cache = FileCache(max_entries=max_entries, ttl=ttl)
    cache._thread = threading.Thread(target=cache._watch_loop, daemon=True)
    cache._thread.start()
    return cache
