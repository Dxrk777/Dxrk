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

import httpx as _httpx

# Re-export httpx so ``from dxrk.utils.http import httpx`` and ``hx.httpx`` work.
httpx = _httpx

# errors
# client
from .client import (
    ClientOptions,
    HTTPClient,
    NewHTTPClient,
    _client_timeout,
    new_http_client,
)

# context
from .context import (
    _CTX_CANCELED,
    _CTX_DEADLINE,
    _ZERO_TIME,
    _background,
    _Context,
    _get_value,
    _is_zero,
    _now,
    _with_cancel,
    _with_timeout,
    _with_value,
)
from .errors import (
    _STR_ERROR,
    _STR_UNKNOWN,
    _TIMEOUT_ERRORS,
    ErrCertKeyMismatch,
    ErrInvalidCA,
    ErrInvalidCert,
    ErrInvalidKey,
    ErrInvalidProxyAuth,
    ErrInvalidProxyURL,
    ErrInvalidTLSConfig,
    ErrMaxRetriesExceeded,
    ErrMissingCertOrKey,
    ErrNoProxyConfigured,
    ErrProxyAuthRequired,
    ErrUnsupportedProxy,
    HttpError,
    _wrap,
)

# logging
from .logging import (
    _CREDIT_CARD_RE,
    _EMAIL_RE,
    _SENSITIVE_HEADER_RE,
    _SENSITIVE_PARAM_BYTES_RE,
    _SENSITIVE_PARAM_RE,
    _SSN_RE,
    DefaultLoggingConfig,
    DumpRequest,
    DumpRequestOut,
    DumpResponse,
    HTTPLogger,
    LoggedTransport,
    Logger,
    LoggerFromContext,
    LoggingConfig,
    LogLevel,
    NewLoggedTransport,
    SanitizeBody,
    SanitizeHeaders,
    SanitizerFunc,
    SanitizeURL,
    WithLogger,
    _DefaultLogger,
    _emit_log,
    _get_remote_addr,
    _headers_of,
    _logger_registry,
    _logger_registry_lock,
    _loggerContextKey,
    _round_ms,
    default_logging_config,
    defaultMaxBodyLogSize,
    dump_request,
    dump_request_out,
    dump_response,
    logger_from_context,
    new_logged_transport,
    sanitize_body,
    sanitize_headers,
    sanitize_url,
    sensitiveHeaders,
    sensitiveParams,
    with_logger,
)

# pool
from .pool import (
    ConnectionPool,
    DefaultPoolConfig,
    NewConnectionPool,
    NewPooledClient,
    PoolConfig,
    PooledClient,
    PoolMonitor,
    PoolStats,
    default_pool_config,
    new_connection_pool,
    new_pooled_client,
)

# proxy
from .proxy import (
    GetProxyFromEnvironment,
    MustParseProxyURL,
    NewHTTPProxy,
    NewHTTPSProxy,
    NewProxyConfig,
    NewSOCKS5Proxy,
    ParseProxyURL,
    ProxyAuth,
    ProxyConfig,
    ProxyType,
    _join_host_port,
    _match_bypass,
    _parse_bypass_list,
    _parse_query,
    get_proxy_from_environment,
    must_parse_proxy_url,
    new_http_proxy,
    new_https_proxy,
    new_proxy_config,
    new_socks5_proxy,
    parse_proxy_url,
)

# retry
from .retry import (
    DefaultRetryPolicy,
    RetryPolicy,
    _is_retryable_error,
    default_retry_policy,
    defaultExpectContinueTimeout,
    defaultIdleConnTimeout,
    defaultMaxIdleConns,
    defaultMaxIdleConnsPerHost,
    defaultMaxRetries,
    defaultRetryBackoff,
    defaultTLSHandshakeTimeout,
    policy_is_retryable,
)

# tls
from .tls import (
    _DEFAULT_CIPHER_SUITES,
    _DEFAULT_CURVE_PREFERENCES,
    VERSION_TLS12,
    VERSION_TLS13,
    CertificateToPEM,
    ClientAuthType,
    LoadSystemCertPool,
    NewCertPool,
    NewTLSConfig,
    ParseCertificate,
    ParsePrivateKey,
    PrivateKeyToPEM,
    TLSConfig,
    _pem_decode,
    certificate_to_pem,
    load_system_cert_pool,
    new_cert_pool,
    new_tls_config,
    parse_certificate,
    parse_private_key,
    private_key_to_pem,
)

# transport
from .transport import (
    Transport,
    _apply_proxy_config_impl,
    _apply_tls_config_impl,
    _build_client_tls_config,
    _env_proxy_url,
    _make_transport,
    _proxy_url_of,
    _proxy_url_of_impl,
    _transport_from_config,
)

# Re-export _is_retryable_error also from client for backwards compat (client imports it)
# Already imported from retry; keep both.

__all__ = [
    # httpx passthrough
    "httpx",
    # errors
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
    # context
    "_Context",
    "_background",
    "_with_cancel",
    "_with_timeout",
    "_with_value",
    "_get_value",
    "_now",
    "_is_zero",
    "_ZERO_TIME",
    "_CTX_CANCELED",
    "_CTX_DEADLINE",
    # retry
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
    # tls
    "ClientAuthType",
    "VERSION_TLS12",
    "VERSION_TLS13",
    "_DEFAULT_CIPHER_SUITES",
    "_DEFAULT_CURVE_PREFERENCES",
    "TLSConfig",
    "new_tls_config",
    "NewTLSConfig",
    "_pem_decode",
    "parse_certificate",
    "ParseCertificate",
    "parse_private_key",
    "ParsePrivateKey",
    "certificate_to_pem",
    "CertificateToPEM",
    "private_key_to_pem",
    "PrivateKeyToPEM",
    "load_system_cert_pool",
    "LoadSystemCertPool",
    "new_cert_pool",
    "NewCertPool",
    # proxy
    "ProxyType",
    "ProxyAuth",
    "ProxyConfig",
    "new_proxy_config",
    "NewProxyConfig",
    "new_http_proxy",
    "NewHTTPProxy",
    "new_https_proxy",
    "NewHTTPSProxy",
    "new_socks5_proxy",
    "NewSOCKS5Proxy",
    "_parse_bypass_list",
    "_match_bypass",
    "_parse_query",
    "_join_host_port",
    "get_proxy_from_environment",
    "GetProxyFromEnvironment",
    "parse_proxy_url",
    "ParseProxyURL",
    "must_parse_proxy_url",
    "MustParseProxyURL",
    # transport
    "Transport",
    "_build_client_tls_config",
    "_env_proxy_url",
    "_make_transport",
    "_transport_from_config",
    "_proxy_url_of",
    "_proxy_url_of_impl",
    "_apply_proxy_config_impl",
    "_apply_tls_config_impl",
    # client
    "ClientOptions",
    "HTTPClient",
    "_client_timeout",
    "new_http_client",
    "NewHTTPClient",
    # pool
    "PoolStats",
    "PoolConfig",
    "default_pool_config",
    "DefaultPoolConfig",
    "ConnectionPool",
    "new_connection_pool",
    "NewConnectionPool",
    "PooledClient",
    "new_pooled_client",
    "NewPooledClient",
    "PoolMonitor",
    # logging
    "defaultMaxBodyLogSize",
    "sensitiveHeaders",
    "sensitiveParams",
    "_SENSITIVE_HEADER_RE",
    "_SENSITIVE_PARAM_RE",
    "_SENSITIVE_PARAM_BYTES_RE",
    "_CREDIT_CARD_RE",
    "_SSN_RE",
    "_EMAIL_RE",
    "LogLevel",
    "Logger",
    "_DefaultLogger",
    "_emit_log",
    "SanitizerFunc",
    "LoggingConfig",
    "default_logging_config",
    "DefaultLoggingConfig",
    "HTTPLogger",
    "LoggedTransport",
    "new_logged_transport",
    "NewLoggedTransport",
    "_get_remote_addr",
    "_headers_of",
    "_round_ms",
    "dump_request",
    "DumpRequest",
    "dump_request_out",
    "DumpRequestOut",
    "dump_response",
    "DumpResponse",
    "sanitize_headers",
    "SanitizeHeaders",
    "sanitize_url",
    "SanitizeURL",
    "sanitize_body",
    "SanitizeBody",
    "_logger_registry",
    "_logger_registry_lock",
    "_loggerContextKey",
    "with_logger",
    "WithLogger",
    "logger_from_context",
    "LoggerFromContext",
]
