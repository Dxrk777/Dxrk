# SPDX-License-Identifier: MIT
"""Swarm coordination utilities.

Provides multi-backend coordination for Dxrk: leader election, task
distribution, health monitoring, backend registration, capacity
management, work stealing, and load balancing.

Concurrency mapping:

* ``time.Duration`` -> ``datetime.timedelta``
* ``time.Time`` -> ``datetime`` (UTC, naive-free; zero time is the epoch)
* ``json.RawMessage`` -> ``bytes | None``
* ``context.Context`` -> the private :class:`_Context` (module-local)
* ``sync.RWMutex`` -> ``threading.RLock`` / ``threading.Lock``
* goroutines -> daemon threads
* channels -> ``queue.Queue``
* ``atomic.Pointer``/``atomic.Bool`` -> lock-guarded attributes
* ``crypto/rand`` -> ``secrets``

Fidelity notes (mirrored intentionally, including upstream quirks):

* ``TaskScheduler`` workers are keyed by ``worker-*`` IDs while
  ``dispatchTask`` looks them up by backend ID, so dispatch always falls
  through to the "backend worker not found" error path.
* ``worker.backend`` is never assigned by ``startWorker``; the
  simulated ``runTask`` dereferences it unconditionally (a nil-pointer
  panic). Python guards it with ``""`` instead of crashing.
* ``EventBus.SubscribeAll`` registers the handler under the event types
  that exist at subscribe time only, and ``dispatch`` invokes it once as
  a type handler and once as an all-handler (duplicated behavior).
* ``Backend.MarshalJSON`` returns a ``dict`` (not ``[]byte``);
  ``json.dumps`` can produce the wire format. Keys keep the original default
  (capitalized) JSON field names.
* ``SwarmCoordinator.GetTaskResult`` and ``Unsubscribe`` are no-op
  stubs.
"""

from __future__ import annotations

import queue
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


class EventBus:
    """Dispatches swarm events to subscribed handlers. Mirrors swarm.EventBus."""

    def __init__(self, ctx: _Context | None = None) -> None:
        self._handlers: dict[SwarmEventType, list[EventHandler]] = {}
        self._mu = threading.RLock()
        self._ctx, self._cancel = _with_cancel(ctx)
        self._thread: threading.Thread | None = None
        self._event_ch: queue.Queue[SwarmEvent] = queue.Queue(maxsize=1024)
        self._closed = False

    def Subscribe(
        self, event_type: SwarmEventType, handler: EventHandler
    ) -> Callable[[], None]:
        """Subscribe a handler to one event type. Mirrors EventBus.Subscribe()."""
        with self._mu:
            self._handlers.setdefault(event_type, []).append(handler)
            index = len(self._handlers[event_type]) - 1
            target = self._handlers[event_type]

            def unsubscribe() -> None:
                with self._mu:
                    if index < len(target):
                        del target[index]

            return unsubscribe

    def SubscribeAll(self, handler: EventHandler) -> Callable[[], None]:
        """Subscribe a handler to every existing event type. Mirrors EventBus.SubscribeAll()."""
        with self._mu:
            for event_type in list(self._handlers):
                self._handlers[event_type].append(handler)

            def unsubscribe() -> None:
                with self._mu:
                    for event_type in list(self._handlers):
                        handlers = self._handlers[event_type]
                        for i, h in enumerate(handlers):
                            if h is handler:
                                del handlers[i]
                                break

            return unsubscribe

    def Publish(self, event: SwarmEvent) -> None:
        """Publish an event to the bus. Mirrors EventBus.Publish()."""
        with self._mu:
            if self._closed:
                return
        try:
            self._event_ch.put_nowait(event)
        except queue.Full:
            pass

    def Start(self) -> None:
        """Start the event processing goroutine. Mirrors EventBus.Start()."""
        self._thread = threading.Thread(target=self._process_events, daemon=True)
        self._thread.start()

    def _process_events(self) -> None:
        while True:
            try:
                event = self._event_ch.get(timeout=0.05)
            except queue.Empty:
                if self._ctx.err() is not None:
                    return
                continue
            self._dispatch(event)

    def _dispatch(self, event: SwarmEvent) -> None:
        with self._mu:
            handlers = list(self._handlers.get(event.type, []))
            all_handlers: list[EventHandler] = []
            for hs in self._handlers.values():
                all_handlers.extend(hs)
        for h in handlers:
            h(event)
        for h in all_handlers:
            h(event)

    def Stop(self) -> None:
        """Stop the event bus. Mirrors EventBus.Stop()."""
        with self._mu:
            if self._closed:
                return
            self._closed = True
        self._cancel()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def Len(self) -> int:
        """Return the total number of registered handlers. Mirrors EventBus.Len()."""
        with self._mu:
            return sum(len(hs) for hs in self._handlers.values())


def NewEventBus(ctx: _Context | None = None) -> EventBus:
    """Create a new event bus. Mirrors swarm.NewEventBus()."""
    return EventBus(ctx)


class BackendRegistry:
    """Maintains the set of registered backends. Mirrors swarm.BackendRegistry."""

    def __init__(
        self, config: SwarmConfig | None = None, events: EventBus | None = None
    ) -> None:
        if config is None:
            config = DefaultSwarmConfig()
        self._backends: dict[BackendID, Backend] = {}
        self._mu = threading.RLock()
        self._config = config
        self._events = events

    def Register(
        self, ctx: _Context | None, backend: Backend | None
    ) -> SwarmError | None:
        """Register a backend in the swarm. Mirrors BackendRegistry.Register()."""
        if backend is None:
            return SwarmError("backend cannot be nil")
        if backend.id == "":
            backend.id = GenerateBackendID()
        if backend.name == "":
            return SwarmError("backend name is required")
        if backend.capacity <= 0:
            backend.capacity = 1
        if not backend.capabilities:
            backend.capabilities = {}
        if not backend.metadata:
            backend.metadata = {}

        backend.registered_at = _now()
        backend.last_heartbeat = _now()
        backend.status = BackendStatus.StatusStarting

        with self._mu:
            if len(self._backends) >= self._config.max_backends:
                return SwarmError("maximum backends reached")
            self._backends[backend.id] = backend

        backend.SetStatus(BackendStatus.StatusHealthy)

        self._emit(
            SwarmEventType.EventBackendRegistered,
            backend.id,
            {
                "name": backend.name,
                "address": backend.address,
                "capacity": backend.capacity,
                "capabilities": backend.capabilities,
            },
        )
        return None

    def Unregister(
        self, ctx: _Context | None, backend_id: BackendID
    ) -> SwarmError | None:
        """Unregister a backend from the swarm. Mirrors BackendRegistry.Unregister()."""
        with self._mu:
            backend = self._backends.get(backend_id)
            if backend is None:
                return ErrBackendNotFound
            backend.SetStatus(BackendStatus.StatusStopping)
            del self._backends[backend_id]

        self._emit(
            SwarmEventType.EventBackendUnregistered,
            backend_id,
            {"name": backend.name},
        )
        return None

    def Get(self, backend_id: BackendID) -> tuple[Backend | None, SwarmError | None]:
        """Return a backend by ID. Mirrors BackendRegistry.Get()."""
        with self._mu:
            backend = self._backends.get(backend_id)
            if backend is None:
                return None, ErrBackendNotFound
            return backend, None

    def GetAll(self) -> list[Backend]:
        """Return all registered backends. Mirrors BackendRegistry.GetAll()."""
        with self._mu:
            return list(self._backends.values())

    def GetHealthy(self) -> list[Backend]:
        """Return backends with healthy or degraded status. Mirrors BackendRegistry.GetHealthy()."""
        with self._mu:
            return [
                b
                for b in self._backends.values()
                if b.status == BackendStatus.StatusHealthy
                or b.status == BackendStatus.StatusDegraded
            ]

    def GetByCapability(self, capability: str, min_amount: int) -> list[Backend]:
        """Return healthy backends offering a capability. Mirrors BackendRegistry.GetByCapability()."""
        with self._mu:
            result = []
            for b in self._backends.values():
                if (
                    b.status != BackendStatus.StatusHealthy
                    and b.status != BackendStatus.StatusDegraded
                ):
                    continue
                amount = b.capabilities.get(capability)
                if amount is not None and amount >= min_amount:
                    result.append(b)
            return result

    def UpdateHeartbeat(self, backend_id: BackendID) -> SwarmError | None:
        """Update a backend's heartbeat. Mirrors BackendRegistry.UpdateHeartbeat()."""
        with self._mu:
            backend = self._backends.get(backend_id)
        if backend is None:
            return ErrBackendNotFound
        backend.UpdateHeartbeat()
        self._emit(SwarmEventType.EventBackendHeartbeat, backend_id, None)
        return None

    def UpdateStatus(
        self, backend_id: BackendID, status: BackendStatus
    ) -> SwarmError | None:
        """Update a backend's status. Mirrors BackendRegistry.UpdateStatus()."""
        with self._mu:
            backend = self._backends.get(backend_id)
        if backend is None:
            return ErrBackendNotFound
        old_status = backend.status
        backend.SetStatus(status)
        if old_status != status:
            self._emit(
                SwarmEventType.EventBackendStatusChanged,
                backend_id,
                {
                    "old_status": old_status.string(),
                    "new_status": status.string(),
                },
            )
        return None

    def UpdateCapacity(self, backend_id: BackendID, capacity: int) -> SwarmError | None:
        """Update a backend's capacity. Mirrors BackendRegistry.UpdateCapacity()."""
        if capacity <= 0:
            return SwarmError("capacity must be positive")
        with self._mu:
            backend = self._backends.get(backend_id)
        if backend is None:
            return ErrBackendNotFound
        with backend._mu:
            backend.capacity = capacity
        return None

    def UpdateCapabilities(
        self, backend_id: BackendID, capabilities: BackendCapabilities
    ) -> SwarmError | None:
        """Update a backend's capabilities. Mirrors BackendRegistry.UpdateCapabilities()."""
        with self._mu:
            backend = self._backends.get(backend_id)
        if backend is None:
            return ErrBackendNotFound
        with backend._mu:
            backend.capabilities = capabilities
        return None

    def Count(self) -> int:
        """Return the number of registered backends. Mirrors BackendRegistry.Count()."""
        with self._mu:
            return len(self._backends)

    def HealthyCount(self) -> int:
        """Return the number of healthy backends. Mirrors BackendRegistry.HealthyCount()."""
        with self._mu:
            return sum(
                1
                for b in self._backends.values()
                if b.status == BackendStatus.StatusHealthy
                or b.status == BackendStatus.StatusDegraded
            )

    def _emit(
        self,
        event_type: SwarmEventType,
        backend_id: BackendID,
        data: dict[str, object] | None,
    ) -> None:
        if self._events is not None:
            self._events.Publish(
                SwarmEvent(
                    type=event_type,
                    timestamp=_now(),
                    backend_id=backend_id,
                    data=data,
                )
            )


def NewBackendRegistry(
    config: SwarmConfig | None, events: EventBus | None
) -> BackendRegistry:
    """Create a new backend registry. Mirrors swarm.NewBackendRegistry()."""
    return BackendRegistry(config, events)


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


@dataclass
class BackendHealth:
    """Health information for a backend. Mirrors swarm.BackendHealth."""

    backend_id: BackendID = ""
    status: BackendStatus = BackendStatus.StatusUnknown
    last_check: datetime = _ZERO_TIME
    consecutive_failures: int = 0


@dataclass
class _HealthCheck:
    """Internal per-backend health state. Mirrors swarm.healthCheck."""

    backend_id: BackendID = ""
    last_check: datetime = _ZERO_TIME
    consecutive_failures: int = 0
    status: BackendStatus = BackendStatus.StatusUnknown


class HealthMonitor:
    """Periodically checks backend health. Mirrors swarm.HealthMonitor."""

    def __init__(
        self,
        registry: BackendRegistry,
        interval: timedelta = timedelta(seconds=10),
        timeout: timedelta = timedelta(seconds=5),
        failure_threshold: int = 3,
    ) -> None:
        if interval <= timedelta(0):
            interval = timedelta(seconds=10)
        if timeout <= timedelta(0):
            timeout = timedelta(seconds=5)
        if failure_threshold <= 0:
            failure_threshold = 3

        self._registry = registry
        self._mu = threading.RLock()
        self._checks: dict[BackendID, _HealthCheck] = {}
        self._interval = interval
        self._timeout = timeout
        self._failure_threshold = failure_threshold
        self._ctx, self._cancel = _with_cancel()
        self._thread: threading.Thread | None = None
        self._callbacks: list[HealthCallback] = []

    def Start(self) -> None:
        """Start the monitoring goroutine. Mirrors HealthMonitor.Start()."""
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def Stop(self) -> None:
        """Stop the monitoring goroutine. Mirrors HealthMonitor.Stop()."""
        self._cancel()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def RegisterCallback(self, cb: HealthCallback) -> None:
        """Register a health-change callback. Mirrors HealthMonitor.RegisterCallback()."""
        with self._mu:
            self._callbacks.append(cb)

    def _monitor_loop(self) -> None:
        interval = _td_seconds(self._interval)
        while True:
            if self._ctx.err() is not None:
                return
            time.sleep(interval)
            self._check_all()

    def _check_all(self) -> None:
        for b in self._registry.GetAll():
            self._check_backend(b)

    def _check_backend(self, b: Backend) -> None:
        with self._mu:
            check = self._checks.get(b.id)
            if check is None:
                check = _HealthCheck(backend_id=b.id, status=b.status)
                self._checks[b.id] = check

        err = self._ping_backend()

        with self._mu:
            check.last_check = _now()
            old_status = check.status

            if err is not None:
                check.consecutive_failures += 1
                if (
                    check.consecutive_failures >= self._failure_threshold
                    and check.status != BackendStatus.StatusUnhealthy
                ):
                    check.status = BackendStatus.StatusUnhealthy
                    b.status = BackendStatus.StatusUnhealthy
                    self._notify_callbacks(
                        b.id, old_status, BackendStatus.StatusUnhealthy
                    )
            else:
                check.consecutive_failures = 0
                if check.status != BackendStatus.StatusHealthy:
                    check.status = BackendStatus.StatusHealthy
                    b.status = BackendStatus.StatusHealthy
                    self._notify_callbacks(
                        b.id, old_status, BackendStatus.StatusHealthy
                    )

    def _ping_backend(self) -> SwarmError | None:
        if self._ctx.err() is not None:
            return SwarmError(self._ctx.err() or _CTX_CANCELED)
        time.sleep(0.01)
        return None

    def _notify_callbacks(
        self,
        backend_id: BackendID,
        old_status: BackendStatus,
        new_status: BackendStatus,
    ) -> None:
        for cb in list(self._callbacks):
            threading.Thread(
                target=cb, args=(backend_id, old_status, new_status), daemon=True
            ).start()

    def GetHealth(self, backend_id: BackendID) -> tuple[BackendStatus, datetime, int]:
        """Return the health state for a backend. Mirrors HealthMonitor.GetHealth()."""
        with self._mu:
            check = self._checks.get(backend_id)
            if check is None:
                return BackendStatus.StatusUnknown, _ZERO_TIME, 0
            return check.status, check.last_check, check.consecutive_failures

    def GetAllHealth(self) -> dict[BackendID, BackendHealth]:
        """Return health state for all checked backends. Mirrors HealthMonitor.GetAllHealth()."""
        with self._mu:
            return {
                backend_id: BackendHealth(
                    backend_id=backend_id,
                    status=check.status,
                    last_check=check.last_check,
                    consecutive_failures=check.consecutive_failures,
                )
                for backend_id, check in self._checks.items()
            }

    def ForceCheck(self, backend_id: BackendID) -> SwarmError | None:
        """Immediately check a backend. Mirrors HealthMonitor.ForceCheck()."""
        for b in self._registry.GetAll():
            if b.id == backend_id:
                self._check_backend(b)
                return None
        return ErrBackendNotFound


def NewHealthMonitor(
    registry: BackendRegistry,
    interval: timedelta,
    timeout: timedelta,
    failure_threshold: int,
) -> HealthMonitor:
    """Create a new health monitor. Mirrors swarm.NewHealthMonitor()."""
    return HealthMonitor(registry, interval, timeout, failure_threshold)


class LeaderElection:
    """Elects and leases a leader backend. Mirrors swarm.LeaderElection."""

    def __init__(
        self,
        config: SwarmConfig | None,
        registry: BackendRegistry,
        events: EventBus,
    ) -> None:
        if config is None:
            config = DefaultSwarmConfig()
        self._config = config
        self._registry = registry
        self._events = events
        self._leader_mu = threading.Lock()
        self._current_leader: Backend | None = None
        self._elect_mu = threading.Lock()
        self._in_election = False
        self._lease_mu = threading.Lock()
        self._lease_expiry = _ZERO_TIME
        self._lease_holder: BackendID = ""
        self._ctx, self._cancel = _with_cancel()
        self._thread: threading.Thread | None = None

    def Start(self) -> None:
        """Start the election goroutine. Mirrors LeaderElection.Start()."""
        if not self._config.leader_election_enabled:
            return
        self._thread = threading.Thread(target=self._election_loop, daemon=True)
        self._thread.start()

    def _election_loop(self) -> None:
        interval = max(0.01, _td_seconds(self._config.lease_duration) / 2)
        while True:
            if self._ctx.err() is not None:
                return
            time.sleep(interval)
            self._try_elect()

    def _try_elect(self) -> None:
        with self._elect_mu:
            if self._in_election:
                return
            self._in_election = True
        try:
            backends = self._registry.GetHealthy()
            if not backends:
                self._step_down()
                return

            candidate: Backend | None = None
            for b in backends:
                if candidate is None or b.registered_at < candidate.registered_at:
                    candidate = b

            if candidate is None:
                self._step_down()
                return

            now = _now()
            with self._lease_mu:
                if now < self._lease_expiry and self._lease_holder == candidate.id:
                    self._lease_expiry = now + self._config.lease_duration
                    return

            with self._lease_mu:
                self._lease_holder = candidate.id
                self._lease_expiry = now + self._config.lease_duration

            with self._leader_mu:
                old_leader = self._current_leader
                self._current_leader = candidate

            if old_leader is not candidate:
                if old_leader is not None:
                    self._events.Publish(
                        SwarmEvent(
                            type=SwarmEventType.EventLeaderLost,
                            timestamp=_now(),
                            backend_id=old_leader.id,
                        )
                    )
                self._events.Publish(
                    SwarmEvent(
                        type=SwarmEventType.EventLeaderElected,
                        timestamp=_now(),
                        backend_id=candidate.id,
                        data={"name": candidate.name},
                    )
                )
        finally:
            self._in_election = False

    def _step_down(self) -> None:
        with self._leader_mu:
            old_leader = self._current_leader
            self._current_leader = None
        if old_leader is not None:
            self._events.Publish(
                SwarmEvent(
                    type=SwarmEventType.EventLeaderLost,
                    timestamp=_now(),
                    backend_id=old_leader.id,
                )
            )
        with self._lease_mu:
            self._lease_holder = ""
            self._lease_expiry = _ZERO_TIME

    def GetLeader(self) -> tuple[Backend | None, SwarmError | None]:
        """Return the current leader. Mirrors LeaderElection.GetLeader()."""
        with self._leader_mu:
            leader = self._current_leader
        if leader is None:
            return None, ErrNoLeader
        return leader, None

    def IsLeader(self, backend_id: BackendID) -> bool:
        """Return True if the backend is the current leader. Mirrors LeaderElection.IsLeader()."""
        with self._leader_mu:
            leader = self._current_leader
        return leader is not None and leader.id == backend_id

    def GetLeaseInfo(self) -> tuple[BackendID, datetime]:
        """Return the lease holder and expiry. Mirrors LeaderElection.GetLeaseInfo()."""
        with self._lease_mu:
            return self._lease_holder, self._lease_expiry

    def RenewLease(self, backend_id: BackendID) -> SwarmError | None:
        """Renew the leader lease. Mirrors LeaderElection.RenewLease()."""
        with self._lease_mu:
            if self._lease_holder != backend_id:
                return SwarmError("not lease holder")
            if _now() > self._lease_expiry:
                return ErrLeaseExpired
            self._lease_expiry = _now() + self._config.lease_duration
        return None

    def ForceElection(self) -> None:
        """Force an immediate election attempt. Mirrors LeaderElection.ForceElection()."""
        with self._elect_mu:
            self._in_election = False
        self._try_elect()

    def Stop(self) -> None:
        """Stop the election goroutine. Mirrors LeaderElection.Stop()."""
        self._cancel()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._step_down()


def NewLeaderElection(
    config: SwarmConfig | None,
    registry: BackendRegistry,
    events: EventBus,
) -> LeaderElection:
    """Create a new leader election. Mirrors swarm.NewLeaderElection()."""
    return LeaderElection(config, registry, events)


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

        self._health = NewHealthMonitor(
            registry, config.heartbeat_interval, timedelta(seconds=5), 3
        )
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

    def UnregisterBackend(
        self, ctx: _Context | None, backend_id: BackendID
    ) -> SwarmError | None:
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


def NewSwarmCoordinator(
    registry: BackendRegistry, config: CoordinatorConfig
) -> SwarmCoordinator:
    """Create a new swarm coordinator. Mirrors swarm.NewSwarmCoordinator()."""
    return SwarmCoordinator(registry, config)
