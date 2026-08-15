"""Tests for the dxrk.utils.http port of the Go http package."""

import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dxrk.utils import http as hx


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.request_count += 1
        mode = getattr(self.server, "mode", "ok")
        if mode == "slow":
            time.sleep(0.05)
            status, body = 200, b"ok"
        elif mode == "retryable":
            if self.server.request_count < getattr(self.server, "ok_at", 3):
                status, body = 503, b"retry"
            else:
                status, body = 200, b"ok"
        elif mode == "not_found":
            status, body = 404, b"nope"
        else:
            status, body = 200, b"ok"
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def http_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.request_count = 0
    httpd.mode = "ok"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()


class TestProxyType:
    def test_values(self):
        assert hx.ProxyType.ProxyTypeHTTP.value == "http"
        assert hx.ProxyType.ProxyTypeHTTPS.value == "https"
        assert hx.ProxyType.ProxyTypeSOCKS4.value == "socks4"
        assert hx.ProxyType.ProxyTypeSOCKS5.value == "socks5"

    def test_compares_with_str(self):
        assert hx.ProxyType.ProxyTypeHTTP == "http"
        assert hx.ProxyType.ProxyTypeHTTPS == "https"

    def test_construct_from_string(self):
        assert hx.ProxyType("https") is hx.ProxyType.ProxyTypeHTTPS


class TestLogLevel:
    def test_values(self):
        assert hx.LogLevel.LogLevelNone == 0
        assert hx.LogLevel.LogLevelError == 1
        assert hx.LogLevel.LogLevelWarn == 2
        assert hx.LogLevel.LogLevelInfo == 3
        assert hx.LogLevel.LogLevelDebug == 4

    def test_string(self):
        assert hx.LogLevel.LogLevelNone.String() == "NONE"
        assert hx.LogLevel.LogLevelError.String() == "ERROR"
        assert hx.LogLevel.LogLevelWarn.String() == "WARN"
        assert hx.LogLevel.LogLevelInfo.String() == "INFO"
        assert hx.LogLevel.LogLevelDebug.String() == "DEBUG"


class TestRetryPolicy:
    def test_retryable_status_codes(self):
        policy = hx.RetryPolicy()
        assert policy.IsRetryable(408)
        assert policy.IsRetryable(429)
        assert policy.IsRetryable(500)
        assert policy.IsRetryable(502)
        assert policy.IsRetryable(503)
        assert policy.IsRetryable(504)

    def test_non_retryable_status_codes(self):
        policy = hx.RetryPolicy()
        assert not policy.IsRetryable(200)
        assert not policy.IsRetryable(301)
        assert not policy.IsRetryable(404)


class TestNewHTTPClient:
    def test_defaults(self):
        client, err = hx.NewHTTPClient(None)
        assert err is None
        assert client is not None
        assert isinstance(client, hx.HTTPClient)
        assert client.client.timeout.read == 30.0
        assert client.client.timeout.connect == hx.defaultTLSHandshakeTimeout.total_seconds()
        assert client.retry_policy.max_retries == hx.defaultMaxRetries

    def test_timeout_option_applied(self):
        client, err = hx.NewHTTPClient(hx.ClientOptions(timeout=timedelta(seconds=7)))
        assert err is None
        assert client is not None
        assert client.client.timeout.read == 7.0

    def test_proxy_config_applied_to_transport(self):
        pc, err = hx.NewProxyConfig("http://127.0.0.1:1234")
        assert err is None
        client, err = hx.NewHTTPClient(hx.ClientOptions(proxy_config=pc))
        assert err is None
        assert client is not None
        pool = client.transport._pool
        assert type(pool).__name__ == "HTTPProxy"
        assert pool._proxy_url.host == b"127.0.0.1"
        assert pool._proxy_url.port == 1234

    def test_invalid_proxy_url_rejected(self):
        pc, err = hx.NewProxyConfig("")
        assert pc is None
        assert err is not None


class TestProxyConfig:
    def test_proxy_url_roundtrip(self):
        pc, err = hx.NewProxyConfig("http://user:pass@127.0.0.1:8080")
        assert err is None
        assert pc.GetProxyURL() == "http://user:pass@127.0.0.1:8080"
        assert pc.type == hx.ProxyType.ProxyTypeHTTP
        assert pc.ProxyPort() == 8080

    def test_should_bypass(self):
        pc, err = hx.NewProxyConfig("http://127.0.0.1:8080")
        assert err is None
        pc.SetNoProxy("localhost")
        assert pc.ShouldBypass("localhost")
        assert not pc.ShouldBypass("example.com")


class TestClientRequests:
    def test_do_success(self, http_server):
        client, err = hx.NewHTTPClient(None)
        assert err is None
        server = f"http://127.0.0.1:{http_server.server_address[1]}/"
        req = hx.httpx.Request("GET", server)
        resp, err = client.Do(req)
        assert err is None
        assert resp.status_code == 200
        assert resp.read() == b"ok"

    def test_timeout_option_enforced(self, http_server):
        http_server.mode = "slow"
        client, err = hx.NewHTTPClient(
            hx.ClientOptions(timeout=timedelta(milliseconds=10))
        )
        assert err is None
        server = f"http://127.0.0.1:{http_server.server_address[1]}/"
        req = hx.httpx.Request("GET", server)
        resp, err = client.Do(req)
        assert err is not None
        assert resp is None

    def test_no_retry_on_success(self, http_server):
        client, err = hx.NewHTTPClient(None)
        assert err is None
        server = f"http://127.0.0.1:{http_server.server_address[1]}/"
        req = hx.httpx.Request("GET", server)
        resp, err = client.Do(req)
        assert err is None
        assert http_server.request_count == 1
        assert resp.status_code == 200

    def test_no_retry_on_non_retryable_status(self, http_server):
        http_server.mode = "not_found"
        policy = hx.RetryPolicy(max_retries=3, retry_backoff=timedelta(milliseconds=5))
        client, err = hx.NewHTTPClient(hx.ClientOptions(retry_policy=policy))
        assert err is None
        server = f"http://127.0.0.1:{http_server.server_address[1]}/"
        req = hx.httpx.Request("GET", server)
        resp, err = client.Do(req)
        assert err is None or isinstance(err, hx.HttpError)
        assert http_server.request_count == 1
        assert resp.status_code == 404

    def test_retry_after_retryable_status(self, http_server):
        http_server.mode = "retryable"
        http_server.ok_at = 3
        policy = hx.RetryPolicy(max_retries=3, retry_backoff=timedelta(milliseconds=5))
        client, err = hx.NewHTTPClient(hx.ClientOptions(retry_policy=policy))
        assert err is None
        server = f"http://127.0.0.1:{http_server.server_address[1]}/"
        req = hx.httpx.Request("GET", server)
        resp, err = client.Do(req)
        assert err is None
        assert http_server.request_count == 3
        assert resp.status_code == 200

    def test_retry_exhausted_returns_error(self, http_server):
        http_server.mode = "retryable"
        http_server.ok_at = 99
        policy = hx.RetryPolicy(max_retries=2, retry_backoff=timedelta(milliseconds=5))
        client, err = hx.NewHTTPClient(hx.ClientOptions(retry_policy=policy))
        assert err is None
        server = f"http://127.0.0.1:{http_server.server_address[1]}/"
        req = hx.httpx.Request("GET", server)
        resp, err = client.Do(req)
        assert err is None
        assert resp is not None
        assert resp.status_code == 503
        assert http_server.request_count == 3


class _CancelledCtx:
    def err(self):
        return Exception("canceled")

    def remaining(self):
        return None


class TestDoWithContext:
    def test_canceled_context_returns_error(self, http_server):
        client, err = hx.NewHTTPClient(None)
        assert err is None
        req = hx.httpx.Request("GET", f"http://127.0.0.1:{http_server.server_address[1]}/")
        resp, err = client.DoWithContext(_CancelledCtx(), req)
        assert resp is None
        assert isinstance(err, hx.HttpError)
        assert "context canceled" in str(err)
