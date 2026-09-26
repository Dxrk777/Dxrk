# SPDX-License-Identifier: MIT
"""Hook error type and sentinel errors."""

from __future__ import annotations


class HookError(Exception):
    """Represents a hook package error. Mirrors hooks error values."""

    def __init__(self, msg: str) -> None:
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


ErrConfigNotFound = HookError("hooks: config not found")
ErrConfigParse = HookError("hooks: config parse error")
ErrHookNotFound = HookError("hooks: hook not found")
ErrHookDisabled = HookError("hooks: hook is disabled")
ErrInvalidConfig = HookError("hooks: invalid configuration")
ErrRegistryClosed = HookError("hooks: registry is closed")
ErrDuplicateHookID = HookError("hooks: duplicate hook ID")
ErrExecutionTimeout = HookError("hooks: execution timeout")
ErrMaxRetriesExceeded = HookError("hooks: max retries exceeded")
ErrCircuitOpen = HookError("hooks: circuit breaker open")
ErrHookAborted = HookError("hooks: hook execution aborted")
ErrQueueClosed = HookError("hooks: queue is closed")
ErrQueueFull = HookError("hooks: queue is full")
ErrWorkerStopped = HookError("hooks: worker stopped")
ErrLoggerClosed = HookError("hooks: logger is closed")
