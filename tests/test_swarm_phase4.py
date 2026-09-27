# SPDX-License-Identifier: MIT
"""Phase 4 (swarm honesty + session linkage) failing-first tests."""

from __future__ import annotations

import queue
import threading
import time
from datetime import timedelta

from dxrk.autonomy import AgentRole, NewSwarmOrchestrator, SwarmResult, SwarmTask
from dxrk.utils import swarm as W


def _reg():
    return W.NewBackendRegistry(W.DefaultSwarmConfig(), None)


# ─── Stack C ───


def test_c_empty_consensus_explicit_empty_verdict():
    orch = NewSwarmOrchestrator()
    passed, ratio, summary = orch.consensus_check([])
    assert passed is False
    assert ratio == 0.0
    assert "empty" in summary.lower()


def test_c_execute_swarm_preserves_input_order():
    orch = NewSwarmOrchestrator(max_workers=4)

    def handler(task: SwarmTask) -> SwarmResult:
        if task.task_id == "slow":
            time.sleep(0.15)
        return SwarmResult(task_id=task.task_id, role=task.role, success=True, output=task.task_id)

    for role in AgentRole:
        orch.register_agent(role, handler)
    tasks = [
        SwarmTask("slow", "S", AgentRole.CODER),
        SwarmTask("fast1", "F1", AgentRole.CODER),
        SwarmTask("fast2", "F2", AgentRole.CODER),
    ]
    results = orch.execute_swarm(tasks)
    assert [r.task_id for r in results] == ["slow", "fast1", "fast2"]


def test_c_execute_swarm_timeout():
    orch = NewSwarmOrchestrator(max_workers=2)

    def handler(task: SwarmTask) -> SwarmResult:
        time.sleep(0.3)
        return SwarmResult(task_id=task.task_id, role=task.role, success=True, output="late")

    orch.register_agent(AgentRole.CODER, handler)
    results = orch.execute_swarm([SwarmTask("t1", "T", AgentRole.CODER)], timeout=0.05)
    assert len(results) == 1
    assert results[0].success is False
    assert "timed out" in " ".join(results[0].errors).lower()


def test_c_consensus_threshold_configurable():
    orch = NewSwarmOrchestrator(consensus_threshold=0.5)
    assert orch.consensus_threshold == 0.5
    res = [
        SwarmResult(task_id="a", role=AgentRole.CODER, success=True, output="x"),
        SwarmResult(task_id="b", role=AgentRole.CODER, success=False, output=""),
    ]
    passed, ratio, _ = orch.consensus_check(res)
    assert ratio == 0.5
    assert passed is True


# ─── Stack D dispatch ───


def test_d_dispatch_e2e_real_payload():
    reg = _reg()
    assert reg.Register(None, W.Backend(name="w1", capacity=5)) is None
    sch = W.NewTaskScheduler(
        reg, W.SchedulerConfig(max_concurrent_tasks=2, queue_size=10, task_timeout=timedelta(seconds=5))
    )
    sch.RegisterHandler(lambda task: (task.payload or b"") + b":done")
    sch.Start()
    try:
        tasks = []
        for i in range(3):
            t = W.Task(id=f"e2e-{i}", type="work", payload=f"p{i}".encode())
            assert sch.Submit(t) is None
            tasks.append(t)
        got = {}
        deadline = time.monotonic() + 5
        while len(got) < 3 and time.monotonic() < deadline:
            try:
                r = sch.Results().get(timeout=0.2)
            except queue.Empty:
                continue
            got[r.task_id] = r
        assert len(got) == 3, got
        for i in range(3):
            r = got[f"e2e-{i}"]
            assert r.output == f"p{i}:done".encode(), r
            assert r.backend_id != "", r
            assert r.metrics.get("error", 0.0) == 0.0
    finally:
        sch.Stop()


def test_d_dispatch_task_timeout():
    reg = _reg()
    assert reg.Register(None, W.Backend(name="w1", capacity=5)) is None
    sch = W.NewTaskScheduler(
        reg,
        W.SchedulerConfig(
            max_concurrent_tasks=1,
            queue_size=10,
            task_timeout=timedelta(milliseconds=100),
            retry_attempts=0,
        ),
    )

    def slow(task):
        time.sleep(2)
        return b"late"

    sch.RegisterHandler(slow)
    sch.Start()
    try:
        t = W.Task(id="to-1", payload=b"x")
        assert sch.Submit(t) is None
        r = sch.Results().get(timeout=5)
        assert r.task_id == "to-1"
        assert r.metrics.get("timeout", 0.0) == 1.0 or "deadline" in t.error.lower()
    finally:
        sch.Stop()


# ─── EventBus ───


def test_d_eventbus_single_dispatch():
    bus = W.NewEventBus(None)
    bus.Start()
    try:
        calls: list[str] = []
        lock = threading.Lock()

        def typed(e):
            with lock:
                calls.append("typed")

        def allh(e):
            with lock:
                calls.append("all")

        bus.Subscribe(W.SwarmEventType.EventBackendRegistered, typed)
        bus.SubscribeAll(allh)
        bus.Publish(W.SwarmEvent(type=W.SwarmEventType.EventBackendRegistered, backend_id="b"))
        deadline = time.monotonic() + 2
        while True:
            with lock:
                if len(calls) >= 2:
                    break
            if time.monotonic() > deadline:
                break
            time.sleep(0.02)
        with lock:
            assert sorted(calls) == ["all", "typed"], calls
    finally:
        bus.Stop()


def test_d_eventbus_subscribe_all_sees_later_types():
    bus = W.NewEventBus(None)
    bus.Start()
    try:
        seen: queue.Queue[str] = queue.Queue()
        bus.SubscribeAll(lambda e: seen.put(e.backend_id))
        bus.Publish(W.SwarmEvent(type=W.SwarmEventType.EventWorkStolen, backend_id="later"))
        assert seen.get(timeout=2) == "later"
    finally:
        bus.Stop()


def test_d_eventbus_drop_counter():
    bus = W.NewEventBus(None)
    assert bus.DroppedCount() == 0
    bus._event_ch = queue.Queue(maxsize=1)
    bus._event_ch.put_nowait(W.SwarmEvent(type=W.SwarmEventType.EventBackendRegistered))
    bus.Publish(W.SwarmEvent(type=W.SwarmEventType.EventBackendRegistered))
    assert bus.DroppedCount() == 1


def test_d_eventbus_unsubscribe_concurrent():
    bus = W.NewEventBus(None)
    fired: list[int] = []
    lock = threading.Lock()

    def h(e):
        with lock:
            fired.append(1)

    unsubs = [bus.Subscribe(W.SwarmEventType.EventBackendRegistered, h) for _ in range(5)]
    for u in unsubs:
        u()
    assert bus.Len() == 0
    bus._dispatch(W.SwarmEvent(type=W.SwarmEventType.EventBackendRegistered))
    assert fired == []


# ─── Health ───


def test_d_health_pluggable_ping_unhealthy_reachable():
    reg = _reg()
    b = W.Backend(name="h", capacity=1)
    assert reg.Register(None, b) is None
    mon = W.NewHealthMonitor(reg, timedelta(seconds=10), timedelta(seconds=5), 2)
    mon.SetPing(lambda backend: W.SwarmError("down"))
    mon._check_backend(b)
    assert mon._checks[b.id].consecutive_failures == 1
    mon._check_backend(b)
    status, _, failures = mon.GetHealth(b.id)
    assert status == W.BackendStatus.StatusUnhealthy
    assert failures == 2
    mon.Stop()


def test_d_health_default_ping_unhealthy_via_status_path():
    reg = _reg()
    b = W.Backend(name="h2", capacity=1)
    assert reg.Register(None, b) is None
    mon = W.NewHealthMonitor(reg, timedelta(seconds=10), timedelta(seconds=5), 1)
    # default probe exercises the backend's own status path: stopping fails
    b.SetStatus(W.BackendStatus.StatusStopping)
    mon._check_backend(b)
    status, _, failures = mon.GetHealth(b.id)
    assert status == W.BackendStatus.StatusUnhealthy, (status, failures)
    assert failures >= 1
    mon.Stop()


# ─── Coordinator ───


def _mk_coord(**kw):
    reg = _reg()
    assert reg.Register(None, W.Backend(name="w1", capacity=5)) is None
    cfg = W.CoordinatorConfig(
        election_timeout=timedelta(milliseconds=100),
        heartbeat_interval=timedelta(milliseconds=50),
        task_timeout=timedelta(seconds=5),
        max_retries=kw.pop("max_retries", 2),
    )
    for k, v in kw.items():
        setattr(cfg, k, v)
    coord = W.NewSwarmCoordinator(reg, cfg)
    return reg, coord


def test_d_coordinator_get_task_result_real():
    reg, coord = _mk_coord()
    coord._scheduler.RegisterHandler(lambda task: b"ok:" + (task.payload or b""))
    coord.Start()
    try:
        t = W.Task(id="cr-1", payload=b"hi")
        assert coord.SubmitTask(t) is None
        result, err = None, None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result, err = coord.GetTaskResult(None, "cr-1")
            if result is not None:
                break
            time.sleep(0.05)
        assert err is None, err
        assert result is not None
        assert result.output == b"ok:hi"
        missing, merr = coord.GetTaskResult(None, "nope")
        assert missing is None and merr is not None
    finally:
        coord.Stop()


def test_d_coordinator_unsubscribe_real():
    _, coord = _mk_coord()
    fired: list[int] = []
    h = lambda e: fired.append(1)  # noqa: E731
    coord.Subscribe(W.SwarmEventType.EventBackendRegistered, h)
    coord.Unsubscribe(W.SwarmEventType.EventBackendRegistered, h)
    coord._event_bus._dispatch(W.SwarmEvent(type=W.SwarmEventType.EventBackendRegistered))
    assert fired == []
    coord.Stop()


def test_d_coordinator_reschedule_bounded_retries():
    reg = _reg()
    bad = W.Backend(name="bad", capacity=5)
    assert reg.Register(None, bad) is None
    coord = W.NewSwarmCoordinator(
        reg,
        W.CoordinatorConfig(
            election_timeout=timedelta(milliseconds=100),
            heartbeat_interval=timedelta(milliseconds=50),
            task_timeout=timedelta(seconds=2),
            max_retries=2,
        ),
    )
    t = W.Task(id="rs-1", assigned_backend=bad.id, max_retries=2, retries=0)
    coord._tasks[t.id] = t
    submitted: list[str] = []
    orig_submit = coord._scheduler.Submit
    coord._scheduler.Submit = lambda task: (submitted.append(task.id), None)[1]  # type: ignore[assignment]
    try:
        coord._reschedule_tasks(bad.id)
        assert t.retries == 1
        assert submitted == ["rs-1"]
        t.retries = 5  # exhausted
        coord._reschedule_tasks(bad.id)
        assert submitted == ["rs-1"]  # no further resubmit
    finally:
        coord._scheduler.Submit = orig_submit  # type: ignore[assignment]
        coord.Stop()


def test_d_coordinator_stop_no_thread_leak():
    _, coord = _mk_coord()
    coord.Start()
    time.sleep(0.15)
    coord.Stop()
    assert coord._thread is None or not coord._thread.is_alive()


def test_d_coordinator_leader_propagates():
    _, coord = _mk_coord()
    coord.Start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if coord.IsLeader():
                break
            time.sleep(0.05)
        assert coord.IsLeader() is True
        assert coord.LeaderID() != ""
    finally:
        coord.Stop()


# ─── Session linkage ───


def test_d_task_session_id_persisted(tmp_path):
    store = W.NewSwarmTaskStore(str(tmp_path / "swarm.db"))
    try:
        t = W.Task(id="s-1", type="work", payload=b"abc", session_id="sess-1")
        store.RecordTask(t)
        res = W.TaskResult(task_id="s-1", backend_id="b1", output=b"done", session_id="sess-1")
        store.RecordResult(res)
        assert store.GetResult("s-1") is not None
        assert store.GetResult("s-1").output == b"done"  # type: ignore[union-attr]
        assert [r.task_id for r in store.ListSession("sess-1")] == ["s-1"]
        text = store.SessionSummaryText("sess-1")
        assert "sess-1" in text
        assert store.SessionSummary("sess-1")["completed"] == 1
    finally:
        store.Close()


def test_d_coordinator_session_summary(tmp_path):
    reg = _reg()
    assert reg.Register(None, W.Backend(name="w1", capacity=5)) is None
    store = W.NewSwarmTaskStore(str(tmp_path / "c.db"))
    try:
        coord = W.NewSwarmCoordinator(
            reg,
            W.CoordinatorConfig(
                election_timeout=timedelta(milliseconds=100),
                heartbeat_interval=timedelta(milliseconds=50),
                task_timeout=timedelta(seconds=5),
            ),
            result_store=store,
        )
        coord._scheduler.RegisterHandler(lambda task: b"r")
        coord.Start()
        try:
            t = W.Task(id="cs-1", payload=b"x", session_id="sess-9")
            assert coord.SubmitTask(t) is None
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if coord.SessionSummary("sess-9")["completed"] >= 1:
                    break
                time.sleep(0.05)
            assert coord.SessionSummary("sess-9")["completed"] == 1
        finally:
            coord.Stop()
    finally:
        store.Close()


def test_d_task_result_timestamps_survive_reopen(tmp_path):
    from datetime import UTC, datetime

    fixed = datetime(2024, 5, 1, 12, 0, 0, tzinfo=UTC)
    db = str(tmp_path / "ts.db")
    store = W.NewSwarmTaskStore(db)
    try:
        t = W.Task(id="ts-1", type="work", payload=b"abc", session_id="sess-ts")
        store.RecordTask(t)
        res = W.TaskResult(
            task_id="ts-1",
            backend_id="b1",
            output=b"done",
            session_id="sess-ts",
            duration=timedelta(seconds=2),
            timestamp=fixed,
        )
        store.RecordResult(res)
    finally:
        store.Close()
    reopened = W.NewSwarmTaskStore(db)
    try:
        got = reopened.GetResult("ts-1")
        assert got is not None
        assert got.timestamp == fixed
        listed = reopened.ListSession("sess-ts")
        assert [r.task_id for r in listed] == ["ts-1"]
        assert listed[0].timestamp == fixed
        assert listed[0].duration == timedelta(seconds=2)
    finally:
        reopened.Close()
