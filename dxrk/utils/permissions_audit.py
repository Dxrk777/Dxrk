# SPDX-License-Identifier: MIT

"""Permission audit trail: entries, filters, log, and streaming."""

from __future__ import annotations

import csv
import json
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import TextIO

from dxrk.utils.permissions_classify import RiskLevel as RiskLevel
from dxrk.utils.permissions_model import _STR_CRITICAL as _STR_CRITICAL
from dxrk.utils.permissions_model import _STR_MEDIUM as _STR_MEDIUM
from dxrk.utils.permissions_model import _ZERO_TIME as _ZERO_TIME
from dxrk.utils.permissions_model import Action as Action
from dxrk.utils.permissions_model import _go_time_fmt as _go_time_fmt
from dxrk.utils.permissions_model import _is_zero as _is_zero
from dxrk.utils.permissions_model import _now as _now
from dxrk.utils.permissions_model import _rfc3339 as _rfc3339

# ---- Audit Entry / Filter ----


@dataclass
class AuditEntry:
    """Records a single permission decision."""

    timestamp: datetime = _ZERO_TIME
    tool: str = ""
    resource: str = ""
    action: Action = Action.Allow
    rule_id: str = ""
    layer: str = ""
    user: str = ""
    risk_level: str = ""
    details: str = ""


@dataclass
class AuditFilter:
    """Defines query criteria for audit entries."""

    from_: datetime = _ZERO_TIME
    to: datetime = _ZERO_TIME
    tool: str = ""
    action: Action | None = None
    min_risk_level: RiskLevel = RiskLevel.Low


def _parse_risk_level(s: str) -> RiskLevel:
    if s == "low":
        return RiskLevel.Low
    if s == _STR_MEDIUM:
        return RiskLevel.Medium
    if s == "high":
        return RiskLevel.High
    if s == _STR_CRITICAL:
        return RiskLevel.Critical
    return RiskLevel.Low


# ---- Audit Log ----


class AuditLog:
    """A thread-safe ring-buffer audit trail. Mirrors permissions.AuditLog."""

    def __init__(self, max_entries: int) -> None:
        if max_entries <= 0:
            max_entries = 4096
        self._mu = threading.RLock()
        self._entries: list[AuditEntry] = [AuditEntry() for _ in range(max_entries)]
        self._max_entries = max_entries
        self._head = 0
        self._full = False

    def Log(self, entry: AuditEntry) -> None:
        """Append an audit entry to the ring buffer."""
        with self._mu:
            if _is_zero(entry.timestamp):
                entry.timestamp = _now()
            self._entries[self._head] = entry
            self._head = (self._head + 1) % self._max_entries
            if self._head == 0:
                self._full = True

    def Query(self, filter_: AuditFilter) -> list[AuditEntry]:
        """Return entries matching the filter, ordered oldest to newest."""
        with self._mu:
            count = self._max_entries if self._full else self._head
            result: list[AuditEntry] = []
            for i in range(count):
                idx = (self._head + i) % self._max_entries if self._full else i
                entry = self._entries[idx]
                if self._matches_filter(entry, filter_):
                    result.append(entry)
            return result

    def _matches_filter(self, entry: AuditEntry, f: AuditFilter) -> bool:
        if not _is_zero(f.from_) and entry.timestamp < f.from_:
            return False
        if not _is_zero(f.to) and entry.timestamp > f.to:
            return False
        if f.tool != "" and entry.tool != f.tool:
            return False
        if f.action is not None and entry.action != f.action:
            return False
        if f.min_risk_level > RiskLevel.Low and entry.risk_level != "":
            level = _parse_risk_level(entry.risk_level)
            if level < f.min_risk_level:
                return False
        return True

    def Len(self) -> int:
        """Return the number of stored entries."""
        with self._mu:
            if self._full:
                return self._max_entries
            return self._head

    def _ordered_entries(self) -> list[AuditEntry]:
        count = self._max_entries if self._full else self._head
        result: list[AuditEntry] = []
        for i in range(count):
            idx = (self._head + i) % self._max_entries if self._full else i
            result.append(self._entries[idx])
        return result

    def ExportJSON(self, w: TextIO) -> Exception | None:
        """Write all entries as a JSON array to w (trailing newline included)."""
        with self._mu:
            entries = self._ordered_entries()
        payload = [
            {
                "timestamp": _go_time_fmt(e.timestamp),
                "tool": e.tool,
                "resource": e.resource,
                "action": int(e.action),
                **({"rule_id": e.rule_id} if e.rule_id else {}),
                **({"layer": e.layer} if e.layer else {}),
                **({"user": e.user} if e.user else {}),
                **({"risk_level": e.risk_level} if e.risk_level else {}),
                **({"details": e.details} if e.details else {}),
            }
            for e in entries
        ]
        try:
            w.write(json.dumps(payload, indent=2) + "\n")
        except OSError as ex:
            return Exception(f"encode audit json: {ex}")
        return None

    def ExportCSV(self, w: TextIO) -> Exception | None:
        """Write all entries as CSV to w."""
        with self._mu:
            entries = self._ordered_entries()
        wr = csv.writer(w, lineterminator="\n")
        try:
            wr.writerow(
                [
                    "timestamp",
                    "tool",
                    "resource",
                    "action",
                    "rule_id",
                    "layer",
                    "user",
                    "risk_level",
                    "details",
                ]
            )
            for e in entries:
                wr.writerow(
                    [
                        _rfc3339(e.timestamp),
                        e.tool,
                        e.resource,
                        e.action.String(),
                        e.rule_id,
                        e.layer,
                        e.user,
                        e.risk_level,
                        e.details,
                    ]
                )
        except OSError as ex:
            return Exception(f"write csv row: {ex}")
        return None


def NewAuditLog(max_entries: int) -> AuditLog:
    """Create an audit log with a fixed maximum entry count."""
    return AuditLog(max_entries)


# ---- Streaming ----


class AuditStreamer:
    """Sends entries to a channel as they are logged. Mirrors permissions.AuditStreamer."""

    def __init__(self, buf_size: int = 256) -> None:
        if buf_size <= 0:
            buf_size = 256
        self._ch: queue.Queue[AuditEntry] = queue.Queue(maxsize=buf_size)
        self._dropped = 0
        self._closed = False

    def Channel(self) -> queue.Queue[AuditEntry]:
        """Return the queue of streamed entries."""
        return self._ch

    def Dropped(self) -> int:
        """Return the count of dropped entries (buffer full)."""
        return self._dropped

    def Send(self, entry: AuditEntry) -> None:
        """Push an entry to the streamer. Drops if the buffer is full."""
        if self._closed:
            return
        try:
            self._ch.put_nowait(entry)
        except queue.Full:
            self._dropped += 1

    def Close(self) -> None:
        """Mark the streamer closed; later Send calls are no-ops."""
        self._closed = True


def NewAuditStreamer(buf_size: int = 256) -> AuditStreamer:
    """Create a streamer with a buffered channel."""
    return AuditStreamer(buf_size)


class StreamingAuditLog:
    """Wraps AuditLog and fans out to registered streamers."""

    def __init__(self, max_entries: int) -> None:
        self._log = AuditLog(max_entries)
        self._streamers: list[AuditStreamer] = []
        self._mu = threading.Lock()

    def Log(self, entry: AuditEntry) -> None:
        """Append an entry and broadcast to all streamers."""
        self._log.Log(entry)
        with self._mu:
            for s in self._streamers:
                s.Send(entry)

    def AddStreamer(self, s: AuditStreamer) -> None:
        """Register a streamer for future entries."""
        with self._mu:
            self._streamers.append(s)

    def Query(self, filter_: AuditFilter) -> list[AuditEntry]:
        """Delegate to the underlying audit log."""
        return self._log.Query(filter_)

    def ExportJSON(self, w: TextIO) -> Exception | None:
        """Delegate to the underlying audit log."""
        return self._log.ExportJSON(w)

    def ExportCSV(self, w: TextIO) -> Exception | None:
        """Delegate to the underlying audit log."""
        return self._log.ExportCSV(w)


def NewStreamingAuditLog(max_entries: int) -> StreamingAuditLog:
    """Create a streaming audit log."""
    return StreamingAuditLog(max_entries)
