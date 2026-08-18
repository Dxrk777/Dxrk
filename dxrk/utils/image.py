# SPDX-License-Identifier: MIT
"""Image and PDF processing utilities.

Provides image format detection, decoding, encoding, resizing, format
conversion, base64 handling, an LRU image cache, a chainable image
processor, and basic (naive byte-scanning) PDF text extraction and
metadata reading.

Python's standard library has
no image codecs, so the codec operations (decode, encode, resize, ...)
lazily require Pillow (PIL). When Pillow is not installed those
functions raise ``ImportError``; format detection, MIME mapping,
caching, the processor math and all PDF helpers work without it.
"""

from __future__ import annotations

import base64
import io
import mimetypes
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
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


class PDFError(Exception):
    """Base class for PDF-related errors."""


ErrNotPDF = PDFError("not a valid PDF file")
ErrPDFEncrypted = PDFError("PDF is encrypted")
ErrPageNotFound = PDFError("page not found")


@dataclass(frozen=True)
class Config:
    """Image configuration (dimensions, color model). Mirrors image.Config."""

    color_model: str
    width: int
    height: int


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


def resize(img: ImageType, width: int, height: int) -> ImageType:
    """Resize an image to the specified width and height using bilinear interpolation.

    If either width or height is 0, the aspect ratio is preserved.
    """
    if _PILImage is None:
        raise ImportError(_PILLOW_REQUIRED)
    src_w, src_h = img.size

    if width <= 0 and height <= 0:
        return img

    if width <= 0:
        width = src_w * height // src_h
    if height <= 0:
        height = src_h * width // src_w

    if width == src_w and height == src_h:
        return img

    dst = _PILImage.new("RGBA", (width, height))
    _scale_bilinear(dst, img)
    return dst


def _scale_bilinear(dst: ImageType, src: ImageType) -> None:
    """Perform bilinear interpolation scaling. Mirrors image.scaleBilinear."""
    src = src.convert("RGBA") if src.mode != "RGBA" else src
    src_w, src_h = src.size
    dst_w, dst_h = dst.size

    x_ratio = src_w / dst_w
    y_ratio = src_h / dst_h

    spx = src.load()
    dpx = dst.load()
    for y in range(dst_h):
        for x in range(dst_w):
            src_x = x * x_ratio
            src_y = y * y_ratio
            x0 = int(src_x)
            y0 = int(src_y)
            x1 = min(x0 + 1, src_w - 1)
            y1 = min(y0 + 1, src_h - 1)

            dx = src_x - x0
            dy = src_y - y0

            c00 = spx[x0, y0]
            c10 = spx[x1, y0]
            c01 = spx[x0, y1]
            c11 = spx[x1, y1]

            r00, g00, b00, a00 = (v * 257 for v in c00)
            r10, g10, b10, a10 = (v * 257 for v in c10)
            r01, g01, b01, a01 = (v * 257 for v in c01)
            r11, g11, b11, a11 = (v * 257 for v in c11)

            # Bilinear interpolation (16-bit values, then >>8).
            r = r00 * (1 - dx) * (1 - dy) + r10 * dx * (1 - dy) + r01 * (1 - dx) * dy + r11 * dx * dy
            g = g00 * (1 - dx) * (1 - dy) + g10 * dx * (1 - dy) + g01 * (1 - dx) * dy + g11 * dx * dy
            b = b00 * (1 - dx) * (1 - dy) + b10 * dx * (1 - dy) + b01 * (1 - dx) * dy + b11 * dx * dy
            a = a00 * (1 - dx) * (1 - dy) + a10 * dx * (1 - dy) + a01 * (1 - dx) * dy + a11 * dx * dy

            dpx[x, y] = (int(r) >> 8, int(g) >> 8, int(b) >> 8, int(a) >> 8)


def resize_fit(img: ImageType, max_width: int, max_height: int) -> ImageType:
    """Resize an image to fit within the specified dimensions, preserving aspect ratio."""
    src_w, src_h = img.size

    ratio_w = max_width / src_w
    ratio_h = max_height / src_h
    ratio = ratio_w
    ratio = min(ratio, ratio_h)

    if ratio >= 1.0:
        return img

    new_w = int(src_w * ratio)
    new_h = int(src_h * ratio)
    return resize(img, new_w, new_h)


def resize_fill(img: ImageType, width: int, height: int) -> ImageType:
    """Resize an image to fill the specified dimensions, cropping if necessary."""
    src_w, src_h = img.size

    ratio_w = width / src_w
    ratio_h = height / src_h
    ratio = ratio_w
    ratio = max(ratio, ratio_h)

    new_w = int(src_w * ratio)
    new_h = int(src_h * ratio)

    resized = resize(img, new_w, new_h)

    # Crop to exact dimensions.
    x = (new_w - width) // 2
    y = (new_h - height) // 2
    return crop(resized, x, y, width, height)


def crop(img: ImageType, x: int, y: int, width: int, height: int) -> ImageType:
    """Crop an image to the specified rectangle (x, y, x+width, y+height)."""
    if _PILImage is None:
        raise ImportError(_PILLOW_REQUIRED)
    return img.crop((x, y, x + width, y + height))


def convert(img: ImageType, target: Format | int) -> ImageType:
    """Convert an image to a different format (color model).

    Currently supports conversion to RGBA, NRGBA, Paletted.
    """
    target = _coerce_format(target)
    if target is Format.JPEG:
        # JPEG typically uses YCbCr, but we return RGBA for further processing.
        return to_rgba(img)
    if target is Format.PNG:
        return to_nrgba(img)
    if target is Format.GIF:
        return to_paletted(img)
    return to_rgba(img)


def to_rgba(img: ImageType) -> ImageType:
    """Convert any image to RGBA. Mirrors image.ToRGBA."""
    if _PILImage is None:
        raise ImportError(_PILLOW_REQUIRED)
    if img.mode == "RGBA":
        return img
    return img.convert("RGBA")


def to_nrgba(img: ImageType) -> ImageType:
    """Convert any image to NRGBA (non-premultiplied alpha).

    PIL's RGBA mode is non-premultiplied (NRGBA-style).
    """
    if _PILImage is None:
        raise ImportError(_PILLOW_REQUIRED)
    if img.mode == "RGBA":
        return img
    return img.convert("RGBA")


def to_paletted(img: ImageType) -> ImageType:
    """Convert any image to paletted (P mode, for GIF).

    A nil palette would allocate; this implementation uses an adaptive palette
    instead (deviation, produces a usable GIF).
    """
    if _PILImage is None:
        raise ImportError(_PILLOW_REQUIRED)
    if img.mode == "P":
        return img
    return img.convert("P", palette=_PILImage.ADAPTIVE)  # type: ignore[attr-defined]


def to_grayscale(img: ImageType) -> ImageType:
    """Convert an image to grayscale. Mirrors image.ToGrayscale."""
    if _PILImage is None:
        raise ImportError(_PILLOW_REQUIRED)
    if img.mode == "L":
        return img
    return img.convert("L")


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


@dataclass
class CacheEntry:
    """A cached image entry. Mirrors image.CacheEntry."""

    data: bytes
    format: Format
    width: int
    height: int
    created_at: datetime
    accessed_at: datetime
    access_count: int


@dataclass
class CacheStats:
    """Image cache statistics. Mirrors image.CacheStats."""

    entry_count: int
    total_size: int
    max_size: int
    max_age: timedelta


class ImageCache:
    """A size-bounded, time-expiring image cache. Mirrors image.ImageCache."""

    def __init__(self, max_size: int = 100, max_age: timedelta | None = None) -> None:
        if max_size <= 0:
            max_size = 100
        if max_age is None or max_age <= timedelta(0):
            max_age = timedelta(hours=24)
        self._entries: dict[str, CacheEntry] = {}
        self._mu = threading.RLock()
        self._max_size = max_size
        self._max_age = max_age
        self._current_size = 0

    def get(self, key: str) -> tuple[bytes | None, Format, int, int, bool]:
        """Return the cached entry for key as (data, format, width, height, ok).

        Expired entries are treated as misses (not removed).
        """
        with self._mu:
            entry = self._entries.get(key)
            if entry is None:
                return None, Format.UNKNOWN, 0, 0, False

            if datetime.now() - entry.created_at > self._max_age:  # noqa: DTZ005 - naive local clock
                return None, Format.UNKNOWN, 0, 0, False

            entry.accessed_at = datetime.now()  # noqa: DTZ005 - naive local clock
            entry.access_count += 1
            return entry.data, entry.format, entry.width, entry.height, True

    def set(self, key: str, data: bytes, format: Format | int, width: int, height: int) -> None:
        """Store an entry, evicting the least-recently-used entry when full."""
        with self._mu:
            if len(self._entries) >= self._max_size:
                self._evict_lru()

            self._entries[key] = CacheEntry(
                data=data,
                format=_coerce_format(format),
                width=width,
                height=height,
                created_at=datetime.now(),  # noqa: DTZ005 - naive local clock
                accessed_at=datetime.now(),  # noqa: DTZ005 - naive local clock
                access_count=1,
            )
            self._current_size += len(data)

    def delete(self, key: str) -> bool:
        """Delete an entry; returns True if it existed."""
        with self._mu:
            entry = self._entries.get(key)
            if entry is None:
                return False
            self._current_size -= len(entry.data)
            del self._entries[key]
            return True

    def clear(self) -> None:
        """Remove all entries."""
        with self._mu:
            self._entries = {}
            self._current_size = 0

    def _evict_lru(self) -> None:
        """Evict the entry with the oldest AccessedAt."""
        oldest_key = ""
        oldest_time: datetime | None = None
        for key, entry in self._entries.items():
            if oldest_key == "" or oldest_time is None or entry.accessed_at < oldest_time:
                oldest_key = key
                oldest_time = entry.accessed_at
        if oldest_key != "":
            self._current_size -= len(self._entries[oldest_key].data)
            del self._entries[oldest_key]

    def stats(self) -> CacheStats:
        """Return cache statistics."""
        with self._mu:
            return CacheStats(
                entry_count=len(self._entries),
                total_size=self._current_size,
                max_size=self._max_size,
                max_age=self._max_age,
            )

    def keys(self) -> list[str]:
        """Return all cached keys."""
        with self._mu:
            return list(self._entries.keys())

    def prune_expired(self) -> int:
        """Remove expired entries; returns the number removed."""
        with self._mu:
            now = datetime.now()  # noqa: DTZ005 - naive local clock
            count = 0
            for key, entry in list(self._entries.items()):
                if now - entry.created_at > self._max_age:
                    self._current_size -= len(entry.data)
                    del self._entries[key]
                    count += 1
            return count


Operation = Callable[["ImageProcessor"], None]


class ImageProcessor:
    """A chainable image processor. Mirrors image.ImageProcessor.

    Default quality is 85. All mutating operations return self.
    """

    def __init__(self, img: ImageType, format: Format | int) -> None:
        self._img = img
        self._format = _coerce_format(format)
        self._quality = 85
        self._mu = threading.Lock()

    def resize(self, width: int, height: int) -> ImageProcessor:
        """Resize using nearest-neighbor sampling."""
        with self._mu:
            if self._img is None:
                return self
            if _PILImage is None:
                raise ImportError(_PILLOW_REQUIRED)
            src_w, src_h = self._img.size
            new_img = _PILImage.new("RGBA", (width, height))
            src = self._img.convert("RGBA") if self._img.mode != "RGBA" else self._img
            spx = src.load()
            dpx = new_img.load()
            for y in range(height):
                for x in range(width):
                    src_x = x * src_w // width
                    src_y = y * src_h // height
                    dpx[x, y] = spx[src_x, src_y]  # type: ignore[index]
            self._img = new_img
            return self

    def crop(self, x: int, y: int, width: int, height: int) -> ImageProcessor:
        """Crop to the rectangle (x, y, x+width, y+height)."""
        with self._mu:
            if self._img is None:
                return self
            if _PILImage is None:
                raise ImportError(_PILLOW_REQUIRED)
            self._img = self._img.crop((x, y, x + width, y + height))
            return self

    def rotate(self, angle: float) -> ImageProcessor:
        """Rotate by the given angle (radians).

        Mirrors the original, including its Taylor-series cos/sin approximations.
        """
        with self._mu:
            if self._img is None:
                return self
            if _PILImage is None:
                raise ImportError(_PILLOW_REQUIRED)
            w, h = self._img.size
            center_x = w / 2
            center_y = h / 2
            cos_a = _cos(angle)
            sin_a = _sin(angle)
            new_img = _PILImage.new("RGBA", (w, h))
            src = self._img.convert("RGBA") if self._img.mode != "RGBA" else self._img
            spx = src.load()
            dpx = new_img.load()
            for y in range(h):
                for x in range(w):
                    dx = x - center_x
                    dy = y - center_y
                    src_x = int(dx * cos_a - dy * sin_a + center_x)
                    src_y = int(dx * sin_a + dy * cos_a + center_y)
                    if 0 <= src_x < w and 0 <= src_y < h:
                        dpx[x, y] = spx[src_x, src_y]  # type: ignore[index]
            self._img = new_img
            return self

    def set_quality(self, q: int) -> ImageProcessor:
        """Clamp and set the encode quality (1..100)."""
        with self._mu:
            q = max(q, 1)
            q = min(q, 100)
            self._quality = q
            return self

    def set_format(self, f: Format | int) -> ImageProcessor:
        """Set the encode format."""
        with self._mu:
            self._format = _coerce_format(f)
            return self

    def grayscale(self) -> ImageProcessor:
        """Convert to grayscale."""
        with self._mu:
            if self._img is None:
                return self
            if _PILImage is None:
                raise ImportError(_PILLOW_REQUIRED)
            self._img = self._img.convert("L")
            return self

    def blur(self, radius: int) -> ImageProcessor:
        """Apply a Gaussian blur with the given radius."""
        with self._mu:
            if self._img is None or radius <= 0:
                return self
            if _PILImage is None:
                raise ImportError(_PILLOW_REQUIRED)
            w, h = self._img.size
            blurred = _PILImage.new("RGBA", (w, h))
            kernel = _gaussian_kernel(radius)
            src = self._img.convert("RGBA") if self._img.mode != "RGBA" else self._img
            spx = src.load()
            dpx = blurred.load()
            for y in range(h):
                for x in range(w):
                    r = 0.0
                    g = 0.0
                    b = 0.0
                    a = 0.0
                    weight_sum = 0.0
                    for ky in range(-radius, radius + 1):
                        for kx in range(-radius, radius + 1):
                            px = x + kx
                            py = y + ky
                            if 0 <= px < w and 0 <= py < h:
                                cr, cg, cb, ca = spx[px, py]  # type: ignore[index]
                                weight = kernel[ky + radius][kx + radius]
                                r += cr * weight
                                g += cg * weight
                                b += cb * weight
                                a += ca * weight
                                weight_sum += weight
                    if weight_sum > 0:
                        dpx[x, y] = (  # type: ignore[index]
                            int(r / weight_sum) >> 8,
                            int(g / weight_sum) >> 8,
                            int(b / weight_sum) >> 8,
                            int(a / weight_sum) >> 8,
                        )
            self._img = blurred
            return self

    def encode(self) -> bytes:
        """Encode the current image to bytes. Raises on error."""
        with self._mu:
            if self._img is None:
                raise ValueError("no image to encode")
            if _PILImage is None:
                raise ImportError(_PILLOW_REQUIRED)
            buf = io.BytesIO()
            if self._format is Format.JPEG:
                self._img.save(buf, "JPEG", quality=self._quality)
            elif self._format is Format.PNG:
                self._img.save(buf, "PNG")
            else:
                raise ValueError(f"unsupported format: {self._format.string()}")
            return buf.getvalue()

    def save(self, path: str) -> None:
        """Encode and write the image to path with 0644 permissions."""
        data = self.encode()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)

    def image(self) -> ImageType:
        """Return the current image."""
        with self._mu:
            return self._img


def _cos(angle: float) -> float:
    """Cosine approximation: 1 - a^2/2 + a^4/24."""
    return 1 - angle * angle / 2 + angle * angle * angle * angle / 24


def _sin(angle: float) -> float:
    """Sine approximation: a - a^3/6."""
    return angle - angle * angle * angle / 6


def _gaussian_kernel(radius: int) -> list[list[float]]:
    """Build a normalized Gaussian kernel. Mirrors image.gaussianKernel."""
    size = 2 * radius + 1
    kernel = [[0.0] * size for _ in range(size)]
    sigma = radius / 3.0
    total = 0.0
    for i in range(size):
        for j in range(size):
            x = float(i - radius)
            y = float(j - radius)
            val = _exp(-(x * x + y * y) / (2 * sigma * sigma))
            kernel[i][j] = val
            total += val
    for i in range(size):
        for j in range(size):
            kernel[i][j] /= total
    return kernel


def _exp(x: float) -> float:
    """Exponential approximation: 20-term Taylor series."""
    result = 1.0
    term = 1.0
    for i in range(1, 20):
        term *= x / float(i)
        result += term
    return result


# ---------------------------------------------------------------------------
# PDF helpers (naive byte scanning, mirroring image/pdf.go)
# ---------------------------------------------------------------------------


@dataclass
class PDFMetadata:
    """PDF metadata. Mirrors image.PDFMetadata."""

    title: str = ""
    author: str = ""
    subject: str = ""
    creator: str = ""
    producer: str = ""
    creation_date: str = ""
    mod_date: str = ""
    pages: int = 0


def _read_all(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def extract_text(path: str) -> str:
    """Extract text from a PDF by scanning raw stream content."""
    data = _read_all(path)

    if len(data) < 5 or data[:5] != _STR_PDF.encode("ascii"):
        raise ErrNotPDF

    return _extract_text_from_bytes(data)


def _extract_text_from_bytes(data: bytes) -> str:
    text = io.StringIO()
    in_stream = False
    stream_start = 0

    for i in range(len(data) - 1):
        if data[i] == ord("s") and data[i + 1] == ord("t") and i + 5 < len(data) and data[i : i + 6] == b"stream":
            in_stream = True
            stream_start = i + 6
            if stream_start < len(data) and data[stream_start] == ord("\r"):
                stream_start += 1
            if stream_start < len(data) and data[stream_start] == ord("\n"):
                stream_start += 1
        elif (
            in_stream
            and data[i] == ord("e")
            and data[i + 1] == ord("n")
            and i + 8 < len(data)
            and data[i : i + 9] == b"endstream"
        ):
            stream_data = data[stream_start:i]
            decoded = _decode_stream(stream_data)
            text.write(decoded)
            in_stream = False

    return text.getvalue()


def _decode_stream(data: bytes) -> str:
    """Decode PDF literal string escapes within a stream. Mirrors image.decodeStream."""
    result = bytearray()
    i = 0
    while i < len(data):
        if data[i] == ord("\\") and i + 1 < len(data):
            nxt = data[i + 1]
            if nxt == ord("n"):
                result.append(ord("\n"))
            elif nxt == ord("r"):
                result.append(ord("\r"))
            elif nxt == ord("t"):
                result.append(ord("\t"))
            elif nxt == ord("("):
                result.append(ord("("))
            elif nxt == ord(")"):
                result.append(ord(")"))
            elif nxt == ord("\\"):
                result.append(ord("\\"))
            else:
                if i + 3 < len(data) and _is_octal(data[i + 1]) and _is_octal(data[i + 2]) and _is_octal(data[i + 3]):
                    val = ((data[i + 1] - ord("0")) << 6) | ((data[i + 2] - ord("0")) << 3) | (data[i + 3] - ord("0"))
                    result.append(val & 0xFF)
                    i += 2
                else:
                    result.append(data[i + 1])
            i += 2
        elif 32 <= data[i] <= 126:
            result.append(data[i])
            i += 1
        else:
            i += 1
    return result.decode("latin-1")


def _is_octal(b: int) -> bool:
    return ord("0") <= b <= ord("7")


def get_page_count(path: str) -> int:
    """Return the max "/Count N" value found in a PDF."""
    data = _read_all(path)

    if len(data) < 5 or data[:5] != _STR_PDF.encode("ascii"):
        raise ErrNotPDF

    count = 0
    for i in range(len(data) - 7):
        if data[i : i + 7] == b"/Count ":
            j = i + 7
            while j < len(data) and ord("0") <= data[j] <= ord("9"):
                j += 1
            if j > i + 7:
                c = int(data[i + 7 : j])
                count = max(count, c)
    return count


def get_metadata(path: str) -> PDFMetadata:
    """Extract basic metadata from a PDF (title, author, subject, ...)."""
    meta = PDFMetadata()
    data = _read_all(path)

    if len(data) < 5 or data[:5] != _STR_PDF.encode("ascii"):
        raise ErrNotPDF

    meta.pages, _ = _page_count_from_bytes(data)

    fields = {
        "/Title": "title",
        "/Author": "author",
        "/Subject": "subject",
        "/Creator": "creator",
        "/Producer": "producer",
        "/CreationDate": "creation_date",
        "/ModDate": "mod_date",
    }

    for field, attr in fields.items():
        idx = _find_field(data, field)
        if idx >= 0:
            start = data.find(b"(", idx + len(field))
            if start >= 0:
                end = _find_end_of_string(data, start)
                if end > start:
                    setattr(meta, attr, data[start : end + 1].decode("latin-1"))

    return meta


def _page_count_from_bytes(data: bytes) -> tuple[int, Exception | None]:
    """GetPageCount over raw bytes; returns (count, error-or-None)."""
    try:
        return get_page_count(_bytes_to_temp(data)), None
    except Exception as exc:  # noqa: BLE001 - defer/recover style cleanup in GetMetadata
        return 0, exc


def _bytes_to_temp(data: bytes) -> str:
    """Write bytes to a temp file and return its path (for parity re-reads)."""
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


def _find_field(data: bytes, field: str) -> int:
    field_bytes = field.encode("ascii")
    for i in range(len(data) - len(field_bytes) + 1):
        if data[i : i + len(field_bytes)] == field_bytes:
            return i
    return -1


def _find_end_of_string(data: bytes, start: int) -> int:
    paren = 0
    in_string = False
    for i in range(start, len(data)):
        if data[i] == ord("(") and (i == start or data[i - 1] != ord("\\")):
            if not in_string:
                in_string = True
                continue
            paren += 1
        elif data[i] == ord(")") and (i == 0 or data[i - 1] != ord("\\")):
            if paren > 0:
                paren -= 1
            elif in_string:
                return i
    return -1


def render_page(path: str, page_num: int, dpi: int) -> bytes:
    """Not implemented (requires an external library)."""
    raise ValueError("PDF rendering not implemented (requires external library)")


def extract_images(path: str) -> list[bytes]:
    """Not implemented (requires an external library)."""
    raise ValueError("PDF image extraction not implemented (requires external library)")


def is_pdf_encrypted(path: str) -> bool:
    """Return True if the PDF contains an /Encrypt entry."""
    data = _read_all(path)

    if len(data) < 5 or data[:5] != _STR_PDF.encode("ascii"):
        raise ErrNotPDF

    for i in range(len(data) - 8):
        if data[i : i + 9] == b"/Encrypt ":
            return True
    return False


def validate_pdf(path: str) -> None:
    """Validate that a PDF has an %%EOF marker. Raises ErrNotPDF or ValueError."""
    data = _read_all(path)

    if len(data) < 5 or data[:5] != _STR_PDF.encode("ascii"):
        raise ErrNotPDF

    if _has_eof_marker(data):
        return

    raise ValueError("PDF missing EOF marker (possibly truncated)")


def _has_eof_marker(data: bytes) -> bool:
    start = max(0, len(data) - 1024)
    for i in range(start, len(data)):
        if i + 5 <= len(data) and data[i : i + 5] == b"%%EOF":
            return True
    return False


def get_pdf_version(path: str) -> str:
    """Return the PDF header version (e.g. "1.4")."""
    with open(path, "rb") as f:
        header = f.read(8)

    if len(header) >= 8 and header[:5] == _STR_PDF.encode("ascii"):
        return header[5:8].decode("ascii")
    raise ErrNotPDF


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------

Decode = decode
DecodeConfig = decode_config
Encode = encode
EncodeToBytes = encode_to_bytes
Resize = resize
ResizeFit = resize_fit
ResizeFill = resize_fill
Crop = crop
Convert = convert
ToRGBA = to_rgba
ToNRGBA = to_nrgba
ToPaletted = to_paletted
ToGrayscale = to_grayscale
ToBase64 = to_base64
ToBase64Raw = to_base64_raw
FromBase64 = from_base64
DetectMIME = detect_mime
DetectMIMEFromReader = detect_mime_from_reader
GetDimensions = get_dimensions
GetBounds = get_bounds
GetColorModel = get_color_model
MIMEFromExtension = mime_from_extension
ExtensionFromMIME = extension_from_mime
DetectFormat = detect_format
DetectFormatFromReader = detect_format_from_reader
DecodeFormat = decode_format
EncodeFormat = encode_format
FormatFromExtension = format_from_extension
FormatFromMIME = format_from_mime
IsSupportedFormat = is_supported_format
ExtractText = extract_text
GetPageCount = get_page_count
GetMetadata = get_metadata
RenderPage = render_page
ExtractImages = extract_images
IsPDFEncrypted = is_pdf_encrypted
ValidatePDF = validate_pdf
GetPDFVersion = get_pdf_version
NewImageCache = ImageCache
NewProcessor = ImageProcessor
