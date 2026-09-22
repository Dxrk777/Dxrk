# SPDX-License-Identifier: MIT

"""Diff model: errors, sentinels, types, lines, hunks, stats, and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class DiffError(Exception):
    """Represents a diff package error. Mirrors diff error values."""

    def __init__(self, msg: str) -> None:
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


ErrFileNotFound = DiffError("file not found")
ErrNotDirectory = DiffError("not a directory")
ErrPatchInvalid = DiffError("patch is invalid")
ErrContextMismatch = DiffError("context mismatch")
ErrPatchConflict = DiffError("patch conflict")
ErrPatchEmpty = DiffError("patch has no hunks")


class DiffType(IntEnum):
    """Represents the type of a diff line. Mirrors diff.DiffType."""

    EQUAL = 0
    INSERT = 1
    DELETE = 2
    MODIFY = 3

    def __str__(self) -> str:
        return self.name.lower()


DiffEqual = DiffType.EQUAL
DiffInsert = DiffType.INSERT
DiffDelete = DiffType.DELETE
DiffModify = DiffType.MODIFY


@dataclass
class DiffLine:
    """A single line in a diff. Mirrors diff.DiffLine."""

    type: DiffType = DiffEqual
    line_num_old: int = 0
    line_num_new: int = 0
    content: str = ""


@dataclass
class DiffHunk:
    """A group of related changes. Mirrors diff.DiffHunk."""

    old_start: int = 0
    old_count: int = 0
    new_start: int = 0
    new_count: int = 0
    lines: list[DiffLine] = field(default_factory=list)
    context: str = ""


@dataclass
class DiffStats:
    """Summary statistics for a diff. Mirrors diff.DiffStats."""

    lines_added: int = 0
    lines_removed: int = 0
    lines_changed: int = 0
    total_lines: int = 0


@dataclass
class DiffResult:
    """The complete diff between two texts. Mirrors diff.DiffResult."""

    hunks: list[DiffHunk] = field(default_factory=list)
    stats: DiffStats = field(default_factory=DiffStats)


DefaultContextLines = 3


@dataclass
class _Op:
    """A single LCS operation."""

    typ: DiffType
    old_idx: int
    new_idx: int
