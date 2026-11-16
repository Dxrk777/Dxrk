# SPDX-License-Identifier: MIT
"""Read-only discovery helpers for the local Omni preview dashboard."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class PreviewError(RuntimeError):
    """A run manifest or media path is invalid."""


@dataclass(frozen=True, slots=True)
class RunSummary:
    slug: str
    workdir: Path
    status: str
    topic: str
    mode: str
    stage: str
    updated_at: str
    video: Path | None
    contact_sheet: Path | None
    progress: float | None


def load_manifest(workdir: Path) -> dict[str, Any]:
    path = Path(workdir) / "manifest.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PreviewError(f"no pude leer {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PreviewError(f"manifest inválido {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PreviewError(f"el manifest {path} debe ser un objeto")
    return data


def resolve_media_path(workdir: Path, raw: str | Path) -> Path | None:
    """Resolve ``raw`` inside ``workdir`` or return ``None`` on escape/missing."""
    root = Path(workdir).resolve()
    try:
        candidate = (root / str(raw)).resolve()
        candidate.relative_to(root)
    except OSError, ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _safe_media(workdir: Path, value: Any) -> Path | None:
    if not value:
        return None
    return resolve_media_path(workdir, str(value))


def discover_runs(root: Path) -> list[RunSummary]:
    root = Path(root)
    if not root.is_dir():
        return []
    runs: list[RunSummary] = []
    for workdir in root.iterdir():
        if not workdir.is_dir() or workdir.name.startswith("."):
            continue
        try:
            data = load_manifest(workdir)
        except PreviewError:
            continue
        try:
            modified = workdir.stat().st_mtime
        except OSError:
            modified = 0.0
        updated_at = str(data.get("updated_at") or data.get("created_at") or "")
        if not updated_at:
            updated_at = datetime.fromtimestamp(modified).isoformat(timespec="seconds")
        progress = data.get("progress")
        runs.append(
            RunSummary(
                slug=workdir.name,
                workdir=workdir,
                status=str(data.get("status") or "unknown"),
                topic=str(data.get("topic") or workdir.name),
                mode="longform" if data.get("longform") else "short",
                stage=str(data.get("stage") or ""),
                updated_at=updated_at,
                video=_safe_media(workdir, data.get("video")),
                contact_sheet=_safe_media(workdir, data.get("contact_sheet")),
                progress=float(progress) if isinstance(progress, (int, float)) else None,
            )
        )

    def _mtime(run: RunSummary) -> float:
        try:
            return run.workdir.stat().st_mtime
        except OSError:
            return 0.0

    runs.sort(key=_mtime, reverse=True)
    return runs


def read_log_tail(path: Path, max_bytes: int = 64_000) -> str:
    if max_bytes <= 0:
        raise PreviewError("max_bytes debe ser positivo")
    path = Path(path)
    if not path.is_file():
        return ""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                data = handle.read()
                newline = data.find(b"\n")
                if newline >= 0:
                    data = data[newline + 1 :]
            else:
                data = handle.read()
    except OSError as exc:
        raise PreviewError(f"no pude leer el log {path}: {exc}") from exc
    return data.decode("utf-8", errors="replace")


__all__ = [
    "PreviewError",
    "RunSummary",
    "discover_runs",
    "load_manifest",
    "read_log_tail",
    "resolve_media_path",
]
