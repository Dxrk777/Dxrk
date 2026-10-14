# SPDX-License-Identifier: MIT
"""Swarm backend registry."""

from __future__ import annotations

import threading

from dxrk.utils.swarm_events import EventBus
from dxrk.utils.swarm_model import (
    Backend,
    BackendCapabilities,
    BackendID,
    BackendStatus,
    DefaultSwarmConfig,
    ErrBackendNotFound,
    GenerateBackendID,
    SwarmConfig,
    SwarmError,
    SwarmEvent,
    SwarmEventType,
    _Context,
    _now,
)


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

    def register(
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

    # Backwards-compatible alias (Go-style name).
    Register = register

    def unregister(
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

    # Backwards-compatible alias (Go-style name).
    Unregister = unregister

    def get(self, backend_id: BackendID) -> tuple[Backend | None, SwarmError | None]:
        """Return a backend by ID. Mirrors BackendRegistry.Get()."""
        with self._mu:
            backend = self._backends.get(backend_id)
            if backend is None:
                return None, ErrBackendNotFound
            return backend, None

    # Backwards-compatible alias (Go-style name).
    Get = get

    def get_all(self) -> list[Backend]:
        """Return all registered backends. Mirrors BackendRegistry.GetAll()."""
        with self._mu:
            return list(self._backends.values())

    # Backwards-compatible alias (Go-style name).
    GetAll = get_all

    def get_healthy(self) -> list[Backend]:
        """Return backends with healthy or degraded status. Mirrors BackendRegistry.GetHealthy()."""
        with self._mu:
            return [
                b
                for b in self._backends.values()
                if b.status == BackendStatus.StatusHealthy
                or b.status == BackendStatus.StatusDegraded
            ]

    # Backwards-compatible alias (Go-style name).
    GetHealthy = get_healthy

    def get_by_capability(self, capability: str, min_amount: int) -> list[Backend]:
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

    # Backwards-compatible alias (Go-style name).
    GetByCapability = get_by_capability

    def update_heartbeat(self, backend_id: BackendID) -> SwarmError | None:
        """Update a backend's heartbeat. Mirrors BackendRegistry.UpdateHeartbeat()."""
        with self._mu:
            backend = self._backends.get(backend_id)
        if backend is None:
            return ErrBackendNotFound
        backend.UpdateHeartbeat()
        self._emit(SwarmEventType.EventBackendHeartbeat, backend_id, None)
        return None

    # Backwards-compatible alias (Go-style name).
    UpdateHeartbeat = update_heartbeat

    def update_status(
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

    # Backwards-compatible alias (Go-style name).
    UpdateStatus = update_status

    def update_capacity(self, backend_id: BackendID, capacity: int) -> SwarmError | None:
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

    # Backwards-compatible alias (Go-style name).
    UpdateCapacity = update_capacity

    def update_capabilities(
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

    # Backwards-compatible alias (Go-style name).
    UpdateCapabilities = update_capabilities

    def count(self) -> int:
        """Return the number of registered backends. Mirrors BackendRegistry.Count()."""
        with self._mu:
            return len(self._backends)

    # Backwards-compatible alias (Go-style name).
    Count = count

    def healthy_count(self) -> int:
        """Return the number of healthy backends. Mirrors BackendRegistry.HealthyCount()."""
        with self._mu:
            return sum(
                1
                for b in self._backends.values()
                if b.status == BackendStatus.StatusHealthy
                or b.status == BackendStatus.StatusDegraded
            )

    # Backwards-compatible alias (Go-style name).
    HealthyCount = healthy_count

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


def new_backend_registry(
    config: SwarmConfig | None, events: EventBus | None
) -> BackendRegistry:
    """Create a new backend registry. Mirrors swarm.NewBackendRegistry()."""
    return BackendRegistry(config, events)

# Backwards-compatible alias (Go-style name).
NewBackendRegistry = new_backend_registry
