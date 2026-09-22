# SPDX-License-Identifier: MIT
"""Swarm model: errors, aliases, config, entities, context, IDs."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum

# Mirrors dxrk/strconst.StrUnknown / dxrk/strconst.StrError /
# dxrk/strconst.StrTimeout / dxrk/strconst.StrTaskId.
_STR_UNKNOWN = "unknown"
_STR_ERROR = "error"
_STR_TIMEOUT = "timeout"
_STR_TASK_ID = "task_id"

_CTX_CANCELED = "context canceled"
_CTX_DEADLINE = "context deadline exceeded"

_ZERO_TIME = datetime.fromtimestamp(0, tz=UTC)


def _now() -> datetime:
    """Return the current UTC time. Mirrors time.Now()."""
    return datetime.now(UTC)


def _is_zero(dt: datetime) -> bool:
    """Return True for a zero (unset) time. Mirrors time.Time.IsZero()."""
    return dt == _ZERO_TIME or dt.timestamp() == 0.0


def _go_time_fmt(dt: datetime) -> str:
    """Format a datetime as RFC 3339 nano JSON (UTC, Z)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    micro = dt.microsecond
    if micro == 0:
        return base + "Z"
    frac = f"{micro:06d}".rstrip("0")
    return base + "." + frac + "Z"


def _td_seconds(td: timedelta) -> float:
    """Convert a timedelta to float seconds."""
    return td.total_seconds()


class SwarmError(Exception):
    """Represents a swarm package error. Mirrors swarm error values."""

    def __init__(self, msg: str) -> None:
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


ErrBackendNotFound = SwarmError("backend not found")
ErrBackendUnhealthy = SwarmError("backend unhealthy")
ErrTaskNotFound = SwarmError("task not found")
ErrNoCapacity = SwarmError("no capacity available")
ErrNotLeader = SwarmError("not leader")
ErrLeaseExpired = SwarmError("lease expired")
ErrInvalidConfig = SwarmError("invalid configuration")
ErrSwarmShuttingDown = SwarmError("swarm shutting down")
ErrNoLeader = SwarmError("no leader elected")
ErrElectionInProgress = SwarmError("election already in progress")
ErrQueueFull = SwarmError("task queue full")

BackendID = str
TaskID = str
BackendCapabilities = dict[str, int]
EventHandler = Callable[["SwarmEvent"], None]
HealthCallback = Callable[[BackendID, "BackendStatus", "BackendStatus"], None]

# Mirrors swarm.Default* constants.
DEFAULT_HEARTBEAT_INTERVAL = timedelta(seconds=5)
DEFAULT_TASK_TIMEOUT = timedelta(seconds=30)
DEFAULT_LEASE_DURATION = timedelta(seconds=10)
DEFAULT_MAX_RETRIES = 3


class BackendStatus(IntEnum):
    """Represents the lifecycle status of a backend. Mirrors swarm.BackendStatus."""

    StatusUnknown = 0
    StatusStarting = 1
    StatusHealthy = 2
    StatusDegraded = 3
    StatusUnhealthy = 4
    StatusStopping = 5
    StatusStopped = 6

    def string(self) -> str:
        """Return the status name. Mirrors BackendStatus.String()."""
        names = (
            _STR_UNKNOWN,
            "starting",
            "healthy",
            "degraded",
            "unhealthy",
            "stopping",
            "stopped",
        )
        if int(self) < len(names):
            return names[int(self)]
        return _STR_UNKNOWN


class TaskPriority(IntEnum):
    """Represents task scheduling priority. Mirrors swarm.TaskPriority."""

    PriorityLow = 0
    PriorityNormal = 1
    PriorityHigh = 2
    PriorityCritical = 3


class SwarmEventType(IntEnum):
    """Represents the types of swarm events. Mirrors swarm.SwarmEventType."""

    EventBackendRegistered = 0
    EventBackendUnregistered = 1
    EventBackendStatusChanged = 2
    EventBackendHeartbeat = 3
    EventTaskSubmitted = 4
    EventTaskAssigned = 5
    EventTaskStarted = 6
    EventTaskCompleted = 7
    EventTaskFailed = 8
    EventTaskRetry = 9
    EventLeaderElected = 10
    EventLeaderLost = 11
    EventWorkStolen = 12
    EventLoadBalanced = 13

    def string(self) -> str:
        """Return the event type name. Mirrors SwarmEventType.String()."""
        names = (
            "backend_registered",
            "backend_unregistered",
            "backend_status_changed",
            "backend_heartbeat",
            "task_submitted",
            "task_assigned",
            "task_started",
            "task_completed",
            "task_failed",
            "task_retry",
            "leader_elected",
            "leader_lost",
            "work_stolen",
            "load_balanced",
        )
        if int(self) < len(names):
            return names[int(self)]
        return _STR_UNKNOWN


@dataclass
class Backend:
    """Represents a backend worker in the swarm. Mirrors swarm.Backend."""

    id: BackendID = ""
    name: str = ""
    address: str = ""
    capabilities: BackendCapabilities = field(default_factory=dict)
    capacity: int = 0
    load: int = 0
    status: BackendStatus = BackendStatus.StatusUnknown
    metadata: dict[str, str] = field(default_factory=dict)
    last_heartbeat: datetime = _ZERO_TIME
    registered_at: datetime = _ZERO_TIME
    lease_id: str = ""
    _mu: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    def AvailableCapacity(self) -> int:
        """Return the remaining capacity. Mirrors Backend.AvailableCapacity()."""
        with self._mu:
            return self.capacity - self.load

    def CanHandle(self, task: Task) -> bool:
        """Return True if the backend can accept the task. Mirrors Backend.CanHandle()."""
        with self._mu:
            if (
                self.status != BackendStatus.StatusHealthy
                and self.status != BackendStatus.StatusDegraded
            ):
                return False
            if self.load >= self.capacity:
                return False
            for req_cap, req_amount in task.required_capabilities.items():
                avail = self.capabilities.get(req_cap)
                if avail is None or avail < req_amount:
                    return False
        return True

    def IncrementLoad(self) -> bool:
        """Increment the load; returns False at capacity. Mirrors Backend.IncrementLoad()."""
        with self._mu:
            if self.load >= self.capacity:
                return False
            self.load += 1
        return True

    def DecrementLoad(self) -> None:
        """Decrement the load. Mirrors Backend.DecrementLoad()."""
        with self._mu:
            if self.load > 0:
                self.load -= 1

    def UpdateHeartbeat(self) -> None:
        """Update the last heartbeat timestamp. Mirrors Backend.UpdateHeartbeat()."""
        with self._mu:
            self.last_heartbeat = _now()

    def SetStatus(self, status: BackendStatus) -> None:
        """Set the backend status. Mirrors Backend.SetStatus()."""
        with self._mu:
            self.status = status

    def MarshalJSON(self) -> dict[str, object]:
        """Return the backend as JSON-able data. Mirrors Backend.MarshalJSON().

        Deviation: the original returns ``[]byte``; Python returns a ``dict`` whose
        keys keep the original default (capitalized) JSON field names and whose
        ``Status`` is the string form.
        """
        with self._mu:
            return {
                "ID": self.id,
                "Name": self.name,
                "Address": self.address,
                "Capabilities": self.capabilities,
                "Capacity": self.capacity,
                "Load": self.load,
                "Status": self.status.string(),
                "Metadata": self.metadata,
                "LastHeartbeat": _go_time_fmt(self.last_heartbeat),
                "RegisteredAt": _go_time_fmt(self.registered_at),
                "LeaseID": self.lease_id,
            }


@dataclass
class Task:
    """Represents a unit of work scheduled on the swarm. Mirrors swarm.Task."""

    id: TaskID = ""
    type: str = ""
    payload: bytes | None = None
    required_capabilities: BackendCapabilities = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.PriorityNormal
    timeout: timedelta = timedelta(0)
    retries: int = 0
    max_retries: int = 0
    created_at: datetime = _ZERO_TIME
    started_at: datetime = _ZERO_TIME
    completed_at: datetime = _ZERO_TIME
    assigned_backend: BackendID = ""
    result: TaskResult | None = None
    error: str = ""
    _mu: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    def IsCompleted(self) -> bool:
        """Return True if the task has completed. Mirrors Task.IsCompleted()."""
        with self._mu:
            return not _is_zero(self.completed_at)

    def IsAssigned(self) -> bool:
        """Return True if the task is assigned. Mirrors Task.IsAssigned()."""
        with self._mu:
            return self.assigned_backend != ""

    def Assign(self, backend_id: BackendID) -> None:
        """Assign the task to a backend. Mirrors Task.Assign()."""
        with self._mu:
            self.assigned_backend = backend_id
            self.started_at = _now()

    def Complete(self, result: TaskResult | None, err: SwarmError | None) -> None:
        """Mark the task complete. Mirrors Task.Complete()."""
        with self._mu:
            self.completed_at = _now()
            self.result = result
            if err is not None:
                self.error = err.msg

    def CanRetry(self) -> bool:
        """Return True if the task can be retried. Mirrors Task.CanRetry()."""
        with self._mu:
            return self.retries < self.max_retries

    def IncrementRetry(self) -> None:
        """Increment the retry counter and reset assignment. Mirrors Task.IncrementRetry()."""
        with self._mu:
            self.retries += 1
            self.assigned_backend = ""
            self.started_at = _ZERO_TIME
            self.error = ""


@dataclass
class TaskResult:
    """Represents the outcome of a scheduled task. Mirrors swarm.TaskResult."""

    task_id: TaskID = ""
    backend_id: BackendID = ""
    output: bytes | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    duration: timedelta = timedelta(0)
    timestamp: datetime = _ZERO_TIME


@dataclass
class SwarmConfig:
    """Configuration for the swarm. Mirrors swarm.SwarmConfig."""

    heartbeat_interval: timedelta = DEFAULT_HEARTBEAT_INTERVAL
    task_timeout: timedelta = DEFAULT_TASK_TIMEOUT
    lease_duration: timedelta = DEFAULT_LEASE_DURATION
    max_retries: int = DEFAULT_MAX_RETRIES
    enable_work_stealing: bool = True
    enable_load_balancing: bool = True
    min_backends: int = 1
    max_backends: int = 100
    leader_election_enabled: bool = True

    def Validate(self) -> SwarmError | None:
        """Validate the configuration. Mirrors SwarmConfig.Validate()."""
        if self.heartbeat_interval <= timedelta(0):
            return ErrInvalidConfig
        if self.task_timeout <= timedelta(0):
            return ErrInvalidConfig
        if self.lease_duration <= timedelta(0):
            return ErrInvalidConfig
        if self.max_retries < 0:
            return ErrInvalidConfig
        if self.min_backends < 0 or self.max_backends < self.min_backends:
            return ErrInvalidConfig
        return None


def DefaultSwarmConfig() -> SwarmConfig:
    """Return the default swarm configuration. Mirrors swarm.DefaultSwarmConfig()."""
    return SwarmConfig()


@dataclass
class SwarmEvent:
    """Represents an event published on the event bus. Mirrors swarm.SwarmEvent."""

    type: SwarmEventType = SwarmEventType.EventBackendRegistered
    timestamp: datetime = _ZERO_TIME
    backend_id: BackendID = ""
    task_id: TaskID = ""
    data: dict[str, object] | None = None


class _Context:
    """Minimal context mirroring the original context behavior used by swarm."""

    __slots__ = ("_done", "_err", "_deadline", "_parent")

    def __init__(
        self, parent: _Context | None = None, deadline: float | None = None
    ) -> None:
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


def _with_cancel(parent: _Context | None = None) -> tuple[_Context, Callable[[], None]]:
    """Return a child context with a cancel function. Mirrors context.WithCancel."""
    child = _Context(parent=parent)
    return child, lambda: child._set(_CTX_CANCELED)


def _rand_string(n: int) -> str:
    """Return a random lowercase alphanumeric string. Mirrors swarm.randString()."""
    letters = "abcdefghijklmnopqrstuvwxyz0123456789"
    data = secrets.token_bytes(n)
    return "".join(letters[b % len(letters)] for b in data)


def GenerateTaskID() -> TaskID:
    """Return a new task ID. Mirrors swarm.GenerateTaskID()."""
    return TaskID("task-" + _rand_string(8))


def GenerateBackendID() -> BackendID:
    """Return a new backend ID. Mirrors swarm.GenerateBackendID()."""
    return BackendID("backend-" + _rand_string(8))
