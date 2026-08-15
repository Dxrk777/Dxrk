from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum


class State(IntEnum):
    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


class CircuitOpenError(RuntimeError):
    pass


ERR_CIRCUIT_OPEN = CircuitOpenError("circuit breaker: open")


@dataclass
class RetryConfig:
    max_attempts: int = 3
    initial_delay: timedelta = timedelta(milliseconds=100)
    max_delay: timedelta = timedelta(seconds=5)
    backoff_factor: float = 2.0
    jitter: bool = False


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    success_threshold: int = 3
    timeout: timedelta = timedelta(seconds=30)


@dataclass
class RateLimiterConfig:
    max_tokens: int = 10
    refill_interval: timedelta = timedelta(seconds=1)
    refill_amount: float = 10.0


@dataclass
class Options:
    retry: RetryConfig
    cb: CircuitBreakerConfig
    rate_limit: RateLimiterConfig


def new_retry_config() -> RetryConfig:
    return RetryConfig()


def backoff_duration(attempt: int, config: RetryConfig) -> timedelta:
    initial_us = config.initial_delay / timedelta(microseconds=1)
    delay_us = initial_us * (config.backoff_factor ** (attempt - 1))
    max_us = config.max_delay / timedelta(microseconds=1)
    if delay_us > max_us:
        delay_us = max_us
    if config.jitter:
        delay_us *= 0.5 + random.random() * 0.5
    return timedelta(microseconds=delay_us)


def do(ctx, fn, config: RetryConfig):
    last_err = None
    for attempt in range(config.max_attempts):
        if attempt > 0:
            if ctx is not None and hasattr(ctx, "done") and ctx.done():
                raise RuntimeError("context canceled")
            delay = backoff_duration(attempt, config)
            time.sleep(delay.total_seconds())
        err = fn(ctx)
        if err is not None:
            last_err = err
            continue
        return None
    return last_err


class RateLimiter:
    def __init__(self, config: RateLimiterConfig):
        self._mu = threading.Lock()
        self._tokens = float(config.max_tokens)
        self._max_tokens = float(config.max_tokens)
        self._refill_amount = config.refill_amount
        self._refill_interval = config.refill_interval
        self._stop = threading.Event()
        self._closed = False
        t = threading.Thread(target=self._refill_loop, daemon=True)
        t.start()

    def _refill_loop(self):
        while not self._stop.wait(self._refill_interval.total_seconds()):
            with self._mu:
                self._tokens = min(self._tokens + self._refill_amount, self._max_tokens)

    def allow(self) -> bool:
        with self._mu:
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            return False

    def wait(self, ctx=None):
        while True:
            if self.allow():
                return None
            if ctx is not None and hasattr(ctx, "done") and ctx.done():
                raise RuntimeError("context canceled")
            time.sleep(0.1)

    def close(self):
        with self._mu:
            if self._closed:
                return
            self._closed = True
            self._stop.set()


def new_rate_limiter() -> RateLimiter:
    return RateLimiter(RateLimiterConfig())


def new_rate_limiter_with_config(config: RateLimiterConfig) -> RateLimiter:
    return RateLimiter(config)


class CircuitBreaker:
    def __init__(self, config: CircuitBreakerConfig):
        self._mu = threading.Lock()
        self._state = State.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._failure_threshold = config.failure_threshold
        self._success_threshold = config.success_threshold
        self._timeout = config.timeout
        self._last_failure: datetime | None = None

    def call(self, ctx, fn):
        self._allow_request()
        err = fn(ctx)
        self._record_result(err)
        return err

    def _allow_request(self):
        with self._mu:
            if self._state == State.OPEN:
                if (
                    self._last_failure is not None
                    and datetime.now() - self._last_failure >= self._timeout
                ):
                    self._state = State.HALF_OPEN
                    return
                raise ERR_CIRCUIT_OPEN

    def _record_result(self, err):
        with self._mu:
            if err is not None:
                self._on_failure()
            else:
                self._on_success()

    def _on_failure(self):
        if self._state == State.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._state = State.OPEN
                self._last_failure = datetime.now()
        elif self._state == State.HALF_OPEN:
            self._state = State.OPEN
            self._last_failure = datetime.now()
            self._success_count = 0

    def _on_success(self):
        if self._state == State.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._success_threshold:
                self._state = State.CLOSED
                self._failure_count = 0
                self._success_count = 0
        elif self._state == State.CLOSED:
            self._failure_count = 0

    def state(self) -> State:
        with self._mu:
            return self._state


def new_circuit_breaker() -> CircuitBreaker:
    return CircuitBreaker(CircuitBreakerConfig())


def new_circuit_breaker_with_config(config: CircuitBreakerConfig) -> CircuitBreaker:
    return CircuitBreaker(config)
