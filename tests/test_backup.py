# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dxrk import backup


# ─── helpers ────────────────────────────────────────────────────────────


def _touch(path: str, content: str = "hello") -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


# ─── ArchiveEntry ────────────────────────────────────────────────────────


class TestArchiveEntry:
    def test_defaults(self):
        e = backup.ArchiveEntry()
        assert e.rel_path == ""
        assert e.source_path == ""
        assert e.mode == 0o644


# ─── create_archive / extract_archive ──────────────────────────────────


class TestArchiveRoundtrip:
    def test_create_and_extract(self, tmp_path):
        src = str(tmp_path / "src")
        dst = str(tmp_path / "dst")
        _touch(f"{src}/a.txt", "aaa")
        _touch(f"{src}/b.txt", "bbb")

        archive_path = str(tmp_path / "out.tar.gz")
        entries = [
            backup.ArchiveEntry(rel_path="a.txt", source_path=f"{src}/a.txt", mode=0o644),
            backup.ArchiveEntry(rel_path="b.txt", source_path=f"{src}/b.txt", mode=0o644),
        ]
        backup.create_archive(archive_path, entries)
        assert os.path.isfile(archive_path)

        extracted = backup.extract_archive(archive_path, dst)
        assert len(extracted) == 2
        for e in extracted:
            assert os.path.isfile(e.source_path)

    def test_raises_on_path_traversal(self, tmp_path):
        archive_path = str(tmp_path / "bad.tar.gz")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="../escape.txt")
            info.size = 4
            tar.addfile(info, io.BytesIO(b"pwn!"))
        buf.seek(0)
        with open(archive_path, "wb") as f:
            f.write(buf.read())
        with pytest.raises(ValueError, match="escapes"):
            backup.extract_archive(archive_path, str(tmp_path / "dest"))

    def test_raises_on_nonexistent(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            backup.extract_archive(str(tmp_path / "nonexistent.tar.gz"), str(tmp_path / "dest"))


# ─── Manifest serialization ────────────────────────────────────────────


class TestManifestRoundtrip:
    def test_write_and_read(self, tmp_path):
        now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
        m = backup.Manifest(
            id="test-123",
            created_at=now,
            root_dir=str(tmp_path),
            entries=[
                backup.ManifestEntry(
                    original_path="/home/user/.claude/config",
                    snapshot_path="files/home/user/.claude/config",
                    existed=True,
                    mode=0o644,
                )
            ],
            source=backup.BackupSource.INSTALL,
            description="test backup",
            file_count=1,
            created_by_version="1.0.0",
            pinned=False,
            compressed=True,
            checksum="abc123",
        )
        path = str(tmp_path / "manifest.json")
        backup.write_manifest(path, m)
        assert os.path.isfile(path)

        m2 = backup.read_manifest(path)
        assert m2.id == "test-123"
        assert m2.created_at == now
        assert len(m2.entries) == 1
        assert m2.entries[0].original_path == "/home/user/.claude/config"
        assert m2.source == backup.BackupSource.INSTALL
        assert m2.compressed is True
        assert m2.checksum == "abc123"

    def test_minimal_manifest(self, tmp_path):
        m = backup.Manifest(id="minimal", root_dir=str(tmp_path))
        path = str(tmp_path / "m.json")
        backup.write_manifest(path, m)
        m2 = backup.read_manifest(path)
        assert m2.id == "minimal"
        assert m2.entries == []
        assert m2.source is None


# ─── BackupRootFn ────────────────────────────────────────────────────


class TestBackupRoot:
    def test_backup_root(self):
        root = backup.backup_root()
        assert root.endswith("/.dxrk/backups")


# ─── Snapshotter ──────────────────────────────────────────────────────


class TestSnapshotter:
    def test_create_with_files(self, tmp_path):
        snapshot_dir = str(tmp_path / "backup" / "snap-001")
        file1 = _touch(f"{tmp_path}/a.txt", "alpha")
        file2 = _touch(f"{tmp_path}/b.txt", "beta")

        snap = backup.Snapshotter()
        manifest = snap.create(snapshot_dir, [file1, file2])

        assert manifest.id == "snap-001"
        assert manifest.file_count == 2
        assert manifest.compressed is True
        assert os.path.isfile(os.path.join(snapshot_dir, backup.ManifestFilename))
        assert os.path.isfile(os.path.join(snapshot_dir, backup.ArchiveFilename))

    def test_create_with_missing_file(self, tmp_path):
        snapshot_dir = str(tmp_path / "backup" / "snap-002")
        snap = backup.Snapshotter()
        manifest = snap.create(snapshot_dir, ["/nonexistent/file.txt"])

        assert manifest.file_count == 0
        assert manifest.compressed is False
        assert not os.path.isfile(os.path.join(snapshot_dir, backup.ArchiveFilename))
        assert manifest.checksum == hashlib.sha256(b"").hexdigest()

    def test_create_empty(self, tmp_path):
        snapshot_dir = str(tmp_path / "backup" / "empty")
        snap = backup.Snapshotter()
        manifest = snap.create(snapshot_dir, [])

        assert manifest.file_count == 0
        assert manifest.compressed is False


# ─── list_backups ─────────────────────────────────────────────────────


class TestListBackups:
    def test_returns_display_labels(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "BackupRootFn", lambda: str(tmp_path))
        now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
        m = backup.Manifest(
            id="b1",
            created_at=now,
            root_dir=str(tmp_path / "b1"),
            source=backup.BackupSource.INSTALL,
            file_count=3,
        )
        os.makedirs(str(tmp_path / "b1"))
        backup.write_manifest(str(tmp_path / "b1" / backup.ManifestFilename), m)

        result = backup.list_backups()
        assert len(result) == 1
        assert "install" in result[0]
        assert "3 files" in result[0]

    def test_no_backups(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "BackupRootFn", lambda: str(tmp_path))
        assert backup.list_backups() == []


# ─── delete / rename / pin ────────────────────────────────────────────


class TestBackupOperations:
    def test_delete_backup_inside_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "BackupRootFn", lambda: str(tmp_path))
        root = str(tmp_path / "my-backup")
        _touch(f"{root}/manifest.json")
        m = backup.Manifest(id="my-backup", root_dir=root)
        backup.delete_backup(m)
        assert not os.path.exists(root)

    def test_rename_backup(self, tmp_path):
        root = str(tmp_path / "snap-001")
        os.makedirs(root)
        m = backup.Manifest(id="snap-001", root_dir=root)
        backup.rename_backup(m, "new description")
        m2 = backup.read_manifest(os.path.join(root, backup.ManifestFilename))
        assert m2.description == "new description"

    def test_toggle_pin(self, tmp_path):
        root = str(tmp_path / "snap-001")
        os.makedirs(root)
        m = backup.Manifest(id="snap-001", root_dir=root)
        assert m.pinned is False
        backup.toggle_pin(m)
        assert m.pinned is True
        m2 = backup.read_manifest(os.path.join(root, backup.ManifestFilename))
        assert m2.pinned is True


# ─── RestoreService ────────────────────────────────────────────────────


class TestRestoreService:
    def test_restore_entry_directly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "UserHomeDirFn", lambda: str(tmp_path))
        home = str(tmp_path / "home" / "user")
        original = f"{home}/.config/app/config.json"
        snapshot = _touch(f"{tmp_path}/snapshot.txt", '{"key": "val"}')

        os.makedirs(os.path.dirname(original))
        entry = backup.ManifestEntry(
            original_path=original,
            snapshot_path=snapshot,
            existed=True,
            mode=0o644,
        )
        rs = backup.RestoreService()
        rs._restore_entry(entry, trusted_snapshot=True)

        assert os.path.isfile(original)
        with open(original) as f:
            assert f.read() == '{"key": "val"}'

    def test_restore_compressed_with_nonexistent_entry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "UserHomeDirFn", lambda: str(tmp_path))
        missing = str(tmp_path / "nonexistent" / "file.txt")
        snap_dir = str(tmp_path / "backups" / "snap-002")
        snap = backup.Snapshotter()
        manifest = snap.create(snap_dir, [missing])

        rs = backup.RestoreService()
        rs.restore(manifest)


# ─── Prune ────────────────────────────────────────────────────────────


class TestPrune:
    def test_prune_removes_oldest_unpinned(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "BackupRootFn", lambda: str(tmp_path))
        for i in range(5):
            d = str(tmp_path / f"b{i}")
            os.makedirs(d)
            backup.write_manifest(
                os.path.join(d, backup.ManifestFilename),
                backup.Manifest(
                    id=f"b{i}",
                    root_dir=d,
                    created_at=datetime(2026, 5, 20 + i, tzinfo=timezone.utc),
                ),
            )
        deleted = backup.prune(str(tmp_path), 2)
        assert len(deleted) == 3
        for d in deleted:
            assert not os.path.exists(str(tmp_path / d))

    def test_prune_keeps_pinned(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "BackupRootFn", lambda: str(tmp_path))
        pinned_dir = str(tmp_path / "pinned")
        os.makedirs(pinned_dir)
        backup.write_manifest(
            os.path.join(pinned_dir, backup.ManifestFilename),
            backup.Manifest(
                id="pinned",
                root_dir=pinned_dir,
                created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
                pinned=True,
            ),
        )
        deleted = backup.prune(str(tmp_path), 0)
        assert deleted == []

    def test_prune_empty_dir(self, tmp_path):
        assert backup.prune(str(tmp_path), 5) == []


# ─── Checksum / dedup ──────────────────────────────────────────────────


class TestChecksum:
    def test_compute_checksum(self, tmp_path):
        f1 = _touch(f"{tmp_path}/a.txt", "hello")
        f2 = _touch(f"{tmp_path}/b.txt", "world")
        cs = backup.compute_checksum([f1, f2])
        assert isinstance(cs, str)
        assert len(cs) == 64
        assert cs == backup.compute_checksum([f1, f2])

    def test_compute_checksum_empty(self, tmp_path):
        assert backup.compute_checksum([]) == ""

    def test_compute_checksum_missing_file(self, tmp_path):
        f1 = _touch(f"{tmp_path}/a.txt", "data")
        cs = backup.compute_checksum([f1, "/nonexistent/file"])
        assert isinstance(cs, str)
        assert len(cs) == 64

    def test_is_duplicate(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "BackupRootFn", lambda: str(tmp_path))
        f1 = _touch(f"{tmp_path}/data.txt", "same")
        snap = backup.Snapshotter()
        m = snap.create(str(tmp_path / "backups" / "snap-1"), [f1])
        assert backup.is_duplicate(str(tmp_path / "backups"), m.checksum) is True

    def test_is_duplicate_no_checksum(self, tmp_path):
        assert backup.is_duplicate(str(tmp_path), "") is False


# ─── Stat helpers ──────────────────────────────────────────────────────


class TestStatHelpers:
    def test_stat_is_dir(self):
        assert backup.stat_is_dir(0o040755) is True
        assert backup.stat_is_dir(0o100644) is False

    def test_stat_is_regular(self):
        assert backup.stat_is_regular(0o100644) is True
        assert backup.stat_is_regular(0o040755) is False

    def test_stat_mode_perm(self):
        assert backup.stat_mode_perm(0o100644) == 0o644
        assert backup.stat_mode_perm(0o755) == 0o755


# ─── List manifests (private, but tested via list_backups) ──────────────


class TestListManifests:
    def test_list_manifests(self, tmp_path):
        for i in range(3):
            d = str(tmp_path / f"b{i}")
            os.makedirs(d)
            backup.write_manifest(
                os.path.join(d, backup.ManifestFilename),
                backup.Manifest(id=f"b{i}", root_dir=d),
            )
        result = backup._list_manifests(str(tmp_path))
        assert len(result) == 3

    def test_list_manifests_empty(self, tmp_path):
        assert backup._list_manifests(str(tmp_path)) == []

    def test_list_manifests_nonexistent(self, tmp_path):
        assert backup._list_manifests(str(tmp_path / "nonexistent")) == []


# ─── Source enum ────────────────────────────────────────────────────────


class TestBackupSource:
    def test_labels(self):
        assert backup.BackupSource.INSTALL.label() == "install"
        assert backup.BackupSource.SYNC.label() == "sync"
        assert backup.BackupSource.UPGRADE.label() == "upgrade"
        assert backup.BackupSource.UNINSTALL.label() == "uninstall"
