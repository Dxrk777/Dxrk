# SPDX-License-Identifier: MIT
"""Hook circuit breaker."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from dxrk.utils.hooks_model import ErrCircuitOpen

if TYPE_CHECKING:
    from dxrk.utils.hooks_exec import _Context


class CircuitBreakerState(IntEnum):
    """Represents the state of a circuit breaker. Mirrors CircuitBreakerState."""

    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


CircuitClosed = CircuitBreakerState.CLOSED
CircuitOpen = CircuitBreakerState.OPEN
CircuitHalfOpen = CircuitBreakerState.HALF_OPEN


class CircuitBreaker:
    """Implements the circuit breaker pattern. Mirrors hooks.CircuitBreaker."""

    def __init__(
        self,
        failure_threshold: int,
        success_threshold: int,
        timeout: timedelta,
    ) -> None:
        self._mu = threading.Lock()
        self._state = CircuitClosed
        self._failures = 0
        self._successes = 0
        self._last_failure: datetime | None = None
        if failure_threshold <= 0:
            failure_threshold = 5
        if success_threshold <= 0:
            success_threshold = 2
        if timeout == timedelta(0):
            timeout = timedelta(seconds=30)
        self._failure_threshold = failure_threshold
        self._success_threshold = success_threshold
        self._timeout = timeout

    def Execute(self, ctx: _Context, fn: Any) -> Any:
        """Run the given function with circuit breaker protection. Mirrors Execute."""
        if not self._allow_request():
            return ErrCircuitOpen
        err = fn(ctx)
        self._record_result(err)
        return err

    def _allow_request(self) -> bool:
        with self._mu:
            if self._state == CircuitClosed:
                return True
            if self._state == CircuitOpen:
                if self._last_failure is not None and datetime.now() - self._last_failure >= self._timeout:
                    self._state = CircuitHalfOpen
                    self._successes = 0
                    return True
                return False
            if self._state == CircuitHalfOpen:
                return True
        return False

    def _record_result(self, err: Any) -> None:
        with self._mu:
            if err is not None:
                self._failures += 1
                self._last_failure = datetime.now()
                if self._state == CircuitHalfOpen:
                    self._state = CircuitOpen
                elif self._failures >= self._failure_threshold:
                    self._state = CircuitOpen
            else:
                self._successes += 1
                if self._state == CircuitHalfOpen and self._successes >= self._success_threshold:
                    self._state = CircuitClosed
                    self._failures = 0

    def State(self) -> CircuitBreakerState:
        """Return the current circuit breaker state. Mirrors hooks.State."""
        with self._mu:
            return self._state

    def Reset(self) -> None:
        """Reset the circuit breaker to closed state. Mirrors hooks.Reset."""
        with self._mu:
            self._state = CircuitClosed
            self._failures = 0
            self._successes = 0


def NewCircuitBreaker(failure_threshold: int, success_threshold: int, timeout: timedelta) -> CircuitBreaker:
    """Create a new circuit breaker. Mirrors hooks.NewCircuitBreaker."""
    return CircuitBreaker(failure_threshold, success_threshold, timeout)
