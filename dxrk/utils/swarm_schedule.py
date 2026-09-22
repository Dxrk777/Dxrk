# SPDX-License-Identifier: MIT
"""Swarm task scheduler."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta

from dxrk.utils.swarm_model import _CTX_DEADLINE as _CTX_DEADLINE
from dxrk.utils.swarm_model import _STR_ERROR as _STR_ERROR
from dxrk.utils.swarm_model import _STR_TIMEOUT as _STR_TIMEOUT
from dxrk.utils.swarm_model import Backend as Backend
from dxrk.utils.swarm_model import ErrQueueFull as ErrQueueFull
from dxrk.utils.swarm_model import SwarmError as SwarmError
from dxrk.utils.swarm_model import Task as Task
from dxrk.utils.swarm_model import TaskResult as TaskResult
from dxrk.utils.swarm_model import _now as _now
from dxrk.utils.swarm_model import _rand_string as _rand_string
from dxrk.utils.swarm_model import _td_seconds as _td_seconds
from dxrk.utils.swarm_model import _with_cancel as _with_cancel
from dxrk.utils.swarm_registry import BackendRegistry as BackendRegistry


@dataclass
class SchedulerConfig:
    """Configuration for the task scheduler. Mirrors swarm.SchedulerConfig."""

    max_concurrent_tasks: int = 0
    queue_size: int = 0
    work_stealing: bool = False
    task_timeout: timedelta = timedelta(0)
    retry_attempts: int = 0
    retry_delay: timedelta = timedelta(0)


@dataclass
class SchedulerStats:
    """Statistics for the task scheduler. Mirrors swarm.SchedulerStats."""

    active_workers: int = 0
    total_workers: int = 0
    queue_length: int = 0
    config: SchedulerConfig = field(default_factory=SchedulerConfig)


@dataclass
class _Worker:
    """A scheduler worker. Mirrors swarm.worker."""

    id: str = ""
    backend: Backend | None = None
    tasks: queue.Queue[Task] = field(default_factory=lambda: queue.Queue(maxsize=10))
    results: queue.Queue[TaskResult] = field(default_factory=lambda: queue.Queue())
    done: threading.Event = field(default_factory=threading.Event, repr=False)


class TaskScheduler:
    """Distributes tasks to worker goroutines. Mirrors swarm.TaskScheduler."""

    def __init__(self, registry: BackendRegistry, config: SchedulerConfig) -> None:
        if config.max_concurrent_tasks <= 0:
            config.max_concurrent_tasks = 10
        if config.queue_size <= 0:
            config.queue_size = 100
        if config.task_timeout <= timedelta(0):
            config.task_timeout = timedelta(minutes=5)
        if config.retry_attempts <= 0:
            config.retry_attempts = 3
        if config.retry_delay <= timedelta(0):
            config.retry_delay = timedelta(seconds=1)

        self._registry = registry
        self._mu = threading.RLock()
        self._workers: dict[str, _Worker] = {}
        self._task_queue: queue.Queue[Task] = queue.Queue(maxsize=config.queue_size)
        self._results: queue.Queue[TaskResult] = queue.Queue(maxsize=config.queue_size)
        self._ctx, self._cancel = _with_cancel()
        self._threads: list[threading.Thread] = []
        self._config = config

    def Start(self) -> None:
        """Start the scheduler workers and dispatch loop. Mirrors TaskScheduler.Start()."""
        for _ in range(self._config.max_concurrent_tasks):
            self._start_worker()
        thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._threads.append(thread)
        thread.start()

    def _start_worker(self) -> None:
        w = _Worker(
            id=self._generate_worker_id(),
            tasks=queue.Queue(maxsize=10),
            results=self._results,
        )
        with self._mu:
            self._workers[w.id] = w
        thread = threading.Thread(target=self._worker_loop, args=(w,), daemon=True)
        self._threads.append(thread)
        thread.start()

    def _worker_loop(self, w: _Worker) -> None:
        while True:
            if self._ctx.err() is not None:
                return
            try:
                task = w.tasks.get(timeout=0.05)
            except queue.Empty:
                continue
            self._execute_task(w, task)

    def _dispatch_loop(self) -> None:
        while True:
            if self._ctx.err() is not None:
                return
            try:
                task = self._task_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            self._dispatch_task(task)

    def _generate_worker_id(self) -> str:
        return "worker-" + _rand_string(8)

    def Stop(self) -> None:
        """Stop the scheduler. Mirrors TaskScheduler.Stop()."""
        self._cancel()
        for thread in self._threads:
            thread.join(timeout=2.0)
        self._threads.clear()

    def Submit(self, task: Task) -> SwarmError | None:
        """Submit a task to the scheduler queue. Mirrors TaskScheduler.Submit()."""
        ctx_err = self._ctx.err()
        if ctx_err is not None:
            return SwarmError(ctx_err)
        try:
            self._task_queue.put_nowait(task)
        except queue.Full:
            return ErrQueueFull
        return None

    def _dispatch_task(self, task: Task) -> None:
        backends = self._registry.GetHealthy()
        if not backends:
            task.error = "no healthy backends available"
            self._results.put(
                TaskResult(
                    task_id=task.id,
                    metrics={_STR_ERROR: 1.0},
                    timestamp=_now(),
                )
            )
            return

        if self._config.work_stealing:
            selected = self._select_backend_work_stealing(backends, task)
        else:
            selected = self._select_backend_least_loaded(backends)

        if selected is None:
            task.error = "no suitable backend found"
            self._results.put(
                TaskResult(
                    task_id=task.id,
                    metrics={_STR_ERROR: 1.0},
                    timestamp=_now(),
                )
            )
            return

        w = self._workers.get(selected.id)
        if w is None:
            task.error = "backend worker not found"
            self._results.put(
                TaskResult(
                    task_id=task.id,
                    metrics={_STR_ERROR: 1.0},
                    timestamp=_now(),
                )
            )
            return

        task.Assign(selected.id)
        task.started_at = _now()

        try:
            w.tasks.put_nowait(task)
        except queue.Full:
            task.error = "worker queue full"
            self._results.put(
                TaskResult(
                    task_id=task.id,
                    metrics={_STR_ERROR: 1.0},
                    timestamp=_now(),
                )
            )

    def _select_backend_least_loaded(self, backends: list[Backend]) -> Backend | None:
        selected: Backend | None = None
        min_load = 1 << 62
        for b in backends:
            if b.load < min_load:
                min_load = b.load
                selected = b
        return selected

    def _select_backend_work_stealing(
        self, backends: list[Backend], task: Task
    ) -> Backend | None:
        scores: list[tuple[Backend, float]] = []
        for b in backends:
            capacity = float(b.capacity - b.load)
            if capacity <= 0:
                continue
            affinity = 1.0
            if task.type != "" and task.type == b.id:
                affinity = 1.5
            score = capacity * affinity / (1 + float(b.load))
            scores.append((b, score))
        if not scores:
            return None
        best = scores[0]
        for candidate in scores[1:]:
            if candidate[1] > best[1]:
                best = candidate
        return best[0]

    def _execute_task(self, w: _Worker, task: Task) -> None:
        deadline = time.monotonic() + _td_seconds(self._config.task_timeout)

        last_err = ""
        for attempt in range(self._config.retry_attempts + 1):
            if self._ctx.err() is not None or time.monotonic() >= deadline:
                task.error = _CTX_DEADLINE
                self._results.put(
                    TaskResult(
                        task_id=task.id,
                        metrics={_STR_ERROR: 1.0, _STR_TIMEOUT: 1.0},
                        duration=_now() - task.started_at,
                        timestamp=_now(),
                    )
                )
                return

            result = self._run_task(w, task)
            if task.error == "":
                self._results.put(result)
                return
            last_err = task.error
            if attempt < self._config.retry_attempts:
                time.sleep(_td_seconds(self._config.retry_delay))

        task.error = last_err
        self._results.put(
            TaskResult(
                task_id=task.id,
                metrics={_STR_ERROR: 1.0, "retries_exhausted": 1.0},
                duration=_now() - task.started_at,
                timestamp=_now(),
            )
        )

    def _run_task(self, w: _Worker, task: Task) -> TaskResult:
        start = _now()
        backend_id = w.backend.id if w.backend is not None else ""

        result = TaskResult(
            task_id=task.id,
            backend_id=backend_id,
            metrics={"simulated": 1.0},
            duration=_now() - start,
            timestamp=_now(),
        )
        task.Complete(result, None)
        return result

    def Results(self) -> queue.Queue[TaskResult]:
        """Return the results channel. Mirrors TaskScheduler.Results()."""
        return self._results

    def Stats(self) -> SchedulerStats:
        """Return scheduler statistics. Mirrors TaskScheduler.Stats()."""
        with self._mu:
            active_workers = 0
            for w in self._workers.values():
                if w.done is not None and not w.done.is_set():
                    active_workers += 1
            return SchedulerStats(
                active_workers=active_workers,
                total_workers=len(self._workers),
                queue_length=self._task_queue.qsize(),
                config=self._config,
            )


def NewTaskScheduler(
    registry: BackendRegistry, config: SchedulerConfig
) -> TaskScheduler:
    """Create a new task scheduler. Mirrors swarm.NewTaskScheduler()."""
    return TaskScheduler(registry, config)
