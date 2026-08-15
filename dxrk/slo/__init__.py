from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Any


class ObjectiveType(IntEnum):
    LATENCY = 0
    AVAILABILITY = 1
    ACCURACY = 2
    THROUGHPUT = 3


@dataclass
class Objective:
    name: str
    type: ObjectiveType = ObjectiveType.LATENCY
    target: float = 0.0
    window: timedelta = timedelta(0)
    current: float = 0.0
    error_budget: float = 0.0
    burn_rate: float = 0.0
    updated_at: datetime | None = None


@dataclass
class WindowSnapshot:
    timestamp: datetime
    objective_name: str
    value: float
    error_budget: float
    within_slo: bool


def calculate_error_budget(target: float, current: float) -> float:
    return 1 - current


def calculate_burn_rate(current: float, previous: float, window: timedelta) -> float:
    if window <= timedelta(0):
        return 0
    delta = current - previous
    secs = window.total_seconds()
    if secs <= 0:
        return 0
    return delta / secs


def time_to_budget_exhaustion(error_budget: float, burn_rate: float) -> timedelta:
    if burn_rate <= 0:
        return timedelta(0)
    secs = error_budget / burn_rate
    if secs < 0:
        return timedelta(0)
    return timedelta(seconds=secs)


def within_slo(current: float, target: float) -> bool:
    return current >= target


class Tracker:
    def __init__(self) -> None:
        self._mu = threading.RLock()
        self._objectives: dict[str, Objective] = {}
        self._history: list[WindowSnapshot] = []

    def register_objective(self, obj: Objective) -> None:
        with self._mu:
            if obj.name in self._objectives:
                raise ValueError(f'objective "{obj.name}" already exists')
            entry = replace(
                obj,
                error_budget=calculate_error_budget(obj.target, obj.current),
                burn_rate=0,
                updated_at=datetime.now(),
            )
            self._objectives[obj.name] = entry

    def update_objective(self, name: str, value: float) -> None:
        with self._mu:
            obj = self._objectives.get(name)
            if obj is None:
                raise ValueError(f'objective "{name}" not found')
            prev = obj.current
            obj.current = value
            obj.error_budget = calculate_error_budget(obj.target, obj.current)
            obj.updated_at = datetime.now()
            if obj.window > timedelta(0):
                obj.burn_rate = calculate_burn_rate(obj.current, prev, obj.window)

    def get_objective(self, name: str) -> Objective:
        with self._mu:
            obj = self._objectives.get(name)
            if obj is None:
                raise ValueError(f'objective "{name}" not found')
            return copy.copy(obj)

    def list_objectives(self) -> list[Objective]:
        with self._mu:
            return [copy.copy(o) for o in self._objectives.values()]

    def delete_objective(self, name: str) -> None:
        with self._mu:
            if name not in self._objectives:
                raise ValueError(f'objective "{name}" not found')
            del self._objectives[name]

    def snapshot(self, ctx: Any = None) -> WindowSnapshot:
        with self._mu:
            if not self._objectives:
                raise ValueError("no objectives registered")
            first = next(iter(self._objectives))
            obj = self._objectives[first]
            snap = WindowSnapshot(
                timestamp=datetime.now(),
                objective_name=obj.name,
                value=obj.current,
                error_budget=obj.error_budget,
                within_slo=within_slo(obj.current, obj.target),
            )
            self._history.append(snap)
            if ctx is not None and hasattr(ctx, "done") and ctx.done():
                raise RuntimeError("context canceled")
            return snap

    def history(self, name: str, limit: int) -> list[WindowSnapshot]:
        with self._mu:
            filtered = [s for s in self._history if s.objective_name == name]
            if len(filtered) > limit:
                filtered = filtered[len(filtered) - limit :]
            return filtered

    def is_within_slo(self, name: str) -> bool:
        with self._mu:
            obj = self._objectives.get(name)
            if obj is None:
                raise ValueError(f'objective "{name}" not found')
            return within_slo(obj.current, obj.target)


def new_tracker() -> Tracker:
    return Tracker()


@dataclass
class WindowConfig:
    short_window: timedelta = timedelta(minutes=5)
    long_window: timedelta = timedelta(minutes=30)
    short_target: float = 0.99
    long_target: float = 0.99


def default_window_config() -> WindowConfig:
    return WindowConfig()


class MultiWindowEvaluator:
    def evaluate(self, values: list[float], config: WindowConfig) -> tuple[bool, str]:
        if not values:
            return False, "no values provided"
        mean = sum(values) / float(len(values))
        pass_short = mean >= config.short_target
        pass_long = mean >= config.long_target
        if not pass_short and not pass_long:
            return (
                False,
                f"both windows failed: short={mean:.4f} (target {config.short_target:.4f}), "
                f"long={mean:.4f} (target {config.long_target:.4f})",
            )
        if not pass_short:
            return (
                False,
                f"short window failed: {mean:.4f} (target {config.short_target:.4f})",
            )
        if not pass_long:
            return (
                False,
                f"long window failed: {mean:.4f} (target {config.long_target:.4f})",
            )
        return True, f"all windows passed: mean={mean:.4f}"
