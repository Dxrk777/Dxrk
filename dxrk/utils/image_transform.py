# SPDX-License-Identifier: MIT
"""Image transforms: resize, crop, and color-model conversion."""

from __future__ import annotations

from dxrk.utils.image_format import _PILLOW_REQUIRED as _PILLOW_REQUIRED
from dxrk.utils.image_format import Format, ImageType, _PILImage
from dxrk.utils.image_format import _coerce_format as _coerce_format


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
