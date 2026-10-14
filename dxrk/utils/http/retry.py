# SPDX-License-Identifier: MIT
"""Retry policy for dxrk.utils.http."""

from __future__ import annotations

import http.client
from dataclasses import dataclass, field
from datetime import timedelta

from .errors import _TIMEOUT_ERRORS

defaultMaxIdleConns = 100
defaultMaxIdleConnsPerHost = 10
defaultIdleConnTimeout = timedelta(seconds=90)
defaultTLSHandshakeTimeout = timedelta(seconds=10)
defaultExpectContinueTimeout = timedelta(seconds=1)
defaultMaxRetries = 3
defaultRetryBackoff = timedelta(milliseconds=100)


@dataclass
class RetryPolicy:
    """retry limits and retryable status codes."""

    max_retries: int = defaultMaxRetries
    retry_backoff: timedelta = defaultRetryBackoff
    retryable_status_codes: list[int] = field(
        default_factory=lambda: [
            http.client.REQUEST_TIMEOUT,  # 408
            http.client.TOO_MANY_REQUESTS,  # 429
            http.client.INTERNAL_SERVER_ERROR,  # 500
            http.client.BAD_GATEWAY,  # 502
            http.client.SERVICE_UNAVAILABLE,  # 503
            http.client.GATEWAY_TIMEOUT,  # 504
        ]
    )

    def is_retryable(self, status_code: int) -> bool:
        """Return True if the given status code should be retried."""
        return status_code in self.retryable_status_codes

    # Backwards-compatible alias (Go-style name).
    IsRetryable = is_retryable


def default_retry_policy() -> RetryPolicy:
    """Return the default retry policy (3 retries, 100ms backoff)."""
    return RetryPolicy()


# Backwards-compatible alias (Go-style name).
DefaultRetryPolicy = default_retry_policy


def _is_retryable_error(err: Exception) -> bool:
    """Mirror isRetryableError: True for timeout-class errors."""
    if isinstance(err, _TIMEOUT_ERRORS):
        return True
    return False


def policy_is_retryable(policy: RetryPolicy, status_code: int) -> bool:
    """Call ``is_retryable`` (or legacy ``IsRetryable``) on a retry policy."""
    is_retryable = getattr(policy, "is_retryable", None)
    if callable(is_retryable):
        return bool(is_retryable(status_code))
    legacy = getattr(policy, "IsRetryable", None)
    if callable(legacy):
        return bool(legacy(status_code))
    raise AttributeError("retry policy must implement is_retryable()")


__all__ = [
    "defaultMaxIdleConns",
    "defaultMaxIdleConnsPerHost",
    "defaultIdleConnTimeout",
    "defaultTLSHandshakeTimeout",
    "defaultExpectContinueTimeout",
    "defaultMaxRetries",
    "defaultRetryBackoff",
    "RetryPolicy",
    "default_retry_policy",
    "DefaultRetryPolicy",
    "_is_retryable_error",
    "policy_is_retryable",
]
