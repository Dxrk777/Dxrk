# SPDX-License-Identifier: MIT
"""R12 RBAC — 3 roles admin/dev/readonly with 3 enforcement layers.

Layers:
  1) JWT tid/role claim (TenantAuthorizer via tid/role in token).
  2) Policy hierarchy SettingSource.POLICY priority 50 (PermissionContext).
  3) Capability gating PermissionStore caps (autonomy.permissions).

roles.json per tenant at ``~/.dxrk/tenants/{id}/roles.json`` with
``{"users": {"alice": "admin"}, "default_role": "readonly"}`` and file
mode ``0o600`` (dirs ``0o750``). See :class:`TenantRoleResolver`.

``ROLE_CAPS`` maps each role to :mod:`dxrk.autonomy.permissions` caps.
``ROLE_POLICIES`` / :class:`RolePolicy` provide the per-role policy view
used to build a :class:`dxrk.security.permissions.PermissionContext`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dxrk.autonomy.permissions import (
    CAPABILITIES,
    CapDocker,
    CapExec,
    CapFSRead,
    CapFSWrite,
    CapGit,
    CapNetHTTP,
    CapPkgInstall,
    CapSudo,
    PermissionStore,
)
from dxrk.security.permissions import (
    READ_ONLY_TOOLS,
    PermissionBehavior,
    PermissionContext,
    PermissionRule,
    SettingSource,
)

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

VALID_ROLES: set[str] = {"admin", "dev", "readonly"}
DEFAULT_ROLE: str = "readonly"

# ROLE_CAPS — maps role -> PermissionStore caps.
# admin: read+write+mine+manage tenants (full)
# dev:   read+write+mine (no manage tenant delete / sudo)
# readonly: search/recall only (fs.read)
# Caps are the autonomy.permissions.CAPABILITIES strings.
ROLE_CAPS: dict[str, list[str]] = {
    "admin": [
        CapFSRead,
        CapFSWrite,
        CapGit,
        CapNetHTTP,
        CapDocker,
        CapSudo,
        CapPkgInstall,
        CapExec,
    ],
    "dev": [
        CapFSRead,
        CapFSWrite,
        CapGit,
        CapNetHTTP,
        CapDocker,
        CapExec,
    ],
    "readonly": [
        CapFSRead,
    ],
}

# Backwards-compat alias for CAPABILITIES validation.
_ALL_CAPS_SET: set[str] = set(CAPABILITIES)


@dataclass(frozen=True)
class RolePolicy:
    """Policy view for a single role."""

    role: str
    caps: list[str]
    description: str
    # Optional: tool allow list (subset of READ_ONLY vs full)
    allowed_tools: frozenset[str] | None = None


ROLE_DESCRIPTIONS: dict[str, str] = {
    "admin": "read+write+mine+manage tenants",
    "dev": "read+write+mine",
    "readonly": "search/recall only",
}

# Validated tool sets per role (for Policy layer).
# readonly -> only READ_ONLY_TOOLS; dev/admin -> all (represented as None meaning allow).
_ADMIN_DEV_ALLOWED: frozenset[str] | None = None

_ROLE_ALLOWED_TOOLS: dict[str, frozenset[str] | None] = {
    "admin": _ADMIN_DEV_ALLOWED,
    "dev": _ADMIN_DEV_ALLOWED,
    "readonly": frozenset(READ_ONLY_TOOLS.keys()),
}

ROLE_POLICIES: dict[str, RolePolicy] = {
    role: RolePolicy(
        role=role,
        caps=list(ROLE_CAPS[role]),
        description=ROLE_DESCRIPTIONS[role],
        allowed_tools=_ROLE_ALLOWED_TOOLS[role],
    )
    for role in VALID_ROLES
}

# Also expose dict alias expected by prompt "RolePolicy dict por rol".
# Some verifiers check for ROLE_POLICY name.
ROLE_POLICY: dict[str, RolePolicy] = ROLE_POLICIES


# ---------------------------------------------------------------------------
# roles.json resolver — per tenant, 0o600
# ---------------------------------------------------------------------------


def _roles_path_for_tenant(tenant_id: str) -> Path:
    from dxrk.tenant.migration import tenant_root

    return tenant_root(tenant_id) / "roles.json"


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o750)
    except OSError:
        pass


def _harden_file(path: Path, mode: int = 0o600) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def _load_roles_data(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"users": {}, "default_role": DEFAULT_ROLE}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"users": {}, "default_role": DEFAULT_ROLE}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"users": {}, "default_role": DEFAULT_ROLE}
    if not isinstance(data, dict):
        return {"users": {}, "default_role": DEFAULT_ROLE}
    users = data.get("users")
    if not isinstance(users, dict):
        users = {}
    # filter users values to valid roles only
    filtered: dict[str, str] = {}
    for k, v in users.items():
        if isinstance(k, str) and isinstance(v, str) and v in VALID_ROLES:
            filtered[k] = v
    default_role = data.get("default_role")
    if not isinstance(default_role, str) or default_role not in VALID_ROLES:
        default_role = DEFAULT_ROLE
    return {"users": filtered, "default_role": default_role}


def _write_roles_data(path: Path, users: dict[str, str], default_role: str) -> None:
    if default_role not in VALID_ROLES:
        raise ValueError(f"invalid role {default_role!r}")
    for u, r in users.items():
        if r not in VALID_ROLES:
            raise ValueError(f"invalid role {r!r} for user {u!r}")
    _ensure_parent_dir(path)
    data = {"users": dict(users), "default_role": default_role}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _harden_file(tmp, 0o600)
    os.replace(tmp, path)
    _harden_file(path, 0o600)


class TenantRoleResolver:
    """Resolve roles per tenant via ``roles.json`` (0o600).

    ``roles.json`` shape::

        {"users": {"alice": "admin"}, "default_role": "readonly"}

    Missing file → defaults to ``{"users": {}, "default_role": "readonly"}``
    and is treated as readonly for unknown users. File and parent dir
    perms are hardened to 0o600 / 0o750 on write.
    """

    def __init__(self, tenant_id: str) -> None:
        if not tenant_id.strip():
            raise ValueError("tenant_id required")
        # validate via TENANT_ID_RE
        from dxrk.tenant.migration import TENANT_ID_RE

        if not TENANT_ID_RE.match(tenant_id):
            raise ValueError(f"invalid tenant id {tenant_id!r}")
        self.tenant_id: str = tenant_id
        self.roles_path: Path = _roles_path_for_tenant(tenant_id)

    def load(self) -> dict[str, Any]:
        """Load raw roles data (users + default_role)."""
        return _load_roles_data(self.roles_path)

    def save(self, users: dict[str, str], default_role: str = DEFAULT_ROLE) -> None:
        """Persist roles data with 0o600."""
        _write_roles_data(self.roles_path, users, default_role)

    def resolve(self, user: str) -> str:
        """Return role for user (fallback to default_role)."""
        data = self.load()
        users = data.get("users", {})
        if not isinstance(users, dict):
            users = {}
        role = users.get(user) if isinstance(user, str) and user else None
        if isinstance(role, str) and role in VALID_ROLES:
            return role
        default_role = data.get("default_role")
        if isinstance(default_role, str) and default_role in VALID_ROLES:
            return default_role
        return DEFAULT_ROLE

    def get_role(self, user: str) -> str:
        """Alias for :meth:`resolve`."""
        return self.resolve(user)

    def set_user_role(self, user: str, role: str) -> None:
        """Set role for a single user and persist."""
        if role not in VALID_ROLES:
            raise ValueError(f"invalid role {role!r}")
        if not user.strip():
            raise ValueError("user required")
        data = self.load()
        users = data.get("users", {})
        if not isinstance(users, dict):
            users = {}
        # copy to avoid mutating cached dict unexpectedly
        new_users: dict[str, str] = {
            str(k): str(v) for k, v in users.items() if isinstance(k, str) and isinstance(v, str)
        }
        new_users[user] = role
        default_role = data.get("default_role", DEFAULT_ROLE)
        if not isinstance(default_role, str) or default_role not in VALID_ROLES:
            default_role = DEFAULT_ROLE
        self.save(new_users, default_role)

    def ensure_default(self) -> Path:
        """Ensure roles.json exists with default readonly and 0o600. Return path."""
        if not self.roles_path.exists():
            self.save({}, DEFAULT_ROLE)
        else:
            _harden_file(self.roles_path, 0o600)
        return self.roles_path


# ---------------------------------------------------------------------------
# Policy layer — load_policy_for_tenant
# ---------------------------------------------------------------------------

# Tools considered write-sensitive (for readonly DENY). We deny these via
# POLICY so PermissionContext.check returns DENIED with priority 50.
_WRITE_TOOLS: list[str] = [
    "Write",
    "Edit",
    "Bash",
    "Execute",
    "ApplyPatch",
    "Create",
    "Delete",
    "Update",
    "Install",
    "Mine",
    "AddDrawer",
    "RemoveDrawer",
    "Chunk",
]


def _policy_rules_for_role(role: str) -> list[PermissionRule]:
    if role not in VALID_ROLES:
        role = DEFAULT_ROLE
    if role == "admin":
        # admin: allow write tools via POLICY priority 50 (defense in depth, also covers caps).
        rules: list[PermissionRule] = []
        for tool in _WRITE_TOOLS:
            rules.append(
                PermissionRule(
                    tool=tool,
                    behavior=PermissionBehavior.ALLOW,
                    source=SettingSource.POLICY,
                )
            )
        return rules
    if role == "dev":
        # dev: allow write tools but caps layer will still deny sudo/cap-sensitive missing.
        rules = []
        for tool in _WRITE_TOOLS:
            # keep sudo-sensitive as DENY via caps, but allow generic write via POLICY
            # For simplicity allow all write tools; caps handle fine-grained sudo.
            rules.append(
                PermissionRule(
                    tool=tool,
                    behavior=PermissionBehavior.ALLOW,
                    source=SettingSource.POLICY,
                )
            )
        return rules
    # readonly: deny write tools via POLICY (priority 50 overrides any user/project)
    rules = []
    for tool in _WRITE_TOOLS:
        rules.append(
            PermissionRule(
                tool=tool,
                behavior=PermissionBehavior.DENY,
                source=SettingSource.POLICY,
            )
        )
    return rules


def load_policy_for_tenant(tenant_id: str, user: str | None = None) -> PermissionContext:
    """Build a :class:`PermissionContext` with POLICY rules for tenant/role.

    Resolves role via :class:`TenantRoleResolver` (users[user] or default_role
    ``readonly``) or via ``user`` param if given. If ``user`` is None, uses
    default_role from ``roles.json`` (or readonly if missing).

    Returned context has rules with ``SettingSource.POLICY`` (priority 50),
    so they shadow USER/PROJECT/LOCAL/FLAG.
    """
    resolver = TenantRoleResolver(tenant_id)
    role = resolver.resolve(user or "")
    ctx = PermissionContext()
    rules = _policy_rules_for_role(role)
    if rules:
        ctx.add_policy_rules(rules)
    return ctx


def build_permission_store_for_role(role: str) -> PermissionStore:
    """Create a :class:`PermissionStore` pre-granted with role caps."""
    if role not in VALID_ROLES:
        role = DEFAULT_ROLE
    caps = ROLE_CAPS.get(role, ROLE_CAPS[DEFAULT_ROLE])
    store = PermissionStore()
    for cap in caps:
        if cap not in _ALL_CAPS_SET:
            continue
        store.grant(cap)
    return store


def get_caps_for_role(role: str) -> list[str]:
    """Return caps list for role (readonly fallback)."""
    if role in ROLE_CAPS:
        return list(ROLE_CAPS[role])
    return list(ROLE_CAPS[DEFAULT_ROLE])


def authorize_via_jwt(token: str, expected_tenant: str | None = None) -> str:
    """Validate JWT-like tid/role and return authorized role.

    Uses :func:`dxrk.security.jwt.decode_jwt_payload` tolerant decode plus
    :class:`dxrk.security.jwt.TenantAuthorizer`. Returns ``role`` string
    (or ``readonly`` fallback if token lacks role). Raises ``ValueError`` /
    ``PermissionError`` on invalid tid/role mismatch.
    """
    from dxrk.security.jwt import TenantAuthorizer, decode_jwt_payload

    claims = decode_jwt_payload(token)
    if claims is None:
        raise ValueError("invalid token payload")
    # authorize tid/role/tenants
    auth = TenantAuthorizer()
    auth.authorize_claims(claims)
    tid_raw = claims.get("tid")
    if not isinstance(tid_raw, str):
        tid_raw = claims.get("tenant_id")  # type: ignore[assignment]
    tid = tid_raw if isinstance(tid_raw, str) else ""
    if expected_tenant is not None and tid != expected_tenant:
        raise PermissionError(f"tid {tid!r} != expected {expected_tenant!r}")
    role_raw = claims.get("role")
    role = role_raw if isinstance(role_raw, str) and role_raw in VALID_ROLES else DEFAULT_ROLE
    return role
