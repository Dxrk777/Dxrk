# SPDX-License-Identifier: MIT
"""Image upscaling backends for Dxrk Omni.

The default path is FFmpeg Lanczos + unsharp because it is deterministic and
available wherever the pipeline already runs. Optional backends:

* ``realesrgan``: the ``realesrgan-ncnn-vulkan`` binary, when installed.
* ``sdwebui``: AUTOMATIC1111 ``/sdapi/v1/extra-single-image``.
* ``comfyui``: native generation at the target resolution is preferred; the
  standalone upscale backend raises a clear error because it needs a user
  workflow with the right upscale nodes.

FFmpeg does not ship an ``HQ5x`` filter. Use Lanczos/unsharp, Real-ESRGAN,
ComfyUI, or SD WebUI for higher-quality upscaling.
"""

from __future__ import annotations

import base64
import logging
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("dxrk.omni.upscale")

DEFAULT_SDWEBUI_UPSCALER = "R-ESRGAN 4x+"


class UpscaleError(RuntimeError):
    """An image could not be upscaled."""


@dataclass(frozen=True, slots=True)
class Resolution:
    width: int
    height: int
    label: str = ""

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise UpscaleError("la resolución debe ser positiva")


@dataclass(frozen=True, slots=True)
class UpscaleConfig:
    enabled: bool = False
    backend: str = "none"
    model: str = ""
    sharpen: float = 0.0

    def __post_init__(self) -> None:
        if self.backend not in {"none", "ffmpeg", "realesrgan", "comfyui", "sdwebui", "auto"}:
            raise UpscaleError("backend de upscaling inválido")
        if self.sharpen < 0:
            raise UpscaleError("upscale_sharpen no puede ser negativo")


_ALIASES: dict[str, tuple[int, int]] = {
    "1080p": (1080, 1920),
    "fhd": (1080, 1920),
    "fullhd": (1080, 1920),
    "1440p": (1440, 2560),
    "2k": (1440, 2560),
    "4k": (2160, 3840),
    "2160p": (2160, 3840),
    "uhd": (2160, 3840),
}


def parse_resolution(label: str, orientation: str = "vertical") -> Resolution:
    """Parse ``1080p``, ``1440p``, ``4k``, or an explicit ``WxH`` label.

    Omni is vertical by default. ``1080p`` means 1080x1920, not 1920x1080.
    """
    raw = str(label).strip().lower().replace(" ", "")
    if not raw:
        raise UpscaleError("la resolución no puede estar vacía")
    if orientation not in {"vertical", "horizontal"}:
        raise UpscaleError("orientation debe ser vertical u horizontal")
    if raw in _ALIASES:
        width, height = _ALIASES[raw]
        return Resolution(width, height, raw)
    if "x" in raw:
        left, right = raw.split("x", 1)
        try:
            width, height = int(left), int(right)
        except ValueError as exc:
            raise UpscaleError(f"resolución inválida: {label!r}") from exc
        if width <= 0 or height <= 0:
            raise UpscaleError(f"resolución inválida: {label!r}")
        if orientation == "vertical" and width > height:
            width, height = height, width
        if orientation == "horizontal" and height > width:
            width, height = height, width
        return Resolution(width, height, raw)
    if raw.endswith("p") and raw[:-1].isdigit():
        short = int(raw[:-1])
        if short <= 0:
            raise UpscaleError(f"resolución inválida: {label!r}")
        if orientation == "vertical":
            return Resolution(short, round(short * 16 / 9), raw)
        return Resolution(round(short * 16 / 9), short, raw)
    if raw.isdigit():
        return parse_resolution(f"{raw}p", orientation)
    raise UpscaleError(f"resolución inválida: {label!r}")


def ffmpeg_upscale_filter(target: Resolution, sharpen: float = 0.0) -> str:
    base = f"scale={target.width}:{target.height}:flags=lanczos"
    if sharpen > 0:
        base += f",unsharp=5:5:{sharpen:.2f}:5:5:0.0"
    return base


def _run(cmd: Sequence[str], runner: Callable[[Sequence[str]], Any] | None) -> None:
    if runner is not None:
        runner(cmd)
        return
    try:
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise UpscaleError(f"no encontré el ejecutable {cmd[0]!r}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise UpscaleError(f"falló {cmd[0]}: {detail[:300]}") from exc
    if completed.returncode != 0:  # pragma: no cover - defensive
        raise UpscaleError(f"falló {cmd[0]}: {completed.stderr[:300]}")


def _image_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise UpscaleError("Pillow no está instalado") from exc
    try:
        with Image.open(path) as image:
            return image.size
    except OSError as exc:
        raise UpscaleError(f"no pude abrir la imagen {path}: {exc}") from exc


def _copy(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)
    return dest


def _fit_image(path: Path, target: Resolution) -> Path:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise UpscaleError("Pillow no está instalado") from exc
    try:
        with Image.open(path) as image:
            prepared = ImageOps.fit(
                image.convert("RGB"), (target.width, target.height), method=Image.Resampling.LANCZOS
            )
            if path.suffix.lower() == ".png":
                prepared.save(path, "PNG")
            else:
                prepared.save(path, "JPEG", quality=95)
    except OSError as exc:
        raise UpscaleError(f"no pude ajustar la imagen {path}: {exc}") from exc
    return path


def _ffmpeg_upscale(
    src: Path,
    dest: Path,
    target: Resolution,
    sharpen: float,
    runner: Callable[[Sequence[str]], Any] | None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        ffmpeg_upscale_filter(target, sharpen),
        "-q:v",
        "2",
        str(dest),
    ]
    _run(cmd, runner)
    return dest


def _realesrgan_upscale(
    src: Path,
    dest: Path,
    target: Resolution,
    model: str,
    runner: Callable[[Sequence[str]], Any] | None,
) -> Path:
    binary = shutil.which("realesrgan-ncnn-vulkan")
    if binary is None:
        raise UpscaleError("realesrgan-ncnn-vulkan no está instalado")
    src_width, _ = _image_size(src)
    scale = max(1, round(target.width / max(1, src_width)))
    temp = dest.with_name(f"{dest.stem}.upscale{dest.suffix}")
    cmd = [binary, "-i", str(src), "-o", str(temp), "-s", str(scale)]
    if model:
        cmd.extend(["-n", model])
    _run(cmd, runner)
    _ffmpeg_upscale(temp, dest, target, 0.0, runner)
    temp.unlink(missing_ok=True)
    return dest


def _sdwebui_upscale(
    src: Path,
    dest: Path,
    target: Resolution,
    model: str,
    client: httpx.Client | None,
    sdwebui_url: str,
    timeout: float,
) -> Path:
    src_width, _ = _image_size(src)
    payload = {
        "image": base64.b64encode(src.read_bytes()).decode("ascii"),
        "resize_mode": 0,
        "upscaling_resize": max(1.0, target.width / max(1, src_width)),
        "upscaler_1": model or DEFAULT_SDWEBUI_UPSCALER,
    }
    url = sdwebui_url.rstrip("/") + "/sdapi/v1/extra-single-image"
    try:
        if client is None:
            with httpx.Client(timeout=timeout) as owned:
                response = owned.post(url, json=payload)
        else:
            response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        image = data.get("image") if isinstance(data, dict) else None
        if not image:
            raise UpscaleError("SD WebUI no devolvió una imagen")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(image))
    except UpscaleError:
        raise
    except Exception as exc:
        raise UpscaleError(f"SD WebUI upscale failed: {exc}") from exc
    return _fit_image(dest, target)


def _comfyui_upscale() -> Path:
    raise UpscaleError(
        "el backend comfyui de upscaling necesita un workflow con nodos de upscale; "
        "usá --upscale auto/ffmpeg o generá directamente a la resolución objetivo"
    )


def upscale_image(
    src: Path,
    dest: Path,
    config: UpscaleConfig,
    *,
    target: Resolution | None = None,
    runner: Callable[[Sequence[str]], Any] | None = None,
    client: httpx.Client | None = None,
    comfyui_url: str = "http://127.0.0.1:8188",
    sdwebui_url: str = "http://127.0.0.1:7860",
    timeout: float = 300.0,
) -> Path:
    """Upscale ``src`` into ``dest``.

    When ``target`` is omitted, the source size is used and the function is a
    copy. ``auto`` uses Real-ESRGAN when the binary exists, otherwise FFmpeg.
    """
    src = Path(src)
    dest = Path(dest)
    if not config.enabled or config.backend == "none":
        return _copy(src, dest)
    src_width, src_height = _image_size(src)
    resolved_target = target or Resolution(src_width, src_height, "source")
    if src_width >= resolved_target.width and src_height >= resolved_target.height:
        return _copy(src, dest)
    backend = config.backend
    if backend == "auto":
        backend = "realesrgan" if shutil.which("realesrgan-ncnn-vulkan") else "ffmpeg"
    try:
        if backend == "ffmpeg":
            return _ffmpeg_upscale(src, dest, resolved_target, config.sharpen, runner)
        if backend == "realesrgan":
            return _realesrgan_upscale(src, dest, resolved_target, config.model, runner)
        if backend == "sdwebui":
            return _sdwebui_upscale(src, dest, resolved_target, config.model, client, sdwebui_url, timeout)
        if backend == "comfyui":
            _comfyui_upscale()
        return _copy(src, dest)  # pragma: no cover - defensive; comfyui always raises
    except UpscaleError:
        if config.backend == "auto" and backend != "ffmpeg":
            logger.warning("%s upscale failed; falling back to ffmpeg", backend)
            return _ffmpeg_upscale(src, dest, resolved_target, config.sharpen, runner)
        raise
