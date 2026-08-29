# SPDX-License-Identifier: MIT
"""Shared atomic JSON persistence helper for config and settings"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def save_json_atomic(path: str | Path, data: dict[str, Any]) -> None:
    """Atomically writes *data* as JSON to *path* with secure permissions.

    Creates parent directories with ``0o750`` and the file with ``0o600``.
    Writes to a temporary file in the same directory and atomically
    replaces the target via ``Path.replace`` to avoid torn writes.
    """
    target = Path(path)
    parent = target.parent
    parent_str = str(parent)
    if parent_str not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True, mode=0o750)

    payload = json.dumps(data, indent=2)
    # Hidden temp file in the same directory for atomic replace
    if parent_str not in ("", "."):
        tmp_path = parent / f".{target.name}.tmp"
    else:
        tmp_path = Path(f".{target.name}.tmp")

    # Ensure any stale tmp is removed before write (best-effort)
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except OSError:
        pass

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(payload)
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(target)
        # Replace preserves tmp perms on POSIX, but ensure final perms
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    finally:
        # Cleanup stale tmp if replace failed
        try:
            if tmp_path.exists() and tmp_path != target:
                tmp_path.unlink()
        except OSError:
            pass
