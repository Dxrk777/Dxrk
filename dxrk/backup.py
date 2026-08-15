# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

logger = logging.getLogger(__name__)

ManifestFilename = "manifest.json"
ArchiveFilename = "snapshot.tar.gz"

_empty_files_checksum = hashlib.sha256(b"").hexdigest()
DefaultRetentionCount = 5


# Compression types


@dataclass
class ArchiveEntry:
    rel_path: str = ""
    source_path: str = ""
    mode: int = 0o644


def create_archive(archive_path: str, entries: list[ArchiveEntry]) -> None:
    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as tar:
        for entry in entries:
            info = tar.gettarinfo(
                entry.source_path, arcname=entry.rel_path.replace(os.sep, "/")
            )
            if info is None:
                continue
            with open(entry.source_path, "rb") as f:
                info.size = os.path.getsize(entry.source_path)
                tar.addfile(info, f)


def extract_archive(archive_path: str, dest_dir: str) -> list[ArchiveEntry]:
    extracted: list[ArchiveEntry] = []
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            dest_path = os.path.join(
                dest_dir, os.path.normpath(member.name.replace("/", os.sep))
            )
            clean_dest = (
                os.path.realpath(dest_path)
                if os.path.exists(dest_path)
                else os.path.normpath(dest_path)
            )
            clean_base = (
                os.path.realpath(dest_dir)
                if os.path.exists(dest_dir)
                else os.path.normpath(dest_dir) + os.sep
            )
            if not clean_dest.startswith(clean_base):
                raise ValueError(
                    f"archive entry {member.name!r} escapes destination directory"
                )
            if clean_dest == os.path.normpath(dest_dir):
                raise ValueError(
                    f"archive entry {member.name!r} resolves to destination directory itself"
                )
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            tar.extract(member, os.path.dirname(dest_path), filter="data")
            extracted.append(
                ArchiveEntry(
                    rel_path=member.name,
                    source_path=dest_path,
                    mode=member.mode,
                )
            )
    return extracted


# Manifest types


class BackupSource(str, Enum):
    INSTALL = "install"
    SYNC = "sync"
    UPGRADE = "upgrade"
    UNINSTALL = "uninstall"

    def label(self) -> str:
        labels: dict[BackupSource, str] = {
            BackupSource.INSTALL: "install",
            BackupSource.SYNC: "sync",
            BackupSource.UPGRADE: "upgrade",
            BackupSource.UNINSTALL: "uninstall",
        }
        return labels.get(self, "unknown source")


@dataclass
class ManifestEntry:
    original_path: str = ""
    snapshot_path: str = ""
    existed: bool = False
    mode: int = 0


@dataclass
class Manifest:
    id: str = ""
    created_at: datetime | None = None
    root_dir: str = ""
    entries: list[ManifestEntry] = field(default_factory=list)
    source: BackupSource | None = None
    description: str = ""
    file_count: int = 0
    created_by_version: str = ""
    pinned: bool = False
    compressed: bool = False
    checksum: str = ""

    def display_label(self) -> str:
        src = self.source.label() if self.source else "unknown source"
        created = self.created_at if self.created_at else datetime.now(UTC)
        base = f"{src} \u2014 {created.astimezone().strftime('%Y-%m-%d %H:%M')}"
        if self.file_count > 0:
            base = f"{base} ({self.file_count} files)"
        if self.pinned:
            return "[pinned] " + base
        return base


def _manifest_to_dict(m: Manifest) -> dict:
    d: dict = {
        "id": m.id,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "root_dir": m.root_dir,
        "entries": [
            {
                "original_path": e.original_path,
                "snapshot_path": e.snapshot_path,
                "existed": e.existed,
            }
            | ({"mode": e.mode} if e.mode != 0 else {})
            for e in m.entries
        ],
    }
    if m.source:
        d["source"] = m.source.value
    if m.description:
        d["description"] = m.description
    if m.file_count:
        d["file_count"] = m.file_count
    if m.created_by_version:
        d["created_by_version"] = m.created_by_version
    if m.pinned:
        d["pinned"] = m.pinned
    if m.compressed:
        d["compressed"] = m.compressed
    if m.checksum:
        d["checksum"] = m.checksum
    return d


def _manifest_from_dict(d: dict) -> Manifest:
    entries = []
    for e in d.get("entries", []):
        entries.append(
            ManifestEntry(
                original_path=e.get("original_path", ""),
                snapshot_path=e.get("snapshot_path", ""),
                existed=e.get("existed", False),
                mode=e.get("mode", 0),
            )
        )
    created_at = None
    raw = d.get("created_at")
    if raw:
        try:
            created_at = datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            pass
    source = None
    raw_src = d.get("source")
    if raw_src:
        try:
            source = BackupSource(raw_src)
        except ValueError:
            pass
    return Manifest(
        id=d.get("id", ""),
        created_at=created_at,
        root_dir=d.get("root_dir", ""),
        entries=entries,
        source=source,
        description=d.get("description", ""),
        file_count=d.get("file_count", 0),
        created_by_version=d.get("created_by_version", ""),
        pinned=d.get("pinned", False),
        compressed=d.get("compressed", False),
        checksum=d.get("checksum", ""),
    )


def write_manifest(path: str, manifest: Manifest) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = json.dumps(_manifest_to_dict(manifest), indent=2) + "\n"
    with open(path, "w") as f:
        f.write(content)


def read_manifest(path: str) -> Manifest:
    with open(path) as f:
        content = f.read()
    return _manifest_from_dict(json.loads(content))


# Backup root resolution


def backup_root() -> str:
    home = os.path.expanduser("~")
    if not home or home == "~":
        raise OSError("resolve home directory: HOME not set")
    return os.path.join(home, ".dxrk", "backups")


BackupRootFn = backup_root


def is_root_dir_under_backup_root(dir_path: str) -> bool:
    root = BackupRootFn()
    clean = os.path.normpath(dir_path)
    root_clean = os.path.normpath(root)
    if not clean.startswith(root_clean + os.sep):
        return False
    if os.path.exists(clean):
        resolved = os.path.realpath(clean)
        resolved_root = os.path.realpath(root_clean)
        return resolved.startswith(resolved_root + os.sep)
    return True


# Delete / rename / pin operations


def delete_backup(manifest: Manifest) -> None:
    if not manifest.root_dir:
        raise ValueError("backup has no root directory")
    if not is_root_dir_under_backup_root(manifest.root_dir):
        raise ValueError(
            f"backup RootDir {manifest.root_dir!r} is outside the expected backup directory"
            " \u2014 refusing to delete"
        )
    shutil.rmtree(manifest.root_dir)


def rename_backup(manifest: Manifest, new_description: str) -> None:
    if not manifest.root_dir:
        raise ValueError("backup has no root directory")
    manifest.description = new_description
    manifest_path = os.path.join(manifest.root_dir, ManifestFilename)
    write_manifest(manifest_path, manifest)


def toggle_pin(manifest: Manifest) -> None:
    if not manifest.root_dir:
        raise ValueError("backup has no root directory")
    manifest.pinned = not manifest.pinned
    manifest_path = os.path.join(manifest.root_dir, ManifestFilename)
    write_manifest(manifest_path, manifest)


# Snapshot creation


class Snapshotter:
    def __init__(self) -> None:
        self._now = datetime.now

    def create(self, snapshot_dir: str, paths: list[str]) -> Manifest:
        os.makedirs(snapshot_dir, exist_ok=True)
        manifest = Manifest(
            id=os.path.basename(snapshot_dir),
            created_at=self._now(UTC),
            root_dir=snapshot_dir,
            entries=[],
            compressed=True,
        )
        archive_entries: list[ArchiveEntry] = []
        existing_paths: list[str] = []

        for path in paths:
            mentry, aentry = self._build_entry(path)
            manifest.entries.append(mentry)
            if mentry.existed:
                manifest.file_count += 1
                archive_entries.append(aentry)
                existing_paths.append(aentry.source_path)

        if not archive_entries:
            manifest.compressed = False
        else:
            archive_path = os.path.join(snapshot_dir, ArchiveFilename)
            create_archive(archive_path, archive_entries)

        if not existing_paths:
            checksum = _empty_files_checksum
        else:
            try:
                checksum = compute_checksum(existing_paths)
            except (OSError, ValueError) as exc:
                logger.warning("backup: compute checksum: %s", exc)
                checksum = ""
        manifest.checksum = checksum

        write_manifest(os.path.join(snapshot_dir, ManifestFilename), manifest)
        return manifest

    def _build_entry(self, source_path: str) -> tuple[ManifestEntry, ArchiveEntry]:
        clean_source = os.path.normpath(source_path)
        mentry = ManifestEntry(original_path=clean_source)

        try:
            info = os.stat(clean_source)
        except FileNotFoundError:
            return mentry, ArchiveEntry()

        if stat_is_dir(info.st_mode):
            return mentry, ArchiveEntry()

        relative = clean_source.lstrip(os.sep)
        if not relative:
            relative = "root"
        rel_path = os.path.join("files", relative).replace(os.sep, "/")

        aentry = ArchiveEntry(
            rel_path=rel_path,
            source_path=clean_source,
            mode=info.st_mode,
        )
        mentry.snapshot_path = rel_path
        mentry.existed = True
        mentry.mode = info.st_mode
        return mentry, aentry


def stat_is_dir(mode: int) -> bool:
    return (mode & 0o170000) == 0o040000


# Checksum / deduplication


def compute_checksum(paths: list[str]) -> str:
    entries: list[tuple[str, str]] = []
    for p in paths:
        try:
            info = os.stat(p)
        except FileNotFoundError:
            continue
        except OSError as e:
            raise ValueError(f"stat {p!r}: {e}") from e
        if not stat_is_regular(info.st_mode):
            continue
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError as e:
            raise ValueError(f"read {p!r}: {e}") from e
        entries.append((p, hashlib.sha256(data).hexdigest()))

    if not entries:
        return ""

    entries.sort(key=lambda x: x[0])
    sb = "\n".join(f"{path}:{hsh}" for path, hsh in entries) + "\n"
    return hashlib.sha256(sb.encode()).hexdigest()


def stat_is_regular(mode: int) -> bool:
    return (mode & 0o170000) == 0o100000


def is_duplicate(backup_dir: str, new_checksum: str) -> bool:
    if not new_checksum:
        return False
    manifests = _list_manifests(backup_dir)
    if not manifests:
        return False
    latest = max(
        manifests,
        key=lambda m: m.created_at or datetime.min.replace(tzinfo=UTC),
    )
    if not latest.checksum:
        return False
    return latest.checksum == new_checksum


def prune(backup_dir: str, retention_count: int) -> list[str]:
    if retention_count <= 0:
        return []
    manifests = _list_manifests(backup_dir)
    manifests.sort(
        key=lambda m: m.created_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    unpinned = [m for m in manifests if not m.pinned]
    if len(unpinned) <= retention_count:
        return []
    to_delete = unpinned[retention_count:]
    deleted: list[str] = []
    for m in to_delete:
        try:
            delete_backup(m)
            deleted.append(m.id)
        except (OSError, ValueError) as e:
            logger.warning("backup: prune: failed to delete %r: %s", m.root_dir, e)
    return deleted


def _list_manifests(backup_dir: str) -> list[Manifest]:
    try:
        entries = os.listdir(backup_dir)
    except FileNotFoundError:
        return []
    manifests: list[Manifest] = []
    for name in entries:
        manifest_path = os.path.join(backup_dir, name, ManifestFilename)
        if not os.path.isfile(manifest_path):
            continue
        try:
            m = read_manifest(manifest_path)
            manifests.append(m)
        except (OSError, json.JSONDecodeError):
            continue
    return manifests


def list_backups() -> list[str]:
    return [m.display_label() for m in _list_manifests(BackupRootFn())]


# Restore

UserHomeDirFn = lambda: os.path.expanduser("~")


def _is_path_under_home(path: str) -> bool:
    home = UserHomeDirFn()
    if not home or home == "~":
        return False
    clean = os.path.normpath(path)
    home_clean = os.path.normpath(home)
    if not clean.startswith(home_clean + os.sep):
        return False
    if os.path.exists(clean):
        resolved = os.path.realpath(clean)
        resolved_home = os.path.realpath(home_clean)
        return resolved.startswith(resolved_home + os.sep)
    return True


def _write_file_atomic(path: str, content: bytes, mode: int) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(content)
        os.chmod(tmp, stat_mode_perm(mode))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def stat_mode_perm(mode: int) -> int:
    return mode & 0o7777


class RestoreService:
    def restore(self, manifest: Manifest) -> None:
        if manifest.compressed:
            self._restore_compressed(manifest)
        else:
            self._restore_plain(manifest)

    def _restore_compressed(self, manifest: Manifest) -> None:
        tmp_dir = tempfile.mkdtemp(prefix="gentle-ai-restore-")
        try:
            archive_path = os.path.join(manifest.root_dir, ArchiveFilename)
            extract_archive(archive_path, tmp_dir)
            for entry in manifest.entries:
                if entry.existed:
                    if os.path.isabs(entry.snapshot_path):
                        raise ValueError(
                            f"manifest entry {entry.original_path!r} has absolute "
                            f"SnapshotPath {entry.snapshot_path!r}, expected relative"
                        )
                    resolved = ManifestEntry(
                        original_path=entry.original_path,
                        snapshot_path=os.path.join(
                            tmp_dir, entry.snapshot_path.replace("/", os.sep)
                        ),
                        existed=True,
                        mode=entry.mode,
                    )
                    self._restore_entry(resolved, trusted_snapshot=True)
                else:
                    if not (
                        os.path.isabs(entry.original_path)
                        and _is_path_under_home(entry.original_path)
                    ):
                        raise ValueError(
                            f"manifest entry has invalid OriginalPath {entry.original_path!r}: "
                            "must be an absolute path under the user home directory"
                        )
                    try:
                        os.remove(entry.original_path)
                    except FileNotFoundError:
                        pass
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _restore_plain(self, manifest: Manifest) -> None:
        for entry in manifest.entries:
            if entry.existed:
                self._restore_entry(entry, trusted_snapshot=False)
            else:
                if not (
                    os.path.isabs(entry.original_path)
                    and _is_path_under_home(entry.original_path)
                ):
                    raise ValueError(
                        f"manifest entry has invalid OriginalPath {entry.original_path!r}: "
                        "must be an absolute path under the user home directory"
                    )
                try:
                    os.remove(entry.original_path)
                except FileNotFoundError:
                    pass

    def _restore_entry(self, entry: ManifestEntry, trusted_snapshot: bool) -> None:
        if not (
            os.path.isabs(entry.original_path)
            and _is_path_under_home(entry.original_path)
        ):
            raise ValueError(
                f"manifest entry has invalid OriginalPath {entry.original_path!r}: "
                "must be an absolute path under the user home directory"
            )
        if not trusted_snapshot:
            if not is_root_dir_under_backup_root(entry.snapshot_path):
                raise ValueError(
                    f"manifest entry has invalid SnapshotPath {entry.snapshot_path!r}: "
                    "must be under the backup root directory"
                )
        try:
            with open(entry.snapshot_path, "rb") as f:
                content = f.read()
        except OSError as e:
            raise ValueError(f"read snapshot file {entry.snapshot_path!r}: {e}") from e
        os.makedirs(os.path.dirname(entry.original_path), exist_ok=True)
        _write_file_atomic(entry.original_path, content, entry.mode)
