# SPDX-License-Identifier: MIT
"""Hook structured logging and metrics."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum
from typing import TYPE_CHECKING, Any, TextIO

from dxrk.utils.hooks_model import (
    _STR_ERROR,
    _STR_UNKNOWN,
    HookConfig,
    HookEvent,
    HookResult,
    HookType,
    PreToolUse,
    _evt_dump,
    _go_time_fmt,
    _result_dump,
    _td_ns,
)

if TYPE_CHECKING:
    from dxrk.utils.hooks_exec import _Context


class LogLevel(IntEnum):
    """Represents the log severity level. Mirrors hooks.LogLevel."""

    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3

    def string(self) -> str:
        """Return the level name. Mirrors LogLevel.String()."""
        names = ("debug", "info", "warn", _STR_ERROR)
        if int(self) < len(names):
            return names[int(self)]
        return _STR_UNKNOWN


LogLevelDebug = LogLevel.DEBUG
LogLevelInfo = LogLevel.INFO
LogLevelWarn = LogLevel.WARN
LogLevelError = LogLevel.ERROR


@dataclass
class HookLogEntry:
    """Represents a single hook execution log entry. Mirrors hooks.HookLogEntry."""

    timestamp: datetime = field(default_factory=datetime.now)
    level: LogLevel = LogLevelDebug
    hook_id: str = ""
    hook_type: HookType = PreToolUse
    event: HookEvent = field(default_factory=HookEvent)
    result: HookResult = field(default_factory=HookResult)
    duration: timedelta = timedelta(0)
    attempt: int = 0
    error: str = ""
    metadata: dict[str, str] | None = None


def _entry_dump(entry: HookLogEntry) -> dict[str, Any]:
    d: dict[str, Any] = {
        "timestamp": _go_time_fmt(entry.timestamp),
        "level": int(entry.level),
        "hook_id": entry.hook_id,
        "hook_type": int(entry.hook_type),
        "event": _evt_dump(entry.event),
        "result": _result_dump(entry.result),
        "duration": _td_ns(entry.duration),
        "attempt": entry.attempt,
    }
    if entry.error:
        d["error"] = entry.error
    if entry.metadata:
        d["metadata"] = entry.metadata
    return d


@dataclass
class TypeMetrics:
    """Per-type execution metrics. Mirrors hooks.TypeMetrics."""

    count: int = 0
    success: int = 0
    failure: int = 0
    total_dur: timedelta = timedelta(0)


@dataclass
class HookMetricsEntry:
    """Per-hook execution metrics. Mirrors hooks.HookMetricsEntry."""

    id: str = ""
    type: HookType = PreToolUse
    count: int = 0
    success: int = 0
    failure: int = 0
    total_dur: timedelta = timedelta(0)
    avg_dur: timedelta = timedelta(0)
    last_exec: datetime = field(default_factory=datetime.now)
    last_result: HookResult = field(default_factory=HookResult)


class HookMetrics:
    """Holds aggregated hook execution metrics. Mirrors hooks.HookMetrics."""

    def __init__(self) -> None:
        self._mu = threading.RLock()
        self._total_executions = 0
        self._success_count = 0
        self._failure_count = 0
        self._total_duration = timedelta(0)
        self._by_type: dict[HookType, TypeMetrics] = {}
        self._by_hook: dict[str, HookMetricsEntry] = {}


@dataclass
class TypeMetricsSnapshot:
    """Read-only snapshot of type metrics. Mirrors hooks.TypeMetricsSnapshot."""

    count: int = 0
    success: int = 0
    failure: int = 0
    total_dur: timedelta = timedelta(0)
    avg_dur: timedelta = timedelta(0)


@dataclass
class HookMetricsEntrySnapshot:
    """Read-only snapshot of hook metrics. Mirrors hooks.HookMetricsEntrySnapshot."""

    id: str = ""
    type: HookType = PreToolUse
    count: int = 0
    success: int = 0
    failure: int = 0
    total_dur: timedelta = timedelta(0)
    avg_dur: timedelta = timedelta(0)
    last_exec: datetime = field(default_factory=datetime.now)


@dataclass
class HookMetricsSnapshot:
    """Read-only snapshot of metrics. Mirrors hooks.HookMetricsSnapshot."""

    total_executions: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_duration: timedelta = timedelta(0)
    by_type: dict[HookType, TypeMetricsSnapshot] = field(default_factory=dict)
    by_hook: dict[str, HookMetricsEntrySnapshot] = field(default_factory=dict)


class _DiscardWriter:
    """Writer that discards output. Mirrors io.Discard."""

    def write(self, s: str) -> int:
        return len(s)


class HookLogger:
    """Handles structured logging and metrics. Mirrors hooks.HookLogger."""

    def __init__(self, output: TextIO | None, level: LogLevel) -> None:
        self._mu = threading.Lock()
        self._output: Any = output if output is not None else _DiscardWriter()
        self._level = level
        self._metrics = HookMetrics()
        self._entries: list[HookLogEntry] = []
        self._max_entries = 1000
        self._closed = False
        self._hooks: list[Any] = []

    def SetLevel(self, level: LogLevel) -> None:
        """Set the minimum log level. Mirrors hooks.SetLevel."""
        with self._mu:
            self._level = level

    def AddHook(self, fn: Any) -> None:
        """Add a callback for log entries. Mirrors hooks.AddHook."""
        with self._mu:
            self._hooks.append(fn)

    def Log(self, entry: HookLogEntry) -> None:
        """Log a hook execution entry. Mirrors hooks.Log."""
        with self._mu:
            if self._closed:
                return
            if entry.level < self._level:
                return

            self._entries.append(entry)
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[1:]

            self._update_metrics(entry)
            self._write_entry(entry)
            for h in self._hooks:
                h(entry)

    def _write_entry(self, entry: HookLogEntry) -> None:
        try:
            data = json.dumps(_entry_dump(entry), separators=(",", ":"))
        except (ValueError, TypeError):
            data = "{}"
        self._output.write(data + "\n")

    def _update_metrics(self, entry: HookLogEntry) -> None:
        m = self._metrics
        m._total_executions += 1
        if entry.result.success:
            m._success_count += 1
        else:
            m._failure_count += 1

        with m._mu:
            m._total_duration += entry.duration

            tm = m._by_type.get(entry.hook_type)
            if tm is None:
                tm = TypeMetrics()
                m._by_type[entry.hook_type] = tm
            tm.count += 1
            if entry.result.success:
                tm.success += 1
            else:
                tm.failure += 1
            tm.total_dur += entry.duration

            hme = m._by_hook.get(entry.hook_id)
            if hme is None:
                hme = HookMetricsEntry(id=entry.hook_id, type=entry.hook_type)
                m._by_hook[entry.hook_id] = hme
            hme.count += 1
            if entry.result.success:
                hme.success += 1
            else:
                hme.failure += 1
            hme.total_dur += entry.duration
            hme.avg_dur = hme.total_dur / max(hme.count, 1)
            hme.last_exec = entry.timestamp
            hme.last_result = entry.result

    def Metrics(self) -> HookMetricsSnapshot:
        """Return a snapshot of current metrics. Mirrors hooks.Metrics."""
        m = self._metrics
        with m._mu:
            by_type: dict[HookType, TypeMetricsSnapshot] = {}
            for k, v in m._by_type.items():
                by_type[k] = TypeMetricsSnapshot(
                    count=v.count,
                    success=v.success,
                    failure=v.failure,
                    total_dur=v.total_dur,
                    avg_dur=v.total_dur / max(v.count, 1),
                )
            by_hook: dict[str, HookMetricsEntrySnapshot] = {}
            for hook_key, metrics_entry in m._by_hook.items():
                by_hook[hook_key] = HookMetricsEntrySnapshot(
                    id=metrics_entry.id,
                    type=metrics_entry.type,
                    count=metrics_entry.count,
                    success=metrics_entry.success,
                    failure=metrics_entry.failure,
                    total_dur=metrics_entry.total_dur,
                    avg_dur=metrics_entry.avg_dur,
                    last_exec=metrics_entry.last_exec,
                )
            return HookMetricsSnapshot(
                total_executions=m._total_executions,
                success_count=m._success_count,
                failure_count=m._failure_count,
                total_duration=m._total_duration,
                by_type=by_type,
                by_hook=by_hook,
            )

    def RecentEntries(self, n: int) -> list[HookLogEntry]:
        """Return the most recent log entries. Mirrors hooks.RecentEntries."""
        with self._mu:
            if n <= 0 or n > len(self._entries):
                n = len(self._entries)
            start = len(self._entries) - n
            return list(self._entries[start:])

    def Close(self) -> None:
        """Close the logger. Mirrors hooks.Close."""
        with self._mu:
            self._closed = True

    def LogHookExecution(
        self,
        ctx: _Context,
        config: HookConfig,
        event: HookEvent,
        result: HookResult,
        attempt: int,
    ) -> None:
        """Log a hook execution conveniently. Mirrors hooks.LogHookExecution."""
        del ctx
        level = LogLevelInfo
        if not result.success:
            level = LogLevelError
        elif result.duration > timedelta(seconds=5):
            level = LogLevelWarn

        entry = HookLogEntry(
            timestamp=datetime.now(),
            level=level,
            hook_id=config.id,
            hook_type=config.type,
            event=event,
            result=result,
            duration=result.duration,
            attempt=attempt,
        )
        if result.error != "":
            entry.error = result.error

        self.Log(entry)


def NewHookLogger(output: TextIO | None, level: LogLevel) -> HookLogger:
    """Create a new hook logger. Mirrors hooks.NewHookLogger."""
    return HookLogger(output, level)
