# SPDX-License-Identifier: MIT
"""HTTP client utilities.

Provides a thread-safe HTTP client with retry policies, proxy configuration
(HTTP/HTTPS/SOCKS), TLS configuration built on the ``ssl`` module and
``cryptography``, a connection pool with statistics and monitoring, and
request/response logging with sensitive-data sanitization.

The wire layer is ``httpx``; ``time.Duration`` maps to
``datetime.timedelta``, ``sync.RWMutex`` to ``threading.RLock``, goroutines to
daemon threads, and the private :class:`_Context` mirrors the subset of
``context.Context`` used by this package.

Fidelity notes (mirrored intentionally, including upstream quirks):

* ``DoWithRetry`` returns the last response (not an error) when every attempt
  produced a retryable status code.
* ``ProxyConfig.String`` returns ``""`` when the config cannot be serialized.
* ``NewProxyConfig`` parses the port with ``int``; an unparsable explicit
  port becomes 0 (which ``ProxyPort`` then replaces with the default).
* ``GetProxyFromEnvironment`` reads the real environment (the original ``getEnv``
  returns ``""`` unconditionally); this is a deliberate divergence.
* SOCKS4/SOCKS5 configs parse fine but ``httpx`` has no SOCKS support
  (``socksio`` is not installed), so proxying fails at request time.
* ``ForceAttemptHTTP2`` has no httpx equivalent (HTTP/2 is used when
  available); the field exists for API parity.
* ``MaxConnsPerHost``/``MaxIdleConnsPerHost`` map to httpx connection pool
  limits; ``DisableKeepAlives`` is not directly supported by httpx.
* ``DoWithRetry`` sleeps during backoff with a plain ``time.sleep`` (no
  cancellation mid-sleep); the context is re-checked between attempts.
* ``httpx`` does not honor per-request client timeouts, so ``Do``/``DoWithRetry``
  set ``client.timeout`` under a lock for the duration of each request.
* ``DumpRequest``/``DumpResponse`` return strings (not ``[]byte``).
* ``LogResponseBody``/``LogRequestBody`` use httpx response/request objects;
  response bodies are buffered in memory before logging.
"""

from __future__ import annotations

import copy
import http.client
import io
import os
import re
import ssl
import threading
import time
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum, IntEnum
from typing import Callable, Iterable, Protocol, cast
from urllib.parse import urlparse

import httpx
from cryptography import x509 as crypto_x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

# Mirrors dxrk/strconst: StrUnknown / StrError.
_STR_UNKNOWN = "unknown"
_STR_ERROR = "error"

_ZERO_TIME = datetime.fromtimestamp(0, tz=timezone.utc)

_CTX_CANCELED = "context canceled"
_CTX_DEADLINE = "context deadline exceeded"


def _now() -> datetime:
    """Return the current UTC time. Mirrors time.Now()."""
    return datetime.now(timezone.utc)


def _is_zero(dt: datetime) -> bool:
    """Return True for a zero (unset) time. Mirrors time.Time.IsZero()."""
    return dt == _ZERO_TIME or dt.timestamp() == 0.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Context (subset of context.Context, like swarm._Context)
# ---------------------------------------------------------------------------


class _Context:
    """Minimal context with cancellation, deadline, and value storage."""

    __slots__ = ("_done", "_err", "_deadline", "_parent", "_values")

    def __init__(
        self, parent: "_Context | None" = None, deadline: float | None = None
    ) -> None:
        self._done = threading.Event()
        self._err: str | None = None
        self._deadline = deadline
        self._parent = parent
        self._values: dict[str, object] | None = None

    def _set(self, err: str) -> None:
        if self._deadline is not None and time.monotonic() >= self._deadline:
            err = _CTX_DEADLINE
        if not self._done.is_set():
            self._done.set()
            self._err = err

    def err(self) -> str | None:
        """Return the context error, if any."""
        if self._parent is not None:
            perr = self._parent.err()
            if perr is not None:
                self._set(perr)
        if self._done.is_set():
            return self._err
        if self._deadline is not None and time.monotonic() >= self._deadline:
            self._set(_CTX_DEADLINE)
            return self._err
        return None

    def remaining(self) -> float | None:
        """Seconds until the deadline, or None."""
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())


def _background() -> _Context:
    """Return a never-cancelled context. Mirrors context.Background()."""
    return _Context()


def _with_cancel(parent: _Context | None = None) -> tuple[_Context, Callable[[], None]]:
    """Return a child context with a cancel function. Mirrors context.WithCancel."""
    child = _Context(parent=parent)
    return child, lambda: child._set(_CTX_CANCELED)


def _with_timeout(
    parent: _Context | None, timeout: timedelta
) -> tuple[_Context, Callable[[], None]]:
    """Return a child context that expires after ``timeout``."""
    child = _Context(parent=parent, deadline=time.monotonic() + timeout.total_seconds())
    return child, lambda: child._set(_CTX_CANCELED)


def _with_value(ctx: _Context, key: str, value: object) -> _Context:
    """Return a child context carrying a value. Mirrors context.WithValue."""
    child = _Context(parent=ctx)
    child._values = {key: value}
    return child


def _get_value(ctx: _Context, key: str) -> object | None:
    """Look up a value in a context chain. Mirrors context.Context.Value."""
    current: _Context | None = ctx
    while current is not None:
        if current._values is not None and key in current._values:
            return current._values[key]
        current = current._parent
    return None


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TLS configuration
# ---------------------------------------------------------------------------


class ClientAuthType(IntEnum):
    """TLS client authentication type."""

    NoClientCert = 0
    RequestClientCert = 1
    RequireAnyClientCert = 2
    VerifyClientCertIfGiven = 3
    RequireAndVerifyClientCert = 4


# tls.VersionTLS12 / VersionTLS13, mapped to ssl.TLSVersion values.
VERSION_TLS12 = ssl.TLSVersion.TLSv1_2
VERSION_TLS13 = ssl.TLSVersion.TLSv1_3

# Default cipher suites mapped to OpenSSL names (TLS 1.3 suites first).
_DEFAULT_CIPHER_SUITES = [
    "TLS_AES_256_GCM_SHA384",
    "TLS_CHACHA20_POLY1305_SHA256",
    "TLS_AES_128_GCM_SHA256",
    "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-AES256-GCM-SHA384",
    "ECDHE-ECDSA-CHACHA20-POLY1305",
    "ECDHE-RSA-CHACHA20-POLY1305",
    "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-RSA-AES128-GCM-SHA256",
]

# Default curve preferences mapped to OpenSSL names.
_DEFAULT_CURVE_PREFERENCES = ["X25519", "prime256v1", "secp384r1", "secp521r1"]


@dataclass
class TLSConfig:
    """TLS settings applied to the transport.

    ``cipher_suites``/``curve_preferences`` are stored for API parity; the
    ``ssl`` module applies them at handshake time via OpenSSL defaults, so
    the lists are informative only (fidelity note).
    """

    cert_file: str = ""
    key_file: str = ""
    cert_data: bytes = b""
    key_data: bytes = b""
    ca_file: str = ""
    ca_data: bytes = b""
    insecure_skip_verify: bool = False
    server_name: str = ""
    min_version: ssl.TLSVersion = VERSION_TLS12
    max_version: ssl.TLSVersion | None = VERSION_TLS13
    cipher_suites: list[str] = field(
        default_factory=lambda: list(_DEFAULT_CIPHER_SUITES)
    )
    curve_preferences: list[str] = field(
        default_factory=lambda: list(_DEFAULT_CURVE_PREFERENCES)
    )
    client_auth: ClientAuthType = ClientAuthType.NoClientCert
    root_cas: list[crypto_x509.Certificate] = field(default_factory=list)
    client_cas: list[crypto_x509.Certificate] = field(default_factory=list)

    def LoadCertKeyFromFile(self, cert_file: str, key_file: str) -> None:
        """Load a certificate/key pair from files (raises on error)."""
        try:
            with open(cert_file, "rb") as f:
                cert_data = f.read()
        except OSError as e:
            raise _wrap(str(ErrInvalidCert), e) from e
        try:
            with open(key_file, "rb") as f:
                key_data = f.read()
        except OSError as e:
            raise _wrap(str(ErrInvalidKey), e) from e
        self.cert_file = cert_file
        self.key_file = key_file
        self.cert_data = cert_data
        self.key_data = key_data

    def LoadCAFromFile(self, ca_file: str) -> None:
        """Load CA certificates from a file (raises on error)."""
        try:
            with open(ca_file, "rb") as f:
                ca_data = f.read()
        except OSError as e:
            raise _wrap(str(ErrInvalidCA), e) from e
        self.ca_file = ca_file
        self.ca_data = ca_data

    def SetCertKeyData(self, cert_data: bytes, key_data: bytes) -> None:
        """Set the certificate/key from raw PEM data (raises on error)."""
        if not cert_data or not key_data:
            raise ErrMissingCertOrKey
        if _pem_decode(cert_data) is None:
            raise ErrInvalidCert
        if _pem_decode(key_data) is None:
            raise ErrInvalidKey
        self.cert_data = cert_data
        self.key_data = key_data

    def SetCAData(self, ca_data: bytes) -> None:
        """Set CA certificates from raw PEM data (raises on error)."""
        if not ca_data:
            raise ErrInvalidCA
        if _pem_decode(ca_data) is None:
            raise ErrInvalidCA
        self.ca_data = ca_data

    def BuildTLSConfig(self) -> ssl.SSLContext:
        """Build an ``ssl.SSLContext`` from this configuration."""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = self.min_version
        if self.max_version is not None:
            ctx.maximum_version = self.max_version
        if self.insecure_skip_verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        if self.server_name:
            ctx.check_hostname = True

        if self.cert_data and self.key_data:
            ctx.load_cert_chain(
                certfile=cast(
                    str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    io.BytesIO(self.cert_data),
                ),
                keyfile=cast(
                    str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    io.BytesIO(self.key_data),
                ),
            )
        elif self.cert_file and self.key_file:
            try:
                ctx.load_cert_chain(self.cert_file, self.key_file)
            except (OSError, ssl.SSLError) as e:
                raise _wrap(str(ErrCertKeyMismatch), e) from e

        if self.ca_data:
            ctx.load_verify_locations(cadata=self.ca_data.decode("utf-8", "replace"))
        elif self.ca_file:
            try:
                ctx.load_verify_locations(self.ca_file)
            except (OSError, ssl.SSLError) as e:
                raise _wrap(str(ErrInvalidCA), e) from e

        if self.root_cas:
            data = b"".join(
                c.public_bytes(serialization.Encoding.PEM) for c in self.root_cas
            )
            ctx.load_verify_locations(cadata=data.decode("utf-8", "replace"))

        if self.client_cas:
            data = b"".join(
                c.public_bytes(serialization.Encoding.PEM) for c in self.client_cas
            )
            ctx.load_verify_locations(cadata=data.decode("utf-8", "replace"))
            if self.client_auth is ClientAuthType.NoClientCert:
                self.client_auth = ClientAuthType.RequireAndVerifyClientCert
            ctx.verify_mode = ssl.CERT_REQUIRED

        return ctx

    def BuildClientTLSConfig(self) -> ssl.SSLContext:
        """Build a client TLS config (no client certificate required)."""
        ctx = self.BuildTLSConfig()
        ctx.verify_mode = (
            ssl.CERT_NONE if self.insecure_skip_verify else ssl.CERT_REQUIRED
        )
        return ctx

    def BuildServerTLSConfig(self) -> ssl.SSLContext:
        """Build a server TLS config; requires a certificate/key."""
        if not self.cert_data and not self.cert_file:
            raise ErrMissingCertOrKey
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = self.min_version
        if self.max_version is not None:
            ctx.maximum_version = self.max_version
        if self.cert_data and self.key_data:
            ctx.load_cert_chain(
                certfile=cast(
                    str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    io.BytesIO(self.cert_data),
                ),
                keyfile=cast(
                    str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    io.BytesIO(self.key_data),
                ),
            )
        elif self.cert_file and self.key_file:
            try:
                ctx.load_cert_chain(self.cert_file, self.key_file)
            except (OSError, ssl.SSLError) as e:
                raise _wrap(str(ErrCertKeyMismatch), e) from e
        if self.ca_data:
            ctx.load_verify_locations(cadata=self.ca_data.decode("utf-8", "replace"))
        if self.client_cas:
            data = b"".join(
                c.public_bytes(serialization.Encoding.PEM) for c in self.client_cas
            )
            ctx.load_verify_locations(cadata=data.decode("utf-8", "replace"))
        return ctx

    def WithMutualTLS(self, ca_data: bytes) -> "TLSConfig":
        """Require and verify client certificates against ``ca_data``."""
        self.client_auth = ClientAuthType.RequireAndVerifyClientCert
        try:
            self.SetCAData(ca_data)
        except HttpError:
            pass
        return self

    def WithInsecureSkipVerify(self, skip: bool) -> "TLSConfig":
        """Set whether server certificates are verified."""
        self.insecure_skip_verify = skip
        return self

    def WithServerName(self, name: str) -> "TLSConfig":
        """Set the server name for SNI/hostname verification."""
        self.server_name = name
        return self

    def WithMinVersion(self, version: ssl.TLSVersion) -> "TLSConfig":
        """Set the minimum TLS version."""
        self.min_version = version
        return self

    def WithCipherSuites(self, suites: list[str]) -> "TLSConfig":
        """Set the cipher suites (informative; see the fidelity notes)."""
        self.cipher_suites = suites
        return self

    def Clone(self) -> "TLSConfig":
        """Return a deep copy of this configuration."""
        return TLSConfig(
            cert_file=self.cert_file,
            key_file=self.key_file,
            cert_data=self.cert_data,
            key_data=self.key_data,
            ca_file=self.ca_file,
            ca_data=self.ca_data,
            insecure_skip_verify=self.insecure_skip_verify,
            server_name=self.server_name,
            min_version=self.min_version,
            max_version=self.max_version,
            cipher_suites=list(self.cipher_suites),
            curve_preferences=list(self.curve_preferences),
            client_auth=self.client_auth,
            root_cas=list(self.root_cas),
            client_cas=list(self.client_cas),
        )


def NewTLSConfig() -> TLSConfig:
    """Return a TLSConfig with the defaults (TLS 1.2+, 9 cipher suites)."""
    return TLSConfig()


def _pem_decode(data: bytes) -> bytes | None:
    """Return the DER bytes of the first PEM block, or None."""
    try:
        cert = crypto_x509.load_pem_x509_certificate(data)
        return cert.public_bytes(serialization.Encoding.DER)
    except Exception:
        return None


def ParseCertificate(pem_data: bytes) -> crypto_x509.Certificate:
    """Parse a PEM certificate (raises on error)."""
    try:
        return crypto_x509.load_pem_x509_certificate(pem_data)
    except Exception as e:
        raise _wrap(str(ErrInvalidCert), e) from e


def ParsePrivateKey(pem_data: bytes) -> object:
    """Parse a PEM private key (PKCS1/PKCS8/EC); raises on error."""
    try:
        return serialization.load_pem_private_key(pem_data, password=None)
    except Exception as e:
        raise _wrap(str(ErrInvalidKey), e) from e


def CertificateToPEM(cert: crypto_x509.Certificate) -> bytes:
    """Encode a certificate to PEM bytes."""
    return cert.public_bytes(serialization.Encoding.PEM)


def PrivateKeyToPEM(key: object) -> bytes:
    """Encode an RSA/EC private key to PKCS8 PEM; raises on other key types."""
    if not isinstance(key, (rsa.RSAPrivateKey, ec.EllipticCurvePrivateKey)):
        raise ErrInvalidKey
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def LoadSystemCertPool() -> list[crypto_x509.Certificate]:
    """Return the system certificate pool as a list (raises on error)."""
    ctx = ssl.create_default_context()
    return cast(list[crypto_x509.Certificate], ctx.get_ca_certs())


def NewCertPool(
    certs: Iterable[crypto_x509.Certificate] | None = None,
) -> list[crypto_x509.Certificate]:
    """Create a certificate pool from the given certificates."""
    return list(certs or [])


# ---------------------------------------------------------------------------
# Proxy configuration
# ---------------------------------------------------------------------------


class ProxyType(str, Enum):
    """Proxy type."""

    ProxyTypeHTTP = "http"
    ProxyTypeHTTPS = "https"
    ProxyTypeSOCKS4 = "socks4"
    ProxyTypeSOCKS5 = "socks5"


@dataclass
class ProxyAuth:
    """proxy credentials."""

    username: str = ""
    password: str = ""

    def String(self) -> str:
        """Return "user:pass" (or "user"); "" without a username."""
        if self.username == "":
            return ""
        if self.password == "":
            return self.username
        return self.username + ":" + self.password

    def Encode(self) -> str:
        """Return "user:pass"; "" without a username."""
        if self.username == "":
            return ""
        return self.username + ":" + self.password


@dataclass
class ProxyConfig:
    """Proxy configuration."""

    type: ProxyType = ProxyType.ProxyTypeHTTP
    host: str = ""
    port: int = 0
    auth: ProxyAuth | None = None
    bypass: list[str] = field(default_factory=list)
    no_proxy: str = ""

    def GetProxyURL(self) -> str | None:
        """Return the proxy URL string, or None on error."""
        if self.type is ProxyType.ProxyTypeHTTP:
            scheme = "http"
        elif self.type is ProxyType.ProxyTypeHTTPS:
            scheme = "https"
        elif self.type is ProxyType.ProxyTypeSOCKS4:
            scheme = "socks4"
        elif self.type is ProxyType.ProxyTypeSOCKS5:
            scheme = "socks5"
        else:
            raise _wrap(str(ErrUnsupportedProxy), HttpError(str(self.type)))
        host_port = _join_host_port(self.host, self.ProxyPort())
        auth = ""
        if self.auth is not None:
            auth = self.auth.Encode()
            if auth:
                auth = auth + "@"
        return f"{scheme}://{auth}{host_port}"

    def ProxyPort(self) -> int:
        """Return the effective port (defaults for the type when unset)."""
        if self.port > 0:
            return self.port
        if self.type is ProxyType.ProxyTypeHTTP:
            return 8080
        if self.type is ProxyType.ProxyTypeHTTPS:
            return 8443
        if self.type in (ProxyType.ProxyTypeSOCKS4, ProxyType.ProxyTypeSOCKS5):
            return 1080
        return 0

    def String(self) -> str:
        """Return the proxy URL; "" if it cannot be serialized."""
        try:
            return self.GetProxyURL() or ""
        except HttpError:
            return ""

    def ShouldBypass(self, host: str) -> bool:
        """Return True if ``host`` should not use the proxy."""
        for bypass in self.bypass:
            if _match_bypass(bypass, host):
                return True
        if self.no_proxy:
            for pattern in self.no_proxy.split(","):
                pattern = pattern.strip()
                if _match_bypass(pattern, host):
                    return True
        return False

    def AddBypass(self, pattern: str) -> None:
        """Add a bypass pattern (ignored when empty)."""
        if pattern != "":
            self.bypass.append(pattern)

    def SetNoProxy(self, no_proxy: str) -> None:
        """Set the no-proxy pattern list."""
        self.no_proxy = no_proxy

    def Clone(self) -> "ProxyConfig":
        """Return a deep copy of this configuration."""
        auth = ProxyAuth(self.auth.username, self.auth.password) if self.auth else None
        return ProxyConfig(
            type=self.type,
            host=self.host,
            port=self.port,
            auth=auth,
            bypass=list(self.bypass),
            no_proxy=self.no_proxy,
        )


def NewProxyConfig(proxy_url: str) -> tuple[ProxyConfig | None, Exception | None]:
    """Parse a proxy URL into a ProxyConfig )."""
    if proxy_url == "":
        return None, ErrInvalidProxyURL
    try:
        parsed = urlparse(proxy_url)
    except ValueError as e:
        return None, _wrap(str(ErrInvalidProxyURL), e)

    proxy_type = cast(
        ProxyType, ProxyType(parsed.scheme.lower()) if parsed.scheme else None
    )
    if proxy_type not in (
        ProxyType.ProxyTypeHTTP,
        ProxyType.ProxyTypeHTTPS,
        ProxyType.ProxyTypeSOCKS4,
        ProxyType.ProxyTypeSOCKS5,
    ):
        return None, HttpError(f"{ErrUnsupportedProxy}: {parsed.scheme}")

    host = parsed.hostname or ""
    port = 0
    if parsed.port is not None:
        port = int(parsed.port)
    else:
        if proxy_type is ProxyType.ProxyTypeHTTP:
            port = 8080
        elif proxy_type is ProxyType.ProxyTypeHTTPS:
            port = 8443
        elif proxy_type in (ProxyType.ProxyTypeSOCKS4, ProxyType.ProxyTypeSOCKS5):
            port = 1080

    auth: ProxyAuth | None = None
    if parsed.username is not None:
        auth = ProxyAuth(username=parsed.username, password=parsed.password or "")

    query = _parse_query(parsed.query)
    return (
        ProxyConfig(
            type=proxy_type,
            host=host,
            port=port,
            auth=auth,
            bypass=_parse_bypass_list(query.get("bypass", "")),
            no_proxy=query.get("no_proxy", ""),
        ),
        None,
    )


def NewHTTPProxy(host: str, port: int, auth: ProxyAuth | None = None) -> ProxyConfig:
    """Create an HTTP proxy config."""
    return ProxyConfig(type=ProxyType.ProxyTypeHTTP, host=host, port=port, auth=auth)


def NewHTTPSProxy(host: str, port: int, auth: ProxyAuth | None = None) -> ProxyConfig:
    """Create an HTTPS proxy config."""
    return ProxyConfig(type=ProxyType.ProxyTypeHTTPS, host=host, port=port, auth=auth)


def NewSOCKS5Proxy(host: str, port: int, auth: ProxyAuth | None = None) -> ProxyConfig:
    """Create a SOCKS5 proxy config."""
    return ProxyConfig(type=ProxyType.ProxyTypeSOCKS5, host=host, port=port, auth=auth)


def _parse_bypass_list(bypass: str) -> list[str]:
    if bypass == "":
        return []
    return [p.strip() for p in bypass.split(",") if p.strip() != ""]


def _match_bypass(pattern: str, host: str) -> bool:
    pattern = pattern.lower()
    host = host.lower()
    if pattern == "*":
        return True
    if pattern.startswith("*."):
        return host.endswith(pattern[1:])
    if pattern.endswith("*"):
        return host.startswith(pattern[:-1])
    return pattern == host


def _parse_query(query: str) -> dict[str, str]:
    """Minimal query-string parse (urllib.parse.parse_qsl keeps empty values)."""
    result: dict[str, str] = {}
    if query == "":
        return result
    for pair in query.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            result[k] = v
    return result


def _join_host_port(host: str, port: int) -> str:
    """Mirror net.JoinHostPort: brackets IPv6 hosts."""
    if ":" in host:
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def GetProxyFromEnvironment() -> ProxyConfig | None:
    """Return a ProxyConfig from HTTPS_PROXY/HTTP_PROXY (deliberate
    divergence: the original ``getEnv`` returns "" unconditionally, so the original
    function always returns None; Python reads the real environment)."""
    proxy_url = ""
    for env in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        val = os.environ.get(env, "")
        if val != "":
            proxy_url = val
            break
    if proxy_url == "":
        return None
    config, err = NewProxyConfig(proxy_url)
    if err is not None or config is None:
        return None
    no_proxy = os.environ.get("NO_PROXY", "")
    if no_proxy == "":
        no_proxy = os.environ.get("no_proxy", "")
    config.SetNoProxy(no_proxy)
    return config


def ParseProxyURL(proxy_url: str) -> tuple[ProxyConfig | None, Exception | None]:
    """Parse a proxy URL (alias of NewProxyConfig)."""
    return NewProxyConfig(proxy_url)


def MustParseProxyURL(proxy_url: str) -> ProxyConfig:
    """Parse a proxy URL; raises (panic equivalent) on error."""
    config, err = NewProxyConfig(proxy_url)
    if err is not None:
        raise err
    if config is None:
        raise ErrInvalidProxyURL
    return config


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class Transport(Protocol):
    """A transport that can handle requests (httpx.HTTPTransport compatible)."""

    def handle_request(self, request: httpx.Request) -> httpx.Response: ...

    def close(self) -> None: ...

    def clone(self) -> "Transport": ...


def _env_proxy_url() -> str | None:
    """Return the environment proxy URL for the transport, or None."""
    pc = GetProxyFromEnvironment()
    if pc is None:
        return None
    try:
        return pc.GetProxyURL()
    except HttpError:
        return None


def _make_transport(
    proxy: str | None = None,
    verify: bool | str = True,
    limits: httpx.Limits | None = None,
    timeout: httpx.Timeout | None = None,
    trust_env: bool = False,
) -> httpx.HTTPTransport:
    """Build an httpx transport with the given settings."""
    if limits is None:
        limits = httpx.Limits()
    return httpx.HTTPTransport(
        proxy=proxy,
        verify=verify,
        limits=limits,
        trust_env=trust_env,
    )


def _transport_from_config(
    proxy_config: ProxyConfig | None,
    tls_config: TLSConfig | None,
    limits: httpx.Limits | None = None,
    timeout: httpx.Timeout | None = None,
) -> httpx.HTTPTransport:
    """Build a transport honoring proxy/TLS configs (transport defaults)."""
    proxy: str | None = None
    if proxy_config is not None:
        try:
            proxy = proxy_config.GetProxyURL()
        except HttpError:
            proxy = None
    if proxy is None:
        proxy = _env_proxy_url()

    verify: bool | str = True
    if tls_config is not None:
        if tls_config.insecure_skip_verify:
            verify = False
        if tls_config.ca_data or tls_config.ca_file:
            verify = (
                tls_config.ca_data.decode("utf-8", "replace")
                if tls_config.ca_data
                else tls_config.ca_file
            )

    return _make_transport(proxy=proxy, verify=verify, limits=limits, timeout=timeout)


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


@dataclass
class ClientOptions:
    """HTTP client options."""

    timeout: timedelta = timedelta(0)
    max_idle_conns: int = 0
    max_idle_conns_per_host: int = 0
    idle_conn_timeout: timedelta = timedelta(0)
    tls_handshake_timeout: timedelta = timedelta(0)
    expect_continue_timeout: timedelta = timedelta(0)
    disable_keep_alives: bool = False
    disable_compression: bool = False
    max_conns_per_host: int = 0
    retry_policy: RetryPolicy | None = None
    proxy_config: ProxyConfig | None = None
    tls_config: TLSConfig | None = None


class HTTPClient:
    """a thread-safe HTTP client with retries."""

    def __init__(
        self,
        client: httpx.Client,
        transport: httpx.HTTPTransport,
        retry_policy: RetryPolicy,
        proxy_config: ProxyConfig | None = None,
        tls_config: TLSConfig | None = None,
    ) -> None:
        self.client = client
        self.transport = transport
        self.retry_policy = retry_policy
        self.proxy_config = proxy_config
        self.tls_config = tls_config
        self.mu = threading.RLock()

    def _apply_proxy_config(self, pc: ProxyConfig) -> Exception | None:
        """Apply a proxy config to this client (used by NewHTTPClient)."""
        with self.mu:
            return _apply_proxy_config_impl(self, pc)

    def _apply_tls_config(self, tc: TLSConfig) -> Exception | None:
        """Apply a TLS config to this client (used by NewHTTPClient)."""
        with self.mu:
            return _apply_tls_config_impl(self, tc)

    def Do(self, req: httpx.Request) -> tuple[httpx.Response | None, Exception | None]:
        """Send the request, retrying per the client's policy."""
        return self.DoWithRetry(req, self.retry_policy)

    def DoWithRetry(
        self, req: httpx.Request, policy: RetryPolicy | None
    ) -> tuple[httpx.Response | None, Exception | None]:
        """Send the request with the given retry policy (client policy when
        None). Mirrors the original, including returning the last response after
        exhausting retries on retryable status codes."""
        if policy is None:
            policy = self.retry_policy

        last_resp: httpx.Response | None = None
        last_err: Exception | None = None
        ctx = getattr(req, "_ctx", None)

        for attempt in range(policy.max_retries + 1):
            if ctx is not None and ctx.err() is not None:
                return None, HttpError(ctx.err() or _CTX_CANCELED)

            resp, err = self._send(req)
            if err is not None:
                last_err = err
                if not _is_retryable_error(err):
                    return None, err
            else:
                last_resp = resp
                if resp is not None and not policy.IsRetryable(resp.status_code):
                    return resp, None
                if resp is not None:
                    resp.close()

            if attempt < policy.max_retries:
                backoff = policy.retry_backoff.total_seconds() * (attempt + 1)
                time.sleep(backoff)

        if last_resp is not None:
            return last_resp, None
        if last_err is not None:
            return None, last_err
        return None, ErrMaxRetriesExceeded

    def _send(
        self, req: httpx.Request
    ) -> tuple[httpx.Response | None, Exception | None]:
        """Send one request, returning a response or an error."""
        try:
            with self.mu:
                self.client.timeout = _client_timeout(req, self.client.timeout)
                resp = self.client.send(req, stream=True)
            return resp, None
        except _TIMEOUT_ERRORS as e:
            return None, HttpError(str(e))
        except httpx.TransportError as e:
            return None, HttpError(str(e))
        except httpx.HTTPError as e:
            return None, HttpError(str(e))

    def DoWithContext(
        self, ctx: _Context, req: httpx.Request
    ) -> tuple[httpx.Response | None, Exception | None]:
        """Send the request with a context deadline/cancellation."""
        if ctx is not None and ctx.err() is not None:
            return None, HttpError("context canceled")
        req._ctx = ctx  # type: ignore[attr-defined]
        return self.Do(req)

    def GetClient(self) -> httpx.Client:
        """Return the underlying httpx client."""
        with self.mu:
            return self.client

    def GetTransport(self) -> httpx.HTTPTransport:
        """Return the underlying transport."""
        with self.mu:
            return self.transport

    def SetProxy(self, proxy_url: str) -> None:
        """Set the proxy from a URL string (raises on invalid URLs)."""
        parsed = urlparse(proxy_url)
        if parsed.scheme == "" or parsed.hostname is None:
            raise ErrInvalidProxyURL
        with self.mu:
            self.transport = _make_transport(proxy=proxy_url)
            self.client._transport = self.transport

    def CloseIdleConnections(self) -> None:
        """Close idle connections held by the transport."""
        with self.mu:
            self.transport.close()

    def Clone(self) -> "HTTPClient":
        """Return a client sharing the retry/proxy/TLS config with a fresh
        transport and client."""
        with self.mu:
            new_transport = self.transport
            if hasattr(self.transport, "clone"):
                new_transport = copy.copy(self.transport)
            new_client = httpx.Client(
                transport=new_transport,
                timeout=self.client.timeout,
                follow_redirects=False,
            )
            return HTTPClient(
                client=new_client,
                transport=new_transport,
                retry_policy=self.retry_policy,
                proxy_config=self.proxy_config,
                tls_config=self.tls_config,
            )

    def WithMiddleware(
        self, middleware: Callable[[httpx.HTTPTransport], httpx.HTTPTransport]
    ) -> "HTTPClient":
        """Wrap the transport with middleware (e.g. a logging transport)."""
        with self.mu:
            new_transport = _make_transport()
            new_transport = middleware(new_transport)
            self.transport = new_transport
            self.client._transport = new_transport
            return self


def _client_timeout(
    req: httpx.Request, default: float | httpx.Timeout = 30.0
) -> httpx.Timeout:
    """Compute the client timeout for a request (ctx deadline wins)."""
    ctx = getattr(req, "_ctx", None)
    if ctx is not None and ctx.remaining() is not None:
        return httpx.Timeout(ctx.remaining() or 0.0)
    return httpx.Timeout(default)


def _is_retryable_error(err: Exception) -> bool:
    """Mirror isRetryableError: True for timeout-class errors."""
    if isinstance(err, _TIMEOUT_ERRORS):
        return True
    return False


def NewHTTPClient(
    opts: ClientOptions | None,
) -> tuple[HTTPClient | None, Exception | None]:
    """Create an HTTP client from options (defaults when zero)."""
    if opts is None:
        opts = ClientOptions()

    timeout = opts.timeout
    if timeout.total_seconds() == 0:
        timeout = timedelta(seconds=30)
    max_idle_conns = opts.max_idle_conns or defaultMaxIdleConns
    max_idle_conns_per_host = opts.max_idle_conns_per_host or defaultMaxIdleConnsPerHost
    idle_conn_timeout = opts.idle_conn_timeout
    if idle_conn_timeout.total_seconds() == 0:
        idle_conn_timeout = defaultIdleConnTimeout
    tls_handshake_timeout = opts.tls_handshake_timeout
    if tls_handshake_timeout.total_seconds() == 0:
        tls_handshake_timeout = defaultTLSHandshakeTimeout
    expect_continue_timeout = opts.expect_continue_timeout
    if expect_continue_timeout.total_seconds() == 0:
        expect_continue_timeout = defaultExpectContinueTimeout

    retry_policy = opts.retry_policy
    if retry_policy is None:
        retry_policy = DefaultRetryPolicy()

    limits = httpx.Limits(
        max_connections=opts.max_conns_per_host or None,
        max_keepalive_connections=max_idle_conns,
    )
    transport_timeout = httpx.Timeout(
        connect=tls_handshake_timeout.total_seconds(),
        pool=tls_handshake_timeout.total_seconds(),
        read=None,
        write=None,
    )

    transport = _transport_from_config(
        opts.proxy_config,
        opts.tls_config,
        limits=limits,
        timeout=transport_timeout,
    )
    if opts.disable_compression:
        transport = _make_transport(
            proxy=_proxy_url_of(opts.proxy_config),
            verify=True,
            limits=limits,
            timeout=transport_timeout,
        )

    hc = HTTPClient(
        client=None,  # type: ignore[arg-type]  # set right after construction
        transport=transport,
        retry_policy=retry_policy,
        proxy_config=opts.proxy_config,
        tls_config=opts.tls_config,
    )

    if opts.proxy_config is not None:
        err = hc._apply_proxy_config(opts.proxy_config)
        if err is not None:
            return None, _wrap("failed to apply proxy config", err)

    if opts.tls_config is not None:
        err = hc._apply_tls_config(opts.tls_config)
        if err is not None:
            return None, _wrap("failed to apply TLS config", err)

    client_timeout = httpx.Timeout(
        timeout.total_seconds(),
        connect=transport_timeout.connect,
        pool=transport_timeout.pool,
    )
    hc.client = httpx.Client(
        transport=hc.transport,
        timeout=client_timeout,
        follow_redirects=False,  # mirrors CheckRedirect -> ErrUseLastResponse
    )
    return hc, None


def _proxy_url_of(pc: ProxyConfig | str | None) -> str | None:
    if pc is None:
        return None
    if isinstance(pc, str):
        return pc
    try:
        return pc.GetProxyURL()
    except HttpError:
        return None


def _apply_proxy_config_impl(client: HTTPClient, pc: ProxyConfig) -> Exception | None:
    """Apply a proxy config to the client's transport."""
    proxy_url = _proxy_url_of(pc)
    if proxy_url is None:
        return ErrNoProxyConfigured
    client.transport = _make_transport(proxy=proxy_url)
    if client.client is not None:
        client.client._transport = client.transport
    client.proxy_config = pc
    return None


def _apply_tls_config_impl(client: HTTPClient, tc: TLSConfig) -> Exception | None:
    """Apply a TLS config to the client's transport."""
    try:
        ctx = tc.BuildClientTLSConfig()
    except HttpError as e:
        return e
    client.transport = _make_transport(
        proxy=_proxy_url_of(client.proxy_config),
        verify=cast(bool | str, ctx),
    )
    if client.client is not None:
        client.client._transport = client.transport
    client.tls_config = tc
    return None


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------


@dataclass
class PoolStats:
    """Connection pool statistics."""

    total_conns: int = 0
    idle_conns: int = 0
    active_conns: int = 0
    wait_count: int = 0
    wait_duration: timedelta = timedelta(0)
    max_idle_conns: int = 0
    max_idle_per_host: int = 0
    idle_conn_timeout: timedelta = timedelta(0)
    max_conns_per_host: int = 0


@dataclass
class PoolConfig:
    """Connection pool configuration."""

    max_idle_conns: int = 0
    max_idle_conns_per_host: int = 0
    idle_conn_timeout: timedelta = timedelta(0)
    max_conns_per_host: int = 0
    dialer_timeout: timedelta = timedelta(seconds=30)
    dialer_keep_alive: timedelta = timedelta(seconds=30)
    tls_handshake_timeout: timedelta = timedelta(0)
    expect_continue_timeout: timedelta = timedelta(0)
    disable_keep_alives: bool = False
    disable_compression: bool = False
    force_http2: bool = True


def DefaultPoolConfig() -> PoolConfig:
    """Return the default pool configuration (defaults)."""
    return PoolConfig(
        max_idle_conns=defaultMaxIdleConns,
        max_idle_conns_per_host=defaultMaxIdleConnsPerHost,
        idle_conn_timeout=defaultIdleConnTimeout,
        max_conns_per_host=0,
        dialer_timeout=timedelta(seconds=30),
        dialer_keep_alive=timedelta(seconds=30),
        tls_handshake_timeout=defaultTLSHandshakeTimeout,
        expect_continue_timeout=defaultExpectContinueTimeout,
        disable_keep_alives=False,
        disable_compression=False,
        force_http2=True,
    )


class ConnectionPool:
    """a shared transport with stats."""

    def __init__(
        self,
        transport: httpx.HTTPTransport,
        max_idle_conns: int,
        max_idle_per_host: int,
        idle_conn_timeout: timedelta,
        max_conns_per_host: int,
    ) -> None:
        self.transport = transport
        self.max_idle_conns = max_idle_conns
        self.max_idle_per_host = max_idle_per_host
        self.idle_conn_timeout = idle_conn_timeout
        self.max_conns_per_host = max_conns_per_host
        self.stats = PoolStats(
            max_idle_conns=max_idle_conns,
            max_idle_per_host=max_idle_per_host,
            idle_conn_timeout=idle_conn_timeout,
            max_conns_per_host=max_conns_per_host,
        )
        self.stats_mu = threading.RLock()
        self.closed = threading.Event()
        self.mu = threading.RLock()

    def GetTransport(self) -> httpx.HTTPTransport:
        """Return the pool transport."""
        with self.mu:
            return self.transport

    def SetMaxIdleConns(self, n: int) -> None:
        """Set the maximum idle connections."""
        with self.mu:
            self.max_idle_conns = n
            self.transport._pool._max_keepalive_connections = n
            with self.stats_mu:
                self.stats.max_idle_conns = n

    def SetMaxIdleConnsPerHost(self, n: int) -> None:
        """Set the maximum idle connections per host."""
        with self.mu:
            self.max_idle_per_host = n
            self.transport._pool._max_keepalive_connections = n
            with self.stats_mu:
                self.stats.max_idle_per_host = n

    def SetMaxConnsPerHost(self, n: int) -> None:
        """Set the maximum connections per host."""
        with self.mu:
            self.max_conns_per_host = n
            self.transport._pool._max_connections = n
            with self.stats_mu:
                self.stats.max_conns_per_host = n

    def SetIdleConnTimeout(self, d: timedelta) -> None:
        """Set the idle connection timeout."""
        with self.mu:
            self.idle_conn_timeout = d
            with self.stats_mu:
                self.stats.idle_conn_timeout = d

    def GetMaxIdleConns(self) -> int:
        """Return the maximum idle connections."""
        with self.mu:
            return self.max_idle_conns

    def GetMaxIdleConnsPerHost(self) -> int:
        """Return the maximum idle connections per host."""
        with self.mu:
            return self.max_idle_per_host

    def GetMaxConnsPerHost(self) -> int:
        """Return the maximum connections per host."""
        with self.mu:
            return self.max_conns_per_host

    def GetIdleConnTimeout(self) -> timedelta:
        """Return the idle connection timeout."""
        with self.mu:
            return self.idle_conn_timeout

    def Stats(self) -> PoolStats:
        """Return a snapshot of the pool statistics."""
        with self.stats_mu:
            stats = PoolStats(
                total_conns=self.stats.total_conns,
                idle_conns=self.stats.idle_conns,
                active_conns=max(0, self.stats.total_conns - self.stats.idle_conns),
                wait_count=self.stats.wait_count,
                wait_duration=self.stats.wait_duration,
                max_idle_conns=self.stats.max_idle_conns,
                max_idle_per_host=self.stats.max_idle_per_host,
                idle_conn_timeout=self.stats.idle_conn_timeout,
                max_conns_per_host=self.stats.max_conns_per_host,
            )
            return stats

    def CloseIdleConnections(self) -> None:
        """Close idle connections."""
        with self.mu:
            self.transport.close()

    def Close(self) -> None:
        """Close the pool (idempotent)."""
        self.closed.set()
        with self.mu:
            self.transport.close()

    def IsClosed(self) -> bool:
        """Return True if the pool has been closed."""
        return self.closed.is_set()

    def Clone(self) -> "ConnectionPool":
        """Return a pool with a fresh transport and copied settings."""
        with self.mu:
            new_transport = copy.copy(self.transport)
            new_pool = ConnectionPool(
                transport=new_transport,
                max_idle_conns=self.max_idle_conns,
                max_idle_per_host=self.max_idle_per_host,
                idle_conn_timeout=self.idle_conn_timeout,
                max_conns_per_host=self.max_conns_per_host,
            )
            with self.stats_mu:
                new_pool.stats = self.stats
            return new_pool

    def WithTLSClientConfig(self, tls_config: TLSConfig) -> None:
        """Apply a TLS config to the pool transport (raises on error)."""
        try:
            ctx = tls_config.BuildClientTLSConfig()
        except HttpError as e:
            raise e
        with self.mu:
            self.transport = _make_transport(
                proxy=_proxy_url_of(_env_proxy_url()), verify=cast(bool | str, ctx)
            )

    def WithProxy(self, proxy_url: str) -> None:
        """Apply a proxy URL to the pool transport (raises on error)."""
        config, err = NewProxyConfig(proxy_url)
        if err is not None:
            raise err
        if config is None:
            raise ErrNoProxyConfigured
        url = config.GetProxyURL()
        if url is None:
            raise ErrNoProxyConfigured
        with self.mu:
            self.transport = _make_transport(proxy=url)

    def Reset(self) -> None:
        """Close idle connections and reset the statistics."""
        with self.mu:
            self.transport.close()
            with self.stats_mu:
                self.stats = PoolStats(
                    max_idle_conns=self.max_idle_conns,
                    max_idle_per_host=self.max_idle_per_host,
                    idle_conn_timeout=self.idle_conn_timeout,
                    max_conns_per_host=self.max_conns_per_host,
                )


def NewConnectionPool(config: PoolConfig | None) -> ConnectionPool:
    """Create a connection pool from a config (defaults when None)."""
    if config is None:
        config = DefaultPoolConfig()

    limits = httpx.Limits(
        max_connections=config.max_conns_per_host or None,
        max_keepalive_connections=config.max_idle_conns,
    )
    timeout = httpx.Timeout(
        connect=config.tls_handshake_timeout.total_seconds(),
        pool=config.tls_handshake_timeout.total_seconds(),
        read=None,
        write=None,
    )
    transport = _transport_from_config(None, None, limits=limits, timeout=timeout)

    return ConnectionPool(
        transport=transport,
        max_idle_conns=config.max_idle_conns,
        max_idle_per_host=config.max_idle_conns_per_host,
        idle_conn_timeout=config.idle_conn_timeout,
        max_conns_per_host=config.max_conns_per_host,
    )


class PooledClient:
    """an HTTP client sharing a pool transport."""

    def __init__(
        self, client: httpx.Client, pool: ConnectionPool, timeout: timedelta
    ) -> None:
        self.client = client
        self.pool = pool
        self.timeout = timeout

    def Do(self, req: httpx.Request) -> tuple[httpx.Response | None, Exception | None]:
        """Send the request through the pool transport."""
        try:
            resp = self.client.send(req, stream=True)
            return resp, None
        except _TIMEOUT_ERRORS as e:
            return None, HttpError(str(e))
        except httpx.HTTPError as e:
            return None, HttpError(str(e))

    def DoWithContext(
        self, ctx: _Context, req: httpx.Request
    ) -> tuple[httpx.Response | None, Exception | None]:
        """Send the request with a context deadline/cancellation."""
        if ctx is not None and ctx.err() is not None:
            return None, HttpError("context canceled")
        req._ctx = ctx  # type: ignore[attr-defined]
        return self.Do(req)

    def GetPool(self) -> ConnectionPool:
        """Return the underlying pool."""
        return self.pool

    def GetClient(self) -> httpx.Client:
        """Return the underlying httpx client."""
        return self.client

    def SetTimeout(self, timeout: timedelta) -> None:
        """Set the request timeout."""
        self.timeout = timeout
        self.client.timeout = timeout.total_seconds()

    def Close(self) -> None:
        """Close the underlying pool."""
        self.pool.Close()


def NewPooledClient(pool: ConnectionPool, timeout: timedelta) -> PooledClient:
    """Create a pooled client (30s timeout when zero)."""
    if timeout.total_seconds() == 0:
        timeout = timedelta(seconds=30)
    client = httpx.Client(
        transport=pool.GetTransport(),
        timeout=timeout.total_seconds(),
        follow_redirects=False,
    )
    return PooledClient(client=client, pool=pool, timeout=timeout)


class PoolMonitor:
    """periodic pool statistics callback."""

    def __init__(
        self,
        pool: ConnectionPool,
        interval: timedelta,
        on_stats: Callable[[PoolStats], None] | None,
    ) -> None:
        if interval.total_seconds() == 0:
            interval = timedelta(seconds=10)
        self.pool = pool
        self.interval = interval
        self.on_stats = on_stats
        self.stop_evt = threading.Event()
        self.mu = threading.RLock()
        self.running = False
        self.thread: threading.Thread | None = None

    def Start(self) -> None:
        """Start the monitoring goroutine (daemon thread)."""
        with self.mu:
            if self.running:
                return
            self.running = True
            self.stop_evt.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def Stop(self) -> None:
        """Stop the monitoring thread."""
        with self.mu:
            if not self.running:
                return
            self.running = False
        self.stop_evt.set()

    def _run(self) -> None:
        while True:
            if self.stop_evt.wait(timeout=self.interval.total_seconds()):
                return
            stats = self.pool.Stats()
            if self.on_stats is not None:
                self.on_stats(stats)

    def IsRunning(self) -> bool:
        """Return True while the monitor thread is active."""
        with self.mu:
            return self.running


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


defaultMaxBodyLogSize = 1024 * 1024
sensitiveHeaders = (
    "authorization,proxy-authorization,www-authenticate,cookie,set-cookie,"
    "x-api-key,x-auth-token,access-token,refresh-token,secret,password,token,"
    "api-key,apikey"
)
sensitiveParams = (
    "password,secret,token,api_key,apikey,access_token,refresh_token,"
    "auth_code,code,client_secret"
)

_SENSITIVE_HEADER_RE = re.compile(
    r"(?i)^(authorization|proxy-authorization|www-authenticate|cookie|set-cookie|"
    r"x-api-key|x-auth-token|access-token|refresh-token|secret|password|token|"
    r"api-key|apikey)$"
)
_SENSITIVE_PARAM_RE = re.compile(
    r"(?i)(password|secret|token|api_key|apikey|access_token|refresh_token|"
    r"auth_code|code|client_secret)=([^&]+)"
)
_CREDIT_CARD_RE = re.compile(rb"\b(?:\d[ -]*?){13,16}\b")
_SSN_RE = re.compile(rb"\b\d{3}-?\d{2}-?\d{4}\b")
_EMAIL_RE = re.compile(rb"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")


class LogLevel(IntEnum):
    """Log level."""

    LogLevelNone = 0
    LogLevelError = 1
    LogLevelWarn = 2
    LogLevelInfo = 3
    LogLevelDebug = 4

    def String(self) -> str:
        names = {
            LogLevel.LogLevelNone: "NONE",
            LogLevel.LogLevelError: "ERROR",
            LogLevel.LogLevelWarn: "WARN",
            LogLevel.LogLevelInfo: "INFO",
            LogLevel.LogLevelDebug: "DEBUG",
        }
        return names.get(self, "UNKNOWN")


class Logger(Protocol):
    """the logging backend."""

    def Printf(self, format: str, *args: object) -> None: ...

    def Println(self, *args: object) -> None: ...


class _DefaultLogger:
    """prints to stdout."""

    def Printf(self, format: str, *args: object) -> None:
        msg = format % args if args else format
        print(msg)

    def Println(self, *args: object) -> None:
        print(*args)


class SanitizerFunc(Protocol):
    """Log sanitizer callback."""

    def __call__(self, data: bytes) -> bytes: ...


@dataclass
class LoggingConfig:
    """Logging configuration."""

    level: LogLevel = LogLevel.LogLevelInfo
    logger: Logger | None = None
    max_body_size: int = defaultMaxBodyLogSize
    log_request_headers: bool = True
    log_response_headers: bool = True
    log_request_body: bool = True
    log_response_body: bool = True
    sanitize_headers: bool = True
    sanitize_params: bool = True
    sanitize_body: bool = True
    include_timestamp: bool = True
    include_duration: bool = True
    include_remote_addr: bool = True
    include_user_agent: bool = True
    custom_sanitizers: list[SanitizerFunc] = field(default_factory=list)


def DefaultLoggingConfig() -> LoggingConfig:
    """Return the default logging configuration."""
    return LoggingConfig()


class HTTPLogger:
    """request/response logging with sanitization."""

    def __init__(self, config: LoggingConfig | None = None) -> None:
        if config is None:
            config = DefaultLoggingConfig()
        if config.logger is None:
            config.logger = _DefaultLogger()
        if config.max_body_size == 0:
            config.max_body_size = defaultMaxBodyLogSize
        self.config = config
        self.mu = threading.RLock()

    def LogRequest(self, req: httpx.Request) -> None:
        """Log an outgoing request."""
        if self.config.level < LogLevel.LogLevelInfo:
            return
        config = self.config
        buf: list[str] = []
        self._write_timestamp(buf)
        self._write_request_line(buf, req)
        self._write_remote_addr(buf, req)
        self._write_user_agent(buf, req)
        if config.log_request_headers:
            self._write_headers(
                buf, "Request Headers", _headers_of(req), config.sanitize_headers
            )
        if config.log_request_body and req.content:
            self._write_request_body(buf, req, config)
        if config.logger is not None:
            config.logger.Printf("%s", "".join(buf))

    def LogResponse(self, resp: httpx.Response, duration: timedelta) -> None:
        """Log a response with the given duration."""
        if self.config.level < LogLevel.LogLevelInfo:
            return
        config = self.config
        buf: list[str] = []
        self._write_timestamp(buf)
        self._write_response_line(buf, resp)
        if config.include_duration:
            buf.append(f" Duration: {_round_ms(duration)}")
        if config.log_response_headers:
            self._write_headers(
                buf, "Response Headers", _headers_of(resp), config.sanitize_headers
            )
        if config.log_response_body and resp.content:
            self._write_response_body(buf, resp, config)
        if config.logger is not None:
            config.logger.Printf("%s", "".join(buf))

    def LogRoundTrip(
        self,
        req: httpx.Request,
        resp: httpx.Response | None,
        duration: timedelta,
        err: Exception | None,
    ) -> None:
        """Log a full round trip (request + response or error)."""
        if self.config.level < LogLevel.LogLevelInfo and err is None:
            return
        config = self.config
        buf: list[str] = []
        self._write_timestamp(buf)
        if err is not None:
            buf.append(f" ERROR: {err}")
            if config.level >= LogLevel.LogLevelDebug:
                buf.append(" ")
                self._write_request_line(buf, req)
                self._write_remote_addr(buf, req)
        else:
            self._write_request_line(buf, req)
            self._write_remote_addr(buf, req)
            if resp is not None:
                self._write_response_line(buf, resp)
            if config.include_duration:
                buf.append(f" Duration: {_round_ms(duration)}")
        if config.logger is not None:
            config.logger.Printf("%s", "".join(buf))

    def _write_timestamp(self, buf: list[str]) -> None:
        if self.config.include_timestamp:
            buf.append(_now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " ")

    def _write_request_line(self, buf: list[str], req: httpx.Request) -> None:
        buf.append(f" {req.method} {req.url} HTTP/1.1")

    def _write_response_line(self, buf: list[str], resp: httpx.Response) -> None:
        text = http.client.responses.get(resp.status_code, _STR_UNKNOWN)
        buf.append(f" {resp.status_code} {text}")

    def _write_remote_addr(self, buf: list[str], req: httpx.Request) -> None:
        if self.config.include_remote_addr:
            buf.append(f" RemoteAddr: {_get_remote_addr(req)}")

    def _write_user_agent(self, buf: list[str], req: httpx.Request) -> None:
        if self.config.include_user_agent:
            ua = req.headers.get("user-agent", "")
            if ua:
                buf.append(f" User-Agent: {ua}")

    def _write_headers(
        self, buf: list[str], title: str, headers: list[tuple[str, str]], sanitize: bool
    ) -> None:
        buf.append(f"\n{title}:")
        for key, value in headers:
            if sanitize and _SENSITIVE_HEADER_RE.match(key):
                buf.append(f"\n  {key}: [REDACTED]")
                continue
            buf.append(f"\n  {key}: {value}")

    def _write_request_body(
        self, buf: list[str], req: httpx.Request, config: LoggingConfig
    ) -> None:
        body = req.content
        if len(body) == 0:
            buf.append("\nRequest Body: [empty]")
            return
        if config.sanitize_body:
            body = self._sanitize_body(body)
        if config.sanitize_params:
            body = self._sanitize_params(body)
        for sanitizer in config.custom_sanitizers:
            body = sanitizer(body)
        buf.append(
            f"\nRequest Body ({len(body)} bytes): {body.decode('utf-8', 'replace')}"
        )

    def _write_response_body(
        self, buf: list[str], resp: httpx.Response, config: LoggingConfig
    ) -> None:
        body = resp.content
        if len(body) == 0:
            buf.append("\nResponse Body: [empty]")
            return
        if config.sanitize_body:
            body = self._sanitize_body(body)
        for sanitizer in config.custom_sanitizers:
            body = sanitizer(body)
        buf.append(
            f"\nResponse Body ({len(body)} bytes): {body.decode('utf-8', 'replace')}"
        )

    def _sanitize_body(self, data: bytes) -> bytes:
        result = _CREDIT_CARD_RE.sub(b"[CREDIT_CARD_REDACTED]", data)
        result = _SSN_RE.sub(b"[SSN_REDACTED]", result)
        result = _EMAIL_RE.sub(b"[EMAIL_REDACTED]", result)
        return result

    def _sanitize_params(self, data: bytes) -> bytes:
        return cast(re.Pattern[bytes], _SENSITIVE_PARAM_RE).sub(b"\\1=[REDACTED]", data)

    def SetLevel(self, level: LogLevel) -> None:
        """Set the logging level."""
        with self.mu:
            self.config.level = level

    def GetLevel(self) -> LogLevel:
        """Return the logging level."""
        with self.mu:
            return self.config.level

    def SetConfig(self, config: LoggingConfig) -> None:
        """Replace the logging configuration."""
        with self.mu:
            self.config = config

    def GetConfig(self) -> LoggingConfig:
        """Return the logging configuration."""
        with self.mu:
            return self.config

    def Middleware(self, next: httpx.HTTPTransport) -> httpx.HTTPTransport:
        """Return a transport that logs every round trip."""
        logger = self

        class _LoggingTransport(httpx.HTTPTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                start = time.monotonic()
                logger.LogRequest(request)
                try:
                    resp = next.handle_request(request)
                except Exception as e:
                    logger.LogRoundTrip(
                        request, None, timedelta(seconds=time.monotonic() - start), e
                    )
                    raise
                duration = timedelta(seconds=time.monotonic() - start)
                logger.LogResponse(resp, duration)
                logger.LogRoundTrip(request, resp, duration, None)
                return resp

        _LoggingTransport.__name__ = "LoggedTransport"
        return _LoggingTransport(proxy=_env_proxy_url(), trust_env=False)


class LoggedTransport:
    """a transport with request logging."""

    def __init__(self, transport: httpx.HTTPTransport, logger: HTTPLogger) -> None:
        if transport is None:
            transport = _make_transport()
        self.transport = transport
        self.logger = logger

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Log and forward a request."""
        start = time.monotonic()
        self.logger.LogRequest(request)
        try:
            resp = self.transport.handle_request(request)
        except Exception as e:
            self.logger.LogRoundTrip(
                request, None, timedelta(seconds=time.monotonic() - start), e
            )
            raise
        duration = timedelta(seconds=time.monotonic() - start)
        self.logger.LogResponse(resp, duration)
        self.logger.LogRoundTrip(request, resp, duration, None)
        return resp

    def close(self) -> None:
        """Close the wrapped transport."""
        self.transport.close()

    def clone(self) -> "LoggedTransport":
        """Return a copy wrapping a fresh transport."""
        return LoggedTransport(self.transport, self.logger)


def NewLoggedTransport(
    transport: httpx.HTTPTransport | None, logger: HTTPLogger
) -> LoggedTransport:
    """Create a logged transport (defaults to a plain transport when None)."""
    if transport is None:
        transport = _make_transport()
    return LoggedTransport(transport, logger)


def _get_remote_addr(req: httpx.Request) -> str:
    """Mirror getRemoteAddr: X-Forwarded-For, then X-Real-IP, else ""."""
    xff: str = req.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    xri: str = req.headers.get("x-real-ip", "")
    if xri:
        return xri
    return ""


def _headers_of(obj: httpx.Request | httpx.Response) -> list[tuple[str, str]]:
    """Return headers as a list of (key, value) pairs (duplicates preserved)."""
    result: list[tuple[str, str]] = []
    for key, value in obj.headers.multi_items():
        result.append((key, value))
    return result


def _round_ms(d: timedelta) -> timedelta:
    """Round a duration to whole milliseconds (like time.Duration.Round)."""
    us = round(d.total_seconds() * 1_000_000 / 1000) * 1000
    return timedelta(microseconds=us)


# ---------------------------------------------------------------------------
# Dump helpers and public sanitizers
# ---------------------------------------------------------------------------


def DumpRequest(req: httpx.Request, body: bool = True) -> str:
    """Serialize a request for debugging (strings, not bytes)."""
    lines = [f"{req.method} {req.url} HTTP/1.1"]
    for key, value in _headers_of(req):
        lines.append(f"{key}: {value}")
    if body and req.content:
        lines.append("")
        lines.append(req.content.decode("utf-8", "replace"))
    return "\n".join(lines) + "\n"


def DumpRequestOut(req: httpx.Request, body: bool = True) -> str:
    """Serialize an outgoing request (alias of DumpRequest)."""
    return DumpRequest(req, body)


def DumpResponse(resp: httpx.Response, body: bool = True) -> str:
    """Serialize a response for debugging (strings, not bytes)."""
    text = http.client.responses.get(resp.status_code, _STR_UNKNOWN)
    lines = [f"HTTP/1.1 {resp.status_code} {text}"]
    for key, value in _headers_of(resp):
        lines.append(f"{key}: {value}")
    if body and resp.content:
        lines.append("")
        lines.append(resp.content.decode("utf-8", "replace"))
    return "\n".join(lines) + "\n"


def SanitizeHeaders(headers: httpx.Headers) -> httpx.Headers:
    """Return a copy of the headers with sensitive values redacted."""
    sanitized: list[tuple[str, str]] = []
    for key, value in headers.multi_items():
        if _SENSITIVE_HEADER_RE.match(key):
            sanitized.append((key, "[REDACTED]"))
        else:
            sanitized.append((key, value))
    return httpx.Headers(sanitized)


def SanitizeURL(url: str) -> str:
    """Redact sensitive query parameters in a URL string."""
    return _SENSITIVE_PARAM_RE.sub(r"\1=[REDACTED]", url)


def SanitizeBody(body: bytes) -> bytes:
    """Redact credit cards, SSNs, emails, and sensitive parameters."""
    result = _CREDIT_CARD_RE.sub(b"[CREDIT_CARD_REDACTED]", body)
    result = _SSN_RE.sub(b"[SSN_REDACTED]", result)
    result = _EMAIL_RE.sub(b"[EMAIL_REDACTED]", result)
    result = cast(re.Pattern[bytes], _SENSITIVE_PARAM_RE).sub(b"\\1=[REDACTED]", result)
    return result


# ---------------------------------------------------------------------------
# Logger in context
# ---------------------------------------------------------------------------

_logger_registry: weakref.WeakValueDictionary[int, HTTPLogger] = (
    weakref.WeakValueDictionary()
)
_logger_registry_lock = threading.RLock()

_loggerContextKey = "http_logger"


def WithLogger(ctx: _Context, logger: HTTPLogger) -> _Context:
    """Return a context carrying an HTTP logger (context.WithValue)."""
    with _logger_registry_lock:
        _logger_registry[id(ctx)] = logger
    return ctx


def LoggerFromContext(ctx: _Context) -> HTTPLogger | None:
    """Return the logger stored in the context, if any."""
    with _logger_registry_lock:
        logger = _logger_registry.get(id(ctx))
    if logger is not None:
        return logger
    return None
