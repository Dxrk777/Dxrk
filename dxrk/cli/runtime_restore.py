# SPDX-License-Identifier: MIT
"""Restore a managed backup snapshot."""

from __future__ import annotations

import os
import sys
from typing import Any


def run_restore(args: list[str], stdout: Any = None) -> str | None:
    if stdout is None:
        stdout = sys.stdout

    home_dir = os.path.expanduser("~")

    positional: list[str] = []
    list_flag = False
    yes_flag = False

    for a in args:
        if a in ("--list", "-list"):
            list_flag = True
        elif a in ("--yes", "-yes", "-y"):
            yes_flag = True
        elif a.startswith("-"):
            raise ValueError(f"flag desconocido {a!r}")
        else:
            positional.append(a)

    backups = _list_backups(home_dir)

    if list_flag:
        _render_restore_list(backups, stdout)
        return None

    if not positional:
        return "uso: dxrk-py restore [--list | latest | <id>] [--yes]"

    target = positional[0]
    manifest = _resolve_restore_target(target, backups)

    if not yes_flag:
        confirmed = _prompt_restore_confirm(manifest, stdout)
        if not confirmed:
            print("restauración cancelada", file=stdout)
            return None

    manifest_dir = manifest.get("_dir", "")

    for entry in manifest.get("entries", []):
        dest_path = entry.get("source", "")
        rel = entry.get("dest", "")
        src_path = os.path.join(manifest_dir, rel) if manifest_dir else ""
        if os.path.isfile(src_path) and dest_path:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            import shutil

            shutil.copy2(src_path, dest_path)

    label = manifest.get("description", "") or manifest.get("source", "") or target
    print(f"restauración completa — copia {target} restaurada ({label})", file=stdout)
    return None


def _list_backups(home_dir: str) -> list[dict[str, Any]]:
    backup_root = os.path.join(home_dir, ".gentle-ai", "backups")
    if not os.path.isdir(backup_root):
        return []

    manifests: list[dict[str, Any]] = []
    for entry in sorted(os.listdir(backup_root), reverse=True):
        entry_path = os.path.join(backup_root, entry)
        if not os.path.isdir(entry_path):
            continue
        manifest_path = os.path.join(entry_path, "manifest.json")
        if os.path.isfile(manifest_path):
            try:
                import json

                with open(manifest_path) as f:
                    m = json.load(f)
                m["_dir"] = entry_path
                m["_id"] = entry
                manifests.append(m)
            except Exception:
                continue

    manifests.sort(key=lambda m: m.get("_id", ""), reverse=True)
    return manifests


def _render_restore_list(backups: list[dict[str, Any]], stdout: Any) -> None:
    if not backups:
        print("no se encontraron copias de seguridad", file=stdout)
        return
    print(f"Copias disponibles ({len(backups)}):", file=stdout)
    for i, m in enumerate(backups):
        bid = m.get("_id", "?")
        source = m.get("source", "desconocido")
        count = len(m.get("entries", []))
        version = m.get("created_by_version", "")
        line = f"  [{i + 1}] {bid}  source={source} files={count}"
        if version:
            line += f"  [v{version}]"
        print(line, file=stdout)


def _resolve_restore_target(target: str, backups: list[dict[str, Any]]) -> dict[str, Any]:
    if target == "latest":
        if not backups:
            raise ValueError("no hay copias disponibles para restaurar")
        return backups[0]
    for m in backups:
        if m.get("_id") == target:
            return m
    raise ValueError(f"copia {target!r} no encontrada — usa `dxrk-py restore --list` para ver las copias disponibles")


def _prompt_restore_confirm(manifest: dict[str, Any], stdout: Any) -> bool:
    bid = manifest.get("_id", "?")
    source = manifest.get("source", "desconocido")
    count = len(manifest.get("entries", []))
    print(f"¿Restaurar la copia {bid} (source={source}, files={count})?", file=stdout)
    print(
        "Esto sobrescribirá tu configuración actual. Escribe 'yes' para confirmar: ",
        end="",
        file=stdout,
    )
    try:
        answer = input().strip()
    except EOFError:
        return False
    return answer.lower() == "yes"
