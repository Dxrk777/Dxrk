import time
from datetime import timedelta

import pytest

from dxrk.resilience import (
    CircuitBreakerConfig,
    CircuitOpenError,
    RateLimiterConfig,
    RetryConfig,
    State,
    backoff_duration,
    do,
    new_circuit_breaker,
    new_circuit_breaker_with_config,
    new_rate_limiter_with_config,
    new_retry_config,
)


class CancellableCtx:
    def __init__(self):
        self._done = False

    def done(self) -> bool:
        return self._done

    def cancel(self):
        self._done = True


def counting_fn(succeed_on):
    count = 0

    def fn(ctx):
        nonlocal count
        count += 1
        if count < succeed_on:
            return RuntimeError("retry")
        return None

    return fn, lambda: count


def test_do():
    cases = [
        (1, new_retry_config(), False, 1),
        (
            2,
            RetryConfig(
                max_attempts=3,
                initial_delay=timedelta(milliseconds=1),
                max_delay=timedelta(milliseconds=1),
                backoff_factor=1.0,
            ),
            False,
            2,
        ),
        (
            3,
            RetryConfig(
                max_attempts=3,
                initial_delay=timedelta(milliseconds=1),
                max_delay=timedelta(milliseconds=1),
                backoff_factor=1.0,
            ),
            False,
            3,
        ),
        (
            99,
            RetryConfig(
                max_attempts=3,
                initial_delay=timedelta(milliseconds=1),
                max_delay=timedelta(milliseconds=1),
                backoff_factor=1.0,
            ),
            True,
            3,
        ),
        (1, RetryConfig(max_attempts=1), False, 1),
        (99, RetryConfig(max_attempts=1), True, 1),
    ]
    for succeed_on, config, want_err, want_attempts in cases:
        fn, get_count = counting_fn(succeed_on)
        err = do(None, fn, config)
        assert (err is not None) == want_err
        assert get_count() == want_attempts


def test_do_context_cancelled():
    ctx = CancellableCtx()
    ctx.cancel()
    fn, get_count = counting_fn(99)
    config = RetryConfig(
        max_attempts=10,
        initial_delay=timedelta(hours=1),
        max_delay=timedelta(hours=1),
        backoff_factor=1.0,
    )
    with pytest.raises(RuntimeError, match="context canceled"):
        do(ctx, fn, config)
    assert get_count() == 1


def test_do_backoff_caps_at_max_delay():
    config = RetryConfig(
        max_attempts=5,
        initial_delay=timedelta(seconds=1),
        max_delay=timedelta(milliseconds=10),
        backoff_factor=100,
    )
    fn, get_count = counting_fn(5)
    start = time.perf_counter()
    err = do(None, fn, config)
    elapsed = time.perf_counter() - start
    assert err is None
    assert get_count() == 5
    assert elapsed < 0.5


def test_backoff_duration_caps_at_max_delay():
    config = RetryConfig(
        max_attempts=5,
        initial_delay=timedelta(seconds=1),
        max_delay=timedelta(milliseconds=10),
        backoff_factor=100,
    )
    assert backoff_duration(1, config) == timedelta(milliseconds=10)
    assert backoff_duration(2, config) == timedelta(milliseconds=10)


def test_circuit_breaker_initial_state():
    assert new_circuit_breaker().state() == State.CLOSED


def test_circuit_breaker_opens_after_threshold():
    cb = new_circuit_breaker_with_config(
        CircuitBreakerConfig(failure_threshold=2, success_threshold=1, timeout=timedelta(minutes=1))
    )
    cb.call(None, lambda ctx: RuntimeError("boom"))
    assert cb.state() == State.CLOSED
    cb.call(None, lambda ctx: RuntimeError("boom"))
    assert cb.state() == State.OPEN


def test_circuit_breaker_rejects_when_open():
    cb = new_circuit_breaker_with_config(
        CircuitBreakerConfig(failure_threshold=1, success_threshold=1, timeout=timedelta(hours=1))
    )
    cb.call(None, lambda ctx: RuntimeError("boom"))
    with pytest.raises(CircuitOpenError):
        cb.call(None, lambda ctx: None)


def test_circuit_breaker_half_open_after_timeout():
    cb = new_circuit_breaker_with_config(
        CircuitBreakerConfig(failure_threshold=1, success_threshold=1, timeout=timedelta(milliseconds=50))
    )
    cb.call(None, lambda ctx: RuntimeError("boom"))
    assert cb.state() == State.OPEN
    time.sleep(0.06)
    err = cb.call(None, lambda ctx: None)
    assert err is None
    assert cb.state() == State.CLOSED


def test_circuit_breaker_half_open_fail_returns_to_open():
    cb = new_circuit_breaker_with_config(
        CircuitBreakerConfig(failure_threshold=1, success_threshold=1, timeout=timedelta(milliseconds=50))
    )
    cb.call(None, lambda ctx: RuntimeError("boom"))
    time.sleep(0.06)
    err = cb.call(None, lambda ctx: RuntimeError("boom"))
    assert err is not None
    assert cb.state() == State.OPEN


def test_circuit_breaker_closed_resets_failure_count():
    cb = new_circuit_breaker_with_config(
        CircuitBreakerConfig(failure_threshold=3, success_threshold=1, timeout=timedelta(minutes=1))
    )
    cb.call(None, lambda ctx: RuntimeError("boom"))
    cb.call(None, lambda ctx: RuntimeError("boom"))
    cb.call(None, lambda ctx: None)
    cb.call(None, lambda ctx: RuntimeError("boom"))
    assert cb.state() == State.CLOSED


def test_circuit_breaker_requires_success_threshold():
    cb = new_circuit_breaker_with_config(
        CircuitBreakerConfig(failure_threshold=1, success_threshold=3, timeout=timedelta(milliseconds=50))
    )
    cb.call(None, lambda ctx: RuntimeError("boom"))
    assert cb.state() == State.OPEN
    time.sleep(0.06)
    err = cb.call(None, lambda ctx: None)
    assert err is None
    assert cb.state() == State.HALF_OPEN
    err = cb.call(None, lambda ctx: None)
    assert err is None
    assert cb.state() == State.HALF_OPEN
    err = cb.call(None, lambda ctx: None)
    assert err is None
    assert cb.state() == State.CLOSED


def test_rate_limiter_allow():
    cases = [
        (3, 3, 0),
        (2, 5, 3),
        (0, 1, 1),
    ]
    for max_tokens, consume, want_deny in cases:
        rl = new_rate_limiter_with_config(
            RateLimiterConfig(
                max_tokens=max_tokens,
                refill_interval=timedelta(hours=1),
                refill_amount=0,
            )
        )
        denied = 0
        for _ in range(consume):
            if not rl.allow():
                denied += 1
        assert denied == want_deny
        rl.close()


def test_rate_limiter_wait():
    rl = new_rate_limiter_with_config(
        RateLimiterConfig(max_tokens=1, refill_interval=timedelta(milliseconds=50), refill_amount=1)
    )
    assert rl.allow()
    start = time.perf_counter()
    err = rl.wait()
    elapsed = time.perf_counter() - start
    assert err is None
    assert elapsed >= 0.03
    rl.close()


def test_rate_limiter_wait_context_cancel():
    rl = new_rate_limiter_with_config(
        RateLimiterConfig(max_tokens=0, refill_interval=timedelta(hours=1), refill_amount=0)
    )
    ctx = CancellableCtx()
    ctx.cancel()
    with pytest.raises(RuntimeError, match="context canceled"):
        rl.wait(ctx)
    rl.close()


def test_rate_limiter_refill():
    rl = new_rate_limiter_with_config(
        RateLimiterConfig(max_tokens=5, refill_interval=timedelta(milliseconds=10), refill_amount=3)
    )
    for _ in range(5):
        assert rl.allow()
    assert not rl.allow()
    deadline = time.monotonic() + 5.0
    while not rl.allow():
        assert time.monotonic() < deadline, "refill did not happen in time"
        time.sleep(0.001)
    rl.close()


import sys

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific paths")
