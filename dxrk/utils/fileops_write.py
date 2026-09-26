# SPDX-License-Identifier: MIT
"""Atomic file writes, backups, appends, and directory setup."""

from __future__ import annotations

import os
import stat as _stat
import tempfile
from dataclasses import dataclass

from dxrk.utils.fileops_errors import FileopsError, ValidatePath


@dataclass
class WriteOpts:
    """Configures how WriteFile behaves. Mirrors fileops.WriteOpts."""

    create_dirs: bool = False
    mode: int = 0
    backup: bool = False
    overwrite: bool = True
    encoding: str = ""


def DefaultWriteOpts() -> WriteOpts:
    """Return sensible defaults. Mirrors fileops.DefaultWriteOpts."""
    return WriteOpts(create_dirs=True, mode=0o644, overwrite=True)


def WriteFile(path: str, content: str, opts: WriteOpts) -> FileopsError | None:
    """Write content to path atomically. Mirrors fileops.WriteFile."""
    err = ValidatePath(path)
    if err is not None:
        return err
    if opts.mode == 0:
        opts.mode = 0o644
    if opts.create_dirs:
        err = EnsureDir(path)
        if err is not None:
            return err
    if not opts.overwrite:
        if os.path.exists(path):
            return FileopsError(f"fileops: file exists and Overwrite is false: {path}")
    if opts.backup:
        if os.path.exists(path):
            _, err = BackupFile(path)
            if err is not None:
                return FileopsError(f"fileops: backup failed: {err}")
    return WriteAtomic(path, content.encode("utf-8"))


def WriteAtomic(path: str, data: bytes) -> FileopsError | None:
    """Write to a temp file in the same directory, then rename. Mirrors WriteAtomic."""
    err = ValidatePath(path)
    if err is not None:
        return err
    dirname = os.path.dirname(path)
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=".fileops-tmp-", dir=dirname)
    except OSError as e:
        return FileopsError(f"fileops: create temp: {e}")
    cleanup = True
    try:
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except OSError as e:
                    return FileopsError(f"fileops: sync temp: {e}")
        except OSError as e:
            return FileopsError(f"fileops: write temp: {e}")
        try:
            os.replace(tmp_name, path)
        except OSError as e:
            return FileopsError(f"fileops: rename: {e}")
        cleanup = False
        return None
    finally:
        if cleanup:
            try:
                os.remove(tmp_name)
            except OSError:
                pass


def BackupFile(path: str) -> tuple[str, FileopsError | None]:
    """Create a backup of path at path.bak. Mirrors fileops.BackupFile."""
    err = ValidatePath(path)
    if err is not None:
        return "", err
    bak = path + ".bak"
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return "", FileopsError(f"fileops: read for backup: {e}")
    try:
        info = os.stat(path)
    except OSError as e:
        return "", FileopsError(str(e))
    try:
        with open(bak, "wb") as f:
            f.write(data)
        os.chmod(bak, _stat.S_IMODE(info.st_mode))
    except OSError as e:
        return "", FileopsError(f"fileops: write backup: {e}")
    return bak, None


def WriteLines(path: str, lines: list[str], opts: WriteOpts) -> FileopsError | None:
    """Write each string as a line (joined by newlines) atomically. Mirrors WriteLines."""
    text = "\n".join(lines)
    if len(lines) > 0:
        text += "\n"
    return WriteFile(path, text, opts)


def AppendFile(path: str, content: str) -> FileopsError | None:
    """Append content to the file at path, creating it if necessary. Mirrors AppendFile."""
    err = ValidatePath(path)
    if err is not None:
        return err
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return FileopsError(str(e))
    return None


def EnsureDir(path: str) -> FileopsError | None:
    """Create parent directories for the given file path. Mirrors fileops.EnsureDir."""
    try:
        os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    except OSError as e:
        return FileopsError(str(e))
    return None
