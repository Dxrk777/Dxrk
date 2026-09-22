# SPDX-License-Identifier: MIT
"""Async hook execution queue with a worker pool."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from dxrk.utils.hooks_exec import HookExecutor, NewHookExecutor, _background, _Context, _with_cancel
from dxrk.utils.hooks_model import ErrQueueFull, HookConfig, HookEvent, HookResult


@dataclass
class HookTask:
    """Represents a hook execution task. Mirrors hooks.HookTask."""

    event: HookEvent = field(default_factory=HookEvent)
    config: HookConfig = field(default_factory=HookConfig)
    result: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=1))
    context: _Context = field(default_factory=_background)
    cancel: Any = None


@dataclass
class QueueStats:
    """Holds queue statistics. Mirrors hooks.QueueStats."""

    processed: int = 0
    failed: int = 0
    workers: int = 0
    queue_len: int = 0
    queue_cap: int = 0
    uptime: timedelta = timedelta(0)


_SENTINEL = object()


class HookQueue:
    """Manages async hook execution with a worker pool. Mirrors hooks.HookQueue."""

    def __init__(
        self,
        *,
        tasks: queue.Queue,
        workers: int,
        executor: HookExecutor,
        started_at: datetime,
    ) -> None:
        self._mu = threading.RLock()
        self._tasks = tasks
        self._workers = workers
        self._worker_threads: list[threading.Thread] = []
        self._closed = False
        self._executor = executor
        self._processed = 0
        self._failed = 0
        self._started_at = started_at

    def Start(self) -> None:
        """Launch the worker pool. Mirrors hooks.Start."""
        with self._mu:
            if self._closed:
                return
            for _ in range(self._workers):
                t = threading.Thread(target=self._worker, daemon=True)
                self._worker_threads.append(t)
                t.start()

    def Stop(self, ctx: _Context | None = None) -> Any:
        """Gracefully shut down the queue. Mirrors hooks.Stop."""
        ctx = ctx if ctx is not None else _background()
        with self._mu:
            if self._closed:
                return None
            self._closed = True
        for _ in range(self._workers):
            self._tasks.put(_SENTINEL)

        deadline = ctx.remaining()
        for t in self._worker_threads:
            t.join(timeout=deadline)
            if ctx.remaining() == 0:
                return ctx.err()
        return None

    def Submit(self, ctx: _Context, event: HookEvent, config: HookConfig) -> tuple[HookResult, Any]:
        """Add a task to the queue and wait for its result. Mirrors hooks.Submit."""
        child_ctx, cancel = _with_cancel(ctx)
        result_ch: queue.Queue = queue.Queue(maxsize=1)

        if child_ctx.err() is not None:
            cancel()
            return HookResult(), child_ctx.err()

        try:
            self._tasks.put_nowait(
                HookTask(
                    event=event,
                    config=config,
                    result=result_ch,
                    context=child_ctx,
                    cancel=cancel,
                )
            )
            self._processed += 1
        except queue.Full:
            cancel()
            return HookResult(), ErrQueueFull

        while True:
            if child_ctx.err() is not None:
                cancel()
                return HookResult(), child_ctx.err()
            try:
                result = result_ch.get(timeout=0.05)
                break
            except queue.Empty:
                continue

        if not result.success:
            self._failed += 1
        return result, None

    def SubmitAsync(self, event: HookEvent, config: HookConfig) -> Any:
        """Add a task without waiting for a result. Mirrors hooks.SubmitAsync."""
        child_ctx, cancel = _with_cancel(_background())
        result_ch: queue.Queue = queue.Queue(maxsize=1)

        try:
            self._tasks.put_nowait(
                HookTask(
                    event=event,
                    config=config,
                    result=result_ch,
                    context=child_ctx,
                    cancel=cancel,
                )
            )
            self._processed += 1
        except queue.Full:
            cancel()
            return ErrQueueFull

        def drain() -> None:
            try:
                result_ch.get()
            except queue.Empty:
                pass

        threading.Thread(target=drain, daemon=True).start()
        return None

    def Stats(self) -> QueueStats:
        """Return queue statistics. Mirrors hooks.Stats."""
        return QueueStats(
            processed=self._processed,
            failed=self._failed,
            workers=self._workers,
            queue_len=self._tasks.qsize(),
            queue_cap=self._tasks.maxsize,
            uptime=datetime.now() - self._started_at,
        )

    def IsRunning(self) -> bool:
        """Return True if the queue is running. Mirrors hooks.IsRunning."""
        with self._mu:
            return not self._closed

    def _worker(self) -> None:
        while True:
            try:
                task = self._tasks.get()
            except queue.Empty:
                continue
            if task is _SENTINEL:
                return
            if task.context.err() is not None:
                continue

            result = self._executor.Execute(task.context, task.config, task.event)
            while True:
                if task.context.err() is not None:
                    break
                try:
                    task.result.put_nowait(result)
                    break
                except queue.Full:
                    time.sleep(0.01)


def WithQueueWorkers(n: int) -> Any:
    """Set the number of worker goroutines. Mirrors hooks.WithQueueWorkers."""

    def opt(q: HookQueue) -> None:
        q._workers = n

    return opt


def WithQueueExecutor(e: HookExecutor) -> Any:
    """Set a custom executor. Mirrors hooks.WithQueueExecutor."""

    def opt(q: HookQueue) -> None:
        q._executor = e

    return opt


def WithQueueBuffer(n: int) -> Any:
    """Set the task queue buffer size. Mirrors hooks.WithQueueBuffer."""

    def opt(q: HookQueue) -> None:
        if n > 0:
            q._tasks = queue.Queue(maxsize=n)

    return opt


def NewHookQueue(*opts: Any) -> HookQueue:
    """Create a new hook queue with a worker pool. Mirrors hooks.NewHookQueue."""
    q = HookQueue(
        tasks=queue.Queue(maxsize=100),
        workers=4,
        executor=NewHookExecutor(),
        started_at=datetime.now(),
    )
    for opt in opts:
        opt(q)
    return q
