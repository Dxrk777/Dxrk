# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import pytest

from dxrk.log import new_slog
from dxrk.task import (
    Payload,
    StatusCancelled,
    StatusCompleted,
    StatusFailed,
    StatusPending,
    StatusRunning,
    Task,
    TaskStatus,
    TypeDream,
    TypeGeneric,
    TypeLocalAgent,
    TypeLocalBash,
    new_queue,
    new_task,
    new_task_id,
    new_worker_pool,
    with_logger,
    with_metadata,
    with_priority,
    with_worker_count,
)


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestQueue:
    def test_push_pop(self):
        q = new_queue()
        task = new_task(TypeGeneric, Payload())
        q.push(task)

        popped = q.pop()
        assert popped is not None
        assert popped.id == task.id

    def test_empty(self):
        q = new_queue()
        assert q.is_empty()
        q.push(new_task(TypeGeneric, Payload()))
        assert not q.is_empty()

    def test_try_pop(self):
        q = new_queue()
        assert q.try_pop() is None

        task = new_task(TypeGeneric, Payload())
        q.push(task)
        popped = q.try_pop()
        assert popped is not None
        assert popped.id == task.id

    def test_priority(self):
        q = new_queue()
        low = new_task(TypeGeneric, Payload(), with_priority(1))
        high = new_task(TypeGeneric, Payload(), with_priority(10))
        medium = new_task(TypeGeneric, Payload(), with_priority(5))

        q.push(low)
        q.push(high)
        q.push(medium)

        first = q.pop()
        assert first is not None and first.id == high.id
        second = q.pop()
        assert second is not None and second.id == medium.id
        third = q.pop()
        assert third is not None and third.id == low.id

    def test_fifo_within_priority(self):
        q = new_queue()
        task1 = new_task(TypeGeneric, Payload(), with_priority(0))
        task2 = new_task(TypeGeneric, Payload(), with_priority(0))
        task3 = new_task(TypeGeneric, Payload(), with_priority(0))

        q.push(task1)
        q.push(task2)
        q.push(task3)

        t1 = q.pop()
        assert t1 is not None and t1.id == task1.id
        t2 = q.pop()
        assert t2 is not None and t2.id == task2.id
        t3 = q.pop()
        assert t3 is not None and t3.id == task3.id

    def test_len(self):
        q = new_queue()
        assert len(q) == 0

        q.push(new_task(TypeGeneric, Payload()))
        q.push(new_task(TypeGeneric, Payload()))
        assert len(q) == 2

        q.pop()
        assert len(q) == 1


class TestTask:
    @pytest.mark.parametrize(
        ("typ", "prefix"),
        [
            (TypeLocalBash, "b"),
            (TypeLocalAgent, "a"),
            (TypeDream, "d"),
            (TypeGeneric, "g"),
        ],
    )
    def test_new_task_id_has_prefix(self, typ, prefix):
        id = new_task_id(typ)
        assert id.startswith(prefix)
        assert len(id) == 9  # prefix + 8 hex chars

    def test_new_task_id_unique(self):
        seen: set[str] = set()
        for _ in range(100):
            id = new_task_id(TypeGeneric)
            assert id not in seen
            seen.add(id)

    def test_lifecycle(self):
        task = new_task(TypeGeneric, Payload(data={"key": "val"}))
        assert task.status == StatusPending

        task.set_running()
        assert task.status == StatusRunning

        task.complete("done")
        assert task.status == StatusCompleted
        assert task.result == "done"

    def test_fail(self):
        task = new_task(TypeGeneric, Payload())
        task.set_running()

        expected = ValueError("something broke")
        task.fail(expected)
        assert task.status == StatusFailed
        assert task.error is expected

    def test_cancel_pending(self):
        task = new_task(TypeGeneric, Payload())
        task.cancel()
        assert task.status == StatusCancelled

    def test_cancel_running(self):
        cancelled = threading.Event()
        task = new_task(
            TypeGeneric, Payload(), lambda t: setattr(t, "_cancel", cancelled.set)
        )
        task.set_running()
        task.cancel()
        assert task.status == StatusCancelled
        assert cancelled.is_set()

    def test_wait(self):
        task = new_task(TypeGeneric, Payload())

        def complete_later() -> None:
            time.sleep(0.02)
            task.complete("ok")

        threading.Thread(target=complete_later, daemon=True).start()
        task.wait(timeout=5.0)
        assert task.status == StatusCompleted

    def test_options(self):
        task = new_task(
            TypeLocalBash,
            Payload(),
            with_priority(5),
            with_metadata("env", "prod"),
        )
        assert task.priority == 5
        md = task.metadata()
        assert md["env"] == "prod"

    @pytest.mark.parametrize(
        ("status", "want"),
        [
            (StatusPending, "pending"),
            (StatusRunning, "running"),
            (StatusCompleted, "completed"),
            (StatusFailed, "failed"),
            (StatusCancelled, "cancelled"),
        ],
    )
    def test_status_string(self, status: TaskStatus, want: str):
        assert status.label() == want


class TestWorkerPool:
    def test_processes_tasks(self):
        q = new_queue()
        count: list[int] = [0]

        def handler(task: Task) -> tuple[object | None, Exception | None]:
            count[0] += 1
            return "ok", None

        wp = new_worker_pool(q, handler, with_worker_count(2))
        wp.start()

        for _ in range(5):
            q.push(new_task(TypeGeneric, Payload()))

        assert _wait_until(lambda: count[0] == 5)
        wp.stop()

        assert count[0] == 5

    def test_error_does_not_crash(self):
        q = new_queue()
        count: list[int] = [0]

        def handler(task: Task) -> tuple[object | None, Exception | None]:
            count[0] += 1
            return None, HandlerError("assert")

        wp = new_worker_pool(
            q,
            handler,
            with_worker_count(1),
            with_logger(new_slog(logging.getLogger("dxrk.task.test"))),
        )
        wp.start()

        q.push(new_task(TypeGeneric, Payload()))
        q.push(new_task(TypeGeneric, Payload()))
        q.push(new_task(TypeGeneric, Payload()))

        assert _wait_until(lambda: count[0] == 3)
        wp.stop()

        assert count[0] == 3

    def test_stop_no_tasks(self):
        q = new_queue()
        wp = new_worker_pool(q, None)
        wp.start()
        wp.stop()

    def test_cancelled_task_skipped(self):
        q = new_queue()
        count: list[int] = [0]

        def handler(task: Task) -> tuple[object | None, Exception | None]:
            count[0] += 1
            return "ok", None

        wp = new_worker_pool(q, handler, with_worker_count(1))
        wp.start()

        task = new_task(TypeGeneric, Payload())
        task.cancel()
        q.push(task)

        time.sleep(0.2)
        wp.stop()

        assert count[0] == 0

    def test_active_workers(self):
        q = new_queue()
        block = threading.Event()

        def handler(task: Task) -> tuple[object | None, Exception | None]:
            block.wait()
            return "ok", None

        wp = new_worker_pool(q, handler, with_worker_count(2))
        wp.start()

        q.push(new_task(TypeGeneric, Payload()))
        q.push(new_task(TypeGeneric, Payload()))

        assert _wait_until(lambda: wp.active_workers() == 2)

        block.set()
        assert _wait_until(lambda: wp.active_workers() == 0)

        wp.stop()


class HandlerError(Exception):
    pass
