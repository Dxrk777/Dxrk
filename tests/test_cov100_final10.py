# SPDX-License-Identifier: MIT
"""Cobertura 100% final10 — logging/pool/proxy ramas restantes.

Tests reales de comportamiento: cada test ejercita líneas/ramas exactas del
``coverage report --show-missing``. Sin red real, sin pragma, sin relleno.
Incluye 1 simplificación en código: proxy new_proxy_config (elif SOCKS
inalcanzable → else, el guard ya rechazó otros esquemas).
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import httpx
import pytest


class _Cap:
    """Logger backend de captura."""

    def __init__(self) -> None:
        self.msgs: list[str] = []

    def printf(self, format: str, *args: object) -> None:
        self.msgs.append(format % args if args else format)

    def println(self, *args: object) -> None:
        self.msgs.append(" ".join(str(a) for a in args))


def _req(content: bytes | None = None) -> httpx.Request:
    if content is not None:
        return httpx.Request("POST", "http://example.com/", content=content)
    return httpx.Request("GET", "http://example.com/")


def _resp(req: httpx.Request, content: bytes = b"ok") -> httpx.Response:
    return httpx.Response(200, request=req, content=content)


# ═══════════ logging.py 87, 89, 123 — cuerpos abstractos Protocol ═══════════


class TestProtocolBodies:
    def test_logger_printf_body(self) -> None:
        from dxrk.utils.http.logging import Logger

        assert Logger.printf(object(), "hi %s", "x") is None

    def test_logger_println_body(self) -> None:
        from dxrk.utils.http.logging import Logger

        assert Logger.println(object(), "hi") is None

    def test_sanitizer_func_body(self) -> None:
        from dxrk.utils.http.logging import SanitizerFunc

        assert SanitizerFunc.__call__(object(), b"x") is None


# ═══════════ logging.py 96-97, 100 — _DefaultLogger ═══════════


class TestDefaultLogger:
    def test_printf_with_and_without_args(self, capsys: pytest.CaptureFixture[str]) -> None:
        from dxrk.utils.http.logging import _DefaultLogger

        d = _DefaultLogger()
        d.printf("hi %s", "x")
        assert "hi x" in capsys.readouterr().out
        d.printf("plain")
        assert "plain" in capsys.readouterr().out

    def test_println(self, capsys: pytest.CaptureFixture[str]) -> None:
        from dxrk.utils.http.logging import _DefaultLogger

        _DefaultLogger().println("a", "b")
        assert "a b" in capsys.readouterr().out


# ═══════════ logging.py 113-117 — _emit_log legacy + raise ═══════════


class TestEmitLog:
    def test_legacy_printf_backend(self) -> None:
        from dxrk.utils.http.logging import _emit_log

        seen: list[str] = []

        class _Legacy:
            def Printf(self, fmt: str, *args: object) -> None:
                seen.append(fmt % args if args else fmt)

        _emit_log(_Legacy(), "hi %s", "x")  # type: ignore[arg-type]
        assert seen == ["hi x"]

    def test_no_backend_raises(self) -> None:
        from dxrk.utils.http.logging import _emit_log

        with pytest.raises(AttributeError, match="printf"):
            _emit_log(object(), "hi")  # type: ignore[arg-type]


# ═══════════ logging.py 183, 203, 235 — logger None ═══════════


class TestLoggerNone:
    def test_log_request_logger_none(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, LogLevel

        lg = HTTPLogger(LoggingConfig(logger=_Cap(), level=LogLevel.LogLevelInfo))
        lg.config.logger = None
        lg.log_request(_req())  # no emite, no rompe

    def test_log_response_logger_none(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, LogLevel

        lg = HTTPLogger(LoggingConfig(logger=_Cap(), level=LogLevel.LogLevelInfo))
        lg.config.logger = None
        lg.log_response(_resp(_req()), timedelta(milliseconds=1))

    def test_log_round_trip_logger_none(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, LogLevel

        lg = HTTPLogger(LoggingConfig(logger=_Cap(), level=LogLevel.LogLevelInfo))
        lg.config.logger = None
        lg.log_round_trip(_req(), None, timedelta(milliseconds=1), None)


# ═══════════ logging.py 197, 199, 201 — log_response mínimo ═══════════


class TestLogResponseMinimal:
    def test_no_duration_no_headers_no_body(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, LogLevel

        cap = _Cap()
        cfg = LoggingConfig(
            logger=cap,
            level=LogLevel.LogLevelInfo,
            include_duration=False,
            log_response_headers=False,
            log_response_body=False,
        )
        HTTPLogger(cfg).log_response(_resp(_req(), b"secreto"), timedelta(milliseconds=5))
        assert len(cap.msgs) == 1
        assert "Duration" not in cap.msgs[0]
        assert "Response Headers" not in cap.msgs[0]
        assert "secreto" not in cap.msgs[0]


# ═══════════ logging.py 231, 233 — round_trip sin resp y sin duración ═══════════


class TestLogRoundTripMinimal:
    def test_resp_none_no_duration(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, LogLevel

        cap = _Cap()
        cfg = LoggingConfig(logger=cap, level=LogLevel.LogLevelInfo, include_duration=False)
        HTTPLogger(cfg).log_round_trip(_req(), None, timedelta(milliseconds=5), None)
        assert len(cap.msgs) == 1
        assert "GET http://example.com/" in cap.msgs[0]
        assert "Duration" not in cap.msgs[0]


# ═══════════ logging.py 242, 253, 257 — flags de escritura apagados ═══════════


class TestWriteFlagsOff:
    def test_no_timestamp_no_remote_no_ua(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, LogLevel

        cap = _Cap()
        cfg = LoggingConfig(
            logger=cap,
            level=LogLevel.LogLevelInfo,
            include_timestamp=False,
            include_remote_addr=False,
            include_user_agent=False,
        )
        req = _req()
        req.headers["User-Agent"] = "ua-test"
        HTTPLogger(cfg).log_request(req)
        assert "User-Agent" not in cap.msgs[0]
        assert "RemoteAddr" not in cap.msgs[0]
        # sin timestamp el mensaje arranca con el request-line
        assert cap.msgs[0].lstrip().startswith("GET")


# ═══════════ logging.py 273-274, 277, 287-288, 289 — cuerpos vacíos/sin sanitize ═══════════


class TestWriteBodies:
    def test_request_body_empty(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, LogLevel

        cap = _Cap()
        lg = HTTPLogger(LoggingConfig(logger=cap, level=LogLevel.LogLevelInfo))
        buf: list[str] = []
        lg._write_request_body(buf, httpx.Request("POST", "http://example.com/", content=b""), lg.config)
        assert buf == ["\nRequest Body: [empty]"]

    def test_request_body_no_sanitize_params(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, LogLevel

        cap = _Cap()
        cfg = LoggingConfig(logger=cap, level=LogLevel.LogLevelInfo, sanitize_params=False)
        lg = HTTPLogger(cfg)
        buf: list[str] = []
        lg._write_request_body(buf, _req(b"password=hunter2&ok=1"), cfg)
        assert "password=hunter2" in buf[0]

    def test_response_body_empty(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, LogLevel

        lg = HTTPLogger(LoggingConfig(logger=_Cap(), level=LogLevel.LogLevelInfo))
        buf: list[str] = []
        lg._write_response_body(buf, httpx.Response(200, request=_req(), content=b""), lg.config)
        assert buf == ["\nResponse Body: [empty]"]

    def test_response_body_no_sanitize_body(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, LogLevel

        cap = _Cap()
        cfg = LoggingConfig(logger=cap, level=LogLevel.LogLevelInfo, sanitize_body=False)
        lg = HTTPLogger(cfg)
        buf: list[str] = []
        lg._write_response_body(buf, httpx.Response(200, request=_req(), content=b"mail a@b.com"), cfg)
        assert "a@b.com" in buf[0]


# ═══════════ logging.py 360-363 — middleware close ═══════════


class TestMiddlewareClose:
    def test_close_forwards_and_releases(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, LogLevel

        closed: list[str] = []

        class _Next(httpx.HTTPTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, request=request, content=b"ok")

            def close(self) -> None:
                closed.append("next")

        lg = HTTPLogger(LoggingConfig(logger=_Cap(), level=LogLevel.LogLevelInfo))
        tr = lg.middleware(_Next())
        tr.close()
        assert closed == ["next"]


# ═══════════ logging.py 377, 406-408 — transport None / con transport ═══════════


class TestLoggedTransportCtor:
    def test_none_builds_default(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggedTransport, LoggingConfig

        lt = LoggedTransport(None, HTTPLogger(LoggingConfig(logger=_Cap())))  # type: ignore[arg-type]
        assert lt.transport is not None
        lt.close()

    def test_new_with_explicit_transport(self) -> None:
        from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, new_logged_transport

        class _Fake(httpx.HTTPTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, request=request, content=b"ok")

            def close(self) -> None:
                pass

        fake = _Fake()
        lt = new_logged_transport(fake, HTTPLogger(LoggingConfig(logger=_Cap())))
        assert lt.transport is fake


# ═══════════ logging.py 520 — truncado ═══════════


class TestTruncateBody:
    def test_truncates_over_max(self) -> None:
        from dxrk.utils.http.logging import _truncate_body

        assert _truncate_body(b"x" * 20, 5) == b"xxxxx...[truncated]"

    def test_no_truncate_when_non_positive_or_short(self) -> None:
        from dxrk.utils.http.logging import _truncate_body

        assert _truncate_body(b"x", 0) == b"x"
        assert _truncate_body(b"xy", 10) == b"xy"


# ═══════════ pool.py 296 — config None defensivo ═══════════


class TestPoolNoneConfig:
    def test_with_proxy_none_config_raises(self) -> None:
        from dxrk.utils.http import pool as poolmod

        pool = poolmod.new_connection_pool(None)
        try:
            with mock.patch.object(poolmod, "new_proxy_config", return_value=(None, None)):
                with pytest.raises(Exception, match="no proxy configured"):
                    pool.with_proxy("http://x:1")
        finally:
            pool.close()


# ═══════════ proxy/__init__.py 338 — config None defensivo + defaults SOCKS ═══════════


class TestProxyNoneConfig:
    def test_must_parse_none_config_raises(self) -> None:
        from dxrk.utils.http import proxy as proxymod

        with mock.patch.object(proxymod, "new_proxy_config", return_value=(None, None)):
            with pytest.raises(Exception):
                proxymod.must_parse_proxy_url("http://x:1")

    def test_socks_defaults_via_else(self) -> None:
        from dxrk.utils.http.proxy import new_proxy_config

        cfg, err = new_proxy_config("socks4://h")
        assert err is None and cfg is not None
        assert cfg.port == 1080
        assert cfg.get_proxy_url() == "socks4://h:1080"
        cfg2, err2 = new_proxy_config("socks5://h")
        assert err2 is None and cfg2 is not None
        assert cfg2.port == 1080
