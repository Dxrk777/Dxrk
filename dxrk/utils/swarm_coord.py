# SPDX-License-Identifier: MIT
"""Swarm coordinator."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from dxrk.utils.swarm_events import EventBus as EventBus
from dxrk.utils.swarm_events import NewEventBus as NewEventBus
from dxrk.utils.swarm_model import _STR_TASK_ID as _STR_TASK_ID
from dxrk.utils.swarm_model import Backend as Backend
from dxrk.utils.swarm_model import BackendID as BackendID
from dxrk.utils.swarm_model import BackendStatus as BackendStatus
from dxrk.utils.swarm_model import EventHandler as EventHandler
from dxrk.utils.swarm_model import SwarmConfig as SwarmConfig
from dxrk.utils.swarm_model import SwarmError as SwarmError
from dxrk.utils.swarm_model import SwarmEvent as SwarmEvent
from dxrk.utils.swarm_model import SwarmEventType as SwarmEventType
from dxrk.utils.swarm_model import Task as Task
from dxrk.utils.swarm_model import TaskResult as TaskResult
from dxrk.utils.swarm_model import _Context as _Context
from dxrk.utils.swarm_model import _now as _now
from dxrk.utils.swarm_model import _td_seconds as _td_seconds
from dxrk.utils.swarm_model import _with_cancel as _with_cancel
from dxrk.utils.swarm_registry import BackendRegistry as BackendRegistry
from dxrk.utils.swarm_schedule import NewTaskScheduler as NewTaskScheduler
from dxrk.utils.swarm_schedule import SchedulerConfig as SchedulerConfig
from dxrk.utils.swarm_schedule import SchedulerStats as SchedulerStats
from dxrk.utils.swarm_schedule import TaskScheduler as TaskScheduler
from dxrk.utils.swarm_supervise import BackendHealth as BackendHealth
from dxrk.utils.swarm_supervise import HealthMonitor as HealthMonitor
from dxrk.utils.swarm_supervise import NewHealthMonitor as NewHealthMonitor
from dxrk.utils.swarm_supervise import NewLeaderElection as NewLeaderElection


@dataclass
class CoordinatorConfig:
    """Configuration for the swarm coordinator. Mirrors swarm.CoordinatorConfig."""

    election_timeout: timedelta = timedelta(seconds=10)
    heartbeat_interval: timedelta = timedelta(seconds=5)
    task_timeout: timedelta = timedelta(minutes=5)
    max_retries: int = 3
    enable_work_stealing: bool = False


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

    def __init__(self, registry: BackendRegistry, config: CoordinatorConfig) -> None:
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
        self._thread: threading.Thread | None = None

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
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._health.Stop()
        self._scheduler.Stop()
        self._election.Stop()
        self._event_bus.Stop()

        for unsub in self._unsubscribes:
            unsub()
        self._unsubscribes.clear()

    def _coordinator_loop(self) -> None:
        interval = _td_seconds(self._config.heartbeat_interval)
        next_heartbeat = time.monotonic() + interval
        while True:
            if self._ctx.err() is not None:
                return
            remaining = max(0.0, next_heartbeat - time.monotonic())
            try:
                result = self._scheduler.Results().get(timeout=remaining)
            except queue.Empty:
                pass
            else:
                self._handle_task_result(result)
                next_heartbeat = time.monotonic() + interval
                continue
            self._heartbeat()
            next_heartbeat = time.monotonic() + interval

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
        """No-op stub. Mirrors SwarmCoordinator.rescheduleTasks()."""

    def SubmitTask(self, task: Task) -> SwarmError | None:
        """Submit a task to the coordinator's scheduler. Mirrors SwarmCoordinator.SubmitTask()."""
        return self._scheduler.Submit(task)

    def GetTaskResult(self, ctx: _Context | None, task_id: str) -> tuple[None, None]:
        """No-op stub. Mirrors SwarmCoordinator.GetTaskResult()."""
        return None, None

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

    def Subscribe(self, event_type: SwarmEventType, handler: EventHandler) -> None:
        """Subscribe to an event type. Mirrors SwarmCoordinator.Subscribe()."""
        unsub = self._event_bus.Subscribe(event_type, handler)
        with self._mu:
            self._unsubscribes.append(unsub)

    def Unsubscribe(self, event_type: SwarmEventType, handler: EventHandler) -> None:
        """No-op stub. Mirrors SwarmCoordinator.Unsubscribe()."""

    def IsLeader(self) -> bool:
        """Return True if the coordinator is leader. Mirrors SwarmCoordinator.IsLeader()."""
        with self._mu:
            return self._is_leader

    def LeaderID(self) -> BackendID:
        """Return the coordinator's leader ID. Mirrors SwarmCoordinator.LeaderID()."""
        with self._mu:
            return self._leader_id

    def Stats(self) -> CoordinatorStats:
        """Return coordinator statistics. Mirrors SwarmCoordinator.Stats()."""
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


def NewSwarmCoordinator(registry: BackendRegistry, config: CoordinatorConfig) -> SwarmCoordinator:
    """Create a new swarm coordinator. Mirrors swarm.NewSwarmCoordinator()."""
    return SwarmCoordinator(registry, config)
