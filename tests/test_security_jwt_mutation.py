# SPDX-License-Identifier: MIT
"""Mutation-targeted tests for ``dxrk.security.jwt``.

The existing security tests assert that failures raise ``ValueError`` but do
not pin the exact message or the populated ``TokenInfo`` fields.  Those gaps
let dozens of mutants survive.  These tests close the gaps with observable
contracts, not with artificial branches.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from dxrk.security.jwt import (
    RefreshConfig,
    TenantAuthorizer,
    TokenInfo,
    TokenKind,
    TokenRefreshScheduler,
    TrustedDevice,
    _b64url_decode,
    _extract_tid_role_tenants,
    _tenant_env_name,
    classify_token,
    decode_jwt_payload,
    default_refresh_config,
    is_device_trusted,
    is_token_expired,
    make_tenant_key_func,
    parse_token_safe,
    redact_token,
    tenant_key_func,
    validate_id,
    validate_ingress_url,
)

SECRET = b"test-secret-key-0123456789"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign(
    claims: object,
    *,
    header: object | None = None,
    secret: bytes = SECRET,
) -> str:
    header_obj = {"alg": "HS256", "typ": "JWT"} if header is None else header
    header_raw = _b64url(json.dumps(header_obj, separators=(",", ":")).encode())
    payload_raw = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signature = hmac.new(secret, f"{header_raw}.{payload_raw}".encode(), hashlib.sha256).digest()
    return f"{header_raw}.{payload_raw}.{_b64url(signature)}"


def _key_func(header: dict[str, object], claims: dict[str, object]) -> bytes:
    return SECRET


def _info(**overrides: object) -> TokenInfo:
    values: dict[str, object] = {
        "kind": TokenKind.UNKNOWN,
        "token": "token",
        "subject": "subject",
        "issuer": "issuer",
        "expires_at": None,
        "issued_at": None,
        "claims": {},
        "is_valid": True,
        "is_expired": False,
        "tenant_id": "acme",
        "role": "admin",
        "tenants": ["acme"],
    }
    values.update(overrides)
    return TokenInfo(**values)  # type: ignore[arg-type]


# ---- Low-level decoding ----


def test_b64url_decode_restores_padding() -> None:
    assert _b64url_decode("YQ") == b"a"
    assert _b64url_decode("YWI") == b"ab"
    assert _b64url_decode("YWJj") == b"abc"


def test_decode_jwt_payload_accepts_two_part_token() -> None:
    header = _b64url(b'{"alg":"HS256"}')
    payload = _b64url(b'{"tid":"acme"}')
    assert decode_jwt_payload(f"{header}.{payload}") == {"tid": "acme"}


def test_decode_jwt_payload_rejects_non_dict_and_bad_shapes() -> None:
    assert decode_jwt_payload("singleton") is None
    assert decode_jwt_payload("a.b.c.d") is None
    assert decode_jwt_payload(f"{_b64url(b'{}')}.{_b64url(b'[]')}") is None
    assert decode_jwt_payload(f"{_b64url(b'{}')}.{_b64url(b'not-json')}") is None
    assert decode_jwt_payload(f"{_b64url(b'{}')}.!!!") is None


# ---- Claim extraction ----


def test_extract_tid_role_tenants_prefers_tid() -> None:
    tid, role, tenants = _extract_tid_role_tenants(
        {"tid": "acme", "tenant_id": "other", "role": "dev", "tenants": ["a", "b"]}
    )
    assert (tid, role, tenants) == ("acme", "dev", ["a", "b"])


def test_extract_tid_role_tenants_falls_back_to_tenant_id() -> None:
    tid, role, tenants = _extract_tid_role_tenants({"tid": 123, "tenant_id": "alt", "role": 5, "tenants": ["alt", 7]})
    assert (tid, role, tenants) == ("alt", "", ["alt"])


def test_extract_tid_role_tenants_handles_string_and_invalid_tenants() -> None:
    assert _extract_tid_role_tenants({"tid": "a", "tenants": "a"})[2] == ["a"]
    assert _extract_tid_role_tenants({"tid": "a", "tenants": ""})[2] == []
    assert _extract_tid_role_tenants({"tid": "a", "tenants": 42})[2] == []
    assert _extract_tid_role_tenants({"tid": "a"})[2] == []
    assert _extract_tid_role_tenants({"tid": "", "tenant_id": ""})[0] == ""


# ---- parse_token_safe ----


def test_parse_token_safe_populates_every_field() -> None:
    now = int(time.time())
    token = _sign(
        {
            "sub": "user42",
            "iss": "dxrk",
            "exp": now + 3600,
            "iat": now,
            "tid": "acme",
            "role": "admin",
            "tenants": ["acme", "beta"],
        }
    )

    info = parse_token_safe(token, _key_func)

    assert info.kind == TokenKind.UNKNOWN
    assert info.token == token
    assert info.subject == "user42"
    assert info.issuer == "dxrk"
    assert info.claims["sub"] == "user42"
    assert info.tenant_id == "acme"
    assert info.role == "admin"
    assert info.tenants == ["acme", "beta"]
    assert info.is_valid is True
    assert info.is_expired is False
    assert info.expires_at == datetime.fromtimestamp(now + 3600, tz=UTC)
    assert info.expires_at is not None and info.expires_at.tzinfo is UTC
    assert info.issued_at == datetime.fromtimestamp(now, tz=UTC)
    assert info.issued_at is not None and info.issued_at.tzinfo is UTC


def test_parse_token_safe_defaults_for_missing_and_non_string_claims() -> None:
    now = int(time.time())
    token = _sign({"exp": now + 3600, "sub": 123, "iss": None})

    info = parse_token_safe(token, _key_func)

    assert info.subject == ""
    assert info.issuer == ""
    assert info.tenant_id == ""
    assert info.role == ""
    assert info.tenants == []
    assert info.issued_at is None
    assert info.expires_at is not None


@pytest.mark.parametrize(
    ("token", "message"),
    [
        ("a.b", "parse token: token is malformed"),
        (_sign({"exp": int(time.time()) + 60}, header={"alg": "none"}), "parse token: unexpected signing method"),
        (_sign({"exp": int(time.time()) - 60}), "parse token: token is expired"),
    ],
)
def test_parse_token_safe_exact_error_messages(token: str, message: str) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        parse_token_safe(token, _key_func)


def test_parse_token_safe_invalid_signature_message() -> None:
    now = int(time.time())
    token = _sign({"exp": now + 60})
    with pytest.raises(ValueError, match="^parse token: signature is invalid$"):
        parse_token_safe(token[:-4] + "AAAA", _key_func)


def test_parse_token_safe_invalid_claims_type_message() -> None:
    header = _b64url(b"[]")
    payload = _b64url(b"{}")
    with pytest.raises(ValueError, match="^parse token: invalid claims type$"):
        parse_token_safe(f"{header}.{payload}.sig", _key_func)

    header = _b64url(b"{}")
    payload = _b64url(b"[]")
    with pytest.raises(ValueError, match="^parse token: invalid claims type$"):
        parse_token_safe(f"{header}.{payload}.sig", _key_func)


def test_parse_token_safe_wraps_decode_and_key_errors() -> None:
    now = int(time.time())
    with pytest.raises(ValueError, match="^parse token: "):
        parse_token_safe("!!!.e30.!!!", _key_func)

    header = _b64url(b"not-json")
    payload = _b64url(b"{}")
    with pytest.raises(ValueError, match="^parse token: "):
        parse_token_safe(f"{header}.{payload}.sig", _key_func)

    token = _sign({"exp": now + 60})

    def boom(header: dict[str, object], claims: dict[str, object]) -> bytes:
        raise RuntimeError("kaboom")

    with pytest.raises(ValueError, match="^parse token: kaboom$"):
        parse_token_safe(token, boom)


# ---- key funcs ----


def test_tenant_key_func_falls_back_when_tid_is_not_a_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DXRK_JWT_SECRET_ACME", "tenant-secret")
    assert tenant_key_func({}, {"tid": 123, "tenant_id": "acme"}) == b"tenant-secret"


def test_tenant_key_func_ignores_non_string_alt_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET_ACME", raising=False)
    monkeypatch.setenv("DXRK_JWT_SECRET", "generic-secret")
    assert tenant_key_func({}, {"tid": 123, "tenant_id": 456}) == b"generic-secret"


def test_tenant_key_func_generic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET_ACME", raising=False)
    monkeypatch.setenv("DXRK_JWT_SECRET", "generic-secret")
    assert tenant_key_func({}, {"tid": "acme"}) == b"generic-secret"


def test_tenant_key_func_missing_tid_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
    with pytest.raises(ValueError, match="^missing tid claim for tenant key resolution$"):
        tenant_key_func({}, {})


def test_tenant_key_func_vault_failure_raises_tenant_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET_ACME", raising=False)
    monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
    monkeypatch.setattr(
        "dxrk.vault.get_tenant_vault",
        lambda tenant_id: (_ for _ in ()).throw(RuntimeError("vault down")),
    )
    with pytest.raises(ValueError, match="^no JWT secret for tenant 'acme'$"):
        tenant_key_func({}, {"tid": "acme"})


def test_make_tenant_key_func_uses_custom_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET_ACME", raising=False)
    monkeypatch.setenv("CUSTOM_DEFAULT", "custom-secret")
    key_func = make_tenant_key_func("CUSTOM_DEFAULT")
    assert key_func({}, {"tid": "acme"}) == b"custom-secret"


def test_make_tenant_key_func_without_tid_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
    key_func = make_tenant_key_func()
    with pytest.raises(ValueError, match="^missing tid claim for tenant key resolution$"):
        key_func({}, {})


def test_tenant_env_name_normalizes() -> None:
    assert _tenant_env_name("acme-corp") == "DXRK_JWT_SECRET_ACME_CORP"
    assert _tenant_env_name("acme", prefix="CUSTOM") == "CUSTOM_ACME"


# ---- refresh config ----


def test_default_refresh_config_exact_values() -> None:
    config = default_refresh_config()
    assert config.poll_interval == timedelta(minutes=5)
    assert config.refresh_before == timedelta(minutes=10)
    assert config.retry_interval == timedelta(seconds=30)
    assert config.max_retries == 2
    assert config.clock_skew == timedelta(seconds=30)


def test_scheduler_with_partial_config_uses_defaults() -> None:
    scheduler = TokenRefreshScheduler("", lambda: "new", RefreshConfig())
    assert scheduler._config == default_refresh_config()
    scheduler.stop()


def test_scheduler_retries_and_records_failure() -> None:
    calls = {"n": 0}

    def refresh() -> str:
        calls["n"] += 1
        raise RuntimeError("refresh failed")

    scheduler = TokenRefreshScheduler(
        _sign({"exp": int(time.time()) - 60}),
        refresh,
        RefreshConfig(
            poll_interval=timedelta(seconds=60),
            refresh_before=timedelta(seconds=0),
            retry_interval=timedelta(seconds=0),
            max_retries=2,
            clock_skew=timedelta(seconds=0),
        ),
    )
    scheduler._attempt_refresh()
    assert calls["n"] == 3
    _, failures, last_refresh, last_error = scheduler.refresh_stats()
    assert failures == 1
    assert last_refresh is None
    assert isinstance(last_error, RuntimeError)


def test_scheduler_empty_refresh_token_counts_failure() -> None:
    scheduler = TokenRefreshScheduler(
        _sign({"exp": int(time.time()) - 60}),
        lambda: "",
        RefreshConfig(
            poll_interval=timedelta(seconds=60),
            retry_interval=timedelta(seconds=0),
            max_retries=0,
        ),
    )
    scheduler._attempt_refresh()
    _, failures, _, last_error = scheduler.refresh_stats()
    assert failures == 1
    assert isinstance(last_error, ValueError)
    assert str(last_error) == "refresh returned empty token"


# ---- trusted devices / validation ----


def test_is_device_trusted_all_branches() -> None:
    now = datetime.now(UTC)
    old = now - timedelta(minutes=11)
    fresh = now - timedelta(minutes=5)
    future = now + timedelta(hours=1)

    assert is_device_trusted(TrustedDevice("", "d", old, future)) is False
    assert is_device_trusted(TrustedDevice("t", "d", old, now - timedelta(seconds=1))) is False
    assert is_device_trusted(TrustedDevice("t", "d", fresh, future)) is False
    assert is_device_trusted(TrustedDevice("t", "d", old, future)) is True


def test_validate_ingress_url_all_branches() -> None:
    assert validate_ingress_url("http://evil.example", is_dev=True) is None
    assert validate_ingress_url("http://localhost:8080", is_dev=False) is None
    assert validate_ingress_url("http://127.0.0.1:8080", is_dev=False) is None
    assert validate_ingress_url("https://example.com", is_dev=False) is None
    with pytest.raises(
        ValueError,
        match=r"^insecure origin required: http://evil\.example \(must use HTTPS in production\)$",
    ):
        validate_ingress_url("http://evil.example", is_dev=False)


def test_validate_ingress_url_does_not_trust_lookalike_hosts() -> None:
    for url in ("http://localhost.evil.example", "http://127.0.0.1.evil.example"):
        with pytest.raises(ValueError, match="^insecure origin required: "):
            validate_ingress_url(url, is_dev=False)


def test_validate_id_boundaries() -> None:
    assert validate_id("") is False
    assert validate_id("a") is True
    assert validate_id("a" * 256) is True
    assert validate_id("a" * 257) is False
    assert validate_id("abc$") is False
    assert validate_id("abc-123_XYZ") is True


def test_redact_token_boundaries() -> None:
    assert redact_token("a" * 15) == "[REDACTED]"
    assert redact_token("a" * 16) == "aaaaaaaa...aaaa"
    token = "sk-ant-oa-0123456789abcdef"
    assert redact_token(token) == "sk-ant-o...cdef"


# ---- authorizer ----


def test_tenant_authorizer_messages() -> None:
    authorizer = TenantAuthorizer()
    with pytest.raises(ValueError, match="^missing tid claim$"):
        authorizer.authorize(_info(tenant_id=""))
    with pytest.raises(PermissionError, match=r"^tid 'acme' not in tenants \['other'\]$"):
        authorizer.authorize(_info(tenants=["other"]))
    with pytest.raises(PermissionError, match="^invalid role 'root'$"):
        authorizer.authorize(_info(role="root"))


def test_tenant_authorizer_is_authorized_and_custom_roles() -> None:
    authorizer = TenantAuthorizer()
    assert authorizer.is_authorized(_info()) is True
    assert authorizer.is_authorized(_info(tenant_id="")) is False
    assert authorizer.is_authorized(_info(tenants=["other"])) is False
    assert authorizer.is_authorized(_info(role="root")) is False

    custom = TenantAuthorizer({"ops"})
    custom.authorize(_info(role="ops", tenants=["acme"]))
    with pytest.raises(PermissionError, match="^invalid role 'admin'$"):
        custom.authorize(_info(role="admin"))


def test_tenant_authorizer_authorize_claims() -> None:
    TenantAuthorizer().authorize_claims({"tid": "acme", "role": "dev", "tenants": ["acme"]})
    with pytest.raises(ValueError, match="^missing tid claim$"):
        TenantAuthorizer().authorize_claims({})


def test_classify_token_unknown_and_access() -> None:
    assert classify_token("sk-ant-si-abc") == TokenKind.SESSION_INGRESS
    assert classify_token("sk-ant-oa-abc") == TokenKind.ACCESS_TOKEN
    assert classify_token("other") == TokenKind.UNKNOWN


def test_is_token_expired_malformed_and_skew() -> None:
    now = int(time.time())
    assert is_token_expired("malformed", timedelta(seconds=0)) is False
    assert is_token_expired(_sign({"exp": now + 3600}), timedelta(seconds=0)) is False
    assert is_token_expired(_sign({"exp": now - 3600}), timedelta(seconds=0)) is True
    assert is_token_expired(_sign({}), timedelta(seconds=0)) is False


# ---- refresh scheduler internals ----


def _scheduler(
    token: str,
    refresh: object,
    *,
    refresh_before: timedelta | None = timedelta(minutes=10),
    clock_skew: timedelta = timedelta(0),
    max_retries: int = 0,
    retry_interval: timedelta = timedelta(0),
) -> TokenRefreshScheduler:
    return TokenRefreshScheduler(
        token,
        refresh,  # type: ignore[arg-type]
        RefreshConfig(
            poll_interval=timedelta(seconds=60),
            refresh_before=refresh_before,
            retry_interval=retry_interval,
            max_retries=max_retries,
            clock_skew=clock_skew,
        ),
    )


class _RefreshSpy:
    def __init__(self, new_token: str) -> None:
        self.new_token = new_token
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.new_token


class _RecordingStop:
    """Stand-in for ``threading.Event`` that records backoff waits."""

    def __init__(self, stop_on: int | None = None) -> None:
        self.delays: list[float] = []
        self.stop_on = stop_on

    def wait(self, seconds: float) -> bool:
        self.delays.append(seconds)
        return self.stop_on is not None and len(self.delays) >= self.stop_on

    def set(self) -> None:
        pass


def test_scheduler_initial_stats_are_zero() -> None:
    scheduler = _scheduler("", lambda: "")
    assert scheduler.refresh_stats() == (0, 0, None, None)
    scheduler.stop()


def test_maybe_refresh_ignores_empty_token() -> None:
    spy = _RefreshSpy("new")
    scheduler = _scheduler("", spy)
    scheduler._maybe_refresh()
    assert spy.calls == 0


def test_maybe_refresh_ignores_malformed_token() -> None:
    spy = _RefreshSpy("new")
    scheduler = _scheduler("not-a-jwt", spy)
    scheduler._maybe_refresh()
    assert spy.calls == 0


def test_maybe_refresh_ignores_token_without_exp() -> None:
    spy = _RefreshSpy("new")
    scheduler = _scheduler(_sign({}), spy)
    scheduler._maybe_refresh()
    assert spy.calls == 0


def test_maybe_refresh_skips_token_outside_refresh_window() -> None:
    spy = _RefreshSpy("new")
    scheduler = _scheduler(_sign({"exp": int(time.time()) + 3600}), spy)
    scheduler._maybe_refresh()
    assert spy.calls == 0


def test_maybe_refresh_refreshes_token_inside_window() -> None:
    spy = _RefreshSpy("new-token")
    scheduler = _scheduler(_sign({"exp": int(time.time()) + 60}), spy)
    scheduler._maybe_refresh()
    assert spy.calls == 1
    assert scheduler.token() == "new-token"


def test_maybe_refresh_refreshes_expired_token() -> None:
    spy = _RefreshSpy("new-token")
    scheduler = _scheduler(_sign({"exp": int(time.time()) - 60}), spy)
    scheduler._maybe_refresh()
    assert spy.calls == 1
    assert scheduler.token() == "new-token"


def test_attempt_refresh_success_updates_state_and_accumulates() -> None:
    tokens = iter(["first", "second"])
    scheduler = _scheduler("old", lambda: next(tokens))
    scheduler._attempt_refresh()

    count, failures, last_refresh, last_error = scheduler.refresh_stats()
    assert scheduler.token() == "first"
    assert (count, failures, last_error) == (1, 0, None)
    assert last_refresh is not None
    assert last_refresh.tzinfo is UTC

    scheduler._attempt_refresh()
    count, failures, _, last_error = scheduler.refresh_stats()
    assert scheduler.token() == "second"
    assert (count, failures, last_error) == (2, 0, None)


def test_attempt_refresh_failure_count_accumulates() -> None:
    def boom() -> str:
        raise RuntimeError("refresh failed")

    scheduler = _scheduler("old", boom)
    scheduler._attempt_refresh()
    scheduler._attempt_refresh()

    count, failures, _, last_error = scheduler.refresh_stats()
    assert (count, failures) == (0, 2)
    assert isinstance(last_error, RuntimeError)


def test_attempt_refresh_zero_retries_means_single_attempt() -> None:
    spy = _RefreshSpy("")
    scheduler = _scheduler("old", spy, max_retries=0)
    scheduler._attempt_refresh()
    assert spy.calls == 1


def test_attempt_refresh_retries_empty_tokens() -> None:
    spy = _RefreshSpy("")
    scheduler = _scheduler("old", spy, max_retries=2)
    scheduler._attempt_refresh()
    assert spy.calls == 3
    _, failures, _, last_error = scheduler.refresh_stats()
    assert failures == 1
    assert isinstance(last_error, ValueError)
    assert str(last_error) == "refresh returned empty token"


def test_attempt_refresh_uses_exponential_backoff() -> None:
    def boom() -> str:
        raise RuntimeError("refresh failed")

    scheduler = _scheduler("old", boom, max_retries=2, retry_interval=timedelta(seconds=1))
    stop = _RecordingStop()
    scheduler._stop = stop  # type: ignore[assignment]
    scheduler._attempt_refresh()
    assert stop.delays == [1.0, 2.0]


def test_attempt_refresh_stops_during_backoff() -> None:
    calls = {"n": 0}

    def boom() -> str:
        calls["n"] += 1
        raise RuntimeError("refresh failed")

    scheduler = _scheduler("old", boom, max_retries=2, retry_interval=timedelta(seconds=1))
    stop = _RecordingStop(stop_on=1)
    scheduler._stop = stop  # type: ignore[assignment]
    scheduler._attempt_refresh()
    assert stop.delays == [1.0]
    assert calls["n"] == 1
    assert scheduler.refresh_stats() == (0, 0, None, None)


def test_scheduler_start_polls_until_stopped() -> None:
    token = _sign({"exp": int(time.time()) + 60})
    calls = {"n": 0}

    def refresh() -> str:
        calls["n"] += 1
        return token

    scheduler = _scheduler(token, refresh)
    scheduler._config.poll_interval = timedelta(seconds=0.01)
    scheduler.start()
    assert scheduler._thread is not None
    assert scheduler._thread.daemon is True

    time.sleep(0.25)
    scheduler.stop()
    assert calls["n"] >= 1
    assert calls["n"] <= 100
    assert scheduler._thread is not None
    assert scheduler._thread.is_alive() is False


def test_scheduler_stop_joins_with_timeout() -> None:
    class _FakeThread:
        def __init__(self) -> None:
            self.timeout: float | None = None

        def join(self, timeout: float | None = None) -> None:
            self.timeout = timeout

    scheduler = _scheduler("", lambda: "")
    fake = _FakeThread()
    scheduler._thread = fake  # type: ignore[assignment]
    scheduler.stop()
    assert fake.timeout == 5


def test_scheduler_start_with_zero_poll_interval() -> None:
    calls = {"n": 0}
    scheduler = _scheduler("", lambda: "")
    scheduler._config.poll_interval = timedelta(0)
    scheduler._maybe_refresh = lambda: calls.__setitem__("n", calls["n"] + 1)  # type: ignore[method-assign]

    scheduler.start()
    time.sleep(0.1)
    scheduler.stop()
    assert calls["n"] >= 1


# ---- clock boundaries ----


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return now

    monkeypatch.setattr("dxrk.security.jwt.datetime", _FrozenDatetime)


def test_maybe_refresh_uses_strict_refresh_window_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    _freeze_clock(monkeypatch, now)
    spy = _RefreshSpy("new-token")
    token = _sign({"exp": int(now.timestamp()) + 600})

    scheduler = _scheduler(token, spy, refresh_before=timedelta(minutes=10))
    scheduler._maybe_refresh()
    assert spy.calls == 1


def test_maybe_refresh_without_window_skips_non_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    _freeze_clock(monkeypatch, now)
    spy = _RefreshSpy("new-token")
    token = _sign({"exp": int(now.timestamp()) + 60})

    scheduler = _scheduler(token, spy, refresh_before=None)
    scheduler._maybe_refresh()
    assert spy.calls == 0


def test_is_token_expired_strict_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    _freeze_clock(monkeypatch, now)
    assert is_token_expired(_sign({"exp": int(now.timestamp())}), timedelta(0)) is False


def test_is_device_trusted_strict_expiry_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    _freeze_clock(monkeypatch, now)
    device = TrustedDevice("t", "d", now - timedelta(minutes=11), now)
    assert is_device_trusted(device) is True


def test_is_device_trusted_strict_age_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    _freeze_clock(monkeypatch, now)
    device = TrustedDevice("t", "d", now - timedelta(minutes=10), now + timedelta(hours=1))
    assert is_device_trusted(device) is True


# ---- key func vault paths ----


class _FakeVault:
    def __init__(self, secret: object, ok: bool) -> None:
        self.secret = secret
        self.ok = ok

    def get(self, key: str) -> tuple[object, bool]:
        if key != "jwt_secret":
            return None, False
        return self.secret, self.ok


def _patch_vault(monkeypatch: pytest.MonkeyPatch, vault: _FakeVault) -> None:
    def fake_get_tenant_vault(tenant_id: str) -> _FakeVault:
        if tenant_id != "acme":
            raise KeyError(tenant_id)
        return vault

    monkeypatch.setattr("dxrk.vault.get_tenant_vault", fake_get_tenant_vault)


@pytest.mark.parametrize("key_func", [tenant_key_func, make_tenant_key_func()], ids=["tenant", "factory"])
def test_key_func_reads_tenant_vault(monkeypatch: pytest.MonkeyPatch, key_func: object) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET_ACME", raising=False)
    monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
    _patch_vault(monkeypatch, _FakeVault("vault-secret", True))
    assert key_func({}, {"tid": "acme"}) == b"vault-secret"  # type: ignore[operator]


@pytest.mark.parametrize("key_func", [tenant_key_func, make_tenant_key_func()], ids=["tenant", "factory"])
@pytest.mark.parametrize(("secret", "ok"), [("secret", False), ("", True)])
def test_key_func_rejects_incomplete_vault_secret(
    monkeypatch: pytest.MonkeyPatch,
    key_func: object,
    secret: str,
    ok: bool,
) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET_ACME", raising=False)
    monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
    _patch_vault(monkeypatch, _FakeVault(secret, ok))
    with pytest.raises(ValueError, match="^no JWT secret for tenant 'acme'$"):
        key_func({}, {"tid": "acme"})  # type: ignore[operator]


def test_make_tenant_key_func_reads_tenant_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET_ACME", raising=False)
    monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
    _patch_vault(monkeypatch, _FakeVault("vault-secret", True))

    key_func = make_tenant_key_func()
    assert key_func({}, {"tid": "acme"}) == b"vault-secret"


@pytest.mark.parametrize(("secret", "ok"), [("secret", False), ("", True)])
def test_make_tenant_key_func_rejects_incomplete_vault_secret(
    monkeypatch: pytest.MonkeyPatch,
    secret: str,
    ok: bool,
) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET_ACME", raising=False)
    monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
    _patch_vault(monkeypatch, _FakeVault(secret, ok))

    key_func = make_tenant_key_func()
    with pytest.raises(ValueError, match="^no JWT secret for tenant 'acme'$"):
        key_func({}, {"tid": "acme"})


def test_make_tenant_key_func_uses_default_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET_ACME", raising=False)
    monkeypatch.setenv("DXRK_JWT_SECRET", "generic-secret")
    assert make_tenant_key_func()({}, {"tid": "acme"}) == b"generic-secret"


def test_make_tenant_key_func_uses_tenant_id_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DXRK_JWT_SECRET_ACME", "tenant-secret")
    assert make_tenant_key_func()({}, {"tenant_id": "acme"}) == b"tenant-secret"


def test_make_tenant_key_func_ignores_non_string_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET_ACME", raising=False)
    monkeypatch.setenv("DXRK_JWT_SECRET", "generic-secret")
    assert make_tenant_key_func()({}, {"tid": 123, "tenant_id": 456}) == b"generic-secret"


# ---- remaining observable edges ----


def test_parse_token_safe_defaults_for_missing_subject_and_issuer() -> None:
    info = parse_token_safe(_sign({"exp": int(time.time()) + 60}), _key_func)
    assert info.subject == ""
    assert info.issuer == ""


def test_parse_token_safe_strict_expiry_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    _freeze_clock(monkeypatch, now)
    info = parse_token_safe(_sign({"exp": int(now.timestamp())}), _key_func)
    assert info.is_valid is True


def test_is_device_trusted_accepts_ten_minutes_and_thirty_seconds() -> None:
    now = datetime.now(UTC)
    device = TrustedDevice(
        token="t",
        device_id="d",
        created_at=now - timedelta(minutes=10, seconds=30),
        expires_at=now + timedelta(hours=1),
    )
    assert is_device_trusted(device) is True


def test_extract_tid_role_tenants_rejects_non_string_tid() -> None:
    assert _extract_tid_role_tenants({"tid": 123})[0] == ""
    assert _extract_tid_role_tenants({"tid": None, "tenant_id": 456})[0] == ""


def test_validate_ingress_url_handles_unparseable_url() -> None:
    with pytest.raises(ValueError, match="^insecure origin required: "):
        validate_ingress_url("http://[::1", is_dev=False)
