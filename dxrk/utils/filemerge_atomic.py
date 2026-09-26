# SPDX-License-Identifier: MIT
"""Atomic file writes with symlink guards and parent-dir syncing."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from dataclasses import dataclass

MAX_ATOMIC_FILE_SIZE = 16 << 20


@dataclass(frozen=True)
class WriteResult:
    Changed: bool
    Created: bool


def _default_sync_dir(dir: str) -> None:
    try:
        fd = os.open(dir, os.O_RDONLY)
    except OSError as exc:
        raise OSError(f"open parent directory {dir!r}: {exc}") from exc
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# Module-level vars so tests can override them without spawning a real
# Windows process (runtimeGOOS / syncDirFn overrides).
_runtime_goos: str = sys.platform
_sync_dir_fn = _default_sync_dir


def read_comparable_file(path: str) -> bytes:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise OSError(f"refusing to read symlink {path!r}")
    if info.st_size > MAX_ATOMIC_FILE_SIZE:
        raise OSError(f"file {path!r} exceeds max atomic compare size {MAX_ATOMIC_FILE_SIZE} bytes")

    with open(path, "rb") as file:
        data = file.read(MAX_ATOMIC_FILE_SIZE + 1)
    if len(data) > MAX_ATOMIC_FILE_SIZE:
        raise OSError(f"file {path!r} exceeds max atomic compare size {MAX_ATOMIC_FILE_SIZE} bytes")
    return data


def ensure_atomic_parent_dir(dir: str, path: str) -> None:
    try:
        info = os.lstat(dir)
    except FileNotFoundError:
        try:
            os.makedirs(dir, 0o700)
        except OSError as exc:
            raise OSError(f"create parent directories for {path!r}: {exc}") from exc
        info = os.lstat(dir)
    except OSError as exc:
        raise OSError(f"stat parent directory for {path!r}: {exc}") from exc

    if stat.S_ISLNK(info.st_mode):
        raise OSError(f"refusing symlink parent directory {dir!r} for {path!r}")
    if not stat.S_ISDIR(info.st_mode):
        raise OSError(f"parent path {dir!r} for {path!r} is not a directory")
    if info.st_mode & 0o200 == 0:
        try:
            os.chmod(dir, 0o750)
        except OSError as exc:
            raise OSError(f"relax parent directory permissions for {path!r}: {exc}") from exc


def write_file_atomic(path: str, content: bytes, perm: int = 0o600) -> WriteResult:
    if perm == 0:
        perm = 0o600

    created = False
    try:
        existing = read_comparable_file(path)
    except FileNotFoundError:
        created = True
    except OSError as exc:
        raise OSError(f"read existing file {path!r}: {exc}") from exc
    else:
        if existing == content:
            return WriteResult(Changed=False, Created=False)

    dir = os.path.dirname(path)
    ensure_atomic_parent_dir(dir, path)

    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".dxrk-", suffix=".tmp", dir=dir)
    except OSError as exc:
        raise OSError(f"create temp file for {path!r}: {exc}") from exc

    cleanup = True
    try:
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(content)
                tmp.flush()
                os.fchmod(tmp.fileno(), perm)
                os.fsync(tmp.fileno())
        except OSError as exc:
            raise OSError(f"write temp file for {path!r}: {exc}") from exc

        try:
            os.rename(tmp_path, path)
        except OSError as exc:
            raise OSError(f"replace {path!r} atomically: {exc}") from exc

        # Sync the parent directory to flush the new directory entry to disk.
        # On Windows, NTFS returns ErrPermission when syncing a directory fd —
        # tolerate that specific error only. Any other error is still fatal.
        try:
            _sync_dir_fn(dir)
        except PermissionError as exc:
            if _runtime_goos != "win32":
                raise OSError(f"sync parent directory for {path!r}: {exc}") from exc
        except OSError as exc:
            raise OSError(f"sync parent directory for {path!r}: {exc}") from exc

        cleanup = False
        return WriteResult(Changed=True, Created=created)
    finally:
        if cleanup:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
