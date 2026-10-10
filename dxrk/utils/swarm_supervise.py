# SPDX-License-Identifier: MIT
"""Swarm health monitoring and leader election."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from dxrk.utils.swarm_events import EventBus
from dxrk.utils.swarm_model import (
    _CTX_CANCELED,
    _ZERO_TIME,
    Backend,
    BackendID,
    BackendStatus,
    DefaultSwarmConfig,
    ErrBackendNotFound,
    ErrLeaseExpired,
    ErrNoLeader,
    HealthCallback,
    SwarmConfig,
    SwarmError,
    SwarmEvent,
    SwarmEventType,
    _now,
    _td_seconds,
    _with_cancel,
)
from dxrk.utils.swarm_registry import BackendRegistry


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
    """Periodically checks backend health. Mirrors swarm.HealthMonitor.

    The liveness probe is pluggable: :meth:`SetPing` installs a global
    check, :meth:`SetBackendPing` overrides it per backend. The default
    probe exercises the backend's own status path — a backend in
    ``stopping``/``stopped`` status fails the check — so
    ``StatusUnhealthy`` is reachable without any stubbing once
    ``consecutive_failures`` hits the threshold.
    """

    def __init__(
        self,
        registry: BackendRegistry,
        interval: timedelta = timedelta(seconds=10),
        timeout: timedelta = timedelta(seconds=5),
        failure_threshold: int = 3,
        ping: Callable[[Backend], SwarmError | None] | None = None,
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
        self._ping = ping
        self._backend_pings: dict[BackendID, Callable[[Backend], SwarmError | None]] = {}

    def SetPing(self, ping: Callable[[Backend], SwarmError | None] | None) -> None:
        """Install (or clear) the global liveness probe."""
        with self._mu:
            self._ping = ping

    def SetBackendPing(self, backend_id: BackendID, ping: Callable[[Backend], SwarmError | None] | None) -> None:
        """Install (or clear with None) a per-backend liveness probe."""
        with self._mu:
            if ping is None:
                self._backend_pings.pop(backend_id, None)
            else:
                self._backend_pings[backend_id] = ping

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

        err = self._ping_backend(b)

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
                    self._notify_callbacks(b.id, old_status, BackendStatus.StatusUnhealthy)
            else:
                check.consecutive_failures = 0
                if check.status != BackendStatus.StatusHealthy:
                    check.status = BackendStatus.StatusHealthy
                    b.status = BackendStatus.StatusHealthy
                    self._notify_callbacks(b.id, old_status, BackendStatus.StatusHealthy)

    def _ping_backend(self, backend: Backend | None = None) -> SwarmError | None:
        """Probe one backend's liveness.

        Resolution order: per-backend probe, global probe, then the
        default status-path probe. A cancelled monitor always fails.
        """
        if self._ctx.err() is not None:
            return SwarmError(self._ctx.err() or _CTX_CANCELED)
        if backend is None:
            return None
        with self._mu:
            probe = self._backend_pings.get(backend.id, self._ping)
        if probe is not None:
            return probe(backend)
        return self._default_ping(backend)

    @staticmethod
    def _default_ping(backend: Backend) -> SwarmError | None:
        """Default probe: fail backends that are stopping or stopped.

        This exercises the backend's own status path instead of sleeping
        and returning success unconditionally.
        """
        if backend.status in (BackendStatus.StatusStopping, BackendStatus.StatusStopped):
            return SwarmError(f"backend {backend.id} is {backend.status.string()}")
        return None

    def _notify_callbacks(
        self,
        backend_id: BackendID,
        old_status: BackendStatus,
        new_status: BackendStatus,
    ) -> None:
        for cb in list(self._callbacks):
            threading.Thread(target=cb, args=(backend_id, old_status, new_status), daemon=True).start()

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
    ping: Callable[[Backend], SwarmError | None] | None = None,
) -> HealthMonitor:
    """Create a new health monitor. Mirrors swarm.NewHealthMonitor()."""
    return HealthMonitor(registry, interval, timeout, failure_threshold, ping=ping)


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
