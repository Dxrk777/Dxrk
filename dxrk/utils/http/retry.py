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

    def IsRetryable(self, status_code: int) -> bool:
        """Return True if the given status code should be retried."""
        return status_code in self.retryable_status_codes


def DefaultRetryPolicy() -> RetryPolicy:
    """Return the default retry policy (3 retries, 100ms backoff)."""
    return RetryPolicy()


def _is_retryable_error(err: Exception) -> bool:
    """Mirror isRetryableError: True for timeout-class errors."""
    if isinstance(err, _TIMEOUT_ERRORS):
        return True
    return False


__all__ = [
    "defaultMaxIdleConns",
    "defaultMaxIdleConnsPerHost",
    "defaultIdleConnTimeout",
    "defaultTLSHandshakeTimeout",
    "defaultExpectContinueTimeout",
    "defaultMaxRetries",
    "defaultRetryBackoff",
    "RetryPolicy",
    "DefaultRetryPolicy",
    "_is_retryable_error",
]
