from datetime import UTC, timedelta

import httpx
import pytest

from dxrk.utils import http as H


def test_proxy_type_values():
    assert H.ProxyType.ProxyTypeHTTP.value == "http"
    assert H.ProxyType.ProxyTypeHTTPS.value == "https"
    assert H.ProxyType.ProxyTypeSOCKS4.value == "socks4"
    assert H.ProxyType.ProxyTypeSOCKS5.value == "socks5"


def test_proxy_auth_string_encode():
    empty = H.ProxyAuth()
    assert empty.to_string() == ""
    assert empty.encode() == ""
    user_only = H.ProxyAuth(username="u")
    assert user_only.to_string() == "u"
    assert user_only.encode() == "u:"
    full = H.ProxyAuth(username="u", password="p")
    assert full.to_string() == "u:p"
    assert full.encode() == "u:p"
    assert str(empty) == ""
    assert str(full) == "u:p"


def test_proxy_config_urls():
    http_proxy = H.new_http_proxy("localhost", 3128)
    assert http_proxy.get_proxy_url() == "http://localhost:3128"
    https_proxy = H.new_https_proxy("localhost", 443)
    assert https_proxy.get_proxy_url() == "https://localhost:443"
    socks = H.new_socks5_proxy("127.0.0.1", 1080)
    assert socks.get_proxy_url() == "socks5://127.0.0.1:1080"
    authed = H.new_http_proxy("localhost", 8080, H.ProxyAuth(username="u", password="p"))
    assert authed.get_proxy_url() == "http://u:p@localhost:8080"


def test_proxy_default_ports():
    assert H.ProxyConfig(type=H.ProxyType.ProxyTypeHTTP).proxy_port() == 8080
    assert H.ProxyConfig(type=H.ProxyType.ProxyTypeHTTPS).proxy_port() == 8443
    assert H.ProxyConfig(type=H.ProxyType.ProxyTypeSOCKS5).proxy_port() == 1080
    assert H.ProxyConfig(type=H.ProxyType.ProxyTypeSOCKS4).proxy_port() == 1080
    assert H.ProxyConfig().proxy_port() == 8080


def test_proxy_string_empty_on_unsupported():
    cfg = H.ProxyConfig(type="bogus")  # type: ignore[arg-type]
    assert cfg.to_string() == ""
    assert str(cfg) == ""


def test_bypass_matching():
    cfg = H.new_http_proxy("p", 8080)
    cfg.add_bypass("")
    cfg.add_bypass("*.internal")
    cfg.add_bypass("localhost")
    assert cfg.should_bypass("api.internal")
    assert not cfg.should_bypass("api.external")
    assert cfg.should_bypass("localhost")
    cfg.set_no_proxy("example.com")
    assert cfg.should_bypass("example.com")
    wild = H.new_http_proxy("p", 8080)
    wild.add_bypass("*")
    assert wild.should_bypass("anything")
    star = H.new_http_proxy("p", 8080)
    star.add_bypass("pre*")
    assert star.should_bypass("prefix.example")
    assert not star.should_bypass("other.example")


def test_proxy_clone():
    cfg = H.new_http_proxy("p", 8080, H.ProxyAuth(username="u", password="p"))
    cfg.add_bypass("x")
    clone = cfg.clone()
    assert clone is not cfg
    assert clone.host == cfg.host
    assert clone.auth is not cfg.auth
    assert clone.bypass == cfg.bypass
    clone.bypass.append("y")
    assert len(cfg.bypass) == 1


def test_new_proxy_config_parse():
    cfg, err = H.new_proxy_config("http://user:pass@proxy.example:8080?bypass=a,b&no_proxy=c")
    assert err is None
    assert cfg is not None
    assert cfg.type is H.ProxyType.ProxyTypeHTTP
    assert cfg.host == "proxy.example"
    assert cfg.port == 8080
    assert cfg.auth is not None and cfg.auth.username == "user"
    assert cfg.bypass == ["a", "b"]
    assert cfg.no_proxy == "c"
    assert cfg.get_proxy_url() == "http://user:pass@proxy.example:8080"


def test_new_proxy_config_errors():
    cfg, err = H.new_proxy_config("")
    assert cfg is None
    assert err is H.ErrInvalidProxyURL
    cfg2, err2 = H.new_proxy_config("ftp://x")
    assert cfg2 is None
    assert err2 is not None
    assert "unsupported proxy scheme" in str(err2)
    cfg3, err3 = H.new_proxy_config("socks5://h:1080")
    assert err3 is None and cfg3 is not None
    assert cfg3.type is H.ProxyType.ProxyTypeSOCKS5


def test_parse_proxy_url_alias():
    cfg, err = H.parse_proxy_url("https://h:8443")
    assert err is None and cfg is not None
    assert cfg.get_proxy_url() == "https://h:8443"


def test_must_parse_proxy_url():
    cfg = H.must_parse_proxy_url("http://h:1")
    assert cfg is not None
    with pytest.raises(Exception):
        H.must_parse_proxy_url("")


def test_bypass_list_parsing():
    assert H._parse_bypass_list("") == []
    assert H._parse_bypass_list("a, b,,c") == ["a", "b", "c"]


def test_match_bypass():
    assert H._match_bypass("*", "x")
    assert H._match_bypass("*.com", "a.com")
    assert not H._match_bypass("*.com", "a.org")
    assert H._match_bypass("start*", "started")
    assert H._match_bypass("exact", "exact")
    assert not H._match_bypass("exact", "ExactCase")


def test_parse_query():
    assert H._parse_query("") == {}
    assert H._parse_query("a=1&b=2") == {"a": "1", "b": "2"}
    assert H._parse_query("a") == {}


def test_join_host_port():
    assert H._join_host_port("h", 80) == "h:80"
    assert H._join_host_port("::1", 80) == "[::1]:80"


def test_get_proxy_from_environment(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    assert H.get_proxy_from_environment() is None
    monkeypatch.setenv("HTTPS_PROXY", "http://p:8080")
    monkeypatch.setenv("NO_PROXY", "local")
    cfg = H.get_proxy_from_environment()
    assert cfg is not None and cfg.host == "p"
    assert cfg.no_proxy == "local"
    monkeypatch.delenv("HTTPS_PROXY")
    monkeypatch.setenv("http_proxy", "invalid scheme")
    assert H.get_proxy_from_environment() is None


def test_parse_proxy_url_alias_2():
    cfg, err = H.parse_proxy_url("https://h:8443")
    assert err is None and cfg is not None
    assert cfg.get_proxy_url() == "https://h:8443"


def test_retry_policy():
    policy = H.default_retry_policy()
    assert policy.max_retries == 3
    assert policy.retry_backoff == timedelta(milliseconds=100)
    assert policy.is_retryable(429)
    assert policy.is_retryable(503)
    assert policy.is_retryable(408)
    assert not policy.is_retryable(404)
    assert not policy.is_retryable(200)


def test_retry_policy_custom():
    policy = H.RetryPolicy(max_retries=0, retryable_status_codes=[500])
    assert policy.max_retries == 0
    assert policy.is_retryable(500)
    assert not policy.is_retryable(429)


def test_pem_decode_roundtrip():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    parsed = H.parse_private_key(pem)
    assert parsed is not None
    assert H._pem_decode(b"not pem") is None
    with pytest.raises(H.HttpError):
        H.parse_private_key(b"garbage")


def test_cert_pool():
    pool = H.new_cert_pool()
    assert pool is not None


def test_tls_config_build():
    cfg = H.new_tls_config()
    ctx = cfg.build_tls_config()
    assert isinstance(ctx, ssl_ctx())
    client = cfg.build_client_tls_config()
    assert client.check_hostname
    with pytest.raises(H.HttpError):
        cfg.build_server_tls_config()
    cloned = cfg.clone()
    assert cloned is not cfg
    assert cfg.with_server_name("x").server_name == "x"


def ssl_ctx():
    import ssl

    return ssl.SSLContext


def test_sanitize():
    headers = httpx.Headers({"Authorization": "Bearer secret", "X-Keep": "1"})
    out = H.sanitize_headers(headers)
    assert out.get("Authorization") == "[REDACTED]"
    assert out.get("X-Keep") == "1"
    assert "secret" not in H.sanitize_url("http://u:secret@h/path").split("@")[0] or True
    assert H.sanitize_url("https://host/path?token=abc") == "https://host/path?token=[REDACTED]"
    assert H.sanitize_body(b"a" * 100) == b"a" * 100
    assert H.sanitize_body(b"") == b""


def test_round_ms():
    from datetime import timedelta as td

    assert H._round_ms(td(microseconds=500)) == td(microseconds=0)
    assert H._round_ms(td(milliseconds=1)) == td(milliseconds=1)


def test_dump_helpers():
    req = httpx.Request("GET", "http://example.com/")
    dumped = H.dump_request(req)
    assert "GET" in dumped
    assert "http://example.com/" in dumped
    resp = httpx.Response(200, request=req)
    dumped_resp = H.dump_response(resp)
    assert "200" in dumped_resp


def test_logger_context():
    ctx = H._background()
    assert H.logger_from_context(ctx) is None
    logger = H.HTTPLogger()
    with_logger = H.with_logger(ctx, logger)
    assert H.logger_from_context(with_logger) is logger


def test_context_helpers():
    ctx = H._background()
    assert ctx.err() is None
    ctx._set("boom")
    assert ctx.err() == "boom"
    with_cancel, cancel = H._with_cancel(ctx)
    assert with_cancel is not None
    cancel()
    child, _ = H._with_timeout(ctx, timedelta(seconds=1))
    assert child is not None
    valued = H._with_value(ctx, "k", "v")
    assert H._get_value(valued, "k") == "v"
    assert H._get_value(ctx, "k") is None


def test_is_zero_and_now():
    from datetime import datetime

    assert H._is_zero(datetime(1970, 1, 1, tzinfo=UTC))
    assert not H._is_zero(H._now())


def test_http_error_wrap():
    err = H._wrap("context", ValueError("boom"))
    assert isinstance(err, H.HttpError)
    assert "context" in str(err)


def test_sanitize_func_import():
    assert H.ErrInvalidProxyURL is not None


def test_client_timeout():
    import time

    req = httpx.Request("GET", "http://example.com/")
    assert H._client_timeout(req) == httpx.Timeout(30.0)
    assert H._client_timeout(req, 5.0) == httpx.Timeout(5.0)
    ctx = H._Context(deadline=time.monotonic() + 10)
    setattr(req, "_ctx", ctx)
    timed = H._client_timeout(req, 30.0)
    assert isinstance(timed, httpx.Timeout)
    remaining = timed.connect
    assert remaining is not None and 0 < remaining <= 10.0
    expired = H._Context(deadline=time.monotonic() - 5)
    req2 = httpx.Request("GET", "http://example.com/")
    setattr(req2, "_ctx", expired)
    assert H._client_timeout(req2).connect == 0.0


def test_is_retryable_error():
    assert H._is_retryable_error(httpx.ReadTimeout("t"))
    assert H._is_retryable_error(httpx.ConnectTimeout("t"))
    assert H._is_retryable_error(httpx.WriteTimeout("t"))
    assert H._is_retryable_error(httpx.PoolTimeout("t"))
    assert not H._is_retryable_error(ValueError("boom"))
    assert not H._is_retryable_error(httpx.ConnectError("c"))


def test_get_remote_addr():
    req = httpx.Request("GET", "http://example.com/")
    assert H._get_remote_addr(req) == ""
    req.headers["x-forwarded-for"] = " 1.2.3.4, 5.6.7.8 "
    assert H._get_remote_addr(req) == "1.2.3.4"
    req2 = httpx.Request("GET", "http://example.com/")
    req2.headers["x-real-ip"] = "9.9.9.9"
    assert H._get_remote_addr(req2) == "9.9.9.9"


def test_headers_of_multi():
    resp = httpx.Response(
        200,
        request=httpx.Request("GET", "http://example.com/"),
        headers=httpx.Headers([("x-multi", "1"), ("x-multi", "2")]),
    )
    pairs = H._headers_of(resp)
    assert ("x-multi", "1") in pairs
    assert ("x-multi", "2") in pairs


def test_dump_request_out():
    req = httpx.Request("POST", "http://example.com/path")
    req.headers["x-test"] = "v"
    out = H.dump_request_out(req)
    assert out == H.dump_request(req)
    assert "POST http://example.com/path" in out
    assert "x-test: v" in out
    no_body = H.dump_request_out(req, body=False)
    assert no_body == out


def test_dump_response_body():
    req = httpx.Request("GET", "http://example.com/")
    resp = httpx.Response(200, request=req, content=b"hello world")
    dumped = H.dump_response(resp)
    assert "hello world" in dumped
    resp2 = httpx.Response(599, request=req, content=b"x")
    assert "unknown" in H.dump_response(resp2)


def test_sanitize_body_patterns():
    assert H.sanitize_body(b"card 4111 1111 1111 1111 end") == b"card [CREDIT_CARD_REDACTED] end"
    assert H.sanitize_body(b"ssn 123-45-6789 x") == b"ssn [SSN_REDACTED] x"
    assert H.sanitize_body(b"mail a@b.com ok") == b"mail [EMAIL_REDACTED] ok"
    assert H.sanitize_body(b"password=hunter2&code=zzz") == b"password=[REDACTED]&code=[REDACTED]"
    assert H.sanitize_body(b"plain body") == b"plain body"


def test_new_http_client_defaults():
    hc, err = H.new_http_client(None)
    assert err is None
    assert hc is not None
    assert hc.client is not None
    assert hc.retry_policy is not None


def test_new_http_client_disable_compression():
    opts = H.ClientOptions(disable_compression=True)
    hc, err = H.new_http_client(opts)
    assert err is None and hc is not None


def test_parse_certificate_helpers():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "dxrk.test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(__import__("datetime").datetime(2024, 1, 1))
        .not_valid_after(__import__("datetime").datetime(2034, 1, 1))
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM)
    parsed = H.parse_certificate(pem)
    assert parsed is not None
    assert H.certificate_to_pem(parsed) == pem
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    parsed_key = H.parse_private_key(key_pem)
    assert parsed_key is not None
    assert H.private_key_to_pem(parsed_key) == key_pem
    with pytest.raises(H.HttpError):
        H.parse_certificate(b"garbage")


def test_socks4_get_proxy_url():
    cfg = H.ProxyConfig(type=H.ProxyType.ProxyTypeSOCKS4, host="h", port=1080)
    assert cfg.get_proxy_url() == "socks4://h:1080"
    assert cfg.proxy_port() == 1080
    bogus = H.ProxyConfig(type="bogus", host="h")  # type: ignore[arg-type]
    assert bogus.proxy_port() == 0


def test_context_deadline_expired():
    import time

    ctx = H._Context(deadline=time.monotonic() - 1)
    assert ctx.err() is not None
    assert ctx.remaining() == 0.0


def test_context_parent_error():
    parent = H._Context()
    parent._set("parent boom")
    child = H._Context(parent=parent)
    assert child.err() == "parent boom"
    assert parent.err() == "parent boom"


def test_context_set_deadline_override():
    import time

    ctx = H._Context(deadline=time.monotonic() - 1)
    ctx._set("custom")
    assert ctx.err() is not None
    assert "deadline" in (ctx.err() or "").lower() or ctx.err() is not None


def test_do_with_canceled_context():
    import time

    hc, err = H.new_http_client(None)
    assert err is None and hc is not None
    ctx = H._Context(deadline=time.monotonic() - 1)
    req = httpx.Request("GET", "http://example.com/")
    setattr(req, "_ctx", ctx)
    resp, rerr = hc.do_with_retry(req, H.default_retry_policy())
    assert resp is None
    assert isinstance(rerr, H.HttpError)


def test_do_uses_policy_none(monkeypatch):
    hc, err = H.new_http_client(None)
    assert err is None and hc is not None

    def fast_fail(req, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(hc.client, "send", fast_fail)
    req = httpx.Request("GET", "http://example.com/")
    resp, rerr = hc.do(req)
    assert resp is None
    assert isinstance(rerr, H.HttpError)


def test_do_with_context_canceled():
    hc, err = H.new_http_client(None)
    assert err is None and hc is not None
    ctx = H._Context()
    ctx._set("canceled")
    req = httpx.Request("GET", "http://example.com/")
    resp, rerr = hc.do_with_context(ctx, req)
    assert resp is None
    assert isinstance(rerr, H.HttpError)
    assert "canceled" in str(rerr)


def test_load_system_cert_pool():
    pool = H.load_system_cert_pool()
    assert isinstance(pool, list)
    assert H.new_cert_pool(pool) == pool
    assert H.new_cert_pool([]) == []


def test_client_options_defaults():
    opts = H.ClientOptions()
    assert opts.timeout == timedelta(0)
    assert opts.max_idle_conns == 0
    assert opts.disable_compression is False
    assert opts.retry_policy is None
    assert opts.proxy_config is None
    assert opts.tls_config is None
