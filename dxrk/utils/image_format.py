# SPDX-License-Identifier: MIT
"""Image format model: Pillow bootstrap, format enum, errors, and config."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

try:  # pragma: no cover - exercised only when Pillow is absent
    from PIL import Image as _PILImage  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    _PILImage = None  # type: ignore[assignment]

# Type of a decoded image; Any because Pillow is an optional lazy dependency.
ImageType = Any

_PILLOW_REQUIRED = "image: Pillow (PIL) is required for this operation (install 'pillow' in the project environment)"

# Mirrors dxrk/strconst.StrPdf / dxrk/strconst.StrUnknown.
_STR_PDF = "%PDF-"
_STR_UNKNOWN = "unknown"


class Format(IntEnum):
    """Represents an image format type. Mirrors image.Format."""

    UNKNOWN = 0
    JPEG = 1
    PNG = 2
    GIF = 3
    WEBP = 4

    def string(self) -> str:
        """Return the format name. Mirrors Format.String()."""
        if self is Format.JPEG:
            return "jpeg"
        if self is Format.PNG:
            return "png"
        if self is Format.GIF:
            return "gif"
        if self is Format.WEBP:
            return "webp"
        return _STR_UNKNOWN

    def mime(self) -> str:
        """Return the MIME type for the format. Mirrors Format.MIME()."""
        if self is Format.JPEG:
            return "image/jpeg"
        if self is Format.PNG:
            return "image/png"
        if self is Format.GIF:
            return "image/gif"
        if self is Format.WEBP:
            return "image/webp"
        return "application/octet-stream"

    def extension(self) -> str:
        """Return the file extension for the format. Mirrors Format.Extension()."""
        if self is Format.JPEG:
            return ".jpg"
        if self is Format.PNG:
            return ".png"
        if self is Format.GIF:
            return ".gif"
        if self is Format.WEBP:
            return ".webp"
        return ".bin"


Unknown = Format.UNKNOWN
JPEG = Format.JPEG
PNG = Format.PNG
GIF = Format.GIF
WebP = Format.WEBP

SupportedFormats = [Format.JPEG, Format.PNG, Format.GIF, Format.WEBP]

SupportedMIMEs = {
    "image/jpeg": Format.JPEG,
    "image/jpg": Format.JPEG,
    "image/png": Format.PNG,
    "image/gif": Format.GIF,
    "image/webp": Format.WEBP,
}

SupportedExtensions = {
    ".jpg": Format.JPEG,
    ".jpeg": Format.JPEG,
    ".png": Format.PNG,
    ".gif": Format.GIF,
    ".webp": Format.WEBP,
}


class FormatError(Exception):
    """Represents a format-related error. Mirrors image.FormatError."""

    def __init__(self, msg: str) -> None:
        self.msg = msg

    def __str__(self) -> str:
        return "image: " + self.msg


ErrUnsupportedFormat = FormatError("unsupported format")


def _coerce_format(f: Format | int) -> Format:
    """Normalize an int to a Format, mapping unknown values to UNKNOWN."""
    if isinstance(f, Format):
        return f
    try:
        return Format(f)
    except ValueError:
        return Format.UNKNOWN


@dataclass(frozen=True)
class Config:
    """Image configuration (dimensions, color model). Mirrors image.Config."""

    color_model: str
    width: int
    height: int
