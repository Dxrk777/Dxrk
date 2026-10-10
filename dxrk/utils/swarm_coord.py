# SPDX-License-Identifier: MIT
"""Swarm coordinator."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from dxrk.utils.swarm_events import NewEventBus
from dxrk.utils.swarm_model import (
    _STR_TASK_ID,
    Backend,
    BackendID,
    BackendStatus,
    ErrTaskNotFound,
    EventHandler,
    SwarmConfig,
    SwarmError,
    SwarmEvent,
    SwarmEventType,
    Task,
    TaskID,
    TaskResult,
    _Context,
    _now,
    _td_seconds,
    _with_cancel,
)
from dxrk.utils.swarm_registry import BackendRegistry
from dxrk.utils.swarm_schedule import NewTaskScheduler, SchedulerConfig, SchedulerStats
from dxrk.utils.swarm_session import SwarmTaskStore
from dxrk.utils.swarm_supervise import BackendHealth, NewHealthMonitor, NewLeaderElection


@dataclass
class CoordinatorConfig:
    """Configuration for the swarm coordinator. Mirrors swarm.CoordinatorConfig."""

    election_timeout: timedelta = timedelta(seconds=10)
    heartbeat_interval: timedelta = timedelta(seconds=5)
    task_timeout: timedelta = timedelta(minutes=5)
    max_retries: int = 3
    enable_work_stealing: bool = False
    local_id: BackendID = ""
    """Backend ID identifying this coordinator. When set, IsLeader() is True
    only when the election leader matches it; when empty, IsLeader() is True
    whenever the election has produced a leader."""


@dataclass
class CoordinatorStats:
    """Statistics for the swarm coordinator. Mirrors swarm.CoordinatorStats."""

    is_leader: bool = False
    leader_id: BackendID = ""
    backend_count: int = 0
    healthy_backends: int = 0
    scheduler_stats: SchedulerStats = field(default_factory=SchedulerStats)
    backend_health: dict[BackendID, BackendHealth] = field(default_factory=dict)


class SwarmCoordinator:
    """Coordinates swarm components. Mirrors swarm.SwarmCoordinator."""

    def __init__(
        self,
        registry: BackendRegistry,
        config: CoordinatorConfig,
        result_store: SwarmTaskStore | None = None,
    ) -> None:
        if config.election_timeout <= timedelta(0):
            config.election_timeout = timedelta(seconds=10)
        if config.heartbeat_interval <= timedelta(0):
            config.heartbeat_interval = timedelta(seconds=5)
        if config.task_timeout <= timedelta(0):
            config.task_timeout = timedelta(minutes=5)
        if config.max_retries <= 0:
            config.max_retries = 3

        self._ctx, self._cancel = _with_cancel()

        swarm_config = SwarmConfig(
            heartbeat_interval=config.heartbeat_interval,
            task_timeout=config.task_timeout,
            lease_duration=config.election_timeout,
            max_retries=config.max_retries,
            enable_work_stealing=config.enable_work_stealing,
            enable_load_balancing=True,
            min_backends=1,
            max_backends=100,
            leader_election_enabled=True,
        )

        scheduler_config = SchedulerConfig(
            max_concurrent_tasks=10,
            queue_size=100,
            work_stealing=config.enable_work_stealing,
            task_timeout=config.task_timeout,
            retry_attempts=config.max_retries,
            retry_delay=timedelta(seconds=1),
        )

        self._health = NewHealthMonitor(registry, config.heartbeat_interval, timedelta(seconds=5), 3)
        self._scheduler = NewTaskScheduler(registry, scheduler_config)
        self._event_bus = NewEventBus(self._ctx)
        self._election = NewLeaderElection(swarm_config, registry, self._event_bus)

        self._registry = registry
        self._mu = threading.RLock()
        self._config = config
        self._is_leader = False
        self._leader_id: BackendID = ""
        self._unsubscribes: list[Callable[[], None]] = []
        self._subscriptions: list[tuple[SwarmEventType, EventHandler]] = []
        self._thread: threading.Thread | None = None
        self._tasks: dict[TaskID, Task] = {}
        self._results: dict[TaskID, TaskResult] = {}
        self._store = result_store

        self._health.RegisterCallback(self._on_health_change)

    def Start(self) -> None:
        """Start all swarm components. Mirrors SwarmCoordinator.Start()."""
        self._health.Start()
        self._scheduler.Start()
        self._election.Start()
        self._event_bus.Start()

        self._thread = threading.Thread(target=self._coordinator_loop, daemon=True)
        self._thread.start()

    def Stop(self) -> None:
        """Stop all swarm components. Mirrors SwarmCoordinator.Stop()."""
        self._cancel()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        self._health.Stop()
        self._scheduler.Stop()
        self._election.Stop()
        self._event_bus.Stop()

        for unsub in self._unsubscribes:
            unsub()
        self._unsubscribes.clear()
        with self._mu:
            self._subscriptions.clear()

    def _coordinator_loop(self) -> None:
        interval = _td_seconds(self._config.heartbeat_interval)
        next_heartbeat = time.monotonic() + interval
        while True:
            if self._ctx.err() is not None:
                return
            # Short polls so Stop() never waits out a full heartbeat
            # interval and a result burst cannot starve heartbeats: the
            # deadline is only reset by the heartbeat itself.
            remaining = max(0.0, next_heartbeat - time.monotonic())
            try:
                result = self._scheduler.Results().get(timeout=min(0.05, remaining) or 0.05)
            except queue.Empty:
                pass
            else:
                self._handle_task_result(result)
                continue
            if time.monotonic() >= next_heartbeat:
                self._heartbeat()
                self._sync_leader()
                next_heartbeat = time.monotonic() + interval

    def _sync_leader(self) -> None:
        """Propagate the election result into the cached leader state."""
        leader, err = self._election.GetLeader()
        with self._mu:
            if err is not None or leader is None:
                self._is_leader = False
                self._leader_id = ""
                return
            self._leader_id = leader.id
            local = self._config.local_id
            self._is_leader = leader.id == local if local else True

    def _heartbeat(self) -> None:
        with self._mu:
            is_leader = self._is_leader
            leader_id = self._leader_id
        if is_leader:
            self._event_bus.Publish(
                SwarmEvent(
                    type=SwarmEventType.EventBackendHeartbeat,
                    backend_id=leader_id,
                    timestamp=_now(),
                )
            )

    def _handle_task_result(self, result: TaskResult) -> None:
        with self._mu:
            self._results[result.task_id] = result
        if self._store is not None:
            try:
                self._store.RecordResult(result)
            except Exception:
                pass
        self._event_bus.Publish(
            SwarmEvent(
                type=SwarmEventType.EventTaskCompleted,
                backend_id=result.backend_id,
                timestamp=_now(),
                data={
                    _STR_TASK_ID: result.task_id,
                    "duration": result.duration,
                    "timestamp": result.timestamp,
                },
            )
        )

    def _on_health_change(
        self,
        backend_id: BackendID,
        old_status: BackendStatus,
        new_status: BackendStatus,
    ) -> None:
        self._event_bus.Publish(
            SwarmEvent(
                type=SwarmEventType.EventBackendStatusChanged,
                backend_id=backend_id,
                timestamp=_now(),
                data={
                    "backend_id": backend_id,
                    "old_status": old_status.string(),
                    "new_status": new_status.string(),
                },
            )
        )

        if new_status == BackendStatus.StatusUnhealthy:
            self._reschedule_tasks(backend_id)

    def _reschedule_tasks(self, backend_id: BackendID) -> None:
        """Requeue incomplete tasks assigned to an unhealthy backend.

        Each task is retried while ``CanRetry()`` holds, so retries stay
        bounded by ``max_retries``; exhausted tasks keep their error and
        are left for :meth:`GetTaskResult` callers to observe.
        """
        with self._mu:
            candidates = [t for t in self._tasks.values() if t.assigned_backend == backend_id and not t.IsCompleted()]
        for task in candidates:
            if not task.CanRetry():
                continue
            task.IncrementRetry()
            if self._store is not None:
                try:
                    self._store.RecordTask(task)
                except Exception:
                    pass
            if self._scheduler.Submit(task) is not None:
                break

    def SubmitTask(self, task: Task) -> SwarmError | None:
        """Submit a task to the coordinator's scheduler. Mirrors SwarmCoordinator.SubmitTask()."""
        if task.max_retries <= 0:
            task.max_retries = self._config.max_retries
        with self._mu:
            self._tasks[task.id] = task
        if self._store is not None:
            try:
                self._store.RecordTask(task)
            except Exception:
                pass
        return self._scheduler.Submit(task)

    def GetTaskResult(self, ctx: _Context | None, task_id: str) -> tuple[TaskResult | None, SwarmError | None]:
        """Return the completed result for a task. Mirrors SwarmCoordinator.GetTaskResult().

        Drains newly arrived scheduler results first; unknown ids return
        ``ErrTaskNotFound`` instead of a silent ``(None, None)``.
        """
        del ctx
        with self._mu:
            if task_id in self._results:
                return self._results[task_id], None
        while True:
            try:
                result = self._scheduler.Results().get_nowait()
            except queue.Empty:
                break
            self._handle_task_result(result)
        with self._mu:
            if task_id in self._results:
                return self._results[task_id], None
        return None, ErrTaskNotFound

    def RegisterBackend(self, ctx: _Context | None, b: Backend) -> SwarmError | None:
        """Register a backend. Mirrors SwarmCoordinator.RegisterBackend()."""
        return self._registry.Register(ctx, b)

    def UnregisterBackend(self, ctx: _Context | None, backend_id: BackendID) -> SwarmError | None:
        """Unregister a backend. Mirrors SwarmCoordinator.UnregisterBackend()."""
        return self._registry.Unregister(ctx, backend_id)

    def GetBackends(self) -> list[Backend]:
        """Return all registered backends. Mirrors SwarmCoordinator.GetBackends()."""
        return self._registry.GetAll()

    def GetHealthyBackends(self) -> list[Backend]:
        """Return healthy backends. Mirrors SwarmCoordinator.GetHealthyBackends()."""
        return self._registry.GetHealthy()

    def Subscribe(self, event_type: SwarmEventType, handler: EventHandler) -> Callable[[], None]:
        """Subscribe to an event type. Mirrors SwarmCoordinator.Subscribe()."""
        unsub = self._event_bus.Subscribe(event_type, handler)
        with self._mu:
            self._unsubscribes.append(unsub)
            self._subscriptions.append((event_type, handler))
        return unsub

    def Unsubscribe(self, event_type: SwarmEventType, handler: EventHandler) -> None:
        """Remove a handler subscribed via :meth:`Subscribe`."""
        with self._mu:
            self._subscriptions = [(t, h) for t, h in self._subscriptions if not (t == event_type and h is handler)]
        self._event_bus.Unsubscribe(event_type, handler)

    def IsLeader(self) -> bool:
        """Return True if the coordinator is leader. Mirrors SwarmCoordinator.IsLeader()."""
        self._sync_leader()
        with self._mu:
            return self._is_leader

    def LeaderID(self) -> BackendID:
        """Return the coordinator's leader ID. Mirrors SwarmCoordinator.LeaderID()."""
        self._sync_leader()
        with self._mu:
            return self._leader_id

    def SessionSummary(self, session_id: str) -> dict[str, int]:
        """Return submitted/completed/in-flight swarm counts for a session.

        Served from the durable :class:`SwarmTaskStore` when configured,
        else from in-memory tracking — so resume/summary can show swarm
        work either way.
        """
        if self._store is not None:
            return self._store.SessionSummary(session_id)
        with self._mu:
            submitted = sum(1 for t in self._tasks.values() if t.session_id == session_id)
            completed = sum(1 for r in self._results.values() if r.session_id == session_id)
        return {
            "submitted": submitted,
            "completed": completed,
            "in_flight": max(0, submitted - completed),
        }

    def SessionSummaryText(self, session_id: str) -> str:
        """Render one human line describing a session's swarm work."""
        if self._store is not None:
            return self._store.SessionSummaryText(session_id)
        counts = self.SessionSummary(session_id)
        return (
            f"session {session_id}: swarm {counts['completed']}/{counts['submitted']} tasks completed"
            f" ({counts['in_flight']} in flight)"
        )

    def Stats(self) -> CoordinatorStats:
        """Return coordinator statistics. Mirrors SwarmCoordinator.Stats()."""
        self._sync_leader()
        with self._mu:
            scheduler_stats = self._scheduler.Stats()
            health_stats = self._health.GetAllHealth()
            return CoordinatorStats(
                is_leader=self._is_leader,
                leader_id=self._leader_id,
                backend_count=len(self._registry.GetAll()),
                healthy_backends=len(health_stats),
                scheduler_stats=scheduler_stats,
                backend_health=health_stats,
            )


def NewSwarmCoordinator(
    registry: BackendRegistry,
    config: CoordinatorConfig,
    result_store: SwarmTaskStore | None = None,
) -> SwarmCoordinator:
    """Create a new swarm coordinator. Mirrors swarm.NewSwarmCoordinator()."""
    return SwarmCoordinator(registry, config, result_store=result_store)
