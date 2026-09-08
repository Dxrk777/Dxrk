# SPDX-License-Identifier: MIT
"""Enterprise RBAC matrix — admin/dev/readonly x acciones representativas.

Roles reales descubiertos en ``dxrk.security.rbac``: ``admin`` / ``dev`` /
``readonly`` (``DEFAULT_ROLE == "readonly"``). No existen ``member``/``viewer``
como roles RBAC (solo aparecen como valores tolerados en
``TenantAuthorizer.VALID_ROLES`` de jwt, con fallback a ``readonly``).

Capas verificadas:
  1) Policy (``PermissionContext`` via ``load_policy_for_tenant``): priority 50.
  2) Caps (``PermissionStore`` via ``build_permission_store_for_role``).
  3) JWT tid/role (``authorize_via_jwt``): cross-tenant denegado.

Determinista: sin red ni sleeps. Disco aislado via ``HOME=tmp_path/home``.
"""

from __future__ import annotations

import base64
import json
import stat
from pathlib import Path

import pytest

from dxrk.autonomy.permissions import CapFSRead, CapFSWrite, CapSudo
from dxrk.security.permissions import PermissionResult, classify_tool
from dxrk.security.rbac import (
    DEFAULT_ROLE,
    ROLE_CAPS,
    ROLE_POLICIES,
    ROLE_POLICY,
    VALID_ROLES,
    TenantRoleResolver,
    authorize_via_jwt,
    build_permission_store_for_role,
    get_caps_for_role,
    load_policy_for_tenant,
)


def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    return home


def _b64url(obj: dict) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _make_token(payload: dict) -> str:
    header = _b64url({"alg": "none", "typ": "JWT"})
    body = _b64url(payload)
    return f"{header}.{body}.sig"


def test_real_roles_are_admin_dev_readonly() -> None:
    assert VALID_ROLES == {"admin", "dev", "readonly"}
    assert DEFAULT_ROLE == "readonly"
    assert set(ROLE_POLICIES) == {"admin", "dev", "readonly"}
    assert ROLE_POLICY is ROLE_POLICIES
    for role in ("admin", "dev", "readonly"):
        policy = ROLE_POLICIES[role]
        assert policy.role == role
        assert policy.caps == ROLE_CAPS[role]
        assert policy.caps == get_caps_for_role(role)
    # readonly solo lectura; dev sin sudo; admin full
    assert get_caps_for_role("readonly") == [CapFSRead]
    assert CapFSWrite in get_caps_for_role("dev")
    assert CapSudo not in get_caps_for_role("dev")
    assert CapSudo in get_caps_for_role("admin")


def test_classify_tool_sanity() -> None:
    assert classify_tool("Read") is PermissionResult.ALLOWED
    assert classify_tool("Bash") is PermissionResult.NEEDS_PROMPT
    assert classify_tool("UnknownToolXyz") is PermissionResult.NEEDS_PROMPT


# (role, tool, expected): lectura -> NEEDS_PROMPT (sin regla), escritura/admin -> ALLOW o DENY.
MATRIX: list[tuple[str, str, PermissionResult]] = [
    ("admin", "Read", PermissionResult.NEEDS_PROMPT),
    ("admin", "Write", PermissionResult.ALLOWED),
    ("admin", "Bash", PermissionResult.ALLOWED),
    ("admin", "Delete", PermissionResult.ALLOWED),
    ("admin", "Mine", PermissionResult.ALLOWED),
    ("dev", "Read", PermissionResult.NEEDS_PROMPT),
    ("dev", "Write", PermissionResult.ALLOWED),
    ("dev", "Bash", PermissionResult.ALLOWED),
    ("dev", "Delete", PermissionResult.ALLOWED),
    ("dev", "Edit", PermissionResult.ALLOWED),
    ("readonly", "Read", PermissionResult.NEEDS_PROMPT),
    ("readonly", "Write", PermissionResult.DENIED),
    ("readonly", "Bash", PermissionResult.DENIED),
    ("readonly", "Edit", PermissionResult.DENIED),
    ("readonly", "Delete", PermissionResult.DENIED),
    ("readonly", "Mine", PermissionResult.DENIED),
]


@pytest.mark.parametrize(("role", "tool", "expected"), MATRIX)
def test_policy_matrix_role_x_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str, tool: str, expected: PermissionResult
) -> None:
    _isolate_home(tmp_path, monkeypatch)
    tenant = "matrix"
    user = f"user-{role}"
    resolver = TenantRoleResolver(tenant)
    resolver.save({user: role}, "readonly")
    ctx = load_policy_for_tenant(tenant, user)
    result, _reason = ctx.check(tool, "")
    assert result is expected


def test_default_role_and_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_home(tmp_path, monkeypatch)
    resolver = TenantRoleResolver("acme")
    # fichero ausente -> default readonly
    assert resolver.resolve("ghost") == "readonly"
    assert resolver.get_role("ghost") == "readonly"
    path = resolver.ensure_default()
    assert path.exists()
    assert resolver.resolve("ghost") == "readonly"
    # roundtrip admin + dev
    resolver.set_user_role("alice", "admin")
    assert resolver.get_role("alice") == "admin"
    assert resolver.resolve("alice") == "admin"
    resolver.set_user_role("bob", "dev")
    assert resolver.resolve("bob") == "dev"
    # desconocido sigue en default
    assert resolver.resolve("nobody") == "readonly"
    # roles invalidos rechazan
    with pytest.raises(ValueError):
        resolver.set_user_role("eve", "member")
    with pytest.raises(ValueError):
        resolver.set_user_role("", "admin")
    with pytest.raises(ValueError):
        resolver.save({"x": "viewer"}, "readonly")


def test_load_save_roundtrip_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_home(tmp_path, monkeypatch)
    resolver = TenantRoleResolver("acme")
    resolver.save({"alice": "admin", "bob": "dev"}, "dev")
    data = resolver.load()
    assert data == {"users": {"alice": "admin", "bob": "dev"}, "default_role": "dev"}
    # default_role persistido gobierna a desconocidos
    assert resolver.resolve("stranger") == "dev"
    # fichero endurecido 0o600
    mode = stat.S_IMODE(resolver.roles_path.stat().st_mode)
    assert mode == 0o600
    # recarga desde nueva instancia
    fresh = TenantRoleResolver("acme")
    assert fresh.resolve("alice") == "admin"
    assert fresh.resolve("bob") == "dev"
    # politica coherente con lo persistido
    ctx_admin = load_policy_for_tenant("acme", "alice")
    assert ctx_admin.check("Write", "")[0] is PermissionResult.ALLOWED
    ctx_dev_default = load_policy_for_tenant("acme", "stranger")
    assert ctx_dev_default.check("Write", "")[0] is PermissionResult.ALLOWED
    ctx_readonly = load_policy_for_tenant("acme", None)
    # user None -> resolve("") -> default_role dev -> ALLOW escritura
    assert ctx_readonly.check("Write", "")[0] is PermissionResult.ALLOWED


def test_load_save_default_readonly_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_home(tmp_path, monkeypatch)
    resolver = TenantRoleResolver("globex")
    resolver.ensure_default()
    ctx = load_policy_for_tenant("globex", "unknown-user")
    assert ctx.check("Write", "")[0] is PermissionResult.DENIED
    assert ctx.check("Bash", "")[0] is PermissionResult.DENIED
    assert ctx.check("Read", "")[0] is PermissionResult.NEEDS_PROMPT


def test_build_permission_store_functional() -> None:
    admin = build_permission_store_for_role("admin")
    dev = build_permission_store_for_role("dev")
    readonly = build_permission_store_for_role("readonly")
    # admin: todo permitido incl. sudo
    assert admin.check(CapFSRead, "t") is None
    assert admin.check(CapFSWrite, "t") is None
    assert admin.check(CapSudo, "t") is None
    # dev: escritura si, sudo no
    assert dev.check(CapFSRead, "t") is None
    assert dev.check(CapFSWrite, "t") is None
    assert dev.check(CapSudo, "t") is not None
    # readonly: solo lectura
    assert readonly.check(CapFSRead, "t") is None
    assert readonly.check(CapFSWrite, "t") is not None
    assert readonly.check(CapSudo, "t") is not None
    # rol desconocido -> fallback readonly
    fallback = build_permission_store_for_role("member")
    assert fallback.check(CapFSRead, "t") is None
    assert fallback.check(CapFSWrite, "t") is not None


def test_authorize_via_jwt_cross_tenant_denied() -> None:
    token_a = _make_token({"tid": "tenant-a", "role": "admin", "tenants": ["tenant-a"]})
    assert authorize_via_jwt(token_a, "tenant-a") == "admin"
    assert authorize_via_jwt(token_a, None) == "admin"
    with pytest.raises(PermissionError):
        authorize_via_jwt(token_a, "tenant-b")
    token_b = _make_token({"tid": "tenant-b", "role": "dev", "tenants": ["tenant-b"]})
    assert authorize_via_jwt(token_b, "tenant-b") == "dev"
    with pytest.raises(PermissionError):
        authorize_via_jwt(token_b, "tenant-a")


def test_authorize_via_jwt_invalid_and_fallback() -> None:
    with pytest.raises(ValueError):
        authorize_via_jwt("not-a-token", None)
    with pytest.raises((ValueError, PermissionError)):
        authorize_via_jwt(_make_token({"role": "dev"}), None)
    # rol fuera de VALID_ROLES pero tolerado por TenantAuthorizer -> fallback readonly
    token_member = _make_token({"tid": "tenant-a", "role": "member", "tenants": ["tenant-a"]})
    assert authorize_via_jwt(token_member, "tenant-a") == "readonly"


def test_get_caps_coherent_with_matrix() -> None:
    admin_caps = set(get_caps_for_role("admin"))
    dev_caps = set(get_caps_for_role("dev"))
    readonly_caps = set(get_caps_for_role("readonly"))
    # jerarquia: readonly subset dev subset admin
    assert readonly_caps <= dev_caps <= admin_caps
    assert CapFSRead in readonly_caps & dev_caps & admin_caps
    assert CapFSWrite in admin_caps and CapFSWrite in dev_caps and CapFSWrite not in readonly_caps
    assert CapSudo in admin_caps and CapSudo not in dev_caps and CapSudo not in readonly_caps
    # fallback desconocido == readonly
    assert get_caps_for_role("unknown-role") == get_caps_for_role("readonly")
    assert get_caps_for_role("viewer") == get_caps_for_role("readonly")
    # coherente con PermissionStore funcional
    for role in ("admin", "dev", "readonly"):
        store = build_permission_store_for_role(role)
        for cap in get_caps_for_role(role):
            assert store.check(cap, "t") is None
        assert set(store.allowed) >= set(get_caps_for_role(role))
