# SPDX-License-Identifier: MIT
"""Safe file reading with encoding detection and image loading."""

from __future__ import annotations

import base64
import io
import os
from dataclasses import dataclass, field
from datetime import datetime

from dxrk.utils.fileops_errors import ErrInvalidImage, FileopsError, ValidatePath

try:  # pragma: no cover - exercised only when Pillow is absent
    from PIL import Image as _PILImage  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    _PILImage = None  # type: ignore[assignment]

_PILLOW_REQUIRED = "fileops: Pillow (PIL) is required for this operation (install 'pillow' in the project environment)"

_MAX_TEXT_SIZE = 10 * 1024 * 1024
_READ_LIMIT_DEFAULT = 50 * 1024 * 1024
_BINARY_CHECK_SIZE = 8192


@dataclass
class FileContent:
    """Holds the result of reading a file. Mirrors fileops.FileContent."""

    path: str = ""
    content: str = ""
    encoding: str = ""
    size: int = 0
    mod_time: datetime = field(default_factory=datetime.now)
    line_count: int = 0


@dataclass
class ImageData:
    """Holds a file read as a base64-encoded image. Mirrors fileops.ImageData."""

    media_type: str = ""
    base64_data: str = ""
    width: int = 0
    height: int = 0


def DetectEncoding(data: bytes) -> str:
    """Inspect a byte slice and return a best-guess encoding label. Mirrors DetectEncoding."""
    if len(data) == 0:
        return "UTF-8"
    if len(data) >= 3 and data[0] == 0xEF and data[1] == 0xBB and data[2] == 0xBF:
        return "UTF-8-BOM"
    if len(data) >= 2:
        if data[0] == 0xFF and data[1] == 0xFE:
            return "UTF-16LE"
        if data[0] == 0xFE and data[1] == 0xFF:
            return "UTF-16BE"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is not None:
        for ch in text:
            if ord(ch) > 127:
                return "UTF-8"
        return "ASCII"
    latin1 = 0
    for b in data:
        if (0x20 <= b < 0x7F) or b >= 0xA0:
            latin1 += 1
    if latin1 / len(data) > 0.9:
        return "Latin-1"
    return "Unknown"


def IsBinary(path: str) -> tuple[bool, FileopsError | None]:
    """Detect whether a file is likely binary by inspecting the first bytes. Mirrors IsBinary."""
    try:
        with open(path, "rb") as f:
            buf = f.read(_BINARY_CHECK_SIZE)
    except OSError as e:
        return False, FileopsError(str(e))
    if b"\x00" in buf:
        return True, None
    non_text = 0
    for b in buf:
        if b < 0x09 or (b > 0x0D and b < 0x20):
            non_text += 1
    return non_text / max(len(buf), 1) > 0.1, None


def ReadFile(path: str) -> tuple[FileContent | None, FileopsError | None]:
    """Read a file, detect its encoding, and return a FileContent. Mirrors ReadFile."""
    err = ValidatePath(path)
    if err is not None:
        return None, err
    try:
        info = os.stat(path)
    except OSError as e:
        return None, FileopsError(str(e))
    if os.path.isdir(path):
        return None, FileopsError(f"fileops: {path} is a directory")
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return None, FileopsError(str(e))
    enc = DetectEncoding(data)
    content = data.decode("utf-8", errors="replace")
    lines = content.count("\n")
    if len(content) > 0 and content[-1] != "\n":
        lines += 1
    return (
        FileContent(
            path=path,
            content=content,
            encoding=enc,
            size=info.st_size,
            mod_time=datetime.fromtimestamp(info.st_mtime),
            line_count=lines,
        ),
        None,
    )


def ReadFileLines(path: str, offset: int, limit: int) -> tuple[list[str], int, FileopsError | None]:
    """Read a file and return lines[offset:offset+limit] plus the total count. Mirrors ReadFileLines."""
    fc, err = ReadFile(path)
    if err is not None or fc is None:
        return [], 0, err
    lines = fc.content.split("\n")
    total = len(lines)
    if offset < 0:
        offset = 0
    if offset >= total:
        return [], total, None
    end = offset + limit
    if limit <= 0 or end > total:
        end = total
    return lines[offset:end], total, None


def ReadImage(path: str) -> tuple[ImageData | None, FileopsError | None]:
    """Read an image file and return it as base64 data with dimensions. Mirrors ReadImage."""
    err = ValidatePath(path)
    if err is not None:
        return None, err
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return None, FileopsError(str(e))
    if _PILImage is None:
        raise ImportError(_PILLOW_REQUIRED)
    try:
        with _PILImage.open(io.BytesIO(data)) as img:
            width, height = img.size
    except Exception as e:  # noqa: BLE001 - any decode failure
        return None, FileopsError(f"{ErrInvalidImage}: {e}")
    media_type = "image/png"
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    elif ext == ".gif":
        media_type = "image/gif"
    return (
        ImageData(
            media_type=media_type,
            base64_data=base64.b64encode(data).decode("ascii"),
            width=width,
            height=height,
        ),
        None,
    )
