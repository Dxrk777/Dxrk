# SPDX-License-Identifier: MIT
"""Errors for dxrk.utils.http."""

from __future__ import annotations

import httpx

# Mirrors dxrk/strconst: StrUnknown / StrError.
_STR_UNKNOWN = "unknown"
_STR_ERROR = "error"


class HttpError(Exception):
    """Base class for errors in this module. Mirrors http error values."""


ErrInvalidProxyURL = HttpError("invalid proxy URL")
ErrInvalidTLSConfig = HttpError("invalid TLS configuration")
ErrMaxRetriesExceeded = HttpError("maximum retries exceeded")
ErrUnsupportedProxy = HttpError("unsupported proxy scheme")
ErrProxyAuthRequired = HttpError("proxy authentication required")
ErrInvalidProxyAuth = HttpError("invalid proxy authentication")
ErrNoProxyConfigured = HttpError("no proxy configured")
ErrInvalidCert = HttpError("invalid certificate")
ErrInvalidKey = HttpError("invalid private key")
ErrCertKeyMismatch = HttpError("certificate and private key mismatch")
ErrInvalidCA = HttpError("invalid CA certificate")
ErrMissingCertOrKey = HttpError("both certificate and key must be provided")

# Mirrors net.Error: a timeout error that the retry logic treats as retryable.
_TIMEOUT_ERRORS = (
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
)


def _wrap(msg: str, err: Exception) -> HttpError:
    """Wrap an exception with a message, preserving the cause chain."""
    return HttpError(f"{msg}: {err}")


__all__ = [
    "HttpError",
    "ErrInvalidProxyURL",
    "ErrInvalidTLSConfig",
    "ErrMaxRetriesExceeded",
    "ErrUnsupportedProxy",
    "ErrProxyAuthRequired",
    "ErrInvalidProxyAuth",
    "ErrNoProxyConfigured",
    "ErrInvalidCert",
    "ErrInvalidKey",
    "ErrCertKeyMismatch",
    "ErrInvalidCA",
    "ErrMissingCertOrKey",
    "_TIMEOUT_ERRORS",
    "_wrap",
    "_STR_UNKNOWN",
    "_STR_ERROR",
]
