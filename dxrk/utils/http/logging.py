# SPDX-License-Identifier: MIT
"""Logging helpers for dxrk.utils.http."""

from __future__ import annotations

import http.client
import re
import threading
import time
import weakref
from dataclasses import dataclass, field
from datetime import timedelta
from enum import IntEnum
from typing import Protocol, cast

import httpx

from .context import _Context, _now
from .errors import _STR_UNKNOWN
from .transport import _env_proxy_url, _make_transport

defaultMaxBodyLogSize = 1024 * 1024
sensitiveHeaders = (
    "authorization,proxy-authorization,www-authenticate,cookie,set-cookie,"
    "x-api-key,x-auth-token,access-token,refresh-token,secret,password,token,"
    "api-key,apikey"
)
sensitiveParams = "password,secret,token,api_key,apikey,access_token,refresh_token,auth_code,code,client_secret"

_SENSITIVE_HEADER_RE = re.compile(
    r"(?i)^(authorization|proxy-authorization|www-authenticate|cookie|set-cookie|"
    r"x-api-key|x-auth-token|access-token|refresh-token|secret|password|token|"
    r"api-key|apikey)$"
)
_SENSITIVE_PARAM_RE = re.compile(
    r"(?i)(password|secret|token|api_key|apikey|access_token|refresh_token|"
    r"auth_code|code|client_secret)=([^&]+)"
)
_SENSITIVE_PARAM_BYTES_RE = re.compile(
    rb"(?i)(password|secret|token|api_key|apikey|access_token|refresh_token|"
    rb"auth_code|code|client_secret)=([^&]+)"
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
            self._write_headers(buf, "Request Headers", _headers_of(req), config.sanitize_headers)
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
            self._write_headers(buf, "Response Headers", _headers_of(resp), config.sanitize_headers)
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

    def _write_headers(self, buf: list[str], title: str, headers: list[tuple[str, str]], sanitize: bool) -> None:
        buf.append(f"\n{title}:")
        for key, value in headers:
            if sanitize and _SENSITIVE_HEADER_RE.match(key):
                buf.append(f"\n  {key}: [REDACTED]")
                continue
            buf.append(f"\n  {key}: {value}")

    def _write_request_body(self, buf: list[str], req: httpx.Request, config: LoggingConfig) -> None:
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
        buf.append(f"\nRequest Body ({len(body)} bytes): {body.decode('utf-8', 'replace')}")

    def _write_response_body(self, buf: list[str], resp: httpx.Response, config: LoggingConfig) -> None:
        body = resp.content
        if len(body) == 0:
            buf.append("\nResponse Body: [empty]")
            return
        if config.sanitize_body:
            body = self._sanitize_body(body)
        for sanitizer in config.custom_sanitizers:
            body = sanitizer(body)
        buf.append(f"\nResponse Body ({len(body)} bytes): {body.decode('utf-8', 'replace')}")

    def _sanitize_body(self, data: bytes) -> bytes:
        result = _CREDIT_CARD_RE.sub(b"[CREDIT_CARD_REDACTED]", data)
        result = _SSN_RE.sub(b"[SSN_REDACTED]", result)
        result = _EMAIL_RE.sub(b"[EMAIL_REDACTED]", result)
        return result

    def _sanitize_params(self, data: bytes) -> bytes:
        return cast(re.Pattern[bytes], _SENSITIVE_PARAM_BYTES_RE).sub(b"\\1=[REDACTED]", data)

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
                    logger.LogRoundTrip(request, None, timedelta(seconds=time.monotonic() - start), e)
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
            self.logger.LogRoundTrip(request, None, timedelta(seconds=time.monotonic() - start), e)
            raise
        duration = timedelta(seconds=time.monotonic() - start)
        self.logger.LogResponse(resp, duration)
        self.logger.LogRoundTrip(request, resp, duration, None)
        return resp

    def close(self) -> None:
        """Close the wrapped transport."""
        self.transport.close()

    def clone(self) -> LoggedTransport:
        """Return a copy wrapping a fresh transport."""
        return LoggedTransport(self.transport, self.logger)


def NewLoggedTransport(transport: httpx.HTTPTransport | None, logger: HTTPLogger) -> LoggedTransport:
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
    result = cast(re.Pattern[bytes], _SENSITIVE_PARAM_BYTES_RE).sub(b"\\1=[REDACTED]", result)
    return result


_logger_registry: weakref.WeakValueDictionary[int, HTTPLogger] = weakref.WeakValueDictionary()
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


__all__ = [
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
    "SanitizerFunc",
    "LoggingConfig",
    "DefaultLoggingConfig",
    "HTTPLogger",
    "LoggedTransport",
    "NewLoggedTransport",
    "_get_remote_addr",
    "_headers_of",
    "_round_ms",
    "DumpRequest",
    "DumpRequestOut",
    "DumpResponse",
    "SanitizeHeaders",
    "SanitizeURL",
    "SanitizeBody",
    "_logger_registry",
    "_logger_registry_lock",
    "_loggerContextKey",
    "WithLogger",
    "LoggerFromContext",
]
