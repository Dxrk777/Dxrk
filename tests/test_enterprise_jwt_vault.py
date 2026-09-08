# SPDX-License-Identifier: MIT
"""Enterprise verification: per-tenant JWT isolation + per-tenant vault isolation.

Deterministic: no network, no sleeps, no wall-clock windows (fixed exp timestamps).
Vault disk writes are confined to ``tmp_path`` via isolated ``HOME``. Only this
test file is created; no sources are modified.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import timedelta

import pytest

from dxrk.security.jwt import (
    TenantAuthorizer,
    TokenInfo,
    TokenKind,
    classify_token,
    decode_jwt_payload,
    get_tenant_from_token,
    is_token_expired,
    make_tenant_key_func,
    parse_token_safe,
    redact_token,
    tenant_key_func,
)
from dxrk.security.rbac import authorize_via_jwt
from dxrk.vault import TenantVaultRegistry, _derive_tenant_key

# Fixed timestamps: 2001-09-09 (always past) and 2100-01-01 (always future).
PAST_EXP = 1_000_000_000
FUTURE_EXP = 4_102_444_800


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unsigned_token(payload: dict[str, object]) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    return f"{header}.{body}.c2ln"


def _signed_token(payload: dict[str, object], secret: bytes) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64url(hmac.new(secret, f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def _fixed_key(header: dict[str, object], claims: dict[str, object]) -> bytes:
    return b"fixed-test-key-0123456789"


def _isolated_registry(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> TenantVaultRegistry:
    from pathlib import Path as _Path

    home = str(_Path(str(tmp_path)))
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("DXRK_VAULT_KEY", "enterprise-test-master-key")
    monkeypatch.delenv("DXRK_VAULT_KEY_ACME", raising=False)
    monkeypatch.delenv("DXRK_VAULT_KEY_GLOBEX", raising=False)
    return TenantVaultRegistry()


# ---- tenant id extraction ----


def test_get_tenant_from_token_tid_claim() -> None:
    token = _unsigned_token({"sub": "u1", "tid": "acme"})
    assert get_tenant_from_token(token) == "acme"


def test_get_tenant_from_token_fallback_tenant_id_claim() -> None:
    assert get_tenant_from_token(_unsigned_token({"tenant_id": "globex"})) == "globex"
    assert get_tenant_from_token(_unsigned_token({"tid": 123, "tenant_id": "globex"})) == "globex"


def test_get_tenant_from_token_missing_or_malformed_returns_none() -> None:
    assert get_tenant_from_token(_unsigned_token({"sub": "x"})) is None
    assert get_tenant_from_token(_unsigned_token({"tid": 123})) is None
    assert get_tenant_from_token("not-a-jwt") is None
    assert get_tenant_from_token("a.!!!.c") is None
    assert decode_jwt_payload("not-a-jwt") is None


# ---- per-tenant key funcs ----


def test_tenant_key_func_same_tenant_same_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DXRK_JWT_SECRET_ACME", "acme-secret")
    monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
    assert tenant_key_func({}, {"tid": "acme"}) == b"acme-secret"
    assert tenant_key_func({}, {"tid": "acme"}) == tenant_key_func({}, {"tid": "acme"})


def test_tenant_key_func_different_tenants_different_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DXRK_JWT_SECRET_ACME", "acme-secret")
    monkeypatch.setenv("DXRK_JWT_SECRET_GLOBEX", "globex-secret")
    monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
    assert tenant_key_func({}, {"tid": "acme"}) != tenant_key_func({}, {"tid": "globex"})


def test_tenant_key_func_missing_tid_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
    with pytest.raises(ValueError, match="missing tid"):
        tenant_key_func({}, {})
    with pytest.raises(ValueError, match="missing tid"):
        tenant_key_func({}, {"tid": ""})


def test_make_tenant_key_func_isolation_and_custom_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DXRK_JWT_SECRET_ACME", "acme-secret")
    monkeypatch.setenv("DXRK_JWT_SECRET_GLOBEX", "globex-secret")
    monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
    key_func = make_tenant_key_func()
    assert key_func({}, {"tid": "acme"}) == key_func({}, {"tid": "acme"})
    assert key_func({}, {"tid": "acme"}) != key_func({}, {"tid": "globex"})
    custom = make_tenant_key_func(default_env="DXRK_JWT_SECRET_CUSTOM")
    monkeypatch.setenv("DXRK_JWT_SECRET_CUSTOM", "generic-fallback")
    assert custom({}, {"tid": "unknown-tenant"}) == b"generic-fallback"
    assert custom({}, {"tid": "acme"}) == b"acme-secret"


# ---- authorizer / rbac ----


def test_authorize_via_jwt_same_tenant_ok() -> None:
    token = _unsigned_token({"tid": "acme", "role": "dev", "tenants": ["acme"]})
    assert authorize_via_jwt(token, expected_tenant="acme") == "dev"


def test_authorize_via_jwt_cross_tenant_rejected() -> None:
    token = _unsigned_token({"tid": "acme", "role": "dev", "tenants": ["acme"]})
    with pytest.raises(PermissionError):
        authorize_via_jwt(token, expected_tenant="globex")


def test_tenant_authorizer_rejects_missing_tid_foreign_tid_and_bad_role() -> None:
    auth = TenantAuthorizer()
    with pytest.raises(ValueError, match="missing tid"):
        auth.authorize_claims({})
    with pytest.raises(PermissionError):
        auth.authorize_claims({"tid": "acme", "tenants": ["globex"]})
    with pytest.raises(PermissionError):
        TenantAuthorizer(allowed_roles={"admin"}).authorize_claims({"tid": "acme", "role": "dev"})
    info = TokenInfo(
        kind=TokenKind.UNKNOWN,
        token="",
        subject="",
        issuer="",
        expires_at=None,
        issued_at=None,
        claims={},
        is_valid=True,
        is_expired=False,
        tenant_id="acme",
        role="dev",
        tenants=["acme"],
    )
    assert auth.is_authorized(info)
    assert not auth.is_authorized(
        TokenInfo(
            kind=TokenKind.UNKNOWN,
            token="",
            subject="",
            issuer="",
            expires_at=None,
            issued_at=None,
            claims={},
            is_valid=True,
            is_expired=False,
        )
    )


def test_is_token_expired_deterministic() -> None:
    assert is_token_expired(_unsigned_token({"exp": PAST_EXP}), timedelta(0))
    assert is_token_expired(_unsigned_token({"exp": PAST_EXP}), timedelta(hours=2))
    assert not is_token_expired(_unsigned_token({"exp": FUTURE_EXP}), timedelta(0))
    assert not is_token_expired(_unsigned_token({"sub": "x"}), timedelta(0))
    assert not is_token_expired("not-a-jwt", timedelta(0))


def test_classify_token_kinds() -> None:
    assert classify_token("sk-ant-si-abcdef") == TokenKind.SESSION_INGRESS
    assert classify_token("sk-ant-oa-abcdef") == TokenKind.ACCESS_TOKEN
    assert classify_token("random") == TokenKind.UNKNOWN
    assert classify_token("") == TokenKind.UNKNOWN


def test_parse_token_safe_roundtrip_and_rejects_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "acme-jwt-secret-0123456789"
    monkeypatch.setenv("DXRK_JWT_SECRET_ACME", secret)
    monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
    key = secret.encode()
    base: dict[str, object] = {"sub": "u1", "iss": "dxrk", "tid": "acme", "role": "dev", "tenants": ["acme"]}
    info = parse_token_safe(_signed_token({**base, "exp": FUTURE_EXP, "iat": PAST_EXP}, key), tenant_key_func)
    assert info.is_valid and not info.is_expired
    assert info.tenant_id == "acme" and info.role == "dev" and info.subject == "u1"
    with pytest.raises(ValueError, match="expired"):
        parse_token_safe(_signed_token({**base, "exp": PAST_EXP}, key), tenant_key_func)


def test_parse_token_safe_malformed_raises_value_error() -> None:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({"sub": "x"}).encode())
    none_alg = _b64url(json.dumps({"alg": "none"}).encode())
    cases = [
        "",
        "abc",
        "a.b",
        "a.b.c.d",
        "a.!!!.c",
        f"{_b64url(b'[1,2]')}.{payload}.c2ln",
        f"{header}.{_b64url(b'[1,2]')}.c2ln",
        f"{header}.{_b64url(b'not-json')}.c2ln",
        f"{none_alg}.{payload}.c2ln",
    ]
    for bad in cases:
        with pytest.raises(ValueError):
            parse_token_safe(bad, _fixed_key)
    tampered = _signed_token({"sub": "x", "exp": FUTURE_EXP}, b"fixed-test-key-0123456789")
    with pytest.raises(ValueError):
        parse_token_safe(tampered[:-4] + "AAAA", _fixed_key)


# ---- vault per-tenant isolation ----


def test_vault_roundtrip_same_tenant(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = _isolated_registry(tmp_path, monkeypatch)
    vault = reg.get("acme")
    vault.set("api-key", "s3cr3t-acme")
    assert vault.get("api-key") == ("s3cr3t-acme", True)
    assert "api-key" in vault.list()
    assert reg.get("acme").get("api-key") == ("s3cr3t-acme", True)


def test_vault_isolation_across_tenants(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = _isolated_registry(tmp_path, monkeypatch)
    vault_a = reg.get("acme")
    vault_b = reg.get("globex")
    vault_a.set("only-a", "a-secret")
    value, ok = vault_b.get("only-a")
    assert not ok and value == ""
    assert "only-a" not in vault_b.list()
    vault_b.set("only-a", "b-secret")
    assert vault_a.get("only-a") == ("a-secret", True)
    assert vault_b.get("only-a") == ("b-secret", True)


def test_vault_hkdf_derivation_isolated_per_tenant() -> None:
    master = hashlib.sha256(b"enterprise-test-master-key").digest()
    assert _derive_tenant_key(master, "acme") == _derive_tenant_key(master, "acme")
    assert _derive_tenant_key(master, "acme") != _derive_tenant_key(master, "globex")
    assert len(_derive_tenant_key(master, "acme")) == 32
    with pytest.raises(ValueError):
        _derive_tenant_key(master, "")


# ---- redaction ----


def test_redact_token_does_not_leak_secret() -> None:
    secret = "sk-ant-oa-abcdefghijklmnopqrstuvwxyz0123456789"
    redacted = redact_token(secret)
    assert redacted != secret
    assert secret not in redacted
    assert secret[8:-4] not in redacted
    assert redacted == secret[:8] + "..." + secret[-4:]
    assert redact_token("short") == "[REDACTED]"
