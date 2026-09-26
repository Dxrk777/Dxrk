# SPDX-License-Identifier: MIT
"""Fileops error model and path validation."""

from __future__ import annotations

import os


class FileopsError(Exception):
    """Represents a fileops package error. Mirrors fileops error values."""

    def __init__(self, msg: str) -> None:
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


ErrNotAbsolute = FileopsError("fileops: path is not absolute")
ErrOutsideDir = FileopsError("fileops: path is outside allowed directory")
ErrPathTraversal = FileopsError("fileops: path contains traversal components")
ErrNullByte = FileopsError("fileops: path contains null byte")
ErrBinaryFile = FileopsError("fileops: file is binary")
ErrFileTooLarge = FileopsError("fileops: file exceeds read limit")
ErrInvalidImage = FileopsError("fileops: file is not a valid image")


def ValidatePath(path: str) -> FileopsError | None:
    """Check a file path for traversal attacks and null bytes. Mirrors ValidatePath."""
    if "\x00" in path:
        return ErrNullByte
    cleaned = os.path.normpath(path)
    for part in cleaned.split(os.sep):
        if part == "..":
            return ErrPathTraversal
    return None
