# SPDX-License-Identifier: MIT
"""R04 — migración idempotente legacy single-tenant → multi-tenant tenants/default.

Filesystem canónico: ``~/.dxrk/tenants/{id}/`` (roadmap.md §3.3, ADR-002 R5).
Este módulo mantiene stdlib-only y evita imports circulares con ``dxrk.memory``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

# Reuse validate_id pattern de dxrk/security/jwt.py:371
#   TENANT_ID_RE = ^[a-zA-Z0-9_-]{1,256}$
TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,256}$")

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _dxrk_home() -> Path:
    return Path.home() / ".dxrk"


def _tenants_root() -> Path:
    return _dxrk_home() / "tenants"


def _ensure_dir(path: Path, mode: int = 0o750) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(mode)
    except OSError:
        pass


def _ensure_file_mode(path: Path, mode: int = 0o600) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def _valid_tenant_id(tenant_id: str) -> bool:
    return bool(TENANT_ID_RE.match(tenant_id))


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def tenant_root(tenant_id: str = "default") -> Path:
    """Return ``~/.dxrk/tenants/{tenant_id}`` (expected ``0o750`` when created).

    Validates ``tenant_id`` with :data:`TENANT_ID_RE` (same as
    ``dxrk.security.jwt.validate_id``). No filesystem side-effect except
    ensuring ``~/.dxrk/tenants`` parent exists with ``0o750``.
    """
    if not _valid_tenant_id(tenant_id):
        raise ValueError(f"invalid tenant id {tenant_id!r}")
    # ensure parent ``tenants`` exists (idempotent, cheap)
    tenants = _tenants_root()
    try:
        tenants.mkdir(parents=True, exist_ok=True)
        try:
            tenants.chmod(0o750)
        except OSError:
            pass
    except OSError:
        pass
    return tenants / tenant_id


def is_migrated() -> bool:
    """Return ``True`` if ``~/.dxrk/tenants/_registry.json`` exists."""
    return (_tenants_root() / "_registry.json").exists()


def list_tenants() -> list[str]:
    """List tenant ids under ``~/.dxrk/tenants``.

    Only directories whose name matches :data:`TENANT_ID_RE` /
    ``dxrk.security.jwt.validate_id`` are returned (hidden files, registry
    json, etc. excluded). Sorted ascending.
    """
    root = _tenants_root()
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    tenants: list[str] = []
    for e in entries:
        if e.is_dir() and _valid_tenant_id(e.name):
            tenants.append(e.name)
    return sorted(tenants)


#: Legacy → tenant-relative target (both :class:`pathlib.Path`).
#: ``Path.home()`` is evaluated at import (per spec); callers that
#: monkeypatch ``HOME`` should reimport or patch :data:`LEGACY_PATHS` directly.
LEGACY_PATHS: list[tuple[Path, Path]] = [
    (Path.home() / ".dxrk" / "palace" / "sqlite_palace.db", Path("palace") / "sqlite_palace.db"),
    (Path.home() / ".dxrk" / "locks", Path("locks")),
    (Path.home() / ".dxrk" / "knowledge_graph.sqlite3", Path("knowledge_graph.sqlite3")),
    (Path.home() / ".dxrk" / "identity.txt", Path("identity.txt")),
    (Path.home() / ".dxrk" / "config.yaml", Path("config.yaml")),
    (Path.home() / ".dxrk" / "settings.json", Path("settings.json")),
    (Path.home() / ".dxrk" / "vault.enc", Path("vault.enc")),
    (Path.home() / ".dxrk" / "memories.json", Path("memories.json")),
    (Path.home() / ".dxrk" / "iq.json", Path("iq.json")),
]


def ensure_tenant(tenant_id: str) -> Path:
    """Ensure ``~/.dxrk/tenants/{tenant_id}/`` and subdirs exist.

    Creates ``palace/locks/learn/sessions`` with ``0o750`` (files ``0o600``
    are handled by callers). Validates ``tenant_id`` via :data:`TENANT_ID_RE`.
    """
    if not _valid_tenant_id(tenant_id):
        raise ValueError(f"invalid tenant id {tenant_id!r}")
    root = tenant_root(tenant_id)
    _ensure_dir(root, 0o750)
    for sub in ("palace", "locks", "learn", "sessions"):
        _ensure_dir(root / sub, 0o750)
    return root


def migrate_legacy_to_default(dry_run: bool = False) -> dict[str, list[str]]:
    """Migrar legado single-tenant → ``tenants/default`` idempotente.

    * No borra legado (solo copia).
    * Idempotente: si ``target`` ya existe se registra como ``skipped``.
    * Crea directorios padre y aplica ``0o750`` en dirs / ``0o600`` en files.
    * Si ``dry_run`` es ``True`` no muta el filesystem y reporta el plan.
    * Tras la copia (no dry-run) escribe ``tenants/_registry.json`` y
      ``tenants/_active``::

          {"tenants": [{"id": "default", "display_name": "Default (migrated)",
                        "migrated_from": "single-tenant"}]}
          _active = "default"

    Returns:
        dict with keys ``moved`` | ``copied`` | ``skipped`` (lists of
        string paths). ``moved`` stays empty as migration copies only
        (kept for compat).
    """
    tenants_dir = _tenants_root()
    default_root = tenant_root("default")

    moved: list[str] = []
    copied: list[str] = []
    skipped: list[str] = []

    if not dry_run:
        try:
            tenants_dir.mkdir(parents=True, exist_ok=True)
            try:
                tenants_dir.chmod(0o750)
            except OSError:
                pass
        except OSError:
            pass
        # ensure default tenant skeleton
        ensure_tenant("default")
    else:
        # dry_run: logical default_root path exists only for reporting
        pass

    for legacy, rel in LEGACY_PATHS:
        target = default_root / rel

        if not legacy.exists():
            skipped.append(str(legacy))
            continue

        # For files: if target exists => skip (idempotent). For dirs: merge.
        if legacy.is_file() and target.exists():
            skipped.append(str(legacy))
            continue
        if legacy.is_dir() and target.exists():
            # Check if legacy dir has any file not yet in target -> merge, else skip
            has_missing = False
            for root, _dirs, files in os.walk(legacy):
                rel_root = Path(root).relative_to(legacy)
                for fname in files:
                    dst = target / rel_root / fname
                    if not dst.exists():
                        has_missing = True
                        break
                if has_missing:
                    break
            # also consider empty legacy dir vs empty target
            if not has_missing:
                # if legacy has no files, treat as already migrated
                skipped.append(str(legacy))
                continue
            if dry_run:
                copied.append(f"{legacy} -> {target}")
                continue
            # merge missing files (real run)
            try:
                for root, dirs, files in os.walk(legacy):
                    rel_root = Path(root).relative_to(legacy)
                    dst_dir = target / rel_root
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        dst_dir.chmod(0o750)
                    except OSError:
                        pass
                    for d in dirs:
                        try:
                            (dst_dir / d).chmod(0o750)
                        except OSError:
                            pass
                    for fname in files:
                        src = Path(root) / fname
                        dst = dst_dir / fname
                        if dst.exists():
                            continue
                        shutil.copy2(src, dst)
                        _ensure_file_mode(dst, 0o600)
                copied.append(str(legacy))
                continue
            except OSError as exc:
                skipped.append(f"{legacy} (error: {exc})")
                continue

        if dry_run:
            copied.append(f"{legacy} -> {target}")
            continue

        try:
            if legacy.is_dir():
                # target does not exist (guarded above for dir merge)
                shutil.copytree(legacy, target, symlinks=False, copy_function=shutil.copy2)
                # harden perms recursively
                for dirpath, dirnames, filenames in os.walk(target):
                    for d in dirnames:
                        try:
                            Path(dirpath, d).chmod(0o750)
                        except OSError:
                            pass
                    for f in filenames:
                        try:
                            Path(dirpath, f).chmod(0o600)
                        except OSError:
                            pass
                try:
                    target.chmod(0o750)
                except OSError:
                    pass
                copied.append(str(legacy))
            elif legacy.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    target.parent.chmod(0o750)
                except OSError:
                    pass
                shutil.copy2(legacy, target)
                _ensure_file_mode(target, 0o600)
                # copy sqlite sidecars (-wal/-shm) if they exist
                for suffix in ("-wal", "-shm"):
                    side = Path(str(legacy) + suffix)
                    if side.is_file():
                        side_target = Path(str(target) + suffix)
                        if not side_target.exists():
                            try:
                                shutil.copy2(side, side_target)
                                _ensure_file_mode(side_target, 0o600)
                            except OSError:
                                pass
                copied.append(str(legacy))
            else:
                # special file (fifo/socket/etc.) — skip
                skipped.append(str(legacy))
        except OSError as exc:
            skipped.append(f"{legacy} (error: {exc})")

    if not dry_run:
        # write _registry.json idempotently
        registry_path = tenants_dir / "_registry.json"
        active_path = tenants_dir / "_active"
        registry_data = {
            "tenants": [
                {
                    "id": "default",
                    "display_name": "Default (migrated)",
                    "migrated_from": "single-tenant",
                }
            ]
        }
        try:
            tenants_dir.mkdir(parents=True, exist_ok=True)
            try:
                tenants_dir.chmod(0o750)
            except OSError:
                pass
            tmp = registry_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(registry_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            try:
                tmp.chmod(0o600)
            except OSError:
                pass
            os.replace(tmp, registry_path)
            _ensure_file_mode(registry_path, 0o600)
        except OSError:
            pass
        try:
            active_path.write_text("default", encoding="utf-8")
            _ensure_file_mode(active_path, 0o600)
        except OSError:
            pass

    return {"moved": moved, "copied": copied, "skipped": skipped}
