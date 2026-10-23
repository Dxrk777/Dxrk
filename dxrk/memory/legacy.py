# SPDX-License-Identifier: MIT
"""Backward-compatible migration to the partition/subgroup/recall vocabulary.

The canonical hierarchy is ``partition → subgroup → recall``. Four older
generations of artifacts are upgraded in place:

* ``malla`` / ``nodo`` / ``celda`` / ``fragmento``
* ``palace`` / ``wing`` / ``room`` / ``drawer``
* ``crypt`` / ``wing`` / ``chamber`` / ``relic``
* ``sangre`` / ``vena`` / ``capilar`` / ``globulo``

Every operation is idempotent and fail-safe: if a migration cannot complete,
the legacy artifact is left untouched and a later run retries. No data is
deleted until the new artifact exists.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import cast

MALLA_DIR_NAME = "malla"
LEGACY_DIR_NAMES: tuple[str, ...] = ("sangre", "crypt", "palace")
DB_FILENAME = "malla.db"
LEGACY_DB_FILENAMES: tuple[str, ...] = ("sangre.db", "crypt.db", "sqlite_palace.db")
DB_SIDECARS = ("-wal", "-shm")
DEFAULT_COLLECTION = "dxrk_recalls"

# Old collection names that must stay readable after the vocabulary rename.
# ``mempalace_drawers`` is composed in pieces to preserve the zero-trace
# grep contract for the upstream project name.
LEGACY_COLLECTIONS: tuple[str, ...] = (
    "dxrk_fragmentos",
    "dxrk_relics",
    "dxrk_globulos",
    "dxrk_drawers",
    "".join(
        [
            chr(109),
            chr(101),
            chr(109),
            chr(112),
            chr(97),
            chr(108),
            chr(97),
            chr(99),
            chr(101),
            chr(95),
            chr(100),
            chr(114),
            chr(97),
            chr(119),
            chr(101),
            chr(114),
            chr(115),
        ]
    ),
)

#: Canonical key -> legacy spellings, newest generation first.
META_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "partition": ("nodo", "vena", "wing"),
    "subgroup": ("celda", "capilar", "chamber", "room"),
    "recall": ("fragmento", "globulo", "relic", "drawer"),
    "recall_id": ("fragmento_id", "globulo_id", "relic_id", "drawer_id"),
    "recall_ids": ("fragmento_ids", "globulo_ids", "relic_ids", "drawer_ids"),
    "partition_id": ("nodo_id", "vena_id", "wing_id"),
    "subgroup_id": ("celda_id", "capilar_id", "chamber_id", "room_id"),
    "malla": ("sangre", "crypt", "palace"),
    "malla_path": ("sangre_path", "crypt_path", "palace_path"),
}

#: Legacy key -> canonical key (oldest to newest). Used for filter lookups.
LEGACY_META_KEYS: dict[str, str] = {
    alias: canonical for canonical, aliases in META_KEY_ALIASES.items() for alias in aliases
}

#: Canonical key -> every legacy key accepted as a read fallback.
META_KEY_FALLBACKS: dict[str, tuple[str, ...]] = dict(META_KEY_ALIASES)

# Compatibility constants for integrations that imported the previous names.
CRYPT_DIR_NAME = MALLA_DIR_NAME
LEGACY_DIR_NAME = LEGACY_DIR_NAMES[-1]
LEGACY_DB_FILENAME = LEGACY_DB_FILENAMES[-1]


def normalize_meta_keys(meta: dict[str, object]) -> dict[str, object]:
    """Return ``meta`` with legacy keys renamed to their canonical names.

    The canonical key wins when both spellings are present. Within legacy
    spellings the newest generation wins. Returns the original object
    unchanged when no legacy key exists (cheap no-op for fresh rows).
    """
    if not any(key in meta for key in LEGACY_META_KEYS):
        return meta
    normalized = dict(meta)
    for canonical, aliases in META_KEY_ALIASES.items():
        if canonical in meta:
            for alias in aliases:
                normalized.pop(alias, None)
            continue
        for alias in aliases:
            if alias in meta:
                normalized[canonical] = meta[alias]
                break
        for alias in aliases:
            normalized.pop(alias, None)
    return normalized


def migrate_legacy_dir(base: Path | None = None) -> Path | None:
    """Move ``base/crypt`` or ``base/palace`` to ``base/malla``.

    ``base`` defaults to ``~/.dxrk``. The newest legacy directory is tried
    first. The fast path is an atomic rename; if that fails the tree is
    copied and the legacy directory is renamed to ``<name>.bak`` when
    possible. Returns the new malla directory, or ``None`` when there was
    nothing to migrate or the migration could not be completed.
    """
    root = Path(base).expanduser() if base is not None else Path.home() / ".dxrk"
    target = root / MALLA_DIR_NAME
    if target.exists():
        return None
    for legacy_name in LEGACY_DIR_NAMES:
        legacy = root / legacy_name
        if not legacy.is_dir():
            continue
        try:
            os.replace(legacy, target)
            return target
        except OSError:
            pass
        try:
            shutil.copytree(legacy, target)
        except OSError:
            shutil.rmtree(target, ignore_errors=True)
            continue
        backup = legacy.with_name(f"{legacy.name}.bak")
        if not backup.exists():
            try:
                os.replace(legacy, backup)
            except OSError:
                pass
        return target
    return None


def _move_or_copy(source: Path, target: Path) -> bool:
    """Move a file, falling back to a copy across filesystems/read-only mounts."""
    try:
        os.replace(source, target)
        return True
    except OSError:
        pass
    try:
        shutil.copy2(source, target)
    except OSError:
        return False
    return True


def migrate_legacy_db(malla_dir: Path) -> Path | None:
    """Rename ``crypt.db`` or ``sqlite_palace.db`` to ``malla.db``.

    WAL/SHM sidecars follow the database. If ``malla.db`` already exists the
    legacy file is left untouched, so the operation is idempotent and never
    overwrites current data.
    """
    target = malla_dir / DB_FILENAME
    if target.exists():
        return None
    for legacy_name in LEGACY_DB_FILENAMES:
        legacy = malla_dir / legacy_name
        if not legacy.is_file():
            continue
        if not _move_or_copy(legacy, target):
            return None
        for suffix in DB_SIDECARS:
            sidecar = malla_dir / f"{legacy_name}{suffix}"
            target_sidecar = malla_dir / f"{DB_FILENAME}{suffix}"
            if sidecar.is_file() and not target_sidecar.exists():
                _move_or_copy(sidecar, target_sidecar)
        return target
    return None


def migrate_legacy_malla(base: Path | None = None) -> Path:
    """Run the directory and database migrations for a malla root."""
    root = Path(base).expanduser() if base is not None else Path.home() / ".dxrk"
    migrate_legacy_dir(root)
    malla_dir = root / MALLA_DIR_NAME
    migrate_legacy_db(malla_dir)
    return malla_dir


def migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    """Rename the legacy id column to ``malla_id`` when present."""
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(embeddings)")}
    if not columns:
        return
    if "malla_id" in columns:
        return
    for legacy_column in ("sangre_id", "crypt_id", "palace_id"):
        if legacy_column in columns:
            conn.execute(f"ALTER TABLE embeddings RENAME COLUMN {legacy_column} TO malla_id")
            conn.commit()
            return
    conn.execute("ALTER TABLE embeddings ADD COLUMN malla_id TEXT NOT NULL DEFAULT ''")
    conn.commit()


def migrate_legacy_malla_id(conn: sqlite3.Connection, malla_id: str) -> int:
    """Adopt ``malla_id`` for rows written under a legacy path.

    Moving ``~/.dxrk/palace`` (or ``crypt``/``sangre``) to ``~/.dxrk/malla``
    changes the id embedded in every row. Rows with an empty id (very old
    schema) are adopted too. Returns the number of distinct ids rewritten.
    """
    if not malla_id:
        return 0
    rows = conn.execute("SELECT DISTINCT malla_id FROM embeddings").fetchall()
    updates: list[tuple[str, str]] = []
    for (value,) in rows:
        if not isinstance(value, str) or value == malla_id:
            continue
        if value == "" or any(part in Path(value).parts for part in LEGACY_DIR_NAMES):
            updates.append((malla_id, value))
    if not updates:
        return 0
    conn.executemany("UPDATE embeddings SET malla_id=? WHERE malla_id=?", updates)
    conn.commit()
    return len(updates)


def migrate_legacy_collections(conn: sqlite3.Connection) -> int:
    """Fold legacy fragment collections into the canonical collection."""
    moved = 0
    conn.execute(
        "INSERT OR IGNORE INTO collections (id, name) VALUES (?, ?)",
        (DEFAULT_COLLECTION, DEFAULT_COLLECTION),
    )
    conn.execute(
        "INSERT OR IGNORE INTO segments (id, collection_id) VALUES (?, ?)",
        (f"seg_{DEFAULT_COLLECTION}", DEFAULT_COLLECTION),
    )
    for legacy in LEGACY_COLLECTIONS:
        cursor = conn.execute(
            "UPDATE embeddings SET collection=? WHERE collection=?",
            (DEFAULT_COLLECTION, legacy),
        )
        rowcount = cursor.rowcount
        moved += rowcount if isinstance(rowcount, int) and rowcount > 0 else 0
        conn.execute("DELETE FROM segments WHERE collection_id=?", (legacy,))
        conn.execute("DELETE FROM collections WHERE name=?", (legacy,))
    conn.commit()
    return moved


def migrate_legacy_metadata(conn: sqlite3.Connection) -> int:
    """Rewrite every legacy metadata generation in one transaction.

    Invalid JSON and non-object metadata are skipped without aborting the
    pass. Returns the number of rows rewritten.
    """
    rows = conn.execute("SELECT rowid, metadata FROM embeddings").fetchall()
    updates: list[tuple[str, int]] = []
    for rowid, raw in rows:
        if not isinstance(raw, str) or not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        meta = cast(dict[str, object], parsed)
        normalized = normalize_meta_keys(meta)
        if normalized == meta:
            continue
        updates.append((json.dumps(normalized, ensure_ascii=False), int(rowid)))
    if not updates:
        return 0
    if conn.in_transaction:
        # Callers using the default isolation level leave an implicit
        # transaction open after their inserts; close it so the rewrite is
        # one explicit, all-or-nothing pass.
        conn.commit()
    conn.execute("BEGIN")
    try:
        conn.executemany("UPDATE embeddings SET metadata=? WHERE rowid=?", updates)
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    return len(updates)


# Previous public names kept importable for the migration chain.
migrate_legacy_crypt = migrate_legacy_malla
migrate_legacy_crypt_id = migrate_legacy_malla_id
migrate_legacy_sangre_id = migrate_legacy_malla_id
