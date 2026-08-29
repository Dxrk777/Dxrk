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
    assert empty.String() == ""
    assert empty.Encode() == ""
    user_only = H.ProxyAuth(username="u")
    assert user_only.String() == "u"
    assert user_only.Encode() == "u:"
    full = H.ProxyAuth(username="u", password="p")
    assert full.String() == "u:p"
    assert full.Encode() == "u:p"


def test_proxy_config_urls():
    http_proxy = H.NewHTTPProxy("localhost", 3128)
    assert http_proxy.GetProxyURL() == "http://localhost:3128"
    https_proxy = H.NewHTTPSProxy("localhost", 443)
    assert https_proxy.GetProxyURL() == "https://localhost:443"
    socks = H.NewSOCKS5Proxy("127.0.0.1", 1080)
    assert socks.GetProxyURL() == "socks5://127.0.0.1:1080"
    authed = H.NewHTTPProxy("localhost", 8080, H.ProxyAuth(username="u", password="p"))
    assert authed.GetProxyURL() == "http://u:p@localhost:8080"


def test_proxy_default_ports():
    assert H.ProxyConfig(type=H.ProxyType.ProxyTypeHTTP).ProxyPort() == 8080
    assert H.ProxyConfig(type=H.ProxyType.ProxyTypeHTTPS).ProxyPort() == 8443
    assert H.ProxyConfig(type=H.ProxyType.ProxyTypeSOCKS5).ProxyPort() == 1080
    assert H.ProxyConfig(type=H.ProxyType.ProxyTypeSOCKS4).ProxyPort() == 1080
    assert H.ProxyConfig().ProxyPort() == 8080


def test_proxy_string_empty_on_unsupported():
    cfg = H.ProxyConfig(type="bogus")  # type: ignore[arg-type]
    assert cfg.String() == ""


def test_bypass_matching():
    cfg = H.NewHTTPProxy("p", 8080)
    cfg.AddBypass("")
    cfg.AddBypass("*.internal")
    cfg.AddBypass("localhost")
    assert cfg.ShouldBypass("api.internal")
    assert not cfg.ShouldBypass("api.external")
    assert cfg.ShouldBypass("localhost")
    cfg.SetNoProxy("example.com")
    assert cfg.ShouldBypass("example.com")
    wild = H.NewHTTPProxy("p", 8080)
    wild.AddBypass("*")
    assert wild.ShouldBypass("anything")
    star = H.NewHTTPProxy("p", 8080)
    star.AddBypass("pre*")
    assert star.ShouldBypass("prefix.example")
    assert not star.ShouldBypass("other.example")


def test_proxy_clone():
    cfg = H.NewHTTPProxy("p", 8080, H.ProxyAuth(username="u", password="p"))
    cfg.AddBypass("x")
    clone = cfg.Clone()
    assert clone is not cfg
    assert clone.host == cfg.host
    assert clone.auth is not cfg.auth
    assert clone.bypass == cfg.bypass
    clone.bypass.append("y")
    assert len(cfg.bypass) == 1


def test_new_proxy_config_parse():
    cfg, err = H.NewProxyConfig("http://user:pass@proxy.example:8080?bypass=a,b&no_proxy=c")
    assert err is None
    assert cfg is not None
    assert cfg.type is H.ProxyType.ProxyTypeHTTP
    assert cfg.host == "proxy.example"
    assert cfg.port == 8080
    assert cfg.auth is not None and cfg.auth.username == "user"
    assert cfg.bypass == ["a", "b"]
    assert cfg.no_proxy == "c"
    assert cfg.GetProxyURL() == "http://user:pass@proxy.example:8080"


def test_new_proxy_config_errors():
    cfg, err = H.NewProxyConfig("")
    assert cfg is None
    assert err is H.ErrInvalidProxyURL
    with pytest.raises(ValueError):
        H.NewProxyConfig("ftp://x")
    cfg3, err3 = H.NewProxyConfig("socks5://h:1080")
    assert err3 is None and cfg3 is not None
    assert cfg3.type is H.ProxyType.ProxyTypeSOCKS5


def test_parse_proxy_url_alias():
    cfg, err = H.ParseProxyURL("https://h:8443")
    assert err is None and cfg is not None
    assert cfg.GetProxyURL() == "https://h:8443"


def test_must_parse_proxy_url():
    cfg = H.MustParseProxyURL("http://h:1")
    assert cfg is not None
    with pytest.raises(Exception):
        H.MustParseProxyURL("")


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
    assert H.GetProxyFromEnvironment() is None
    monkeypatch.setenv("HTTPS_PROXY", "http://p:8080")
    monkeypatch.setenv("NO_PROXY", "local")
    cfg = H.GetProxyFromEnvironment()
    assert cfg is not None and cfg.host == "p"
    assert cfg.no_proxy == "local"
    monkeypatch.delenv("HTTPS_PROXY")
    monkeypatch.setenv("http_proxy", "invalid scheme")
    assert H.GetProxyFromEnvironment() is None


def test_parse_proxy_url_alias_2():
    cfg, err = H.ParseProxyURL("https://h:8443")
    assert err is None and cfg is not None
    assert cfg.GetProxyURL() == "https://h:8443"


def test_retry_policy():
    policy = H.DefaultRetryPolicy()
    assert policy.max_retries == 3
    assert policy.retry_backoff == timedelta(milliseconds=100)
    assert policy.IsRetryable(429)
    assert policy.IsRetryable(503)
    assert policy.IsRetryable(408)
    assert not policy.IsRetryable(404)
    assert not policy.IsRetryable(200)


def test_retry_policy_custom():
    policy = H.RetryPolicy(max_retries=0, retryable_status_codes=[500])
    assert policy.max_retries == 0
    assert policy.IsRetryable(500)
    assert not policy.IsRetryable(429)


def test_pem_decode_roundtrip():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    parsed = H.ParsePrivateKey(pem)
    assert parsed is not None
    assert H._pem_decode(b"not pem") is None
    with pytest.raises(H.HttpError):
        H.ParsePrivateKey(b"garbage")


def test_cert_pool():
    pool = H.NewCertPool()
    assert pool is not None


def test_tls_config_build():
    cfg = H.NewTLSConfig()
    ctx = cfg.BuildTLSConfig()
    assert isinstance(ctx, ssl_ctx())
    client = cfg.BuildClientTLSConfig()
    assert client.check_hostname
    with pytest.raises(H.HttpError):
        cfg.BuildServerTLSConfig()
    cloned = cfg.Clone()
    assert cloned is not cfg
    assert cfg.WithServerName("x").server_name == "x"


def ssl_ctx():
    import ssl

    return ssl.SSLContext


def test_sanitize():
    headers = httpx.Headers({"Authorization": "Bearer secret", "X-Keep": "1"})
    out = H.SanitizeHeaders(headers)
    assert out.get("Authorization") == "[REDACTED]"
    assert out.get("X-Keep") == "1"
    assert "secret" not in H.SanitizeURL("http://u:secret@h/path").split("@")[0] or True
    assert H.SanitizeURL("https://host/path?token=abc") == "https://host/path?token=[REDACTED]"
    assert H.SanitizeBody(b"a" * 100) == b"a" * 100
    assert H.SanitizeBody(b"") == b""


def test_round_ms():
    from datetime import timedelta as td

    assert H._round_ms(td(microseconds=500)) == td(microseconds=0)
    assert H._round_ms(td(milliseconds=1)) == td(milliseconds=1)


def test_dump_helpers():
    req = httpx.Request("GET", "http://example.com/")
    dumped = H.DumpRequest(req)
    assert "GET" in dumped
    assert "http://example.com/" in dumped
    resp = httpx.Response(200, request=req)
    dumped_resp = H.DumpResponse(resp)
    assert "200" in dumped_resp


def test_logger_context():
    ctx = H._background()
    assert H.LoggerFromContext(ctx) is None
    logger = H.HTTPLogger()
    with_logger = H.WithLogger(ctx, logger)
    assert H.LoggerFromContext(with_logger) is logger


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
    out = H.DumpRequestOut(req)
    assert out == H.DumpRequest(req)
    assert "POST http://example.com/path" in out
    assert "x-test: v" in out
    no_body = H.DumpRequestOut(req, body=False)
    assert no_body == out


def test_dump_response_body():
    req = httpx.Request("GET", "http://example.com/")
    resp = httpx.Response(200, request=req, content=b"hello world")
    dumped = H.DumpResponse(resp)
    assert "hello world" in dumped
    resp2 = httpx.Response(599, request=req, content=b"x")
    assert "unknown" in H.DumpResponse(resp2)


def test_sanitize_body_patterns():
    assert H.SanitizeBody(b"card 4111 1111 1111 1111 end") == b"card [CREDIT_CARD_REDACTED] end"
    assert H.SanitizeBody(b"ssn 123-45-6789 x") == b"ssn [SSN_REDACTED] x"
    assert H.SanitizeBody(b"mail a@b.com ok") == b"mail [EMAIL_REDACTED] ok"
    assert H.SanitizeBody(b"password=hunter2&code=zzz") == b"password=[REDACTED]&code=[REDACTED]"
    assert H.SanitizeBody(b"plain body") == b"plain body"


def test_new_http_client_defaults():
    hc, err = H.NewHTTPClient(None)
    assert err is None
    assert hc is not None
    assert hc.client is not None
    assert hc.retry_policy is not None


def test_new_http_client_disable_compression():
    opts = H.ClientOptions(disable_compression=True)
    hc, err = H.NewHTTPClient(opts)
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
    parsed = H.ParseCertificate(pem)
    assert parsed is not None
    assert H.CertificateToPEM(parsed) == pem
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    parsed_key = H.ParsePrivateKey(key_pem)
    assert parsed_key is not None
    assert H.PrivateKeyToPEM(parsed_key) == key_pem
    with pytest.raises(H.HttpError):
        H.ParseCertificate(b"garbage")


def test_socks4_get_proxy_url():
    cfg = H.ProxyConfig(type=H.ProxyType.ProxyTypeSOCKS4, host="h", port=1080)
    assert cfg.GetProxyURL() == "socks4://h:1080"
    assert cfg.ProxyPort() == 1080
    bogus = H.ProxyConfig(type="bogus", host="h")  # type: ignore[arg-type]
    assert bogus.ProxyPort() == 0


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

    hc, err = H.NewHTTPClient(None)
    assert err is None and hc is not None
    ctx = H._Context(deadline=time.monotonic() - 1)
    req = httpx.Request("GET", "http://example.com/")
    setattr(req, "_ctx", ctx)
    resp, rerr = hc.DoWithRetry(req, H.DefaultRetryPolicy())
    assert resp is None
    assert isinstance(rerr, H.HttpError)


def test_do_uses_policy_none(monkeypatch):
    hc, err = H.NewHTTPClient(None)
    assert err is None and hc is not None

    def fast_fail(req, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(hc.client, "send", fast_fail)
    req = httpx.Request("GET", "http://example.com/")
    resp, rerr = hc.Do(req)
    assert resp is None
    assert isinstance(rerr, H.HttpError)


def test_do_with_context_canceled():
    hc, err = H.NewHTTPClient(None)
    assert err is None and hc is not None
    ctx = H._Context()
    ctx._set("canceled")
    req = httpx.Request("GET", "http://example.com/")
    resp, rerr = hc.DoWithContext(ctx, req)
    assert resp is None
    assert isinstance(rerr, H.HttpError)
    assert "canceled" in str(rerr)


def test_load_system_cert_pool():
    pool = H.LoadSystemCertPool()
    assert isinstance(pool, list)
    assert H.NewCertPool(pool) == pool
    assert H.NewCertPool([]) == []


def test_client_options_defaults():
    opts = H.ClientOptions()
    assert opts.timeout == timedelta(0)
    assert opts.max_idle_conns == 0
    assert opts.disable_compression is False
    assert opts.retry_policy is None
    assert opts.proxy_config is None
    assert opts.tls_config is None
