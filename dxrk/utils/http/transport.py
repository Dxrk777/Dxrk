# SPDX-License-Identifier: MIT
"""Transport helpers for dxrk.utils.http."""

from __future__ import annotations

import ssl
from typing import TYPE_CHECKING, Protocol, cast

import httpx

from .errors import ErrNoProxyConfigured, HttpError
from .proxy import ProxyConfig, get_proxy_from_environment
from .tls import TLSConfig

if TYPE_CHECKING:
    from .client import HTTPClient


class Transport(Protocol):
    """A transport that can handle requests (httpx.HTTPTransport compatible)."""

    def handle_request(self, request: httpx.Request) -> httpx.Response: ...

    def close(self) -> None: ...

    def clone(self) -> Transport: ...


def _proxy_url_of_impl(pc: ProxyConfig) -> str | None:
    """Call ``get_proxy_url`` (or legacy ``GetProxyURL``) on a proxy config."""
    get = getattr(pc, "get_proxy_url", None)
    if callable(get):
        return cast("str | None", get())
    legacy = getattr(pc, "GetProxyURL", None)
    if callable(legacy):
        return cast("str | None", legacy())
    raise AttributeError("proxy config must implement get_proxy_url()")


def _build_client_tls_config(tc: TLSConfig) -> ssl.SSLContext:
    """Call ``build_client_tls_config`` (or legacy ``BuildClientTLSConfig``)."""
    build = getattr(tc, "build_client_tls_config", None)
    if callable(build):
        return cast(ssl.SSLContext, build())
    legacy = getattr(tc, "BuildClientTLSConfig", None)
    if callable(legacy):
        return cast(ssl.SSLContext, legacy())
    raise AttributeError("TLS config must implement build_client_tls_config()")


def _env_proxy_url() -> str | None:
    """Return the environment proxy URL for the transport, or None."""
    pc = get_proxy_from_environment()
    if pc is None:
        return None
    try:
        return _proxy_url_of_impl(pc)
    except HttpError:
        return None


def _make_transport(
    proxy: str | None = None,
    verify: bool | str | ssl.SSLContext = True,
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
            proxy = _proxy_url_of_impl(proxy_config)
        except HttpError:
            proxy = None
    if proxy is None:
        proxy = _env_proxy_url()

    verify: bool | str | ssl.SSLContext = True
    if tls_config is not None:
        if tls_config.insecure_skip_verify:
            verify = False
        elif tls_config.ca_data or tls_config.ca_file or tls_config.cert_data or tls_config.cert_file:
            try:
                verify = _build_client_tls_config(tls_config)
            except HttpError:
                verify = True

    return _make_transport(proxy=proxy, verify=verify, limits=limits, timeout=timeout)


def _proxy_url_of(pc: ProxyConfig | str | None) -> str | None:
    if pc is None:
        return None
    if isinstance(pc, str):
        return pc
    try:
        return _proxy_url_of_impl(pc)
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
        ctx = _build_client_tls_config(tc)
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
    "_build_client_tls_config",
    "_env_proxy_url",
    "_make_transport",
    "_proxy_url_of",
    "_proxy_url_of_impl",
    "_transport_from_config",
    "_apply_proxy_config_impl",
    "_apply_tls_config_impl",
]
