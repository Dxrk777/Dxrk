# SPDX-License-Identifier: MIT
"""Swarm task scheduler."""

from __future__ import annotations

import concurrent.futures
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
from dxrk.utils.swarm_model import TaskPayloadHandler as TaskPayloadHandler
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

    def __init__(
        self,
        registry: BackendRegistry,
        config: SchedulerConfig,
        handler: TaskPayloadHandler | None = None,
    ) -> None:
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
        self._handler = handler
        # Shared handler pool: one executor for all task attempts (sized to
        # the worker pool) instead of a per-task ThreadPoolExecutor churned
        # on every _run_task. Shut down with the scheduler in Stop().
        self._exec = concurrent.futures.ThreadPoolExecutor(
            max_workers=config.max_concurrent_tasks, thread_name_prefix="swarm-handler"
        )

    def RegisterHandler(self, handler: TaskPayloadHandler) -> None:
        """Register the callable that executes task payloads.

        The handler receives the assigned :class:`Task` and returns the
        output bytes (or None). Without a handler the scheduler echoes
        ``task.payload`` as the output — real data flow, not a simulation.
        """
        with self._mu:
            self._handler = handler

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
        try:
            while True:
                if self._ctx.err() is not None:
                    return
                try:
                    task = w.tasks.get(timeout=0.05)
                except queue.Empty:
                    continue
                self._execute_task(w, task)
        finally:
            w.done.set()

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
        self._exec.shutdown(wait=True)

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
                    session_id=task.session_id,
                    metrics={_STR_ERROR: 1.0},
                    timestamp=_now(),
                )
            )
            return

        if self._config.work_stealing:
            selected = self._select_backend_work_stealing(backends, task)
        else:
            selected = self._select_backend_least_loaded(backends, task)

        if selected is None:
            task.error = "no suitable backend found"
            self._results.put(
                TaskResult(
                    task_id=task.id,
                    session_id=task.session_id,
                    metrics={_STR_ERROR: 1.0},
                    timestamp=_now(),
                )
            )
            return

        # Workers form a generic pool: assign the task to the selected
        # backend, then hand it to the least-queued worker. (Looking workers
        # up by backend ID never matches — workers are keyed ``worker-*`` —
        # so every task used to die here with "backend worker not found".)
        task.Assign(selected.id)
        task.started_at = _now()
        selected.IncrementLoad()

        w = self._select_worker()
        if w is None:
            selected.DecrementLoad()
            with self._mu:
                has_workers = bool(self._workers)
            task.error = "worker queue full" if has_workers else "no workers available"
            self._results.put(
                TaskResult(
                    task_id=task.id,
                    backend_id=selected.id,
                    session_id=task.session_id,
                    metrics={_STR_ERROR: 1.0},
                    timestamp=_now(),
                )
            )
            return

        try:
            w.tasks.put_nowait(task)
        except queue.Full:
            selected.DecrementLoad()
            task.error = "worker queue full"
            self._results.put(
                TaskResult(
                    task_id=task.id,
                    backend_id=selected.id,
                    session_id=task.session_id,
                    metrics={_STR_ERROR: 1.0},
                    timestamp=_now(),
                )
            )

    def _select_worker(self) -> _Worker | None:
        """Return the non-full worker with the shortest queue, if any."""
        with self._mu:
            workers = list(self._workers.values())
        best: _Worker | None = None
        best_depth = 0
        for w in workers:
            try:
                depth = w.tasks.qsize()
            except NotImplementedError:
                depth = 0
            if w.tasks.full():
                continue
            if best is None or depth < best_depth:
                best = w
                best_depth = depth
        return best

    def _select_backend_least_loaded(self, backends: list[Backend], task: Task) -> Backend | None:
        """Return the least-loaded backend able to take ``task``, if any.

        Mirrors :meth:`_select_backend_work_stealing`: saturated backends
        and capability mismatches are skipped via ``CanHandle`` instead
        of being picked and failed later.
        """
        selected: Backend | None = None
        min_load = 1 << 62
        for b in backends:
            if not b.CanHandle(task):
                continue
            if b.load < min_load:
                min_load = b.load
                selected = b
        return selected

    def _select_backend_work_stealing(self, backends: list[Backend], task: Task) -> Backend | None:
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

        try:
            last_err = ""
            for attempt in range(self._config.retry_attempts + 1):
                if self._ctx.err() is not None or time.monotonic() >= deadline:
                    task.error = _CTX_DEADLINE
                    self._results.put(
                        TaskResult(
                            task_id=task.id,
                            backend_id=task.assigned_backend,
                            session_id=task.session_id,
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
                    backend_id=task.assigned_backend,
                    session_id=task.session_id,
                    metrics={_STR_ERROR: 1.0, "retries_exhausted": 1.0},
                    duration=_now() - task.started_at,
                    timestamp=_now(),
                )
            )
        finally:
            backend, _ = self._registry.Get(task.assigned_backend)
            if backend is not None:
                backend.DecrementLoad()

    def _effective_timeout(self, task: Task) -> float:
        if task.timeout > timedelta(0):
            return _td_seconds(task.timeout)
        return _td_seconds(self._config.task_timeout)

    def _run_task(self, w: _Worker, task: Task) -> TaskResult:
        """Execute one task attempt via the registered handler.

        The handler runs with a timeout (the task's own ``timeout`` when
        set, else the scheduler's ``task_timeout``). On timeout the task
        records ``context deadline exceeded`` and the result carries the
        ``timeout`` metric. Without a registered handler the payload is
        echoed as the output.
        """
        start = _now()
        backend_id = task.assigned_backend or (w.backend.id if w.backend is not None else "")
        timeout = self._effective_timeout(task)

        with self._mu:
            handler = self._handler

        if handler is None:
            output = task.payload
        else:
            try:
                future = self._exec.submit(handler, task)
            except RuntimeError as exc:  # executor shut down (Stop raced a task)
                task.error = str(exc) or "handler failed"
                return TaskResult(
                    task_id=task.id,
                    backend_id=backend_id,
                    session_id=task.session_id,
                    metrics={_STR_ERROR: 1.0},
                    duration=_now() - start,
                    timestamp=_now(),
                )
            try:
                output = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                task.error = _CTX_DEADLINE
                return TaskResult(
                    task_id=task.id,
                    backend_id=backend_id,
                    session_id=task.session_id,
                    metrics={_STR_ERROR: 1.0, _STR_TIMEOUT: 1.0},
                    duration=_now() - start,
                    timestamp=_now(),
                )
            except Exception as exc:  # noqa: BLE001 - recorded on the task
                task.error = str(exc) or "handler failed"
                return TaskResult(
                    task_id=task.id,
                    backend_id=backend_id,
                    session_id=task.session_id,
                    metrics={_STR_ERROR: 1.0},
                    duration=_now() - start,
                    timestamp=_now(),
                )

        result = TaskResult(
            task_id=task.id,
            backend_id=backend_id,
            session_id=task.session_id,
            output=output,
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
    registry: BackendRegistry, config: SchedulerConfig, handler: TaskPayloadHandler | None = None
) -> TaskScheduler:
    """Create a new task scheduler. Mirrors swarm.NewTaskScheduler()."""
    return TaskScheduler(registry, config, handler=handler)
