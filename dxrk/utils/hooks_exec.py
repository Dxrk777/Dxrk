# SPDX-License-Identifier: MIT
"""Hook execution context and executor."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from dxrk.utils.hooks_circuit import CircuitBreaker, NewCircuitBreaker
from dxrk.utils.hooks_model import ErrExecutionTimeout, ErrHookAborted, HookConfig, HookError, HookEvent, HookResult

_CTX_CANCELED = "context canceled"
_CTX_DEADLINE = "context deadline exceeded"


class _Context:
    """Minimal context mirroring the original context behavior used by hooks."""

    __slots__ = ("_done", "_err", "_deadline", "_parent")

    def __init__(self, parent: _Context | None = None, deadline: float | None = None) -> None:
        self._done = threading.Event()
        self._err: str | None = None
        self._deadline = deadline
        self._parent = parent

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


def _with_cancel(parent: _Context) -> tuple[_Context, Any]:
    """Return a child context with a cancel function. Mirrors context.WithCancel."""
    child = _Context(parent=parent)
    return child, lambda: child._set(_CTX_CANCELED)


def _with_timeout(parent: _Context, timeout: timedelta) -> tuple[_Context, Any]:
    """Return a child context with a timeout. Mirrors context.WithTimeout."""
    parent_remaining = parent.remaining()
    deadline = time.monotonic() + timeout.total_seconds()
    if parent_remaining is not None:
        deadline = min(deadline, time.monotonic() + parent_remaining)
    child = _Context(parent=parent, deadline=deadline)
    return child, lambda: child._set(_CTX_CANCELED)


def _exec_env(config: HookConfig) -> dict[str, str]:
    """Build a subprocess environment from the current env plus config.Env."""
    env = dict(os.environ)
    for entry in config.env:
        if "=" in entry:
            key, _, value = entry.partition("=")
            env[key] = value
        else:
            env.pop(entry, None)
    return env


def _exec_not_found(command: str) -> HookError:
    return HookError(f'exec: "{command}": executable file not found in $PATH')


class HookExecutor:
    """Executes hooks with timeout, retry, and circuit breaker. Mirrors hooks.HookExecutor."""

    def __init__(
        self,
        timeout: timedelta,
        max_retries: int,
        retry_delay: timedelta,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._circuit_breaker = circuit_breaker

    def Execute(self, ctx: _Context, config: HookConfig, event: HookEvent) -> HookResult:
        """Run a hook command with the given context and configuration."""
        start = datetime.now()
        result = HookResult(success=False, duration=timedelta(0))

        last_err: Any = None
        attempt = 0
        while attempt <= self._max_retries:
            if attempt > 0:
                if ctx.err() is not None:
                    result.error = ctx.err() or ""
                    result.duration = datetime.now() - start
                    return result
                time.sleep(self._retry_delay.total_seconds())

            exec_ctx, cancel = _with_timeout(ctx, self._timeout)
            err = self._execute_once(exec_ctx, config, event, result, attempt)
            cancel()

            if err is None:
                result.success = True
                result.duration = datetime.now() - start
                return result

            last_err = err
            if err is ErrExecutionTimeout or err is ErrHookAborted:
                break
            attempt += 1

        result.success = False
        result.error = str(last_err) if last_err is not None else ""
        result.duration = datetime.now() - start
        return result

    def _execute_once(
        self,
        ctx: _Context,
        config: HookConfig,
        event: HookEvent,
        result: HookResult,
        attempt: int,
    ) -> Any:
        del event, attempt  # HookEvent and attempt are ignored here

        def inner(inner_ctx: _Context) -> Any:
            del inner_ctx
            cmd = [config.command, *config.args]
            env = _exec_env(config)

            timeout = self._timeout.total_seconds()
            remaining = ctx.remaining()
            if remaining is not None:
                timeout = min(timeout, remaining)

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    env=env,
                    timeout=timeout if timeout > 0 else None,
                )
            except FileNotFoundError:
                result.exit_code = -1
                return _exec_not_found(config.command)
            except subprocess.TimeoutExpired as exc:
                result.exit_code = -1
                stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
                stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
                result.stdout = stdout.decode("utf-8", errors="replace")
                result.stderr = stderr.decode("utf-8", errors="replace")
                if ctx.err() is not None:
                    return ErrExecutionTimeout
                return HookError(_CTX_DEADLINE)

            result.exit_code = proc.returncode if proc.returncode >= 0 else -1
            result.stdout = proc.stdout.decode("utf-8", errors="replace")
            result.stderr = proc.stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                if ctx.err() == _CTX_DEADLINE:
                    return ErrExecutionTimeout
                return HookError(f"exit status {proc.returncode}")
            return None

        return self._circuit_breaker.Execute(ctx, inner)


HookExecutorOption = Any


def WithExecutorTimeout(d: timedelta) -> HookExecutorOption:
    """Set the execution timeout. Mirrors hooks.WithExecutorTimeout."""

    def opt(e: HookExecutor) -> None:
        e._timeout = d

    return opt


def WithExecutorRetries(n: int) -> HookExecutorOption:
    """Set the max retries. Mirrors hooks.WithExecutorRetries."""

    def opt(e: HookExecutor) -> None:
        e._max_retries = n

    return opt


def WithExecutorRetryDelay(d: timedelta) -> HookExecutorOption:
    """Set the retry delay. Mirrors hooks.WithExecutorRetryDelay."""

    def opt(e: HookExecutor) -> None:
        e._retry_delay = d

    return opt


def WithCircuitBreaker(cb: CircuitBreaker) -> HookExecutorOption:
    """Set a custom circuit breaker. Mirrors hooks.WithCircuitBreaker."""

    def opt(e: HookExecutor) -> None:
        e._circuit_breaker = cb

    return opt


def NewHookExecutor(*opts: HookExecutorOption) -> HookExecutor:
    """Create a new hook executor. Mirrors hooks.NewHookExecutor."""
    e = HookExecutor(
        timeout=timedelta(seconds=30),
        max_retries=3,
        retry_delay=timedelta(seconds=1),
        circuit_breaker=NewCircuitBreaker(5, 2, timedelta(seconds=30)),
    )
    for opt in opts:
        opt(e)
    return e
