# SPDX-License-Identifier: MIT
"""Backup snapshot and rollback steps for the install pipeline."""

from __future__ import annotations

import logging
import os
from typing import Any

from dxrk.pipeline import RollbackStep

log = logging.getLogger("dxrk.cli.install")


class PrepareBackupStep(RollbackStep):
    def __init__(
        self,
        step_id: str,
        snapshot_dir: str,
        targets: list[str],
        state: dict[str, Any],
        backup_root: str = "",
        source: str = "",
        description: str = "",
        app_version: str = "",
    ):
        self._id = step_id
        self._snapshot_dir = snapshot_dir
        self._targets = targets
        self._state = state
        self._backup_root = backup_root
        self._source = source
        self._description = description
        self._app_version = app_version

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        if not self._targets:
            return None
        os.makedirs(self._snapshot_dir, mode=0o755, exist_ok=True)
        manifest: dict[str, Any] = {"entries": []}
        for target in self._targets:
            if os.path.isfile(target):
                rel = os.path.relpath(target, "/").lstrip("/")
                dest = os.path.join(self._snapshot_dir, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                try:
                    import shutil

                    shutil.copy2(target, dest)
                    manifest["entries"].append({"source": target, "dest": rel})
                except OSError as e:
                    log.warning("backup: no se pudo copiar %s: %s", target, e)
        manifest["source"] = self._source
        manifest["description"] = self._description
        manifest["created_by_version"] = self._app_version
        manifest_path = os.path.join(self._snapshot_dir, "manifest.json")
        try:
            import json

            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)
        except OSError as e:
            log.warning("backup: no se pudo escribir el manifiesto: %s", e)
        self._state["manifest"] = manifest
        return None

    def rollback(self) -> str | None:
        manifest = self._state.get("manifest", {})
        entries = manifest.get("entries", [])
        if not entries:
            return None
        for entry in entries:
            dest = os.path.join(self._snapshot_dir, entry.get("dest", ""))
            source = entry.get("source", "")
            if os.path.isfile(dest) and source:
                try:
                    import shutil

                    shutil.copy2(dest, source)
                except OSError as e:
                    log.warning("rollback: no se pudo restaurar %s: %s", source, e)
        return None


class RollbackRestoreStep(RollbackStep):
    def __init__(self, step_id: str, state: dict[str, Any]):
        self._id = step_id
        self._state = state

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        return None

    def rollback(self) -> str | None:
        manifest = self._state.get("manifest", {})
        entries = manifest.get("entries", [])
        if not entries:
            return None
        import shutil

        for entry in entries:
            dest_path = os.path.join(
                os.path.dirname(manifest.get("_backup_root", "")),
                entry.get("dest", ""),
            )
            source = entry.get("source", "")
            if os.path.isfile(dest_path) and source:
                try:
                    shutil.copy2(dest_path, source)
                except OSError as e:
                    log.warning("rollback: no se pudo restaurar %s: %s", source, e)
        return None
