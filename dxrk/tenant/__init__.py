# SPDX-License-Identifier: MIT
"""Dxrk multi-tenant — filesystem ``~/.dxrk/tenants/{id}/``.

Re-exporta la API de :mod:`dxrk.tenant.migration` para ``from dxrk.tenant import ...``.
Stdlib-only, sin imports de ``dxrk.memory`` para evitar ciclos.
"""

from __future__ import annotations

from .migration import (
    LEGACY_PATHS,
    TENANT_ID_RE,
    ensure_tenant,
    is_migrated,
    list_tenants,
    migrate_legacy_to_default,
    tenant_root,
)

__all__ = [
    "LEGACY_PATHS",
    "TENANT_ID_RE",
    "ensure_tenant",
    "is_migrated",
    "list_tenants",
    "migrate_legacy_to_default",
    "tenant_root",
]
