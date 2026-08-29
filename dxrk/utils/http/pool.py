# SPDX-License-Identifier: MIT
"""Connection pool for dxrk.utils.http."""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import cast

import httpx

from .errors import _TIMEOUT_ERRORS, ErrNoProxyConfigured, HttpError
from .proxy import NewProxyConfig
from .retry import (
    defaultExpectContinueTimeout,
    defaultIdleConnTimeout,
    defaultMaxIdleConns,
    defaultMaxIdleConnsPerHost,
    defaultTLSHandshakeTimeout,
)
from .tls import TLSConfig
from .transport import _env_proxy_url, _make_transport, _proxy_url_of, _transport_from_config


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
            self.transport._pool._max_keepalive_connections = n  # type: ignore[attr-defined]
            with self.stats_mu:
                self.stats.max_idle_conns = n

    def SetMaxIdleConnsPerHost(self, n: int) -> None:
        """Set the maximum idle connections per host."""
        with self.mu:
            self.max_idle_per_host = n
            self.transport._pool._max_keepalive_connections = n  # type: ignore[attr-defined]
            with self.stats_mu:
                self.stats.max_idle_per_host = n

    def SetMaxConnsPerHost(self, n: int) -> None:
        """Set the maximum connections per host."""
        with self.mu:
            self.max_conns_per_host = n
            self.transport._pool._max_connections = n  # type: ignore[attr-defined]
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

    def Clone(self) -> ConnectionPool:
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
            self.transport = _make_transport(proxy=_proxy_url_of(_env_proxy_url()), verify=cast(bool | str, ctx))

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

    def __init__(self, client: httpx.Client, pool: ConnectionPool, timeout: timedelta) -> None:
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

    def DoWithContext(self, ctx, req: httpx.Request) -> tuple[httpx.Response | None, Exception | None]:
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
        self.client.timeout = timeout.total_seconds()  # type: ignore[assignment]

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


__all__ = [
    "PoolStats",
    "PoolConfig",
    "DefaultPoolConfig",
    "ConnectionPool",
    "NewConnectionPool",
    "PooledClient",
    "NewPooledClient",
    "PoolMonitor",
]
