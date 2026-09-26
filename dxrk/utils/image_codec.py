# SPDX-License-Identifier: MIT
"""Image codecs: decode/encode, format detection for decoding, base64 helpers."""

from __future__ import annotations

import base64
import io
from typing import Any

from dxrk.utils.image_format import _PILLOW_REQUIRED as _PILLOW_REQUIRED
from dxrk.utils.image_format import Config, ErrUnsupportedFormat, Format, ImageType, _coerce_format, _PILImage


def decode(r: Any) -> ImageType:
    """Read and decode an image from a file-like object.

    Automatically detects the format (JPEG, PNG, GIF). Raises on error
    (returns ``(image, error)``).
    """
    if _PILImage is None:
        raise ImportError(_PILLOW_REQUIRED)
    img = _PILImage.open(r)
    img.load()
    return img


def decode_config(r: Any) -> tuple[Config, str]:
    """Read the image config (dimensions, color model) without decoding the full image.

    Mirrors ``DecodeConfig(r) (config, format, error)``; the
    format name (e.g. ``"jpeg"``) is the second element. Raises on error.
    """
    if _PILImage is None:
        raise ImportError(_PILLOW_REQUIRED)
    img = _PILImage.open(r)
    fmt = (img.format or "").lower()
    return Config(color_model=img.mode, width=img.width, height=img.height), fmt


def encode(w: io.IOBase, img: ImageType, fmt: Format | int, quality: int) -> None:
    """Write an image to a file-like object in the specified format (quality for JPEG)."""
    if _PILImage is None:
        raise ImportError(_PILLOW_REQUIRED)
    fmt = _coerce_format(fmt)
    if fmt is Format.JPEG:
        img.save(w, "JPEG", quality=quality)
    elif fmt is Format.PNG:
        img.save(w, "PNG")
    elif fmt is Format.GIF:
        img.save(w, "GIF")
    else:
        raise ErrUnsupportedFormat


def encode_to_bytes(img: ImageType, fmt: Format | int, quality: int) -> bytes:
    """Encode an image to bytes in the specified format. Raises on error."""
    buf = io.BytesIO()
    encode(buf, img, fmt, quality)
    return buf.getvalue()


def to_base64(img: ImageType, fmt: Format | int, quality: int) -> str:
    """Encode an image to a base64 string with data URI prefix."""
    data = encode_to_bytes(img, fmt, quality)
    mime_type = _coerce_format(fmt).mime()
    return "data:" + mime_type + ";base64," + base64.b64encode(data).decode("ascii")


def to_base64_raw(img: ImageType, fmt: Format | int, quality: int) -> str:
    """Encode an image to a raw base64 string (no data URI prefix)."""
    data = encode_to_bytes(img, fmt, quality)
    return base64.b64encode(data).decode("ascii")


def from_base64(s: str) -> tuple[ImageType, Format]:
    """Decode a base64 string to an image. Accepts raw base64 and data URI format."""
    # Strip data URI prefix if present.
    if s.startswith("data:"):
        # Find the comma separating metadata from data.
        comma_idx = s.find(",")
        if comma_idx >= 0:
            s = s[comma_idx + 1 :]
            data = base64.b64decode(s)
            return decode_format(data)

    # Raw base64.
    data = base64.b64decode(s)
    return decode_format(data)


def detect_format(data: bytes) -> Format:
    """Detect the image format from raw bytes. Mirrors image.DetectFormat."""
    if len(data) < 12:
        return Format.UNKNOWN

    # JPEG: FF D8 FF.
    if data[:3] == b"\xff\xd8\xff":
        return Format.JPEG

    # PNG: 89 50 4E 47 0D 0A 1A 0A.
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return Format.PNG

    # GIF: GIF87a or GIF89a.
    if data[:6] == b"GIF87a" or data[:6] == b"GIF89a":
        return Format.GIF

    # WebP: RIFF....WEBP.
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return Format.WEBP

    return Format.UNKNOWN


def detect_format_from_reader(r: io.IOBase) -> Format:
    """Detect the format from a seekable reader without consuming it entirely.

    Raises on read/seek errors (returns ``(Format, error)``).
    """
    header = r.read(12)
    r.seek(-len(header), io.SEEK_CUR)
    return detect_format(header)


def decode_format(data: bytes) -> tuple[ImageType, Format]:
    """Decode an image from bytes, detecting the format automatically.

    Mirrors the original: only JPEG/PNG/GIF decode; WebP (detected but not
    decodable) raises ErrUnsupportedFormat.
    """
    fmt = detect_format(data)
    if fmt is Format.UNKNOWN:
        raise ErrUnsupportedFormat
    if _PILImage is None:
        raise ImportError(_PILLOW_REQUIRED)
    if fmt is Format.WEBP:
        raise ErrUnsupportedFormat

    img = _PILImage.open(io.BytesIO(data))
    img.load()
    return img, fmt


def encode_format(img: ImageType, fmt: Format | int, quality: int) -> bytes:
    """Encode an image to bytes in the specified format. Raises on error."""
    buf = io.BytesIO()
    encode(buf, img, fmt, quality)
    return buf.getvalue()
