# SPDX-License-Identifier: MIT
"""Context helpers for dxrk.utils.http."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

_ZERO_TIME = datetime.fromtimestamp(0, tz=UTC)

_CTX_CANCELED = "context canceled"
_CTX_DEADLINE = "context deadline exceeded"


def _now() -> datetime:
    """Return the current UTC time. Mirrors time.Now()."""
    return datetime.now(UTC)


def _is_zero(dt: datetime) -> bool:
    """Return True for a zero (unset) time. Mirrors time.Time.IsZero()."""
    return dt == _ZERO_TIME or dt.timestamp() == 0.0


class _Context:
    """Minimal context with cancellation, deadline, and value storage."""

    __slots__ = ("_done", "_err", "_deadline", "_parent", "_values")

    def __init__(self, parent: _Context | None = None, deadline: float | None = None) -> None:
        self._done = threading.Event()
        self._err: str | None = None
        self._deadline = deadline
        self._parent = parent
        self._values: dict[str, object] | None = None

    def _set(self, err: str) -> None:
        if self._deadline is not None and time.monotonic() >= self._deadline:
            err = _CTX_DEADLINE
        if not self._done.is_set():
            self._done.set()
            self._err = err

    def err(self) -> str | None:
        """Return the context error, if any."""
        if self._parent is not None:
            perr = self._parent.err()
            if perr is not None:
                self._set(perr)
        if self._done.is_set():
            return self._err
        if self._deadline is not None and time.monotonic() >= self._deadline:
            self._set(_CTX_DEADLINE)
            return self._err
        return None

    def remaining(self) -> float | None:
        """Seconds until the deadline, or None."""
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())


def _background() -> _Context:
    """Return a never-cancelled context. Mirrors context.Background()."""
    return _Context()


def _with_cancel(parent: _Context | None = None) -> tuple[_Context, Callable[[], None]]:
    """Return a child context with a cancel function. Mirrors context.WithCancel."""
    child = _Context(parent=parent)
    return child, lambda: child._set(_CTX_CANCELED)


def _with_timeout(parent: _Context | None, timeout: timedelta) -> tuple[_Context, Callable[[], None]]:
    """Return a child context that expires after ``timeout``."""
    child = _Context(parent=parent, deadline=time.monotonic() + timeout.total_seconds())
    return child, lambda: child._set(_CTX_CANCELED)


def _with_value(ctx: _Context, key: str, value: object) -> _Context:
    """Return a child context carrying a value. Mirrors context.WithValue."""
    child = _Context(parent=ctx)
    child._values = {key: value}
    return child


def _get_value(ctx: _Context, key: str) -> object | None:
    """Look up a value in a context chain. Mirrors context.Context.Value."""
    current: _Context | None = ctx
    while current is not None:
        if current._values is not None and key in current._values:
            return current._values[key]
        current = current._parent
    return None


__all__ = [
    "_Context",
    "_background",
    "_with_cancel",
    "_with_timeout",
    "_with_value",
    "_get_value",
    "_now",
    "_is_zero",
    "_ZERO_TIME",
    "_CTX_CANCELED",
    "_CTX_DEADLINE",
]
