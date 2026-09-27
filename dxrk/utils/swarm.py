# SPDX-License-Identifier: MIT
"""Swarm coordination utilities — facade over the swarm_* submodules.

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

Fidelity notes (remaining intentional deviations from the Go original):

* ``Backend.MarshalJSON`` returns a ``dict`` (not ``[]byte``);
  ``json.dumps`` can produce the wire format. Keys keep the original default
  (capitalized) JSON field names.
* ``Task.payload`` is opaque bytes. Without a registered handler the
  scheduler echoes the payload as the output; register a
  ``TaskPayloadHandler`` (per-scheduler or via ``RegisterHandler``) to
  compute real outputs, with per-task timeout support.
* Scope is single-host thread-concurrency: no Raft/CRDT, no cross-process
  transport. Leader election is lease-based among registered backends.
* Session linkage: ``Task.session_id`` / ``TaskResult.session_id`` carry
  the owning session; :class:`SwarmTaskStore` (``swarm_session``) persists
  tasks and results in a local SQLite sidecar so resume/summary can show
  in-flight vs completed swarm work.
"""

from __future__ import annotations

from dxrk.utils.swarm_coord import CoordinatorConfig as CoordinatorConfig
from dxrk.utils.swarm_coord import CoordinatorStats as CoordinatorStats
from dxrk.utils.swarm_coord import NewSwarmCoordinator as NewSwarmCoordinator
from dxrk.utils.swarm_coord import SwarmCoordinator as SwarmCoordinator
from dxrk.utils.swarm_events import EventBus as EventBus
from dxrk.utils.swarm_events import NewEventBus as NewEventBus
from dxrk.utils.swarm_model import _CTX_CANCELED as _CTX_CANCELED
from dxrk.utils.swarm_model import _CTX_DEADLINE as _CTX_DEADLINE
from dxrk.utils.swarm_model import _STR_ERROR as _STR_ERROR
from dxrk.utils.swarm_model import _STR_TASK_ID as _STR_TASK_ID
from dxrk.utils.swarm_model import _STR_TIMEOUT as _STR_TIMEOUT
from dxrk.utils.swarm_model import _STR_UNKNOWN as _STR_UNKNOWN
from dxrk.utils.swarm_model import _ZERO_TIME as _ZERO_TIME
from dxrk.utils.swarm_model import DEFAULT_HEARTBEAT_INTERVAL as DEFAULT_HEARTBEAT_INTERVAL
from dxrk.utils.swarm_model import DEFAULT_LEASE_DURATION as DEFAULT_LEASE_DURATION
from dxrk.utils.swarm_model import DEFAULT_MAX_RETRIES as DEFAULT_MAX_RETRIES
from dxrk.utils.swarm_model import DEFAULT_TASK_TIMEOUT as DEFAULT_TASK_TIMEOUT
from dxrk.utils.swarm_model import Backend as Backend
from dxrk.utils.swarm_model import BackendCapabilities as BackendCapabilities
from dxrk.utils.swarm_model import BackendID as BackendID
from dxrk.utils.swarm_model import BackendStatus as BackendStatus
from dxrk.utils.swarm_model import DefaultSwarmConfig as DefaultSwarmConfig
from dxrk.utils.swarm_model import ErrBackendNotFound as ErrBackendNotFound
from dxrk.utils.swarm_model import ErrBackendUnhealthy as ErrBackendUnhealthy
from dxrk.utils.swarm_model import ErrElectionInProgress as ErrElectionInProgress
from dxrk.utils.swarm_model import ErrInvalidConfig as ErrInvalidConfig
from dxrk.utils.swarm_model import ErrLeaseExpired as ErrLeaseExpired
from dxrk.utils.swarm_model import ErrNoCapacity as ErrNoCapacity
from dxrk.utils.swarm_model import ErrNoLeader as ErrNoLeader
from dxrk.utils.swarm_model import ErrNotLeader as ErrNotLeader
from dxrk.utils.swarm_model import ErrQueueFull as ErrQueueFull
from dxrk.utils.swarm_model import ErrSwarmShuttingDown as ErrSwarmShuttingDown
from dxrk.utils.swarm_model import ErrTaskNotFound as ErrTaskNotFound
from dxrk.utils.swarm_model import EventHandler as EventHandler
from dxrk.utils.swarm_model import GenerateBackendID as GenerateBackendID
from dxrk.utils.swarm_model import GenerateTaskID as GenerateTaskID
from dxrk.utils.swarm_model import HealthCallback as HealthCallback
from dxrk.utils.swarm_model import SwarmConfig as SwarmConfig
from dxrk.utils.swarm_model import SwarmError as SwarmError
from dxrk.utils.swarm_model import SwarmEvent as SwarmEvent
from dxrk.utils.swarm_model import SwarmEventType as SwarmEventType
from dxrk.utils.swarm_model import Task as Task
from dxrk.utils.swarm_model import TaskID as TaskID
from dxrk.utils.swarm_model import TaskPayloadHandler as TaskPayloadHandler
from dxrk.utils.swarm_model import TaskPriority as TaskPriority
from dxrk.utils.swarm_model import TaskResult as TaskResult
from dxrk.utils.swarm_model import _background as _background
from dxrk.utils.swarm_model import _Context as _Context
from dxrk.utils.swarm_model import _go_time_fmt as _go_time_fmt
from dxrk.utils.swarm_model import _is_zero as _is_zero
from dxrk.utils.swarm_model import _now as _now
from dxrk.utils.swarm_model import _rand_string as _rand_string
from dxrk.utils.swarm_model import _td_seconds as _td_seconds
from dxrk.utils.swarm_model import _with_cancel as _with_cancel
from dxrk.utils.swarm_registry import BackendRegistry as BackendRegistry
from dxrk.utils.swarm_registry import NewBackendRegistry as NewBackendRegistry
from dxrk.utils.swarm_schedule import NewTaskScheduler as NewTaskScheduler
from dxrk.utils.swarm_schedule import SchedulerConfig as SchedulerConfig
from dxrk.utils.swarm_schedule import SchedulerStats as SchedulerStats
from dxrk.utils.swarm_schedule import TaskScheduler as TaskScheduler
from dxrk.utils.swarm_schedule import _Worker as _Worker
from dxrk.utils.swarm_session import _SCHEMA as _SCHEMA
from dxrk.utils.swarm_session import NewSwarmTaskStore as NewSwarmTaskStore
from dxrk.utils.swarm_session import SwarmTaskStore as SwarmTaskStore
from dxrk.utils.swarm_supervise import BackendHealth as BackendHealth
from dxrk.utils.swarm_supervise import HealthMonitor as HealthMonitor
from dxrk.utils.swarm_supervise import LeaderElection as LeaderElection
from dxrk.utils.swarm_supervise import NewHealthMonitor as NewHealthMonitor
from dxrk.utils.swarm_supervise import NewLeaderElection as NewLeaderElection
from dxrk.utils.swarm_supervise import _HealthCheck as _HealthCheck
