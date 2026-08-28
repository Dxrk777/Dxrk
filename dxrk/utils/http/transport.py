# SPDX-License-Identifier: MIT
"""Transport helpers for dxrk.utils.http."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

import httpx

from .errors import ErrNoProxyConfigured, HttpError
from .proxy import GetProxyFromEnvironment, ProxyConfig
from .tls import TLSConfig

if TYPE_CHECKING:
    from .client import HTTPClient


class Transport(Protocol):
    """A transport that can handle requests (httpx.HTTPTransport compatible)."""

    def handle_request(self, request: httpx.Request) -> httpx.Response: ...

    def close(self) -> None: ...

    def clone(self) -> Transport: ...


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
            verify = tls_config.ca_data.decode("utf-8", "replace") if tls_config.ca_data else tls_config.ca_file

    return _make_transport(proxy=proxy, verify=verify, limits=limits, timeout=timeout)


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
        client.client._transport = client.transport  # type: ignore[attr-defined]
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
        client.client._transport = client.transport  # type: ignore[attr-defined]
    client.tls_config = tc
    return None


__all__ = [
    "Transport",
    "_env_proxy_url",
    "_make_transport",
    "_transport_from_config",
    "_proxy_url_of",
    "_apply_proxy_config_impl",
    "_apply_tls_config_impl",
]
