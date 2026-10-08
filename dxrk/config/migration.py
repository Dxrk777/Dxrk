# SPDX-License-Identifier: MIT
"""R14 — migrate flat settings.json keys into config.yaml settings section.

Idempotent, dry-run capable, backs up every file it rewrites (``.bak``,
only when absent). Follows the ``tenant migrate`` reporting contract:
``{"moved": [...], "copied": [...], "skipped": [...]}``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

#: settings.json sources migrated by :func:`migrate_settings_to_yaml`.
#: Each entry maps (json_source, yaml_target). Resolved at call time so
#: tests isolating HOME/cwd via monkeypatch behave correctly.
LEGACY_JSON_SOURCES = ("user", "project")


def _user_json_path() -> Path:
    return Path.home() / ".dxrk" / "settings.json"


def _project_json_path() -> Path:
    return Path(".dxrk") / "settings.json"


def _user_yaml_path() -> Path:
    return Path.home() / ".dxrk" / "config.yaml"


def _project_yaml_path() -> Path:
    return Path(".dxrk") / "config.yaml"


def _tenant_yaml_path(tenant_id: str) -> Path:
    from dxrk.tenant.migration import tenant_root

    return tenant_root(tenant_id) / "config.yaml"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_yaml(path: Path) -> dict[str, Any]:
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Writes YAML atomically with 0o600 (parents 0o750).

    Note: comments in a pre-existing file are not preserved (PyYAML
    round-trip limitation); a ``.bak`` backup is always kept.
    """
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o750)
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _backup_once(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".bak")
    if bak.exists() or not path.exists():
        return
    try:
        bak.write_bytes(path.read_bytes())
        try:
            bak.chmod(0o600)
        except OSError:
            pass
    except OSError:
        pass


def migrate_settings_to_yaml(dry_run: bool = False, tenant: str = "") -> dict[str, list[str]]:
    """Moves flat ``settings.json`` keys into ``config.yaml`` settings sections.

    Scopes: user (``~/.dxrk``) always; project (``.dxrk/``) always; when
    ``tenant`` is given the merged keys additionally land in the tenant
    ``config.yaml``. Keys already present in the target YAML are skipped
    (idempotent). Files are only rewritten when at least one key moves;
    every rewritten file keeps a ``.bak`` backup (first run only).

    Returns ``{"moved": [...], "copied": [...], "skipped": [...]}`` with
    human-readable ``src -> dst#key`` entries (``moved`` stays empty:
    sources are never deleted, kept for compat with tenant migrate).
    """
    moved: list[str] = []
    copied: list[str] = []
    skipped: list[str] = []

    user_flat = _read_json(_user_json_path())
    project_flat = _read_json(_project_json_path())
    # Pool for the tenant scope follows ladder precedence (project wins).
    pool: dict[str, Any] = {**user_flat, **project_flat}
    scopes = [
        ("user", user_flat, _user_yaml_path()),
        ("project", project_flat, _project_yaml_path()),
    ]
    if tenant.strip():
        try:
            scopes.append(("tenant", pool, _tenant_yaml_path(tenant.strip())))
        except Exception as exc:
            skipped.append(f"tenant: invalid tenant ({exc})")

    for scope, flat, yaml_path in scopes:
        if not flat:
            skipped.append(f"{scope}: no settings.json keys")
            continue
        doc = _read_yaml(yaml_path)
        section = doc.get("settings")
        if not isinstance(section, dict):
            section = {}
        pending = {k: v for k, v in flat.items() if k not in section}
        for k in flat:
            if k in section:
                skipped.append(f"{scope}:{yaml_path}#settings.{k} (already present)")
        if not pending:
            continue
        src = "settings.json pool" if scope == "tenant" else "settings.json"
        if dry_run:
            for k in pending:
                copied.append(f"{scope}:{src} -> {yaml_path}#settings.{k}")
            continue
        _backup_once(yaml_path)
        section.update(pending)
        doc["settings"] = section
        try:
            _write_yaml(yaml_path, doc)
        except OSError as exc:
            skipped.append(f"{scope}:{yaml_path} (error: {exc})")
            continue
        for k in pending:
            copied.append(f"{scope}:{src} -> {yaml_path}#settings.{k}")

    return {"moved": moved, "copied": copied, "skipped": skipped}
