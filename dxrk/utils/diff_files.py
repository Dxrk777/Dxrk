# SPDX-License-Identifier: MIT

"""File-level diff: file and directory comparison with mode helpers."""

from __future__ import annotations

import os
import re
import stat as _stat
from dataclasses import dataclass, field
from enum import IntEnum

from dxrk.utils.diff_core import ComputeDiff as ComputeDiff
from dxrk.utils.diff_model import DefaultContextLines as DefaultContextLines
from dxrk.utils.diff_model import DiffHunk as DiffHunk
from dxrk.utils.diff_model import ErrFileNotFound as ErrFileNotFound
from dxrk.utils.diff_model import ErrNotDirectory as ErrNotDirectory


class DiffStatus(IntEnum):
    """Status of a file in a comparison. Mirrors filediff.DiffStatus."""

    UNCHANGED = 0
    MODIFIED = 1
    ADDED = 2
    REMOVED = 3

    def __str__(self) -> str:
        return {
            DiffStatus.UNCHANGED: "unchanged",
            DiffStatus.MODIFIED: "modified",
            DiffStatus.ADDED: "added",
            DiffStatus.REMOVED: "removed",
        }[self]


DiffStatusUnchanged = DiffStatus.UNCHANGED
DiffStatusModified = DiffStatus.MODIFIED
DiffStatusAdded = DiffStatus.ADDED
DiffStatusRemoved = DiffStatus.REMOVED


@dataclass
class FileDiff:
    """The result of comparing two files. Mirrors filediff.FileDiff."""

    old_path: str = ""
    new_path: str = ""
    status: DiffStatus = DiffStatus.UNCHANGED
    lines_added: int = 0
    lines_removed: int = 0
    hunks: list[DiffHunk] = field(default_factory=list)
    is_binary: bool = False


def CompareFiles(old_path: str, new_path: str) -> FileDiff:
    """Compare two files on disk. Mirrors CompareFiles."""
    return CompareFilesWithOptions(old_path, new_path)


def CompareFilesWithOptions(
    old_path: str,
    new_path: str,
    ignore_whitespace: bool = False,
    context_lines: int = DefaultContextLines,
) -> FileDiff:
    """Compare two files on disk with options. Mirrors CompareFilesWithOptions."""
    try:
        with open(old_path, "rb") as f:
            old_data = f.read()
    except OSError:
        raise ErrFileNotFound
    try:
        with open(new_path, "rb") as f:
            new_data = f.read()
    except OSError:
        raise ErrFileNotFound

    fd = FileDiff(old_path=old_path, new_path=new_path)
    if _looks_binary(old_data) or _looks_binary(new_data):
        fd.is_binary = True
        if old_data != new_data:
            fd.status = DiffStatusModified
        return fd

    old_text = old_data.decode("utf-8", errors="replace")
    new_text = new_data.decode("utf-8", errors="replace")
    if ignore_whitespace:
        old_text = _strip_whitespace(old_text)
        new_text = _strip_whitespace(new_text)
    result = ComputeDiff(old_text, new_text)
    fd.hunks = result.hunks
    fd.lines_added = result.stats.lines_added
    fd.lines_removed = result.stats.lines_removed
    if fd.lines_added or fd.lines_removed or result.stats.lines_changed:
        fd.status = DiffStatusModified
    return fd


def CompareDirectories(old_dir: str, new_dir: str) -> list[FileDiff]:
    """Compare two directories recursively. Mirrors CompareDirectories."""
    if not os.path.isdir(old_dir):
        raise ErrNotDirectory
    if not os.path.isdir(new_dir):
        raise ErrNotDirectory
    return _compare_dirs_recursive(old_dir, new_dir, "")


def SummarizeDirectory(directory: str) -> dict[str, str]:
    """Return a summary of files in a directory: path -> short hash. Mirrors SummarizeDirectory."""
    result: dict[str, str] = {}
    if not os.path.isdir(directory):
        return result
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(root, name)
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            rel = os.path.relpath(path, directory)
            result[rel] = _short_hash(data)
    return result


def _short_hash(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()[:12]


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _strip_whitespace(text: str) -> str:
    return "\n".join(re.sub(r"\s+", "", l) for l in text.split("\n"))


def _compare_dirs_recursive(old_dir: str, new_dir: str, rel: str) -> list[FileDiff]:
    results: list[FileDiff] = []
    old_entries = dict(_dir_entries(old_dir))
    new_entries = dict(_dir_entries(new_dir))

    for name, is_dir in sorted(old_entries.items()):
        old_path = os.path.join(old_dir, name)
        rel_path = os.path.join(rel, name)
        if name not in new_entries:
            if is_dir:
                results.extend(_removed_tree(old_path, rel_path))
            else:
                results.append(
                    FileDiff(old_path=rel_path, new_path="", status=DiffStatusRemoved)
                )
            continue
        new_path = os.path.join(new_dir, name)
        if is_dir:
            results.extend(_compare_dirs_recursive(old_path, new_path, rel_path))
        else:
            fd = CompareFiles(old_path, new_path)
            fd.old_path = rel_path
            fd.new_path = rel_path
            results.append(fd)

    for name, is_dir in sorted(new_entries.items()):
        if name not in old_entries:
            rel_path = os.path.join(rel, name)
            new_path = os.path.join(new_dir, name)
            if is_dir:
                results.extend(_added_tree(new_path, rel_path))
            else:
                results.append(
                    FileDiff(old_path="", new_path=rel_path, status=DiffStatusAdded)
                )
    return results


def _dir_entries(directory: str) -> list[tuple[str, bool]]:
    entries = []
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        entries.append((name, os.path.isdir(full)))
    return entries


def _removed_tree(directory: str, rel: str) -> list[FileDiff]:
    results = []
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        rel_path = os.path.join(rel, name)
        if os.path.isdir(full):
            results.extend(_removed_tree(full, rel_path))
        else:
            results.append(
                FileDiff(old_path=rel_path, new_path="", status=DiffStatusRemoved)
            )
    return results


def _added_tree(directory: str, rel: str) -> list[FileDiff]:
    results = []
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        rel_path = os.path.join(rel, name)
        if os.path.isdir(full):
            results.extend(_added_tree(full, rel_path))
        else:
            results.append(
                FileDiff(old_path="", new_path=rel_path, status=DiffStatusAdded)
            )
    return results


# --- helpers for symlink/file mode handling in directory diffs ---

def _file_mode(path: str) -> str:
    try:
        st = os.stat(path)
    except OSError:
        return ""
    return oct(_stat.S_IMODE(st.st_mode))
