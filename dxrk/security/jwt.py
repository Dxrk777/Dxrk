# SPDX-License-Identifier: MIT
"""JWT parsing, classification, and token refresh scheduling"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Callable, Dict, List, Optional, Tuple, Union

# ---- JWT Token Types ----


class TokenKind(IntEnum):
    SESSION_INGRESS = 0  # sk-ant-si-* (session ingress JWT)
    ACCESS_TOKEN = 1  # sk-ant-oa-* (API access token)
    UNKNOWN = 2

    def __str__(self) -> str:
        if self == TokenKind.SESSION_INGRESS:
            return "session_ingress"
        if self == TokenKind.ACCESS_TOKEN:
            return "access_token"
        return "unknown"


@dataclass
class TokenInfo:
    kind: TokenKind
    token: str
    subject: str
    issuer: str
    expires_at: Optional[datetime]
    issued_at: Optional[datetime]
    claims: Dict[str, object]
    is_valid: bool
    is_expired: bool


# ---- JWT Utilities ----


def _b64url_decode(data: str) -> bytes:
    """Decode base64url with padding (tolerant, like RawURLEncoding)."""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


def decode_jwt_payload(token_string: str) -> Optional[Dict[str, object]]:
    """Decode the payload of a JWT without signature verification.

    Returns None if the token is malformed.
    """
    parts = token_string.split(".")
    if len(parts) != 2 and len(parts) != 3:
        return None

    try:
        payload = _b64url_decode(parts[1])
        claims = json.loads(payload)
    except (binascii.Error, ValueError):
        return None

    if not isinstance(claims, dict):
        return None
    return claims


def classify_token(token: str) -> TokenKind:
    """Determine the kind of a token based on its prefix."""
    if token.startswith("sk-ant-si-"):
        return TokenKind.SESSION_INGRESS
    if token.startswith("sk-ant-oa-"):
        return TokenKind.ACCESS_TOKEN
    return TokenKind.UNKNOWN


def is_token_expired(token_string: str, skew: timedelta) -> bool:
    """Check if a JWT is expired using clock skew tolerance."""
    claims = decode_jwt_payload(token_string)
    if claims is None:
        return False  # can't determine → assume not expired (fail-open for check)

    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False  # no exp claim → assume not expired

    expiry = datetime.fromtimestamp(int(exp), tz=timezone.utc)
    now = datetime.now(timezone.utc)

    return now > expiry + skew


KeyFunc = Callable[[Dict[str, object], Dict[str, object]], bytes]


def parse_token_safe(token_string: str, key_func: KeyFunc) -> TokenInfo:
    """Parse a JWT with signature verification.

    Raises ValueError on any parse or verification failure.
    """
    parts = token_string.split(".")
    if len(parts) != 3:
        raise ValueError("parse token: token is malformed")

    header_raw, payload_raw, sig_raw = parts

    try:
        header = json.loads(_b64url_decode(header_raw))
        claims = json.loads(_b64url_decode(payload_raw))
        signature = _b64url_decode(sig_raw)
    except (binascii.Error, ValueError) as err:
        raise ValueError(f"parse token: {err}") from err

    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ValueError("parse token: invalid claims type")

    try:
        key = key_func(header, claims)
    except Exception as err:
        raise ValueError(f"parse token: {err}") from err

    # Signature verification (HMAC-SHA256)
    alg = header.get("alg")
    if alg != "HS256":
        raise ValueError("parse token: unexpected signing method")

    signing_input = f"{header_raw}.{payload_raw}".encode()
    expected = hmac.new(key, signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("parse token: signature is invalid")

    # Expiration validation (mirrors golang-jwt/v5 default validation)
    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        expiry = datetime.fromtimestamp(int(exp), tz=timezone.utc)
        if datetime.now(timezone.utc) > expiry:
            raise ValueError("parse token: token is expired")

    def _claim_date(name: str) -> Optional[datetime]:
        value = claims.get(name)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        return None

    subject = claims.get("sub", "")
    issuer = claims.get("iss", "")
    if not isinstance(subject, str):
        subject = ""
    if not isinstance(issuer, str):
        issuer = ""

    info = TokenInfo(
        kind=classify_token(token_string),
        token=token_string,
        subject=subject,
        issuer=issuer,
        expires_at=_claim_date("exp"),
        issued_at=_claim_date("iat"),
        claims=claims,
        is_valid=True,
        is_expired=False,
    )

    return info


# ---- Token Refresh Scheduler ----


@dataclass
class RefreshConfig:
    # PollInterval is how often to check token expiry. Default: 5 min.
    poll_interval: Optional[timedelta] = None
    # RefreshBefore is how long before expiry to refresh. Default: 10 min.
    refresh_before: Optional[timedelta] = None
    # RetryInterval is the base interval between refresh retries. Default: 30s.
    retry_interval: Optional[timedelta] = None
    # MaxRetries is the maximum number of retries on refresh failure. Default: 2.
    max_retries: Optional[int] = None
    # ClockSkew is the tolerance for clock skew. Default: 30s.
    clock_skew: Optional[timedelta] = None


def default_refresh_config() -> RefreshConfig:
    """Return sensible defaults."""
    return RefreshConfig(
        poll_interval=timedelta(minutes=5),
        refresh_before=timedelta(minutes=10),
        retry_interval=timedelta(seconds=30),
        max_retries=2,
        clock_skew=timedelta(seconds=30),
    )


RefreshFunc = Callable[[], str]


class TokenRefreshScheduler:
    """Manage automatic token refresh."""

    def __init__(
        self,
        token: str,
        refresh_func: RefreshFunc,
        config: RefreshConfig,
    ) -> None:
        if config.poll_interval is None:
            config = default_refresh_config()
        self._lock = threading.Lock()
        self._config = config
        self._token = token
        self._refresh_func = refresh_func
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # State
        self._last_refresh: Optional[datetime] = None
        self._last_error: Optional[Exception] = None
        self._refresh_count: int = 0
        self._failure_count: int = 0

    def start(self) -> None:
        """Begin the background refresh loop."""

        def loop() -> None:
            poll = (self._config.poll_interval or timedelta(0)).total_seconds()
            while not self._stop.wait(poll):
                self._maybe_refresh()

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Halt the refresh loop and wait for it to finish."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def token(self) -> str:
        """Return the current (possibly refreshed) token."""
        with self._lock:
            return self._token

    def refresh_stats(
        self,
    ) -> Tuple[int, int, Optional[datetime], Optional[Exception]]:
        """Return refresh metrics: (refresh_count, failure_count, last_refresh, last_error)."""
        with self._lock:
            return (
                self._refresh_count,
                self._failure_count,
                self._last_refresh,
                self._last_error,
            )

    def _maybe_refresh(self) -> None:
        with self._lock:
            token = self._token
        if token == "":
            return

        expired = is_token_expired(token, self._config.clock_skew or timedelta(0))
        if not expired:
            # Not expired yet — check if we're within the refresh window
            claims = decode_jwt_payload(token)
            if claims is None:
                return
            exp = claims.get("exp")
            if not isinstance(exp, (int, float)):
                return
            expiry = datetime.fromtimestamp(int(exp), tz=timezone.utc)
            time_until_expiry = expiry - datetime.now(timezone.utc)

            # Only refresh if within the refresh window
            if time_until_expiry > (self._config.refresh_before or timedelta(0)):
                return

        # Attempt refresh with retries
        self._attempt_refresh()

    def _attempt_refresh(self) -> None:
        last_err: Optional[Exception] = None
        max_retries = self._config.max_retries or 0
        retry_interval = self._config.retry_interval or timedelta(0)

        for attempt in range(max_retries + 1):
            if attempt > 0:
                # Exponential backoff: retry interval * attempt
                retry_delay = retry_interval * attempt
                if self._stop.wait(retry_delay.total_seconds()):
                    return

            try:
                new_token = self._refresh_func()
            except Exception as err:
                last_err = err
                continue

            if new_token == "":
                last_err = ValueError("refresh returned empty token")
                continue

            # Success
            with self._lock:
                self._token = new_token
                self._last_refresh = datetime.now(timezone.utc)
                self._last_error = None
                self._refresh_count += 1

            return

        # All retries failed
        with self._lock:
            self._last_error = last_err
            self._failure_count += 1


# ---- Trusted Device Tokens ----


@dataclass
class TrustedDevice:
    token: str
    device_id: str
    created_at: datetime
    expires_at: datetime


def is_device_trusted(device: TrustedDevice) -> bool:
    """Check if a device token is valid and not expired."""
    if device.token == "":
        return False
    now = datetime.now(timezone.utc)
    if now > device.expires_at:
        return False
    # Must be at least 10 minutes old to be considered trusted
    if now - device.created_at < timedelta(minutes=10):
        return False
    return True


# ---- URL Safety ----


def validate_ingress_url(url: str, is_dev: bool) -> None:
    """Check that an ingress URL uses HTTPS (except localhost).

    Raises ValueError if the URL is not allowed.
    """
    if is_dev:
        return None  # dev mode allows any protocol

    if url.startswith("http://localhost") or url.startswith("http://127.0.0.1"):
        return None  # localhost exception

    if not url.startswith("https://"):
        raise ValueError(
            f"insecure origin required: {url} (must use HTTPS in production)"
        )

    return None


def validate_id(id_value: str) -> bool:
    """Check that a server-provided ID is safe for URL paths."""
    safe_pattern = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    for c in id_value:
        if c not in safe_pattern:
            return False
    return len(id_value) > 0 and len(id_value) <= 256


def redact_token(token: str) -> str:
    """Return a partially redacted version of a token for logging."""
    if len(token) < 16:
        return "[REDACTED]"
    return token[:8] + "..." + token[-4:]
