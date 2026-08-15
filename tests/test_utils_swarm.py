# SPDX-License-Identifier: MIT
"""Tests for dxrk.utils.swarm (mirrors internal/utils/swarm port)."""

from __future__ import annotations

import queue
import time
from datetime import timedelta

from dxrk.utils import swarm

_BG = swarm._background()


class TestBackendRegistry_Register:
    def test_register(self):
        reg = swarm.NewBackendRegistry(swarm.DefaultSwarmConfig(), None)

        backend = swarm.Backend(
            name="test-backend",
            address="localhost:8080",
            capacity=5,
            capabilities={"cpu": 4},
        )

        err = reg.Register(_BG, backend)
        assert err is None, err

        assert backend.id != ""
        assert backend.status == swarm.BackendStatus.StatusHealthy


class TestBackendRegistry_RegisterValidation:
    def test_validation_cases(self):
        reg = swarm.NewBackendRegistry(swarm.DefaultSwarmConfig(), None)

        cases = [
            (None, True),
            (swarm.Backend(capacity=1), True),
            (swarm.Backend(name="test", capacity=1), False),
        ]

        for backend, want_err in cases:
            err = reg.Register(_BG, backend)
            assert (err is not None) == want_err, (backend, err)


class TestBackendRegistry_Unregister:
    def test_unregister(self):
        reg = swarm.NewBackendRegistry(swarm.DefaultSwarmConfig(), None)

        backend = swarm.Backend(name="test", capacity=1)
        assert reg.Register(_BG, backend) is None

        err = reg.Unregister(_BG, backend.id)
        assert err is None, err

        _, err = reg.Get(backend.id)
        assert err is not None


class TestBackendRegistry_Get:
    def test_get(self):
        reg = swarm.NewBackendRegistry(swarm.DefaultSwarmConfig(), None)

        backend = swarm.Backend(name="test", capacity=1)
        assert reg.Register(_BG, backend) is None

        got, err = reg.Get(backend.id)
        assert err is None, err
        assert got is not None
        assert got.id == backend.id


class TestBackendRegistry_GetAll:
    def test_get_all(self):
        reg = swarm.NewBackendRegistry(swarm.DefaultSwarmConfig(), None)

        assert reg.Register(_BG, swarm.Backend(name="b1", capacity=1)) is None
        assert reg.Register(_BG, swarm.Backend(name="b2", capacity=1)) is None

        assert len(reg.GetAll()) == 2


class TestBackendRegistry_GetHealthy:
    def test_get_healthy(self):
        reg = swarm.NewBackendRegistry(swarm.DefaultSwarmConfig(), None)

        assert reg.Register(_BG, swarm.Backend(name="healthy", capacity=1)) is None
        b2 = swarm.Backend(name="unhealthy", capacity=1)
        assert reg.Register(_BG, b2) is None
        b2.SetStatus(swarm.BackendStatus.StatusUnhealthy)

        healthy = reg.GetHealthy()
        assert len(healthy) == 1
        assert healthy[0].name == "healthy"


class TestBackendRegistry_UpdateStatus:
    def test_update_status(self):
        reg = swarm.NewBackendRegistry(swarm.DefaultSwarmConfig(), None)

        backend = swarm.Backend(name="test", capacity=1)
        assert reg.Register(_BG, backend) is None

        err = reg.UpdateStatus(backend.id, swarm.BackendStatus.StatusDegraded)
        assert err is None, err

        got, _ = reg.Get(backend.id)
        assert got is not None
        assert got.status == swarm.BackendStatus.StatusDegraded


class TestBackendRegistry_Count:
    def test_count(self):
        reg = swarm.NewBackendRegistry(swarm.DefaultSwarmConfig(), None)

        assert reg.Count() == 0

        assert reg.Register(_BG, swarm.Backend(name="b1", capacity=1)) is None
        assert reg.Count() == 1


class TestBackendRegistry_MaxBackends:
    def test_max_backends(self):
        config = swarm.DefaultSwarmConfig()
        config.max_backends = 1
        reg = swarm.NewBackendRegistry(config, None)

        assert reg.Register(_BG, swarm.Backend(name="b1", capacity=1)) is None
        err = reg.Register(_BG, swarm.Backend(name="b2", capacity=1))
        assert err is not None


class TestBackend_CanHandle:
    def test_can_handle(self):
        backend = swarm.Backend(
            id="test",
            capacity=2,
            load=0,
            status=swarm.BackendStatus.StatusHealthy,
            capabilities={"cpu": 4, "memory": 8},
        )

        task = swarm.Task(required_capabilities={"cpu": 2})
        assert backend.CanHandle(task)

        task.required_capabilities = {"cpu": 8}
        assert not backend.CanHandle(task)

        backend.SetStatus(swarm.BackendStatus.StatusUnhealthy)
        task.required_capabilities = {"cpu": 2}
        assert not backend.CanHandle(task)


class TestBackend_AvailableCapacity:
    def test_available_capacity(self):
        backend = swarm.Backend(capacity=10, load=3)
        assert backend.AvailableCapacity() == 7


class TestBackend_IncrementDecrementLoad:
    def test_increment_decrement_load(self):
        backend = swarm.Backend(capacity=2, load=0)

        ok = backend.IncrementLoad()
        assert ok and backend.load == 1

        ok = backend.IncrementLoad()
        assert ok and backend.load == 2

        ok = backend.IncrementLoad()
        assert not ok

        backend.DecrementLoad()
        assert backend.load == 1


class TestTask_Assign:
    def test_assign(self):
        task = swarm.Task(id="task-1")

        task.Assign("backend-1")
        assert task.assigned_backend == "backend-1"
        assert task.started_at != swarm._ZERO_TIME


class TestTask_CanRetry:
    def test_can_retry(self):
        task = swarm.Task(max_retries=3, retries=0)
        assert task.CanRetry()

        task.retries = 3
        assert not task.CanRetry()


class TestTask_IncrementRetry:
    def test_increment_retry(self):
        task = swarm.Task(assigned_backend="b1", retries=0)
        task.IncrementRetry()

        assert task.retries == 1
        assert task.assigned_backend == ""
        assert task.started_at == swarm._ZERO_TIME


class TestBackendStatus_String:
    def test_string(self):
        cases = [
            (swarm.BackendStatus.StatusUnknown, "unknown"),
            (swarm.BackendStatus.StatusStarting, "starting"),
            (swarm.BackendStatus.StatusHealthy, "healthy"),
            (swarm.BackendStatus.StatusDegraded, "degraded"),
            (swarm.BackendStatus.StatusUnhealthy, "unhealthy"),
            (swarm.BackendStatus.StatusStopping, "stopping"),
            (swarm.BackendStatus.StatusStopped, "stopped"),
        ]

        for status, expect in cases:
            assert status.string() == expect, status


class TestSwarmEventType_String:
    def test_string(self):
        assert swarm.SwarmEventType.EventBackendRegistered.string() == "backend_registered"
        assert swarm.SwarmEventType.EventLeaderElected.string() == "leader_elected"


class TestDefaultSwarmConfig:
    def test_default_config(self):
        config = swarm.DefaultSwarmConfig()
        assert config.heartbeat_interval > timedelta(0)
        assert config.task_timeout > timedelta(0)
        assert config.max_retries >= 0


class TestSwarmConfig_Validate:
    def test_validate(self):
        cases = [
            ("valid", swarm.DefaultSwarmConfig(), False),
            (
                "zero heartbeat",
                swarm.SwarmConfig(heartbeat_interval=timedelta(0)),
                True,
            ),
            (
                "negative timeout",
                swarm.SwarmConfig(task_timeout=timedelta(seconds=-1)),
                True,
            ),
            (
                "invalid backends",
                swarm.SwarmConfig(min_backends=5, max_backends=1),
                True,
            ),
        ]

        for name, config, want_err in cases:
            err = config.Validate()
            assert (err is not None) == want_err, name


class TestTaskScheduler:
    def test_scheduler(self):
        reg = swarm.NewBackendRegistry(swarm.DefaultSwarmConfig(), None)

        assert reg.Register(_BG, swarm.Backend(name="worker1", capacity=5)) is None
        assert reg.Register(_BG, swarm.Backend(name="worker2", capacity=5)) is None

        scheduler = swarm.NewTaskScheduler(
            reg,
            swarm.SchedulerConfig(
                max_concurrent_tasks=2,
                queue_size=10,
                task_timeout=timedelta(seconds=1),
            ),
        )
        scheduler.Start()

        task = swarm.Task(type="test", required_capabilities={"cpu": 1})

        err = scheduler.Submit(task)
        assert err is None, err

        try:
            result = scheduler.Results().get(timeout=2)
        except queue.Empty:
            raise AssertionError("Timeout waiting for result")
        finally:
            scheduler.Stop()

        assert result.task_id == task.id


class TestLeaderElection:
    def test_leader_election(self):
        reg = swarm.NewBackendRegistry(swarm.DefaultSwarmConfig(), None)

        assert reg.Register(_BG, swarm.Backend(name="leader1", capacity=5)) is None
        assert reg.Register(_BG, swarm.Backend(name="leader2", capacity=5)) is None

        events = swarm.NewEventBus(_BG)
        events.Start()

        config = swarm.DefaultSwarmConfig()
        config.leader_election_enabled = True
        config.lease_duration = timedelta(milliseconds=100)

        election = swarm.NewLeaderElection(config, reg, events)
        election.Start()

        try:
            time.sleep(0.2)

            leader, err = election.GetLeader()
            assert err is None, err
            assert leader is not None
        finally:
            election.Stop()
            events.Stop()


class TestEventBus:
    def test_event_bus(self):
        bus = swarm.NewEventBus(_BG)
        bus.Start()

        received = queue.Queue(maxsize=10)
        unsub = bus.Subscribe(swarm.SwarmEventType.EventBackendRegistered, received.put)

        try:
            bus.Publish(
                swarm.SwarmEvent(
                    type=swarm.SwarmEventType.EventBackendRegistered,
                    backend_id="test-backend",
                    timestamp=swarm._now(),
                )
            )

            try:
                e = received.get(timeout=1)
            except queue.Empty:
                raise AssertionError("Timeout waiting for event")

            assert e.backend_id == "test-backend"
        finally:
            unsub()
            bus.Stop()


class TestEventBus_SubscribeAll:
    def test_subscribe_all(self):
        bus = swarm.NewEventBus(_BG)
        bus.Start()

        received = queue.Queue(maxsize=10)
        bus.Subscribe(swarm.SwarmEventType.EventBackendRegistered, lambda e: None)
        bus.Subscribe(swarm.SwarmEventType.EventTaskCompleted, lambda e: None)
        unsub = bus.SubscribeAll(received.put)

        try:
            bus.Publish(
                swarm.SwarmEvent(type=swarm.SwarmEventType.EventBackendRegistered, backend_id="b1")
            )
            bus.Publish(
                swarm.SwarmEvent(type=swarm.SwarmEventType.EventTaskCompleted, backend_id="b2")
            )

            seen = set()
            deadline = time.monotonic() + 1
            while len(seen) < 2:
                if time.monotonic() >= deadline:
                    raise AssertionError(
                        "Timeout waiting for events, seen: %s" % sorted(seen)
                    )
                try:
                    e = received.get(timeout=0.2)
                except queue.Empty:
                    continue
                seen.add(e.backend_id)

            assert seen == {"b1", "b2"}
        finally:
            unsub()
            bus.Stop()


class TestHealthMonitor:
    def test_health_monitor(self):
        reg = swarm.NewBackendRegistry(swarm.DefaultSwarmConfig(), None)

        backend = swarm.Backend(name="test", capacity=1)
        assert reg.Register(_BG, backend) is None

        monitor = swarm.NewHealthMonitor(
            reg,
            timedelta(milliseconds=50),
            timedelta(milliseconds=10),
            2,
        )
        monitor.Start()

        try:
            time.sleep(0.15)

            status, _, failures = monitor.GetHealth(backend.id)
            assert status == swarm.BackendStatus.StatusHealthy
            assert failures == 0
        finally:
            monitor.Stop()


class TestSwarmCoordinator:
    def test_coordinator(self):
        reg = swarm.NewBackendRegistry(swarm.DefaultSwarmConfig(), None)

        assert reg.Register(_BG, swarm.Backend(name="worker1", capacity=5)) is None

        coord = swarm.NewSwarmCoordinator(
            reg,
            swarm.CoordinatorConfig(
                election_timeout=timedelta(milliseconds=100),
                heartbeat_interval=timedelta(milliseconds=50),
                enable_work_stealing=True,
            ),
        )
        coord.Start()

        try:
            time.sleep(0.2)

            backends = coord.GetBackends()
            assert len(backends) == 1

            stats = coord.Stats()
            assert stats.backend_count == 1
        finally:
            coord.Stop()


class TestGenerateIDs:
    def test_generate_ids(self):
        task_id = swarm.GenerateTaskID()
        assert len(task_id) >= 10, task_id

        backend_id = swarm.GenerateBackendID()
        assert len(backend_id) >= 10, backend_id


class TestBackend_MarshalJSON:
    def test_marshal_json(self):
        backend = swarm.Backend(
            id="test",
            name="test-backend",
            status=swarm.BackendStatus.StatusHealthy,
            capacity=5,
        )

        data = backend.MarshalJSON()
        assert data
