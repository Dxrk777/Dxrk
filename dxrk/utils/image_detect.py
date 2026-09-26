# SPDX-License-Identifier: MIT
"""Image format/mime/extension mapping plus dimension and color introspection."""

from __future__ import annotations

import io
import mimetypes
import os

from dxrk.utils.image_codec import detect_format, detect_format_from_reader
from dxrk.utils.image_format import Format, ImageType, SupportedExtensions, SupportedFormats, SupportedMIMEs
from dxrk.utils.image_format import _coerce_format as _coerce_format


def format_from_extension(ext: str) -> Format:
    """Return the format for a file extension. Mirrors image.FormatFromExtension."""
    ext = ext.lower()
    if not ext.startswith("."):
        ext = "." + ext
    return SupportedExtensions.get(ext, Format.UNKNOWN)


def format_from_mime(mime: str) -> Format:
    """Return the format for a MIME type. Mirrors image.FormatFromMIME."""
    return SupportedMIMEs.get(mime.lower(), Format.UNKNOWN)


def is_supported_format(fmt: Format | int) -> bool:
    """Check if a format is supported."""
    fmt = _coerce_format(fmt)
    return fmt in SupportedFormats


def detect_mime(data: bytes) -> str:
    """Detect the MIME type from raw image bytes. Mirrors image.DetectMIME."""
    return detect_format(data).mime()


def detect_mime_from_reader(r: io.IOBase) -> str:
    """Detect the MIME type from a seekable reader. Raises on read/seek errors."""
    fmt = detect_format_from_reader(r)
    return fmt.mime()


def get_dimensions(img: ImageType) -> tuple[int, int]:
    """Return the width and height of an image. Mirrors image.GetDimensions."""
    width, height = img.size
    return (int(width), int(height))


def get_bounds(img: ImageType) -> tuple[int, int, int, int]:
    """Return the bounds rectangle (x0, y0, x1, y1). Mirrors image.GetBounds."""
    w, h = img.size
    return (0, 0, w, h)


def get_color_model(img: ImageType) -> str:
    """Return the color model of an image (PIL mode string). Mirrors image.GetColorModel."""
    return str(img.mode)


def mime_from_extension(filename: str) -> str:
    """Return the MIME type for a file extension. Mirrors image.MIMEFromExtension."""
    ext = os.path.splitext(filename)[1].lower()
    mime_type, _ = mimetypes.guess_type("file" + ext)
    return mime_type or ""


def extension_from_mime(mime_type: str) -> str:
    """Return the file extension for a MIME type. Mirrors image.ExtensionFromMIME."""
    exts = mimetypes.guess_all_extensions(mime_type)
    if exts:
        return exts[0]
    return ""
