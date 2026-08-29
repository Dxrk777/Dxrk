# SPDX-License-Identifier: MIT
"""HTTP client for dxrk.utils.http."""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlparse

import httpx

from .context import _CTX_CANCELED, _Context
from .errors import _TIMEOUT_ERRORS, ErrInvalidProxyURL, HttpError, _wrap
from .proxy import ProxyConfig
from .retry import (
    DefaultRetryPolicy,
    RetryPolicy,
    _is_retryable_error,
    defaultExpectContinueTimeout,
    defaultIdleConnTimeout,
    defaultMaxIdleConns,
    defaultTLSHandshakeTimeout,
)
from .tls import TLSConfig
from .transport import (
    _apply_proxy_config_impl,
    _apply_tls_config_impl,
    _make_transport,
    _proxy_url_of,
    _transport_from_config,
)


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
        from .errors import ErrMaxRetriesExceeded

        return None, ErrMaxRetriesExceeded

    def _send(self, req: httpx.Request) -> tuple[httpx.Response | None, Exception | None]:
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

    def DoWithContext(self, ctx: _Context, req: httpx.Request) -> tuple[httpx.Response | None, Exception | None]:
        """Send the request with a context deadline/cancellation."""
        if ctx is not None and ctx.err() is not None:
            return None, HttpError(_CTX_CANCELED)
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
            self.client._transport = self.transport  # type: ignore[attr-defined]

    def CloseIdleConnections(self) -> None:
        """Close idle connections held by the transport."""
        with self.mu:
            self.transport.close()

    def Clone(self) -> HTTPClient:
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

    def WithMiddleware(self, middleware: Callable[[httpx.HTTPTransport], httpx.HTTPTransport]) -> HTTPClient:
        """Wrap the transport with middleware (e.g. a logging transport)."""
        with self.mu:
            new_transport = _make_transport()
            new_transport = middleware(new_transport)
            self.transport = new_transport
            self.client._transport = new_transport  # type: ignore[attr-defined]
            return self


def _client_timeout(req: httpx.Request, default: float | httpx.Timeout = 30.0) -> httpx.Timeout:
    """Compute the client timeout for a request (ctx deadline wins)."""
    ctx = getattr(req, "_ctx", None)
    if ctx is not None and ctx.remaining() is not None:
        return httpx.Timeout(ctx.remaining() or 0.0)
    return httpx.Timeout(default)


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


__all__ = [
    "ClientOptions",
    "HTTPClient",
    "_client_timeout",
    "_is_retryable_error",
    "NewHTTPClient",
]
