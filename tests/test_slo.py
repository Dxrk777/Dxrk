import threading
from datetime import timedelta

import pytest

from dxrk.slo import (
    MultiWindowEvaluator,
    Objective,
    ObjectiveType,
    calculate_burn_rate,
    calculate_error_budget,
    default_window_config,
    new_tracker,
    time_to_budget_exhaustion,
    within_slo,
)


def test_register_objective():
    tracker = new_tracker()
    obj = Objective(
        name="test-latency",
        type=ObjectiveType.LATENCY,
        target=0.99,
        window=timedelta(minutes=5),
    )
    tracker.register_objective(obj)
    with pytest.raises(ValueError):
        tracker.register_objective(obj)


def test_update_objective():
    tracker = new_tracker()
    tracker.register_objective(
        Objective(
            name="test-avail",
            type=ObjectiveType.AVAILABILITY,
            target=0.999,
            window=timedelta(minutes=1),
            current=0.99,
        )
    )
    tracker.update_objective("test-avail", 0.995)
    updated = tracker.get_objective("test-avail")
    assert updated.current == 0.995
    assert abs(updated.error_budget - 0.005) < 1e-9
    with pytest.raises(ValueError):
        tracker.update_objective("nonexistent", 0.99)


def test_get_objective():
    tracker = new_tracker()
    tracker.register_objective(
        Objective(
            name="test-acc",
            type=ObjectiveType.ACCURACY,
            target=0.95,
            window=timedelta(hours=1),
        )
    )
    got = tracker.get_objective("test-acc")
    assert got.name == "test-acc"
    with pytest.raises(ValueError):
        tracker.get_objective("nonexistent")


def test_list_objectives():
    tracker = new_tracker()
    tracker.register_objective(
        Objective(name="obj1", type=ObjectiveType.LATENCY, target=0.99)
    )
    tracker.register_objective(
        Objective(name="obj2", type=ObjectiveType.AVAILABILITY, target=0.999)
    )
    tracker.register_objective(
        Objective(name="obj3", type=ObjectiveType.ACCURACY, target=0.95)
    )
    assert len(tracker.list_objectives()) == 3


def test_delete_objective():
    tracker = new_tracker()
    tracker.register_objective(Objective(name="delete-me", target=0.99))
    tracker.delete_objective("delete-me")
    with pytest.raises(ValueError):
        tracker.get_objective("delete-me")
    with pytest.raises(ValueError):
        tracker.delete_objective("already-gone")


def test_snapshot():
    tracker = new_tracker()
    tracker.register_objective(Objective(name="snap-test", target=0.99, current=0.985))
    snap = tracker.snapshot()
    assert snap.objective_name == "snap-test"
    assert snap.value == 0.985
    assert snap.within_slo is False


def test_snapshot_no_objectives():
    tracker = new_tracker()
    with pytest.raises(ValueError):
        tracker.snapshot()


def test_history():
    tracker = new_tracker()
    tracker.register_objective(Objective(name="hist-test", target=0.99, current=0.98))
    for i in range(5):
        tracker.update_objective("hist-test", 0.98 + float(i) * 0.005)
        tracker.snapshot()
    history = tracker.history("hist-test", 3)
    assert len(history) == 3
    for snap in history:
        assert snap.objective_name == "hist-test"
    history = tracker.history("hist-test", 100)
    assert len(history) == 5
    history = tracker.history("nonexistent", 10)
    assert len(history) == 0


def test_is_within_slo():
    tracker = new_tracker()
    tracker.register_objective(Objective(name="good", target=0.99, current=0.995))
    tracker.register_objective(Objective(name="bad", target=0.99, current=0.98))
    assert tracker.is_within_slo("good") is True
    assert tracker.is_within_slo("bad") is False
    with pytest.raises(ValueError):
        tracker.is_within_slo("nonexistent")


def test_calculate_error_budget():
    assert abs(calculate_error_budget(0.99, 0.985) - 0.015) < 1e-9
    assert abs(calculate_error_budget(0.99, 0.99) - 0.01) < 1e-9
    assert abs(calculate_error_budget(0.99, 1.0) - 0.0) < 1e-9


def test_calculate_burn_rate():
    rate = calculate_burn_rate(0.99, 0.98, timedelta(minutes=1))
    assert abs(rate - 0.01 / 60.0) < 1e-9
    rate = calculate_burn_rate(0.99, 0.99, timedelta(minutes=1))
    assert abs(rate - 0) < 1e-9
    rate = calculate_burn_rate(0.99, 0.98, timedelta(0))
    assert abs(rate - 0) < 1e-9


def test_time_to_budget_exhaustion():
    d = time_to_budget_exhaustion(0.01, 0.001)
    assert d == timedelta(seconds=10)
    assert time_to_budget_exhaustion(0.01, 0) == timedelta(0)
    assert time_to_budget_exhaustion(-0.01, 0.001) == timedelta(0)


def test_within_slo():
    assert within_slo(0.995, 0.99) is True
    assert within_slo(0.99, 0.99) is True
    assert within_slo(0.98, 0.99) is False


def test_multi_window_evaluator():
    eval_ = MultiWindowEvaluator()
    cfg = default_window_config()
    passed, msg = eval_.evaluate([0.995, 0.993, 0.991], cfg)
    assert passed, msg
    passed, msg = eval_.evaluate([0.85, 0.80, 0.90], cfg)
    assert not passed, msg
    cfg.short_target = 0.80
    cfg.long_target = 0.80
    passed, msg = eval_.evaluate([0.85, 0.83, 0.82], cfg)
    assert passed, msg


def test_multi_window_evaluator_empty():
    eval_ = MultiWindowEvaluator()
    passed, msg = eval_.evaluate([], default_window_config())
    assert not passed
    assert msg == "no values provided"


def test_tracker_concurrent_access():
    tracker = new_tracker()
    tracker.register_objective(
        Objective(
            name="concurrent", target=0.99, current=0.95, window=timedelta(minutes=1)
        )
    )

    def update():
        tracker.update_objective("concurrent", 0.95)

    def get():
        tracker.get_objective("concurrent")

    def snap():
        tracker.snapshot()

    def within():
        tracker.is_within_slo("concurrent")

    def list_():
        tracker.list_objectives()

    threads = []
    for _ in range(20):
        threads.append(threading.Thread(target=update))
    for _ in range(20):
        threads.append(threading.Thread(target=get))
    for _ in range(10):
        threads.append(threading.Thread(target=snap))
    for _ in range(10):
        threads.append(threading.Thread(target=within))
    for _ in range(10):
        threads.append(threading.Thread(target=list_))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert tracker.get_objective("concurrent").name == "concurrent"


def test_zero_burn_rate():
    tracker = new_tracker()
    tracker.register_objective(
        Objective(
            name="no-change", target=0.99, current=0.99, window=timedelta(minutes=1)
        )
    )
    tracker.update_objective("no-change", 0.99)
    obj = tracker.get_objective("no-change")
    assert obj.burn_rate == 0
    assert time_to_budget_exhaustion(0.01, 0) == timedelta(0)


def test_missing_objective():
    tracker = new_tracker()
    with pytest.raises(ValueError):
        tracker.get_objective("nonexistent")
    with pytest.raises(ValueError):
        tracker.is_within_slo("nonexistent")
    with pytest.raises(ValueError):
        tracker.update_objective("nonexistent", 0.99)
    with pytest.raises(ValueError):
        tracker.delete_objective("nonexistent")
