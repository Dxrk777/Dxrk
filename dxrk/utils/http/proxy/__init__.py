# SPDX-License-Identifier: MIT
"""Proxy configuration for dxrk.utils.http."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast
from urllib.parse import urlparse

from ..errors import (
    ErrInvalidProxyURL,
    ErrNoProxyConfigured,
    ErrUnsupportedProxy,
    HttpError,
    _wrap,
)


class ProxyType(StrEnum):
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

    def __str__(self) -> str:
        """Return "user:pass" (or "user"); "" without a username."""
        if self.username == "":
            return ""
        if self.password == "":
            return self.username
        return self.username + ":" + self.password

    def to_string(self) -> str:
        """Backwards-compatible alias for ``str(auth)``."""
        return str(self)

    # Backwards-compatible alias (Go-style name).
    String = to_string

    def encode(self) -> str:
        """Return "user:pass"; "" without a username."""
        if self.username == "":
            return ""
        return self.username + ":" + self.password

    # Backwards-compatible alias (Go-style name).
    Encode = encode


@dataclass
class ProxyConfig:
    """Proxy configuration."""

    type: ProxyType = ProxyType.ProxyTypeHTTP
    host: str = ""
    port: int = 0
    auth: ProxyAuth | None = None
    bypass: list[str] = field(default_factory=list)
    no_proxy: str = ""

    def get_proxy_url(self) -> str | None:
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
        if not self.host:
            return None
        host_port = _join_host_port(self.host, self.proxy_port())
        auth = ""
        if self.auth is not None:
            auth = self.auth.encode()
            if auth:
                auth = auth + "@"
        return f"{scheme}://{auth}{host_port}"

    # Backwards-compatible alias (Go-style name).
    GetProxyURL = get_proxy_url

    def proxy_port(self) -> int:
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

    # Backwards-compatible alias (Go-style name).
    ProxyPort = proxy_port

    def __str__(self) -> str:
        """Return the proxy URL; "" if it cannot be serialized."""
        try:
            return self.get_proxy_url() or ""
        except HttpError:
            return ""

    def to_string(self) -> str:
        """Backwards-compatible alias for ``str(config)``."""
        return str(self)

    # Backwards-compatible alias (Go-style name).
    String = to_string

    def should_bypass(self, host: str) -> bool:
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

    # Backwards-compatible alias (Go-style name).
    ShouldBypass = should_bypass

    def add_bypass(self, pattern: str) -> None:
        """Add a bypass pattern (ignored when empty)."""
        if pattern != "":
            self.bypass.append(pattern)

    # Backwards-compatible alias (Go-style name).
    AddBypass = add_bypass

    def set_no_proxy(self, no_proxy: str) -> None:
        """Set the no-proxy pattern list."""
        self.no_proxy = no_proxy

    # Backwards-compatible alias (Go-style name).
    SetNoProxy = set_no_proxy

    def clone(self) -> ProxyConfig:
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

    # Backwards-compatible alias (Go-style name).
    Clone = clone


def new_proxy_config(proxy_url: str) -> tuple[ProxyConfig | None, Exception | None]:
    """Parse a proxy URL into a ProxyConfig )."""
    if proxy_url == "":
        return None, ErrInvalidProxyURL
    try:
        parsed = urlparse(proxy_url)
    except ValueError as e:
        return None, _wrap(str(ErrInvalidProxyURL), e)

    try:
        scheme = (parsed.scheme or "").lower()
        proxy_type = cast(ProxyType, ProxyType(scheme) if scheme else None)
    except ValueError:
        return None, HttpError(f"{ErrUnsupportedProxy}: {parsed.scheme}")
    if proxy_type not in (
        ProxyType.ProxyTypeHTTP,
        ProxyType.ProxyTypeHTTPS,
        ProxyType.ProxyTypeSOCKS4,
        ProxyType.ProxyTypeSOCKS5,
    ):
        return None, HttpError(f"{ErrUnsupportedProxy}: {parsed.scheme}")

    host = parsed.hostname or ""
    port = 0
    try:
        raw_port = parsed.port
    except ValueError as e:
        return None, _wrap(str(ErrInvalidProxyURL), e)
    if raw_port is not None:
        port = int(raw_port)
    else:
        if proxy_type is ProxyType.ProxyTypeHTTP:
            port = 8080
        elif proxy_type is ProxyType.ProxyTypeHTTPS:
            port = 8443
        else:
            # Solo quedan SOCKS4/SOCKS5: el guard de arriba ya rechazó
            # cualquier otro esquema, así que el fall-through era inalcanzable.
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


def new_http_proxy(host: str, port: int, auth: ProxyAuth | None = None) -> ProxyConfig:
    """Create an HTTP proxy config."""
    return ProxyConfig(type=ProxyType.ProxyTypeHTTP, host=host, port=port, auth=auth)


# Backwards-compatible alias (Go-style name).
NewProxyConfig = new_proxy_config


# Backwards-compatible alias (Go-style name).
NewHTTPProxy = new_http_proxy


def new_https_proxy(host: str, port: int, auth: ProxyAuth | None = None) -> ProxyConfig:
    """Create an HTTPS proxy config."""
    return ProxyConfig(type=ProxyType.ProxyTypeHTTPS, host=host, port=port, auth=auth)


# Backwards-compatible alias (Go-style name).
NewHTTPSProxy = new_https_proxy


def new_socks5_proxy(host: str, port: int, auth: ProxyAuth | None = None) -> ProxyConfig:
    """Create a SOCKS5 proxy config."""
    return ProxyConfig(type=ProxyType.ProxyTypeSOCKS5, host=host, port=port, auth=auth)


# Backwards-compatible alias (Go-style name).
NewSOCKS5Proxy = new_socks5_proxy


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


def get_proxy_from_environment() -> ProxyConfig | None:
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
    config, err = new_proxy_config(proxy_url)
    if err is not None or config is None:
        return None
    no_proxy = os.environ.get("NO_PROXY", "")
    if no_proxy == "":
        no_proxy = os.environ.get("no_proxy", "")
    config.set_no_proxy(no_proxy)
    return config


# Backwards-compatible alias (Go-style name).
GetProxyFromEnvironment = get_proxy_from_environment


def parse_proxy_url(proxy_url: str) -> tuple[ProxyConfig | None, Exception | None]:
    """Parse a proxy URL (alias of new_proxy_config)."""
    return new_proxy_config(proxy_url)


# Backwards-compatible alias (Go-style name).
ParseProxyURL = parse_proxy_url


def must_parse_proxy_url(proxy_url: str) -> ProxyConfig:
    """Parse a proxy URL; raises (panic equivalent) on error."""
    config, err = new_proxy_config(proxy_url)
    if err is not None:
        raise err
    if config is None:
        raise ErrInvalidProxyURL
    return config


# Backwards-compatible alias (Go-style name).
MustParseProxyURL = must_parse_proxy_url


__all__ = [
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
]
