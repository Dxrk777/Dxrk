from __future__ import annotations

import sys
import threading
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Any

from dxrk.strconst import StrError


class Level(IntEnum):
    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3

    def __str__(self) -> str:
        if self is Level.DEBUG:
            return "DEBUG"
        if self is Level.INFO:
            return "INFO"
        if self is Level.WARN:
            return "WARN"
        if self is Level.ERROR:
            return "ERROR"
        return "UNKNOWN"


class Logger:
    def __init__(self, prefix: str, level: Level):
        self._mu = threading.Lock()
        self._level = level
        self._output: Any = sys.stderr
        self._prefix = prefix

    def set_level(self, level: Level) -> None:
        with self._mu:
            self._level = level

    def set_output(self, w: Any) -> None:
        with self._mu:
            self._output = w

    def debug(self, format: str, *args: Any) -> None:
        self._log(Level.DEBUG, format, args)

    def info(self, format: str, *args: Any) -> None:
        self._log(Level.INFO, format, args)

    def warn(self, format: str, *args: Any) -> None:
        self._log(Level.WARN, format, args)

    def error(self, format: str, *args: Any) -> None:
        self._log(Level.ERROR, format, args)

    def with_fields(self, fields: LogFields) -> Logger:
        parts = [f"{k}={v}" for k, v in fields.items()]
        suffix = " " + " ".join(parts)
        return new_logger(self._prefix + suffix, self._level)

    def _log(self, level: Level, format: str, args: tuple[Any, ...]) -> None:
        if level < self._level:
            return
        with self._mu:
            msg = (format % args) if args else format
            timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
            line = f"{timestamp} [{level}] [{self._prefix}] {msg}\n"
            self._output.write(line)
            if level >= Level.ERROR:
                sys.stderr.write(
                    f"{datetime.now().strftime('%Y/%m/%d %H:%M:%S')} {msg}\n"
                )


LogFields = dict[str, Any]


def new_logger(prefix: str, level: Level) -> Logger:
    return Logger(prefix, level)


def default_logger() -> Logger:
    return new_logger("dxrk", Level.INFO)


LOG = default_logger()


class Counter:
    def __init__(self, name: str):
        self._mu = threading.Lock()
        self._name = name
        self._count = 0

    def add(self, n: int) -> None:
        with self._mu:
            self._count += n

    def inc(self) -> None:
        self.add(1)

    def value(self) -> int:
        with self._mu:
            return self._count


class Gauge:
    def __init__(self, name: str):
        self._mu = threading.Lock()
        self._name = name
        self._value = 0.0

    def set(self, v: float) -> None:
        with self._mu:
            self._value = v

    def add(self, v: float) -> None:
        with self._mu:
            self._value += v

    def value(self) -> float:
        with self._mu:
            return self._value


class Histogram:
    def __init__(self, name: str, buckets: list[float], counts: list[int]):
        self._mu = threading.Lock()
        self._name = name
        self._buckets = buckets
        self._counts = counts
        self._total = 0
        self._sum = 0.0

    def observe(self, v: float) -> None:
        with self._mu:
            self._total += 1
            self._sum += v
            for i, b in enumerate(self._buckets):
                if v <= b:
                    self._counts[i] += 1
                    return
            self._counts[-1] += 1


DEFAULT_BUCKETS = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000]


class MetricsRegistry:
    def __init__(self):
        self._mu = threading.Lock()
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}

    def counter(self, name: str) -> Counter:
        with self._mu:
            if name in self._counters:
                return self._counters[name]
            c = Counter(name)
            self._counters[name] = c
            return c

    def gauge(self, name: str) -> Gauge:
        with self._mu:
            if name in self._gauges:
                return self._gauges[name]
            g = Gauge(name)
            self._gauges[name] = g
            return g

    def histogram(self, name: str, buckets: list[float] | None = None) -> Histogram:
        with self._mu:
            if name in self._histograms:
                return self._histograms[name]
            if buckets is None:
                buckets = list(DEFAULT_BUCKETS)
            h = Histogram(name, buckets, [0] * (len(buckets) + 1))
            self._histograms[name] = h
            return h

    def snapshot(self) -> MetricsSnapshot:
        with self._mu:
            counters = {n: c.value() for n, c in self._counters.items()}
            gauges = {n: g.value() for n, g in self._gauges.items()}
            histograms: dict[str, HistogramSnap] = {}
            for n, h in self._histograms.items():
                with h._mu:
                    histograms[n] = HistogramSnap(
                        buckets=list(h._buckets),
                        counts=list(h._counts),
                        total=h._total,
                        sum=h._sum,
                    )
            return MetricsSnapshot(counters, gauges, histograms)


def new_metrics_registry() -> MetricsRegistry:
    return MetricsRegistry()


@dataclass
class HistogramSnap:
    buckets: list[float]
    counts: list[int]
    total: int
    sum: float


@dataclass
class MetricsSnapshot:
    counters: dict[str, int] = field(default_factory=dict)
    gauges: dict[str, float] = field(default_factory=dict)
    histograms: dict[str, HistogramSnap] = field(default_factory=dict)

    def __str__(self) -> str:
        parts: list[str] = []
        for n, v in self.counters.items():
            parts.append(f"counter {n}: {v}")
        for n, g in self.gauges.items():
            parts.append(f"gauge {n}: {g:.2f}")
        for n, h in self.histograms.items():
            parts.append(f"histogram {n}: total={h.total} sum={h.sum:.2f}")
        return "\n".join(parts) + "\n"


global_metrics = new_metrics_registry()

metric_requests = global_metrics.counter("requests_total")
metric_errors = global_metrics.counter("errors_total")
metric_tokens_in = global_metrics.counter("tokens_input_total")
metric_tokens_out = global_metrics.counter("tokens_output_total")
metric_cost_total = global_metrics.gauge("cost_total")
metric_active_agents = global_metrics.gauge("active_agents")
metric_queue_depth = global_metrics.gauge("queue_depth")
metric_cache_hits = global_metrics.counter("cache_hits_total")
metric_cache_misses = global_metrics.counter("cache_misses_total")
metric_latency = global_metrics.histogram("latency_ms", None)
metric_rag_vectors = global_metrics.gauge("rag_vectors")
metric_iq_score = global_metrics.gauge("iq_score")


def latency_ms(d: timedelta) -> float:
    return float(d // timedelta(milliseconds=1))


@dataclass
class Attribute:
    key: str
    value: Any


CURRENT_SPAN: ContextVar[Span | None] = ContextVar("observe_current_span", default=None)


class Span:
    def __init__(self, name: str, attributes: list[Attribute] | None = None):
        self._name = name
        self._attributes: dict[str, Any] = {}
        self._events: list[tuple[str, list[Attribute]]] = []
        self._status = "UNSET"
        self._status_description = ""
        self._token: Token | None = None
        if attributes:
            for a in attributes:
                self._attributes[a.key] = a.value

    def end(self) -> None:
        if self._token is not None:
            CURRENT_SPAN.reset(self._token)
            self._token = None

    def set_attributes(self, *kv: Attribute) -> None:
        for a in kv:
            self._attributes[a.key] = a.value

    def record_error(self, err: Exception) -> None:
        self._events.append(("exception", [Attribute("exception.message", str(err))]))
        self._status = "ERROR"
        self._status_description = str(err)

    def set_status(self, status: str, description: str) -> None:
        self._status = status
        self._status_description = description

    def add_event(self, name: str, attrs: list[Attribute]) -> None:
        self._events.append((name, attrs))


class Tracer:
    def __init__(self, name: str):
        self._name = name

    def start(
        self, ctx: Any | None, name: str, *attrs: Attribute
    ) -> tuple[Any | None, Span]:
        span = Span(name, list(attrs))
        span._token = CURRENT_SPAN.set(span)
        return ctx, span


def new_tracer(name: str) -> Tracer:
    return Tracer(name)


def span_from_context(ctx: Any | None) -> Span:
    span = CURRENT_SPAN.get()
    if span is not None:
        return span
    return Span("", [])


def span_add_event(ctx: Any | None, name: str, *attrs: Attribute) -> None:
    span_from_context(ctx).add_event(name, list(attrs))


def span_record_duration(
    ctx: Any | None, name: str, start: datetime, *attrs: Attribute
) -> None:
    sp = span_from_context(ctx)
    duration_ms = int((datetime.now() - start) // timedelta(milliseconds=1))
    sp.add_event(name + ".done", list(attrs) + [Attribute("duration_ms", duration_ms)])


def err_attr(err: Exception) -> Attribute:
    return Attribute(StrError, str(err))


def int_attr(key: str, val: int) -> Attribute:
    return Attribute(key, val)


def str_attr(key: str, val: str) -> Attribute:
    return Attribute(key, val)


def bool_attr(key: str, val: bool) -> Attribute:
    return Attribute(key, val)


def str_slice_attr(key: str, val: list[str]) -> Attribute:
    return Attribute(key, list(val))


def format_provider_span_name(provider: str, model: str) -> str:
    return f"llm.{provider}.{model}"


def format_stage_span_name(pipeline: str, stage: str) -> str:
    return f"pipeline.{pipeline}.{stage}"
