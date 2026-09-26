# SPDX-License-Identifier: MIT
"""Chainable image processor with math helpers for rotate/blur."""

from __future__ import annotations

import io
import os
import threading
from collections.abc import Callable

from dxrk.utils.image_format import _PILLOW_REQUIRED as _PILLOW_REQUIRED
from dxrk.utils.image_format import Format, ImageType, _PILImage
from dxrk.utils.image_format import _coerce_format as _coerce_format

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
