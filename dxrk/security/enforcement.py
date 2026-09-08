# SPDX-License-Identifier: MIT
"""R12 RBAC enforcement — thin gate over TenantRoleResolver + ROLE_CAPS.

Maps high-level ops to capability requirements:

- ``read``   <- search/recall/list (requires ``fs.read``; all roles pass)
- ``mine``   <- mine/write (requires ``fs.write``; admin/dev pass, readonly denied)
- ``manage`` <- tenant create/delete (requires ``sudo``; admin only)

Local trusted mode: empty ``tenant_id`` OR empty ``user`` bypasses
enforcement (returns ``""`` without raising) to preserve back-compat
with the 4283 existing tests and single-user local usage.
"""

from __future__ import annotations

import os

from dxrk.autonomy.permissions import CapFSRead, CapFSWrite, CapSudo
from dxrk.security.rbac import TenantRoleResolver, get_caps_for_role

VALID_OPS: frozenset[str] = frozenset({"read", "mine", "manage"})

_OP_CAP: dict[str, str] = {
    "read": CapFSRead,
    "mine": CapFSWrite,
    "manage": CapSudo,
}


def resolve_user() -> str:
    """Return current user from ``DXRK_USER`` env (``""`` when unset).

    Empty string means no identity -> local trusted mode (no enforcement).
    """
    return (os.environ.get("DXRK_USER", "") or "").strip()


def require_op(tenant_id: str, user: str, op: str) -> str:
    """Enforce ``op`` for ``user`` in ``tenant_id``; return role on success.

    - ``op`` must be one of ``{"read", "mine", "manage"}`` else ``ValueError``.
    - Empty ``tenant_id`` or empty ``user`` -> return ``""`` without
      enforcing (local trusted mode, back-compat).
    - Unknown user falls back to the tenant ``default_role`` via
      :meth:`TenantRoleResolver.resolve`.
    - Invalid ``tenant_id`` propagates ``ValueError`` from
      :class:`TenantRoleResolver`.
    - Missing capability raises
      ``PermissionError("RBAC_DENIED: role=... op=... tenant=...")``.
    """
    if op not in VALID_OPS:
        raise ValueError(f"invalid op {op!r} (expected one of {sorted(VALID_OPS)})")
    tid = (tenant_id or "").strip()
    usr = (user or "").strip()
    if not tid or not usr:
        return ""
    resolver = TenantRoleResolver(tid)
    role = resolver.resolve(usr)
    caps = get_caps_for_role(role)
    needed = _OP_CAP[op]
    if needed not in caps:
        raise PermissionError(f"RBAC_DENIED: role={role} op={op} tenant={tid}")
    return role
