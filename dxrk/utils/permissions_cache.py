# SPDX-License-Identifier: MIT

"""Permission cache: TTL/LRU entries with disk persistence."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from dxrk.utils.permissions_model import _ZERO_TIME as _ZERO_TIME
from dxrk.utils.permissions_model import Action as Action
from dxrk.utils.permissions_model import _go_time_fmt as _go_time_fmt
from dxrk.utils.permissions_model import _is_zero as _is_zero
from dxrk.utils.permissions_model import _now as _now
from dxrk.utils.permissions_model import _parse_go_time as _parse_go_time

# ---- Permission Cache ----


@dataclass
class CacheEntry:
    """A single cached permission decision."""

    key: str = ""
    action: Action = Action.Allow
    rule_id: str = ""
    expiry: datetime = _ZERO_TIME
    timestamp: datetime = _ZERO_TIME

    def IsExpired(self) -> bool:
        """Report whether the entry has expired."""
        return not _is_zero(self.expiry) and _now() > self.expiry


class PermissionCache:
    """A thread-safe LRU permission cache with TTL. Mirrors permissions.PermissionCache."""

    def __init__(self, ttl: timedelta, max_size: int = 1024) -> None:
        if max_size <= 0:
            max_size = 1024
        self._mu = threading.RLock()
        self._entries: dict[str, CacheEntry] = {}
        self._order: list[str] = []
        self._max_size = max_size
        self._ttl = ttl

    def _touch_locked(self, key: str) -> None:
        for i, k in enumerate(self._order):
            if k == key:
                del self._order[i]
                self._order.append(key)
                return

    def _remove_locked(self, key: str) -> None:
        if key not in self._entries:
            return
        del self._entries[key]
        for i, k in enumerate(self._order):
            if k == key:
                del self._order[i]
                return

    def _evict_oldest_locked(self) -> None:
        if not self._order:
            return
        oldest = self._order[0]
        del self._entries[oldest]
        self._order = self._order[1:]

    def Get(self, key: str) -> tuple[CacheEntry | None, bool]:
        """Retrieve a cache entry by key. Returns (None, False) if missing or expired."""
        with self._mu:
            entry = self._entries.get(key)
            if entry is None:
                return None, False
            if entry.IsExpired():
                self._remove_locked(key)
                return None, False
            self._touch_locked(key)
            return entry, True

    def Set(self, key: str, entry: CacheEntry) -> None:
        """Store a cache entry. Evicts the least recently used entry when full."""
        with self._mu:
            existing = self._entries.get(key)
            if existing is not None:
                self._touch_locked(key)
                entry.timestamp = _now()
                if _is_zero(entry.expiry) and not _is_zero(existing.expiry):
                    entry.expiry = existing.expiry
                self._entries[key] = entry
                return

            while len(self._order) >= self._max_size:
                self._evict_oldest_locked()

            entry.timestamp = _now()
            if _is_zero(entry.expiry) and self._ttl > timedelta(0):
                entry.expiry = _now() + self._ttl
            self._entries[key] = entry
            self._order.append(key)

    def SetWithTTL(self, key: str, entry: CacheEntry, ttl: timedelta) -> None:
        """Store a cache entry with a custom TTL, overriding the default."""
        entry.expiry = _now() + ttl
        self.Set(key, entry)

    def Invalidate(self, key: str) -> None:
        """Remove a single cache entry."""
        with self._mu:
            self._remove_locked(key)

    def InvalidateAll(self) -> None:
        """Clear the entire cache."""
        with self._mu:
            self._entries = {}
            self._order = []

    def Size(self) -> int:
        """Return the number of entries in the cache."""
        with self._mu:
            return len(self._entries)

    def Purge(self) -> int:
        """Remove all expired entries; return the number removed."""
        with self._mu:
            removed = 0
            remaining: list[str] = []
            for key in self._order:
                entry = self._entries.get(key)
                if entry is not None and entry.IsExpired():
                    del self._entries[key]
                    removed += 1
                else:
                    remaining.append(key)
            self._order = remaining
            return removed

    # ---- Disk persistence ----

    def PersistToDisk(self, path: str) -> Exception | None:
        """Write the cache to a JSON file."""
        with self._mu:
            snapshot: list[CacheEntry] = []
            for entry in self._entries.values():
                if not entry.IsExpired():
                    snapshot.append(entry)
        payload = {
            "entries": [
                {
                    "key": e.key,
                    "action": int(e.action),
                    **({"rule_id": e.rule_id} if e.rule_id else {}),
                    "expiry": _go_time_fmt(e.expiry),
                    "timestamp": _go_time_fmt(e.timestamp),
                }
                for e in snapshot
            ]
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(payload, indent=2))
        except OSError as ex:
            return Exception(f"write cache file {json.dumps(path)}: {ex}")
        return None

    def LoadFromDisk(self, path: str) -> Exception | None:
        """Load a cache from a JSON file."""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except OSError as ex:
            return Exception(f"read cache file: {ex}")
        except json.JSONDecodeError as ex:
            return Exception(f"unmarshal cache: {ex}")
        if not isinstance(data, dict):
            return Exception("unmarshal cache: invalid JSON payload")
        entries = data.get("entries", [])
        if not isinstance(entries, list):
            return Exception("unmarshal cache: invalid JSON payload")

        with self._mu:
            for ed in entries:
                if not isinstance(ed, dict):
                    continue
                try:
                    entry = CacheEntry(
                        key=str(ed.get("key", "")),
                        action=Action(int(ed.get("action", 0))),
                        rule_id=str(ed.get("rule_id", "")),
                        expiry=_parse_go_time(str(ed.get("expiry", ""))),
                        timestamp=_parse_go_time(str(ed.get("timestamp", ""))),
                    )
                except (ValueError, TypeError):
                    continue
                if entry.IsExpired():
                    continue
                if len(self._order) >= self._max_size:
                    self._evict_oldest_locked()
                self._entries[entry.key] = entry
                self._order.append(entry.key)
        return None


def NewPermissionCache(ttl: timedelta, max_size: int = 1024) -> PermissionCache:
    """Create a cache with the given TTL and max entries. Use ttl=0 for
    session-only entries (no expiry). MaxSize of 0 defaults to 1024."""
    return PermissionCache(ttl, max_size)


def CacheKey(tool: str, resource: str, extra: str) -> str:
    """Build a cache key from tool, resource, and optional context hash."""
    h = hashlib.sha256()
    h.update(tool.encode("utf-8"))
    h.update(b"\x00")
    h.update(resource.encode("utf-8"))
    if extra != "":
        h.update(b"\x00")
        h.update(extra.encode("utf-8"))
    return h.digest()[:16].hex()
