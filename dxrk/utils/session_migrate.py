# SPDX-License-Identifier: MIT
"""Session version migration framework."""

from __future__ import annotations

import json
import threading
from typing import Any

from dxrk.utils.session_model import CurrentVersion, SessionError

# ─── migration ─────────────────────────────────────────────────────────────


MigrationFunc = Any

_migrations_mu = threading.Lock()
_migrations: list[tuple[int, int, MigrationFunc]] = []
_migrations_built = False


def register_migration(from_version: int, to_version: int, fn: MigrationFunc) -> None:
    with _migrations_mu:
        for m in _migrations:
            if m[0] == from_version and m[1] == to_version:
                return
        _migrations.append((from_version, to_version, fn))


def migrate_session(data: str, from_version: int, to_version: int) -> str:
    if from_version == to_version:
        return data
    if from_version > to_version:
        raise SessionError(f"downgrade migrations not supported: {from_version} -> {to_version}")
    current = from_version
    current_data = data
    while current < to_version:
        fn = find_migration(current, current + 1)
        if fn is None:
            raise SessionError(f"no migration from version {current} to {current + 1}")
        try:
            current_data = fn(current_data)
        except SessionError as e:
            raise SessionError(f"migration {current} -> {current + 1} failed: {e}") from e
        try:
            probe = json.loads(current_data)
            probe_version = int(probe.get("version", 0) or 0) if isinstance(probe, dict) else 0
        except ValueError:
            probe_version = current
        if probe_version > current:
            current = probe_version
        else:
            current += 1
    return current_data


def find_migration(from_version: int, to_version: int) -> MigrationFunc | None:
    with _migrations_mu:
        for m in _migrations:
            if m[0] == from_version and m[1] == to_version:
                return m[2]
    return None


def _build_migrations() -> None:
    global _migrations_built
    with _migrations_mu:
        if _migrations_built:
            return
        _migrations_built = True

        def v1_to_v2(data: str) -> str:
            try:
                raw = json.loads(data)
            except ValueError as e:
                raise SessionError(f"unmarshal v1: {e}") from e
            if not isinstance(raw, dict):
                raise SessionError("unmarshal v1: expected object")
            raw["version"] = 2
            if "messages" not in raw:
                raw["messages"] = []
            status = raw.get("status")
            if isinstance(status, (int, float)) and not isinstance(status, bool):
                names = {
                    0: "active",
                    1: "paused",
                    2: "completed",
                    3: "archived",
                    4: "expired",
                }
                raw["status"] = names.get(int(status), "active")
            return json.dumps(raw, indent=2)

        _migrations.append((1, 2, v1_to_v2))


def list_migrations() -> list[str]:
    with _migrations_mu:
        paths = [f"{m[0]} -> {m[1]}" for m in _migrations]
    return sorted(paths)


def has_migration(from_version: int, to_version: int) -> bool:
    return find_migration(from_version, to_version) is not None


def detect_version(data: str) -> int:
    try:
        probe = json.loads(data)
        version = int(probe.get("version", 0) or 0) if isinstance(probe, dict) else 0
    except (ValueError, TypeError) as e:
        raise SessionError(f"detect version: {e}") from e
    return version


def migrate_to_current(data: str) -> str:
    v = detect_version(data)
    return migrate_session(data, v, CurrentVersion)


_build_migrations()


RegisterMigration = register_migration
MigrateSession = migrate_session
ListMigrations = list_migrations
HasMigration = has_migration
DetectVersion = detect_version
MigrateToCurrent = migrate_to_current
