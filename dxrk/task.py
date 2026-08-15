# SPDX-License-Identifier: MIT
"""Task queue and workers.

Task with typed ID, status lifecycle, and metadata; a thread-safe priority
queue (FIFO within equal priorities); a configurable worker pool.
"""

from __future__ import annotations

import heapq
import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import NewType

from dxrk.log import Logger, new_slog
from dxrk.strconst import (
    StrCancelled,
    StrCompleted,
    StrError,
    StrFailed,
    StrPending,
    StrRunning,
    StrTaskId,
    StrUnknown,
)


class TaskType(str, Enum):
    LOCAL_BASH = "local_bash"
    LOCAL_AGENT = "local_agent"
    DREAM = "dream"
    GENERIC = "generic"


# Constant aliases (TypeLocalBash, TypeLocalAgent, ...)
TypeLocalBash = TaskType.LOCAL_BASH
TypeLocalAgent = TaskType.LOCAL_AGENT
TypeDream = TaskType.DREAM
TypeGeneric = TaskType.GENERIC


class TaskStatus(int, Enum):
    PENDING = 0
    RUNNING = 1
    COMPLETED = 2
    FAILED = 3
    CANCELLED = 4

    def label(self) -> str:
        labels: dict[TaskStatus, str] = {
            TaskStatus.PENDING: StrPending,
            TaskStatus.RUNNING: StrRunning,
            TaskStatus.COMPLETED: StrCompleted,
            TaskStatus.FAILED: StrFailed,
            TaskStatus.CANCELLED: StrCancelled,
        }
        return labels.get(self, StrUnknown)


# Constant aliases (StatusPending, StatusRunning, ...)
StatusPending = TaskStatus.PENDING
StatusRunning = TaskStatus.RUNNING
StatusCompleted = TaskStatus.COMPLETED
StatusFailed = TaskStatus.FAILED
StatusCancelled = TaskStatus.CANCELLED


# TaskID generates typed IDs like "b3a1f2..." (prefix + 8 random hex chars).
TaskID = NewType("TaskID", str)

_ID_PREFIXES: dict[TaskType, str] = {
    TaskType.LOCAL_BASH: "b",
    TaskType.LOCAL_AGENT: "a",
    TaskType.DREAM: "d",
    TaskType.GENERIC: "g",
}


def new_task_id(typ: TaskType) -> TaskID:
    return TaskID(_ID_PREFIXES[typ] + secrets.token_hex(4))


@dataclass
class Payload:
    data: dict[str, object] = field(default_factory=dict)


@dataclass
class Task:
    id: TaskID
    type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0  # higher = sooner
    payload: Payload = field(default_factory=Payload)
    result: object | None = None
    error: Exception | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    _cancel: Callable[[], None] | None = field(default=None, init=False, repr=False)
    _metadata: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _cond: threading.Condition = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._cond = threading.Condition()

    def set_running(self) -> None:
        with self._cond:
            self.status = TaskStatus.RUNNING
            self.updated_at = datetime.now()

    def complete(self, result: object | None) -> None:
        with self._cond:
            self.status = TaskStatus.COMPLETED
            self.result = result
            self.updated_at = datetime.now()
            self._cond.notify_all()

    def fail(self, error: Exception) -> None:
        with self._cond:
            self.status = TaskStatus.FAILED
            self.error = error
            self.updated_at = datetime.now()
            self._cond.notify_all()

    def cancel(self) -> None:
        with self._cond:
            if self.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                self.status = TaskStatus.CANCELLED
                self.updated_at = datetime.now()
                if self._cancel is not None:
                    self._cancel()
                self._cond.notify_all()

    def wait(self, timeout: float | None = None) -> None:
        with self._cond:
            deadline = None if timeout is None else time.monotonic() + timeout
            while self.status not in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            ):
                if deadline is None:
                    self._cond.wait()
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return
                    self._cond.wait(remaining)

    def metadata(self) -> dict[str, str]:
        with self._cond:
            return dict(self._metadata)


Option = Callable[[Task], None]


def new_task(typ: TaskType, payload: Payload, *opts: Option) -> Task:
    t = Task(id=new_task_id(typ), type=typ, payload=payload)
    for opt in opts:
        opt(t)
    return t


def with_priority(p: int) -> Option:
    return lambda t: setattr(t, "priority", p)


def with_metadata(key: str, value: str) -> Option:
    return lambda t: t._metadata.__setitem__(key, value)


# --- Queue ---


class Queue:
    """Thread-safe priority queue of tasks (mirrors queue.go)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._items: list[tuple[int, int, Task]] = []
        self._seq = 0
        self._closed = False
        self._registry: dict[TaskID, Task] = {}  # tracks all tasks by ID

    def push(self, t: Task) -> None:
        with self._lock:
            if self._closed:
                return
            self._registry[t.id] = t
            heapq.heappush(self._items, (-t.priority, self._seq, t))
            self._seq += 1
            self._cond.notify()

    def list(self) -> list[Task]:
        with self._lock:
            return list(self._registry.values())

    def get(self, id: TaskID) -> Task | None:
        with self._lock:
            return self._registry.get(id)

    def remove(self, id: TaskID) -> bool:
        """Remove a task by ID from the queue. Returns True if it was removed."""
        with self._lock:
            removed = self._registry.pop(id, None)
            if removed is None:
                return False
            self._items = [item for item in self._items if item[2].id != id]
            return True

    def pop(self) -> Task | None:
        """Blocks until a task is available, then returns the highest-priority task.

        Returns None if the queue is closed.
        """
        with self._lock:
            while not self._items:
                if self._closed:
                    return None
                self._cond.wait()
            return heapq.heappop(self._items)[2]

    def try_pop(self) -> Task | None:
        """Returns the highest-priority task immediately, or None if empty/closed."""
        with self._lock:
            if not self._items or self._closed:
                return None
            return heapq.heappop(self._items)[2]

    def close(self) -> None:
        """Wakes all blocked Pop calls and prevents further pushes."""
        with self._lock:
            self._closed = True
            self._cond.notify_all()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def is_empty(self) -> bool:
        return len(self) == 0


def new_queue() -> Queue:
    return Queue()


# --- Worker pool ---


Handler = Callable[[Task], tuple[object | None, Exception | None]]


class WorkerPool:
    """Manages a configurable number of threads consuming tasks from a Queue."""

    def __init__(
        self,
        queue: Queue,
        handler: Handler | None,
        workers: int = 4,
        logger: Logger | None = None,
    ) -> None:
        self._queue = queue
        self._handler = handler
        self._workers = workers
        self._logger = (
            logger if logger is not None else new_slog(logging.getLogger("dxrk.task"))
        )
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._active = 0
        self._stopped = False

    def start(self) -> None:
        """Launches the worker threads and returns immediately."""
        for i in range(self._workers):
            thread = threading.Thread(
                target=self._run_worker,
                args=(i,),
                name=f"dxrk-worker-{i}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        """Signals all workers to stop by closing the queue and waits for them to finish."""
        self._stopped = True
        self._queue.close()
        for thread in self._threads:
            thread.join()

    def active_workers(self) -> int:
        """Returns the number of workers currently processing a task."""
        with self._lock:
            return self._active

    def submit(self, t: Task) -> None:
        """Adds a task to the worker pool's queue."""
        self._queue.push(t)

    def queue(self) -> Queue:
        """Returns the underlying task queue."""
        return self._queue

    def _run_worker(self, worker_id: int) -> None:
        logger = self._logger.with_("worker", worker_id)
        while True:
            task = self._queue.pop()
            if task is None:
                # queue closed; worker exits
                return
            if task.status == TaskStatus.CANCELLED:
                continue
            if self._handler is None:
                continue
            with self._lock:
                self._active += 1
            task.set_running()

            result, err = self._handler(task)
            if err is not None:
                task.fail(err)
                logger.error(
                    "task failed",
                    StrTaskId,
                    task.id,
                    "type",
                    task.type.value,
                    StrError,
                    err,
                )
            else:
                task.complete(result)
                logger.debug(
                    "task completed", StrTaskId, task.id, "type", task.type.value
                )
            with self._lock:
                self._active -= 1


WorkerPoolOption = Callable[[WorkerPool], None]


def with_logger(logger: Logger) -> WorkerPoolOption:
    return lambda wp: setattr(wp, "_logger", logger)


def with_worker_count(n: int) -> WorkerPoolOption:
    return lambda wp: setattr(wp, "_workers", n)


def new_worker_pool(
    queue: Queue, handler: Handler | None, *opts: WorkerPoolOption
) -> WorkerPool:
    wp = WorkerPool(queue=queue, handler=handler)
    for opt in opts:
        opt(wp)
    return wp
