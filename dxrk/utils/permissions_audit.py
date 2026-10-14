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

from dxrk.utils.permissions_classify import RiskLevel
from dxrk.utils.permissions_model import (
    _STR_CRITICAL,
    _STR_MEDIUM,
    _ZERO_TIME,
    Action,
    _go_time_fmt,
    _is_zero,
    _now,
    _rfc3339,
)

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

    def log(self, entry: AuditEntry) -> None:
        """Append an audit entry to the ring buffer."""
        with self._mu:
            if _is_zero(entry.timestamp):
                entry.timestamp = _now()
            self._entries[self._head] = entry
            self._head = (self._head + 1) % self._max_entries
            if self._head == 0:
                self._full = True

    # Backwards-compatible alias (Go-style name).
    Log = log

    def query(self, filter_: AuditFilter) -> list[AuditEntry]:
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

    # Backwards-compatible alias (Go-style name).
    Query = query

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

    def len(self) -> int:
        """Return the number of stored entries."""
        with self._mu:
            if self._full:
                return self._max_entries
            return self._head

    # Backwards-compatible alias (Go-style name).
    Len = len

    def _ordered_entries(self) -> list[AuditEntry]:
        count = self._max_entries if self._full else self._head
        result: list[AuditEntry] = []
        for i in range(count):
            idx = (self._head + i) % self._max_entries if self._full else i
            result.append(self._entries[idx])
        return result

    def export_json(self, w: TextIO) -> Exception | None:
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

    # Backwards-compatible alias (Go-style name).
    ExportJSON = export_json

    def export_csv(self, w: TextIO) -> Exception | None:
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

    # Backwards-compatible alias (Go-style name).
    ExportCSV = export_csv


def new_audit_log(max_entries: int) -> AuditLog:
    """Create an audit log with a fixed maximum entry count."""
    return AuditLog(max_entries)

# Backwards-compatible alias (Go-style name).
NewAuditLog = new_audit_log


# ---- Streaming ----


class AuditStreamer:
    """Sends entries to a channel as they are logged. Mirrors permissions.AuditStreamer."""

    def __init__(self, buf_size: int = 256) -> None:
        if buf_size <= 0:
            buf_size = 256
        self._ch: queue.Queue[AuditEntry] = queue.Queue(maxsize=buf_size)
        self._dropped = 0
        self._closed = False

    def channel(self) -> queue.Queue[AuditEntry]:
        """Return the queue of streamed entries."""
        return self._ch

    # Backwards-compatible alias (Go-style name).
    Channel = channel

    def dropped(self) -> int:
        """Return the count of dropped entries (buffer full)."""
        return self._dropped

    # Backwards-compatible alias (Go-style name).
    Dropped = dropped

    def send(self, entry: AuditEntry) -> None:
        """Push an entry to the streamer. Drops if the buffer is full."""
        if self._closed:
            return
        try:
            self._ch.put_nowait(entry)
        except queue.Full:
            self._dropped += 1

    # Backwards-compatible alias (Go-style name).
    Send = send

    def close(self) -> None:
        """Mark the streamer closed; later Send calls are no-ops."""
        self._closed = True

    # Backwards-compatible alias (Go-style name).
    Close = close


def new_audit_streamer(buf_size: int = 256) -> AuditStreamer:
    """Create a streamer with a buffered channel."""
    return AuditStreamer(buf_size)

# Backwards-compatible alias (Go-style name).
NewAuditStreamer = new_audit_streamer


class StreamingAuditLog:
    """Wraps AuditLog and fans out to registered streamers."""

    def __init__(self, max_entries: int) -> None:
        self._log = AuditLog(max_entries)
        self._streamers: list[AuditStreamer] = []
        self._mu = threading.Lock()

    def log(self, entry: AuditEntry) -> None:
        """Append an entry and broadcast to all streamers."""
        self._log.Log(entry)
        with self._mu:
            for s in self._streamers:
                s.Send(entry)

    # Backwards-compatible alias (Go-style name).
    Log = log

    def add_streamer(self, s: AuditStreamer) -> None:
        """Register a streamer for future entries."""
        with self._mu:
            self._streamers.append(s)

    # Backwards-compatible alias (Go-style name).
    AddStreamer = add_streamer

    def query(self, filter_: AuditFilter) -> list[AuditEntry]:
        """Delegate to the underlying audit log."""
        return self._log.Query(filter_)

    # Backwards-compatible alias (Go-style name).
    Query = query

    def export_json(self, w: TextIO) -> Exception | None:
        """Delegate to the underlying audit log."""
        return self._log.ExportJSON(w)

    # Backwards-compatible alias (Go-style name).
    ExportJSON = export_json

    def export_csv(self, w: TextIO) -> Exception | None:
        """Delegate to the underlying audit log."""
        return self._log.ExportCSV(w)

    # Backwards-compatible alias (Go-style name).
    ExportCSV = export_csv


def new_streaming_audit_log(max_entries: int) -> StreamingAuditLog:
    """Create a streaming audit log."""
    return StreamingAuditLog(max_entries)

# Backwards-compatible alias (Go-style name).
NewStreamingAuditLog = new_streaming_audit_log
