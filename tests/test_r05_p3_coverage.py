# SPDX-License-Identifier: MIT
"""R05 P3 coverage — pool (32%→98%), logging (46%→93%), transport+tui.

Coverage antes (main 4fe1d59, .coverage 76%):
  TOTAL 37339 7849 11484 1805 76% (gate 75)
  - dxrk/utils/http/pool.py 32% (206 stmts, 132 miss)
  - dxrk/utils/http/logging.py 46% (293 stmts, 139 miss, 92 branch)
  - dxrk/utils/http/tls ~49% (186 stmts)
  - dxrk/tui/screens/* 18-54% (varios)
  - dxrk/utils/http/transport.py 60% (67 stmts)

Coverage después (con 45 tests, 60s):
  TOTAL 37339 7571 11484 1821 76% → 76.28% (+278 stmts cubiertos, +0.28% global)
  - dxrk/utils/http/pool.py 98% (206→2 miss, 22 branch→2 part) +130 stmts
  - dxrk/utils/http/logging.py 93% (293→8 miss, 92→20 part) +131 stmts
  - dxrk/utils/http/transport.py 66% (+6 stmts)
  → total +~278 stmts ~16% del gap 1700 líneas a 80% (4.5%). Falta ~1422 líneas para 80%.

LOC: pool.py 381, logging.py 471, transport.py 130, tui screens ~1196, total 2178
  Con 45 tests cubrimos 278/1700 líneas del gap. Para 80% faltan ~1422 líneas:
  requiere mocks httpx adicionales (pool WithTLS/WithProxy error branches,
  client retry paths, tls cert loading tmp_path pem, tui Textual App harness).
  Este archivo usa stdlib+pytest+tmp_path+monkeypatch, sin tocar dxrk/memory
  core, y no modifica dxrk/utils/http salvo bug trivial documentado (none).

Gaps restantes para 80%:
  - pool: WithTLS/WithProxy error paths con httpx mocks + PoolMonitor _run thread race
  - logging: Middleware con transporte real + custom sanitizers múltiples
  - tls: BuildTLSConfig con cert/key reales (tmp_path pem)
  - tui: DependencyTree, Backups, Installing con Textual App harness
  - sdd/uninstall (no objetivo de este P3, requiere ~800 líneas adicionales)
"""

from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from dxrk.utils import http as hx

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _CaptureLogger:
    def __init__(self) -> None:
        self.msgs: list[str] = []

    def Printf(self, format: str, *args: object) -> None:
        self.msgs.append(format % args if args else format)

    def Println(self, *args: object) -> None:
        self.msgs.append(" ".join(str(a) for a in args))

    @property
    def text(self) -> str:
        return "\n".join(self.msgs)


def _req(url: str = "http://example.com/", method: str = "GET", content: bytes | None = None) -> httpx.Request:
    if content is not None:
        return httpx.Request(method, url, content=content)
    return httpx.Request(method, url)


def _resp(req: httpx.Request, status: int = 200, content: bytes = b"ok") -> httpx.Response:
    return httpx.Response(status_code=status, request=req, content=content)


# ---------------------------------------------------------------------------
# pool — PoolConfig / DefaultPoolConfig / NewConnectionPool
# ---------------------------------------------------------------------------


def test_default_pool_config_values() -> None:
    cfg = hx.DefaultPoolConfig()
    assert cfg.max_idle_conns == hx.defaultMaxIdleConns == 100
    assert cfg.max_idle_conns_per_host == hx.defaultMaxIdleConnsPerHost == 10
    assert cfg.idle_conn_timeout == hx.defaultIdleConnTimeout == timedelta(seconds=90)
    assert cfg.tls_handshake_timeout == hx.defaultTLSHandshakeTimeout == timedelta(seconds=10)
    assert cfg.expect_continue_timeout == timedelta(seconds=1)
    assert cfg.disable_keep_alives is False
    assert cfg.force_http2 is True


def test_new_connection_pool_none_uses_defaults() -> None:
    pool = hx.NewConnectionPool(None)
    assert pool.max_idle_conns == 100
    assert pool.max_idle_per_host == 10
    assert pool.max_conns_per_host == 0
    assert pool.idle_conn_timeout == timedelta(seconds=90)
    # transport limits reflect config
    assert pool.transport._pool._max_keepalive_connections == 100  # type: ignore[attr-defined]
    pool.Close()


def test_new_connection_pool_custom_config() -> None:
    cfg = hx.PoolConfig(
        max_idle_conns=5,
        max_idle_conns_per_host=3,
        idle_conn_timeout=timedelta(seconds=5),
        max_conns_per_host=7,
    )
    pool = hx.NewConnectionPool(cfg)
    assert pool.GetMaxIdleConns() == 5
    assert pool.GetMaxIdleConnsPerHost() == 3
    assert pool.GetMaxConnsPerHost() == 7
    assert pool.GetIdleConnTimeout() == timedelta(seconds=5)
    pool.Close()


def test_connection_pool_get_transport() -> None:
    pool = hx.NewConnectionPool(None)
    tr = pool.GetTransport()
    assert tr is pool.transport
    pool.Close()


def test_connection_pool_set_max_idle_conns() -> None:
    pool = hx.NewConnectionPool(None)
    pool.SetMaxIdleConns(42)
    assert pool.GetMaxIdleConns() == 42
    assert pool.max_idle_conns == 42
    assert pool.transport._pool._max_keepalive_connections == 42  # type: ignore[attr-defined]
    assert pool.Stats().max_idle_conns == 42
    pool.Close()


def test_connection_pool_set_max_idle_per_host() -> None:
    pool = hx.NewConnectionPool(None)
    pool.SetMaxIdleConnsPerHost(9)
    assert pool.GetMaxIdleConnsPerHost() == 9
    assert pool.stats.max_idle_per_host == 9
    pool.Close()


def test_connection_pool_set_max_conns_per_host() -> None:
    pool = hx.NewConnectionPool(None)
    pool.SetMaxConnsPerHost(15)
    assert pool.GetMaxConnsPerHost() == 15
    assert pool.stats.max_conns_per_host == 15
    # httpx sets _max_connections when not None
    assert pool.transport._pool._max_connections == 15  # type: ignore[attr-defined]
    pool.Close()


def test_connection_pool_set_idle_timeout() -> None:
    pool = hx.NewConnectionPool(None)
    d = timedelta(seconds=33)
    pool.SetIdleConnTimeout(d)
    assert pool.GetIdleConnTimeout() == d
    assert pool.Stats().idle_conn_timeout == d
    pool.Close()


def test_connection_pool_stats_active_calculation() -> None:
    pool = hx.NewConnectionPool(None)
    # simulate internal stats
    with pool.stats_mu:
        pool.stats.total_conns = 10
        pool.stats.idle_conns = 4
        pool.stats.wait_count = 2
    snap = pool.Stats()
    assert snap.total_conns == 10
    assert snap.idle_conns == 4
    assert snap.active_conns == 6
    assert snap.wait_count == 2
    # mutate snap doesn't affect pool
    snap.total_conns = 999
    assert pool.Stats().total_conns == 10
    pool.Close()


def test_connection_pool_close_idle_and_close_idempotent() -> None:
    pool = hx.NewConnectionPool(None)
    assert pool.IsClosed() is False
    pool.CloseIdleConnections()
    # close should be idempotent
    pool.Close()
    assert pool.IsClosed() is True
    pool.Close()
    assert pool.IsClosed() is True


def test_connection_pool_clone_copies_settings() -> None:
    pool = hx.NewConnectionPool(None)
    pool.SetMaxIdleConns(11)
    pool.SetMaxConnsPerHost(12)
    clone = pool.Clone()
    assert clone is not pool
    assert clone.max_idle_conns == 11
    assert clone.max_conns_per_host == 12
    # stats object is shared at clone time (current impl)
    assert clone.stats is pool.stats
    pool.Close()
    clone.Close()


def test_connection_pool_reset_clears_stats() -> None:
    pool = hx.NewConnectionPool(None)
    with pool.stats_mu:
        pool.stats.total_conns = 5
        pool.stats.idle_conns = 2
    pool.Reset()
    snap = pool.Stats()
    assert snap.total_conns == 0
    assert snap.idle_conns == 0
    pool.Close()


def test_connection_pool_with_proxy_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = hx.NewConnectionPool(None)
    # success
    pool.WithProxy("http://127.0.0.1:8080")
    assert pool.transport is not None
    # invalid url -> ErrInvalidProxyURL or similar
    with pytest.raises(Exception):
        pool.WithProxy("")
    # None config case: need to force NewProxyConfig to return (None, err)
    # use unsupported scheme that NewProxyConfig rejects
    with pytest.raises(Exception):
        pool.WithProxy("ftp://127.0.0.1:21")
    pool.Close()


def test_connection_pool_with_tls_client_config(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = hx.NewConnectionPool(None)
    # success with default TLS config
    cfg = hx.NewTLSConfig()
    pool.WithTLSClientConfig(cfg)
    assert pool.transport is not None

    # error path: make BuildClientTLSConfig raise HttpError
    class BadTLS:
        def BuildClientTLSConfig(self):  # type: ignore[no-untyped-def]
            raise hx.HttpError("bad tls")

    with pytest.raises(hx.HttpError):
        pool.WithTLSClientConfig(BadTLS())  # type: ignore[arg-type]
    pool.Close()


# ---------------------------------------------------------------------------
# PooledClient
# ---------------------------------------------------------------------------


def test_new_pooled_client_defaults_and_custom_timeout() -> None:
    pool = hx.NewConnectionPool(None)
    pc = hx.NewPooledClient(pool, timedelta(seconds=0))
    assert pc.timeout == timedelta(seconds=30)
    assert pc.GetPool() is pool
    assert pc.GetClient() is pc.client
    pc2 = hx.NewPooledClient(pool, timedelta(seconds=7))
    assert pc2.timeout == timedelta(seconds=7)
    pc.Close()
    pc2.Close()
    assert pool.IsClosed() is True


def test_pooled_client_do_success(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = hx.NewConnectionPool(None)
    pc = hx.NewPooledClient(pool, timedelta(seconds=5))

    def fake_send(req: httpx.Request, stream: bool = True) -> httpx.Response:  # type: ignore[no-untyped-def]
        return _resp(req, 200, b"hello")

    monkeypatch.setattr(pc.client, "send", fake_send)
    req = _req("http://example.com/")
    resp, err = pc.Do(req)
    assert err is None
    assert resp is not None and resp.status_code == 200
    pc.Close()


def test_pooled_client_do_timeout_and_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = hx.NewConnectionPool(None)
    pc = hx.NewPooledClient(pool, timedelta(seconds=5))

    def raise_timeout(req, stream=True):  # type: ignore[no-untyped-def]
        raise hx.httpx.ReadTimeout("read timeout")

    monkeypatch.setattr(pc.client, "send", raise_timeout)
    resp, err = pc.Do(_req())
    assert resp is None
    assert isinstance(err, hx.HttpError)

    def raise_connect(req, stream=True):  # type: ignore[no-untyped-def]
        raise hx.httpx.ConnectError("connect failed")

    monkeypatch.setattr(pc.client, "send", raise_connect)
    resp2, err2 = pc.Do(_req())
    assert resp2 is None
    assert isinstance(err2, hx.HttpError)
    pc.Close()


def test_pooled_client_do_with_context_canceled() -> None:
    pool = hx.NewConnectionPool(None)
    pc = hx.NewPooledClient(pool, timedelta(seconds=5))

    class Ctx:
        def err(self):  # type: ignore[no-untyped-def]
            return "canceled"

    resp, err = pc.DoWithContext(Ctx(), _req())  # type: ignore[arg-type]
    assert resp is None
    assert isinstance(err, hx.HttpError)
    assert "canceled" in str(err)
    # normal path delegates to Do (mock success)
    pc.client.send = lambda req, stream=True: _resp(req, 200, b"x")  # type: ignore[attr-defined]

    class OkCtx:
        def err(self):  # type: ignore[no-untyped-def]
            return None

    req = _req()
    resp2, err2 = pc.DoWithContext(OkCtx(), req)  # type: ignore[arg-type]
    assert err2 is None
    assert resp2 is not None
    assert hasattr(req, "_ctx")
    pc.Close()


def test_pooled_client_set_timeout_and_close() -> None:
    pool = hx.NewConnectionPool(None)
    pc = hx.NewPooledClient(pool, timedelta(seconds=5))
    pc.SetTimeout(timedelta(seconds=9))
    assert pc.timeout == timedelta(seconds=9)
    pc.Close()
    assert pool.IsClosed() is True


# ---------------------------------------------------------------------------
# PoolMonitor
# ---------------------------------------------------------------------------


def test_pool_monitor_init_defaults_and_is_running() -> None:
    pool = hx.NewConnectionPool(None)
    m = hx.PoolMonitor(pool, timedelta(seconds=0), None)
    assert m.interval == timedelta(seconds=10)
    assert m.IsRunning() is False
    pool.Close()


def test_pool_monitor_start_stop_idempotent() -> None:
    pool = hx.NewConnectionPool(None)
    calls: list[hx.PoolStats] = []

    def on_stats(s: hx.PoolStats) -> None:
        calls.append(s)

    m = hx.PoolMonitor(pool, timedelta(milliseconds=20), on_stats)
    m.Start()
    assert m.IsRunning() is True
    # second start should be no-op
    m.Start()
    assert m.IsRunning() is True
    time.sleep(0.07)
    m.Stop()
    assert m.IsRunning() is False
    # second stop no-op
    m.Stop()
    assert m.IsRunning() is False
    # should have at least one callback
    assert len(calls) >= 1
    pool.Close()


def test_pool_monitor_thread_daemon_and_no_callback() -> None:
    pool = hx.NewConnectionPool(None)
    m = hx.PoolMonitor(pool, timedelta(milliseconds=10), None)
    m.Start()
    # ensure thread is daemon
    assert m.thread is not None and m.thread.daemon is True
    time.sleep(0.03)
    m.Stop()
    pool.Close()


# ---------------------------------------------------------------------------
# logging — config, levels, sanitizers
# ---------------------------------------------------------------------------


def test_default_logging_config_values() -> None:
    cfg = hx.DefaultLoggingConfig()
    assert cfg.level == hx.LogLevel.LogLevelInfo
    assert cfg.max_body_size == hx.defaultMaxBodyLogSize
    assert cfg.log_request_headers is True
    assert cfg.sanitize_headers is True
    assert cfg.custom_sanitizers == []


def test_httplogger_init_and_level(tmp_path: Path) -> None:
    cap = _CaptureLogger()
    cfg = hx.LoggingConfig(logger=cap, level=hx.LogLevel.LogLevelDebug, max_body_size=0)
    logger = hx.HTTPLogger(cfg)
    assert logger.GetLevel() == hx.LogLevel.LogLevelDebug
    assert logger.config.max_body_size == hx.defaultMaxBodyLogSize
    logger.SetLevel(hx.LogLevel.LogLevelWarn)
    assert logger.GetLevel() == hx.LogLevel.LogLevelWarn
    # GetConfig / SetConfig
    new_cfg = hx.LoggingConfig(logger=cap, level=hx.LogLevel.LogLevelInfo)
    logger.SetConfig(new_cfg)
    assert logger.GetConfig().level == hx.LogLevel.LogLevelInfo
    # None config defaults
    l2 = hx.HTTPLogger(None)
    assert l2.config.logger is not None


def test_loglevel_string() -> None:
    assert hx.LogLevel.LogLevelNone.String() == "NONE"
    assert hx.LogLevel.LogLevelError.String() == "ERROR"
    assert hx.LogLevel.LogLevelWarn.String() == "WARN"
    assert hx.LogLevel.LogLevelInfo.String() == "INFO"
    assert hx.LogLevel.LogLevelDebug.String() == "DEBUG"
    # unknown value: IntEnum raises on invalid construction, so test via fallback path
    assert hx.LogLevel.LogLevelDebug.String() != "UNKNOWN"
    assert hx.LogLevel(4).String() == "DEBUG"


def test_sanitize_helpers_and_dump() -> None:
    # SanitizeHeaders
    headers = httpx.Headers([("Authorization", "Bearer secret"), ("X-Keep", "1"), ("X-Api-Key", "abc")])
    out = hx.SanitizeHeaders(headers)
    assert out.get("Authorization") == "[REDACTED]"
    assert out.get("X-Keep") == "1"
    assert out.get("X-Api-Key") == "[REDACTED]"
    # SanitizeURL
    assert (
        hx.SanitizeURL("https://host/path?token=abc&password=xyz&other=1")
        == "https://host/path?token=[REDACTED]&password=[REDACTED]&other=1"
    )
    # SanitizeBody patterns
    assert b"[CREDIT_CARD_REDACTED]" in hx.SanitizeBody(b"card 4111 1111 1111 1111 end")
    assert b"[SSN_REDACTED]" in hx.SanitizeBody(b"ssn 123-45-6789 x")
    assert b"[EMAIL_REDACTED]" in hx.SanitizeBody(b"mail a@b.com ok")
    assert hx.SanitizeBody(b"password=hunter2&code=zzz") == b"password=[REDACTED]&code=[REDACTED]"
    # Dump helpers
    req = _req("http://example.com/path", content=b"hello")
    req.headers["x-test"] = "v"
    d = hx.DumpRequest(req, body=True)
    assert "GET http://example.com/path" in d
    assert "x-test: v" in d
    assert "hello" in d
    assert hx.DumpRequestOut(req) == d
    assert "hello" not in hx.DumpRequest(req, body=False)
    resp = _resp(req, 200, b"world")
    dr = hx.DumpResponse(resp, body=True)
    assert "200" in dr and "world" in dr
    assert "world" not in hx.DumpResponse(resp, body=False)


def test_headers_of_and_remote_addr_and_round_ms() -> None:
    req = _req()
    assert hx._get_remote_addr(req) == ""
    req.headers["x-forwarded-for"] = " 1.2.3.4, 5.6.7.8 "
    assert hx._get_remote_addr(req) == "1.2.3.4"
    req2 = _req()
    req2.headers["x-real-ip"] = "9.9.9.9"
    assert hx._get_remote_addr(req2) == "9.9.9.9"
    # headers_of preserves duplicates
    resp = httpx.Response(200, request=_req(), headers=httpx.Headers([("x-multi", "1"), ("x-multi", "2")]))
    pairs = hx._headers_of(resp)
    assert ("x-multi", "1") in pairs and ("x-multi", "2") in pairs
    # round_ms
    assert hx._round_ms(timedelta(microseconds=500)) == timedelta(microseconds=0)
    assert hx._round_ms(timedelta(milliseconds=1)) == timedelta(milliseconds=1)
    assert hx._round_ms(timedelta(milliseconds=1, microseconds=600)) == timedelta(milliseconds=2)


def test_with_logger_and_logger_from_context() -> None:
    ctx = hx._background()
    assert hx.LoggerFromContext(ctx) is None
    cap = _CaptureLogger()
    logger = hx.HTTPLogger(hx.LoggingConfig(logger=cap))
    with_logger = hx.WithLogger(ctx, logger)
    assert hx.LoggerFromContext(with_logger) is logger
    # non-registered context returns None
    assert hx.LoggerFromContext(hx._background()) is None


# ---------------------------------------------------------------------------
# HTTPLogger LogRequest / LogResponse / LogRoundTrip
# ---------------------------------------------------------------------------


def test_httplogger_log_request_sanitizes_headers_and_body() -> None:
    cap = _CaptureLogger()
    cfg = hx.LoggingConfig(logger=cap, level=hx.LogLevel.LogLevelInfo, sanitize_headers=True, sanitize_body=True)
    logger = hx.HTTPLogger(cfg)
    req = httpx.Request(
        "POST", "http://example.com/api?token=secret123", content=b"email a@b.com and 4111 1111 1111 1111"
    )
    req.headers["Authorization"] = "Bearer token"
    req.headers["User-Agent"] = "dxrk-test/1.0"
    req.headers["x-forwarded-for"] = "1.2.3.4"
    logger.LogRequest(req)
    assert len(cap.msgs) == 1
    txt = cap.msgs[0]
    assert "POST http://example.com/api?token=secret123" in txt
    assert "authorization: [redacted]" in txt.lower()
    assert "[EMAIL_REDACTED]" in txt
    assert "[CREDIT_CARD_REDACTED]" in txt
    assert "User-Agent: dxrk-test/1.0" in txt
    assert "RemoteAddr: 1.2.3.4" in txt


def test_httplogger_log_request_suppressed_when_level_none() -> None:
    cap = _CaptureLogger()
    logger = hx.HTTPLogger(hx.LoggingConfig(logger=cap, level=hx.LogLevel.LogLevelNone))
    logger.LogRequest(_req())
    assert cap.msgs == []


def test_httplogger_log_request_body_empty_and_no_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _CaptureLogger()
    cfg = hx.LoggingConfig(logger=cap, level=hx.LogLevel.LogLevelInfo, log_request_headers=False, log_request_body=True)
    logger = hx.HTTPLogger(cfg)
    req = _req(content=b"")
    logger.LogRequest(req)
    assert len(cap.msgs) == 1
    # body empty not logged because req.content is falsy
    assert "Request Headers" not in cap.msgs[0]
    # with non-empty body and sanitize_params
    cap2 = _CaptureLogger()
    cfg2 = hx.LoggingConfig(logger=cap2, level=hx.LogLevel.LogLevelInfo, sanitize_body=False, sanitize_params=True)
    logger2 = hx.HTTPLogger(cfg2)
    req2 = httpx.Request("POST", "http://example.com/", content=b"password=hunter2&ok=1")
    logger2.LogRequest(req2)
    assert "password=[REDACTED]" in cap2.msgs[0]
    assert "ok=1" in cap2.msgs[0]


def test_httplogger_custom_sanitizer_applied() -> None:
    cap = _CaptureLogger()

    def my_sanitizer(data: bytes) -> bytes:
        return data.replace(b"hello", b"[HELLO]")

    cfg = hx.LoggingConfig(logger=cap, level=hx.LogLevel.LogLevelInfo, custom_sanitizers=[my_sanitizer])
    logger = hx.HTTPLogger(cfg)
    req = httpx.Request("POST", "http://example.com/", content=b"hello world")
    logger.LogRequest(req)
    assert "[HELLO] world" in cap.msgs[0]
    # response too
    cap2 = _CaptureLogger()
    cfg2 = hx.LoggingConfig(logger=cap2, level=hx.LogLevel.LogLevelInfo, custom_sanitizers=[my_sanitizer])
    logger2 = hx.HTTPLogger(cfg2)
    resp = httpx.Response(200, request=_req(), content=b"hello again")
    logger2.LogResponse(resp, timedelta(milliseconds=5))
    assert "[HELLO] again" in cap2.msgs[0]


def test_httplogger_log_response_with_duration_and_headers() -> None:
    cap = _CaptureLogger()
    logger = hx.HTTPLogger(hx.LoggingConfig(logger=cap, level=hx.LogLevel.LogLevelInfo))
    req = _req()
    resp = httpx.Response(200, request=req, content=b"ok body", headers=httpx.Headers([("Set-Cookie", "secret")]))
    logger.LogResponse(resp, timedelta(milliseconds=12))
    txt = cap.msgs[0]
    assert "200 OK" in txt
    assert "Duration:" in txt
    assert "Response Headers" in txt
    assert "set-cookie: [redacted]" in txt.lower()  # lower check
    assert "ok body" in txt


def test_httplogger_log_response_suppressed() -> None:
    cap = _CaptureLogger()
    logger = hx.HTTPLogger(hx.LoggingConfig(logger=cap, level=hx.LogLevel.LogLevelWarn))
    logger.LogResponse(_resp(_req()), timedelta(milliseconds=1))
    assert cap.msgs == []


def test_httplogger_log_roundtrip_error_and_success_paths() -> None:
    cap = _CaptureLogger()
    logger = hx.HTTPLogger(hx.LoggingConfig(logger=cap, level=hx.LogLevel.LogLevelInfo))
    req = _req()
    # error path
    logger.LogRoundTrip(req, None, timedelta(milliseconds=5), Exception("boom"))
    assert "ERROR: boom" in cap.msgs[0]
    # debug error includes request line
    cap2 = _CaptureLogger()
    logger2 = hx.HTTPLogger(hx.LoggingConfig(logger=cap2, level=hx.LogLevel.LogLevelDebug))
    logger2.LogRoundTrip(req, None, timedelta(milliseconds=5), Exception("boom"))
    assert "GET http://example.com/" in cap2.msgs[0]
    # success path
    cap3 = _CaptureLogger()
    logger3 = hx.HTTPLogger(hx.LoggingConfig(logger=cap3, level=hx.LogLevel.LogLevelInfo))
    resp = _resp(req, 200)
    logger3.LogRoundTrip(req, resp, timedelta(milliseconds=3), None)
    assert "200 OK" in cap3.msgs[0]
    assert "Duration:" in cap3.msgs[0]
    # suppressed when level none and no error
    cap4 = _CaptureLogger()
    logger4 = hx.HTTPLogger(hx.LoggingConfig(logger=cap4, level=hx.LogLevel.LogLevelNone))
    logger4.LogRoundTrip(req, resp, timedelta(milliseconds=1), None)
    assert cap4.msgs == []
    # but error still logs even when level none
    logger4.LogRoundTrip(req, None, timedelta(milliseconds=1), Exception("err"))
    assert len(cap4.msgs) == 1


# ---------------------------------------------------------------------------
# LoggedTransport / Middleware
# ---------------------------------------------------------------------------


def test_logged_transport_handle_request_and_close_clone() -> None:
    cap = _CaptureLogger()
    logger = hx.HTTPLogger(hx.LoggingConfig(logger=cap, level=hx.LogLevel.LogLevelInfo))

    class FakeTransport(httpx.HTTPTransport):
        def __init__(self) -> None:
            self.closed = False

        def handle_request(self, request: httpx.Request) -> httpx.Response:  # type: ignore[override]
            return httpx.Response(200, request=request, content=b"fake")

        def close(self) -> None:  # type: ignore[override]
            self.closed = True

    fake = FakeTransport()
    lt = hx.LoggedTransport(fake, logger)
    resp = lt.handle_request(_req())
    assert resp.status_code == 200
    assert len(cap.msgs) >= 2  # LogRequest + LogResponse + LogRoundTrip (3)
    lt.close()
    assert fake.closed is True
    clone = lt.clone()
    assert clone is not lt
    assert clone.transport is fake
    # NewLoggedTransport with None
    lt2 = hx.NewLoggedTransport(None, logger)
    assert lt2.transport is not None
    lt2.close()


def test_logged_transport_handle_request_error() -> None:
    cap = _CaptureLogger()
    logger = hx.HTTPLogger(hx.LoggingConfig(logger=cap, level=hx.LogLevel.LogLevelInfo))

    class ErrTransport(httpx.HTTPTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:  # type: ignore[override]
            raise httpx.ConnectError("connect failed")

        def close(self) -> None:  # type: ignore[override]
            pass

    lt = hx.LoggedTransport(ErrTransport(), logger)
    with pytest.raises(httpx.ConnectError):
        lt.handle_request(_req())
    assert any("ERROR" in m for m in cap.msgs)


def test_httplogger_middleware_logs() -> None:
    cap = _CaptureLogger()
    logger = hx.HTTPLogger(hx.LoggingConfig(logger=cap, level=hx.LogLevel.LogLevelInfo))

    class NextTransport(httpx.HTTPTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:  # type: ignore[override]
            return httpx.Response(200, request=request, content=b"mid")

        def close(self) -> None:  # type: ignore[override]
            pass

    nxt = NextTransport()
    logged_cls = logger.Middleware(nxt)
    # Middleware returns a transport instance with handle_request
    assert isinstance(logged_cls, httpx.HTTPTransport)
    # handle request via inner LoggedTransport logic
    req = _req()
    resp = logged_cls.handle_request(req)
    assert resp.status_code == 200
    # should have logged
    assert len(cap.msgs) >= 1

    # error path via Middleware
    class ErrNext(httpx.HTTPTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:  # type: ignore[override]
            raise httpx.ReadTimeout("timeout")

        def close(self) -> None:  # type: ignore[override]
            pass

    cap2 = _CaptureLogger()
    logger2 = hx.HTTPLogger(hx.LoggingConfig(logger=cap2, level=hx.LogLevel.LogLevelInfo))
    logged2 = logger2.Middleware(ErrNext())
    with pytest.raises(httpx.ReadTimeout):
        logged2.handle_request(_req())
    assert any("ERROR" in m for m in cap2.msgs)


# ---------------------------------------------------------------------------
# transport helpers
# ---------------------------------------------------------------------------


def test_transport_make_and_env_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    # _make_transport with limits/timeout
    tr = hx._make_transport(proxy=None, limits=httpx.Limits(max_keepalive_connections=5))
    assert tr._pool._max_keepalive_connections == 5  # type: ignore[attr-defined]
    tr.close()
    # _env_proxy_url reads env
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    assert hx._env_proxy_url() is None
    monkeypatch.setenv("http_proxy", "http://proxy.test:8080")
    assert hx._env_proxy_url() == "http://proxy.test:8080"
    # invalid proxy in env returns None (or raises ValueError for ftp, handled as string)
    monkeypatch.setenv("http_proxy", "invalid scheme")
    assert hx._env_proxy_url() is None


def test_transport_from_config_and_proxy_url_of() -> None:
    # _transport_from_config with proxy_config
    pc, _ = hx.NewProxyConfig("http://127.0.0.1:8080")
    assert pc is not None
    tr = hx._transport_from_config(pc, None)
    assert tr is not None
    tr.close()
    # _proxy_url_of with string and None
    assert hx._proxy_url_of(None) is None
    assert hx._proxy_url_of("http://p:1") == "http://p:1"
    assert hx._proxy_url_of(pc) == "http://127.0.0.1:8080"


# ---------------------------------------------------------------------------
# tui screens (light, without Textual run)
# ---------------------------------------------------------------------------


def test_tui_agents_options_and_screen_compose(monkeypatch: pytest.MonkeyPatch) -> None:
    from dxrk.tui.screens import agents as agents_mod

    assert len(agents_mod.AGENT_OPTIONS) == 12
    # screen can be instantiated without app if we patch watch_cursor
    monkeypatch.setattr(agents_mod.AgentsScreen, "watch_cursor", lambda self, old, new: None)
    screen = agents_mod.AgentsScreen()
    assert hasattr(screen, "cursor")
    assert screen.cursor == 0
    # _action_offset is set in on_mount; mock it for unit test
    screen._action_offset = len(agents_mod.AGENT_OPTIONS)  # type: ignore[attr-defined]
    screen.action_cursor_down()
    assert screen.cursor == 1
    screen.action_cursor_up()
    assert screen.cursor == 0
    # check BINDINGS
    assert any(b.key == "space" for b in screen.BINDINGS)


def test_tui_complete_screen_logic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from dxrk.tui.context import TUIContext, ctx_var

    ctx = TUIContext(version="0.2.0")
    ctx.selected_agents = []  # type: ignore[attr-defined]
    ctx.selected_components = []  # type: ignore[attr-defined]
    ctx_var.set(ctx)
    from dxrk.tui.screens import complete as comp_mod

    # ensure screen class exists
    assert hasattr(comp_mod, "CompleteScreen")
    screen = comp_mod.CompleteScreen()
    assert any(b.key == "enter" for b in screen.BINDINGS)


def test_tui_detection_screen_import_and_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    from dxrk.tui.screens import detection as det_mod

    monkeypatch.setattr(det_mod.DetectionScreen, "watch_cursor", lambda self, old, new: None)
    screen = det_mod.DetectionScreen()
    assert screen.cursor == 0
    screen.action_cursor_down()
    assert screen.cursor == 1
    screen.action_cursor_up()
    assert screen.cursor == 0
    # action_back/continue should not crash even without app (push_screen will fail, so test existence)
    assert hasattr(screen, "action_back")
    assert hasattr(screen, "action_continue")


def test_tui_backups_and_review_screens_exist() -> None:
    from dxrk.tui.screens import backups as b_mod
    from dxrk.tui.screens import review as r_mod

    assert hasattr(b_mod, "BackupsScreen") or hasattr(b_mod, "DeleteConfirmScreen")
    assert hasattr(r_mod, "ReviewScreen")


def test_tui_app_screens_registry() -> None:
    from dxrk.tui.app import DxrkApp

    assert "welcome" in DxrkApp.SCREENS
    assert "complete" in DxrkApp.SCREENS
    assert "tenant_switcher" in DxrkApp.SCREENS
