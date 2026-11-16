# SPDX-License-Identifier: MIT
"""Tests for resolution parsing and image upscaling backends."""

from __future__ import annotations

import base64
import subprocess
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from scripts.omni_media import upscale


def _png_bytes(size: tuple[int, int] = (32, 32), color=(10, 200, 180)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _image(path: Path, size: tuple[int, int] = (32, 32)) -> Path:
    path.write_bytes(_png_bytes(size))
    return path


def _write_runner(commands: list[list[str]]):
    def run(cmd) -> None:
        commands.append(list(cmd))
        target = Path(cmd[-1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_png_bytes())

    return run


def test_resolution_and_config_validation() -> None:
    with pytest.raises(upscale.UpscaleError, match="positiva"):
        upscale.Resolution(0, 10)
    with pytest.raises(upscale.UpscaleError, match="backend"):
        upscale.UpscaleConfig(backend="bad")
    with pytest.raises(upscale.UpscaleError, match="sharpen"):
        upscale.UpscaleConfig(sharpen=-1)
    assert upscale.UpscaleConfig().backend == "none"


def test_parse_resolution_aliases_and_errors() -> None:
    assert upscale.parse_resolution("1080p") == upscale.Resolution(1080, 1920, "1080p")
    assert upscale.parse_resolution("4K") == upscale.Resolution(2160, 3840, "4k")
    assert upscale.parse_resolution("1440p") == upscale.Resolution(1440, 2560, "1440p")
    assert upscale.parse_resolution("1920x1080") == upscale.Resolution(1080, 1920, "1920x1080")
    assert upscale.parse_resolution("1920x1080", "horizontal") == upscale.Resolution(1920, 1080, "1920x1080")
    assert upscale.parse_resolution("1080x1920", "horizontal") == upscale.Resolution(1920, 1080, "1080x1920")
    assert upscale.parse_resolution("720p") == upscale.Resolution(720, 1280, "720p")
    assert upscale.parse_resolution("720p", "horizontal") == upscale.Resolution(1280, 720, "720p")
    assert upscale.parse_resolution("1080") == upscale.Resolution(1080, 1920, "1080p")
    with pytest.raises(upscale.UpscaleError, match="vacía"):
        upscale.parse_resolution("  ")
    with pytest.raises(upscale.UpscaleError, match="orientation"):
        upscale.parse_resolution("1080p", "diagonal")
    with pytest.raises(upscale.UpscaleError, match="inválida"):
        upscale.parse_resolution("bad")
    with pytest.raises(upscale.UpscaleError, match="inválida"):
        upscale.parse_resolution("axb")
    with pytest.raises(upscale.UpscaleError, match="inválida"):
        upscale.parse_resolution("0x10")
    with pytest.raises(upscale.UpscaleError, match="inválida"):
        upscale.parse_resolution("0p")


def test_ffmpeg_filter_and_run() -> None:
    target = upscale.Resolution(64, 96)
    assert upscale.ffmpeg_upscale_filter(target) == "scale=64:96:flags=lanczos"
    assert "unsharp=5:5:0.75" in upscale.ffmpeg_upscale_filter(target, 0.75)
    commands: list[list[str]] = []
    upscale._run(["echo"], commands.append)
    assert commands == [["echo"]]
    with pytest.raises(upscale.UpscaleError, match="no encontré"):
        upscale._run(["missing"], None)
    with pytest.raises(upscale.UpscaleError, match="falló"):
        upscale._run(["false"], None)


def test_run_wraps_file_not_found_and_called_process_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(cmd, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(upscale.subprocess, "run", missing)
    with pytest.raises(upscale.UpscaleError, match="no encontré"):
        upscale._run(["missing"], None)

    def failed(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="boom")

    monkeypatch.setattr(upscale.subprocess, "run", failed)
    with pytest.raises(upscale.UpscaleError, match="boom"):
        upscale._run(["bad"], None)


def test_image_helpers_and_copy(tmp_path: Path) -> None:
    src = _image(tmp_path / "src.png")
    assert upscale._image_size(src) == (32, 32)
    bad = tmp_path / "bad.jpg"
    bad.write_text("nope", encoding="utf-8")
    with pytest.raises(upscale.UpscaleError, match="no pude abrir"):
        upscale._image_size(bad)
    with pytest.raises(upscale.UpscaleError, match="no pude ajustar"):
        upscale._fit_image(bad, upscale.Resolution(64, 64))
    assert upscale._copy(src, src) == src
    dest = tmp_path / "dest.png"
    assert upscale._copy(src, dest) == dest
    assert dest.read_bytes() == src.read_bytes()
    fitted = _image(tmp_path / "fit.jpg")
    upscale._fit_image(fitted, upscale.Resolution(64, 96))
    assert upscale._image_size(fitted) == (64, 96)
    fitted_png = _image(tmp_path / "fit.png")
    upscale._fit_image(fitted_png, upscale.Resolution(48, 72))
    assert upscale._image_size(fitted_png) == (48, 72)


def test_upscale_image_copy_paths(tmp_path: Path) -> None:
    src = _image(tmp_path / "src.png")
    dest = tmp_path / "dest.png"
    disabled = upscale.UpscaleConfig()
    assert upscale.upscale_image(src, dest, disabled) == dest
    assert dest.exists()
    dest2 = tmp_path / "dest2.png"
    assert upscale.upscale_image(src, dest2, upscale.UpscaleConfig(enabled=True, backend="ffmpeg")) == dest2
    assert dest2.read_bytes() == src.read_bytes()
    dest3 = tmp_path / "dest3.png"
    assert (
        upscale.upscale_image(
            src,
            dest3,
            upscale.UpscaleConfig(enabled=True, backend="ffmpeg"),
            target=upscale.Resolution(16, 16),
        )
        == dest3
    )
    assert dest3.read_bytes() == src.read_bytes()


def test_upscale_image_ffmpeg_and_auto(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _image(tmp_path / "src.png")
    commands: list[list[str]] = []
    runner = _write_runner(commands)
    target = upscale.Resolution(64, 96)
    dest = tmp_path / "ffmpeg.png"
    upscale.upscale_image(
        src,
        dest,
        upscale.UpscaleConfig(enabled=True, backend="ffmpeg", sharpen=0.5),
        target=target,
        runner=runner,
    )
    assert dest.exists()
    assert commands[0][0] == "ffmpeg"
    assert "unsharp" in commands[0][commands[0].index("-vf") + 1]

    monkeypatch.setattr(upscale.shutil, "which", lambda name: None)
    auto_dest = tmp_path / "auto.png"
    upscale.upscale_image(
        src,
        auto_dest,
        upscale.UpscaleConfig(enabled=True, backend="auto"),
        target=target,
        runner=runner,
    )
    assert auto_dest.exists()


def test_upscale_image_auto_realesrgan_and_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _image(tmp_path / "src.png")
    target = upscale.Resolution(64, 96)
    commands: list[list[str]] = []

    def runner(cmd) -> None:
        commands.append(list(cmd))
        target_path = Path(cmd[cmd.index("-o") + 1]) if "-o" in cmd else Path(cmd[-1])
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(_png_bytes())

    monkeypatch.setattr(upscale.shutil, "which", lambda name: "/bin/realesrgan-ncnn-vulkan")
    dest = tmp_path / "auto-realesrgan.png"
    upscale.upscale_image(
        src,
        dest,
        upscale.UpscaleConfig(enabled=True, backend="auto", model="x4"),
        target=target,
        runner=runner,
    )
    assert dest.exists()
    assert commands[0][0] == "/bin/realesrgan-ncnn-vulkan"
    assert "-n" in commands[0]

    def failing_runner(cmd) -> None:
        commands.append(list(cmd))
        if cmd[0] == "/bin/realesrgan-ncnn-vulkan":
            raise upscale.UpscaleError("boom")
        Path(cmd[-1]).write_bytes(_png_bytes())

    fallback = tmp_path / "fallback.png"
    upscale.upscale_image(
        src,
        fallback,
        upscale.UpscaleConfig(enabled=True, backend="auto"),
        target=target,
        runner=failing_runner,
    )
    assert fallback.exists()
    assert commands[-1][0] == "ffmpeg"


def test_upscale_image_realesrgan_and_comfyui_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _image(tmp_path / "src.png")
    target = upscale.Resolution(64, 96)
    monkeypatch.setattr(upscale.shutil, "which", lambda name: None)
    with pytest.raises(upscale.UpscaleError, match="no está instalado"):
        upscale.upscale_image(
            src,
            tmp_path / "out.png",
            upscale.UpscaleConfig(enabled=True, backend="realesrgan"),
            target=target,
        )
    with pytest.raises(upscale.UpscaleError, match="workflow"):
        upscale.upscale_image(
            src,
            tmp_path / "out.png",
            upscale.UpscaleConfig(enabled=True, backend="comfyui"),
            target=target,
        )


def test_sdwebui_upscale_with_client(tmp_path: Path) -> None:
    src = _image(tmp_path / "src.png")
    target = upscale.Resolution(64, 96)
    encoded = base64.b64encode(_png_bytes()).decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sdapi/v1/extra-single-image"
        payload = request.read().decode()
        assert "upscaling_resize" in payload
        return httpx.Response(200, json={"image": encoded})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    dest = tmp_path / "sd.png"
    try:
        result = upscale.upscale_image(
            src,
            dest,
            upscale.UpscaleConfig(enabled=True, backend="sdwebui", model="model"),
            target=target,
            client=client,
            sdwebui_url="http://sd.local/",
        )
    finally:
        client.close()
    assert result == dest
    assert upscale._image_size(dest) == (64, 96)


def test_sdwebui_errors_and_owned_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _image(tmp_path / "src.png")
    target = upscale.Resolution(64, 96)
    encoded = base64.b64encode(_png_bytes()).decode("ascii")

    def empty_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(empty_handler))
    try:
        with pytest.raises(upscale.UpscaleError, match="no devolvió"):
            upscale.upscale_image(
                src,
                tmp_path / "out.png",
                upscale.UpscaleConfig(enabled=True, backend="sdwebui"),
                target=target,
                client=client,
            )
    finally:
        client.close()

    class OwnedClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, json):
            return httpx.Response(
                200,
                json={"image": encoded},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(upscale.httpx, "Client", OwnedClient)
    dest = tmp_path / "owned.png"
    result = upscale.upscale_image(
        src,
        dest,
        upscale.UpscaleConfig(enabled=True, backend="sdwebui"),
        target=target,
        timeout=1.0,
    )
    assert result == dest
    assert dest.exists()


def test_sdwebui_transport_error(tmp_path: Path) -> None:
    src = _image(tmp_path / "src.png")
    target = upscale.Resolution(64, 96)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "nope"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(upscale.UpscaleError, match="SD WebUI"):
            upscale.upscale_image(
                src,
                tmp_path / "out.png",
                upscale.UpscaleConfig(enabled=True, backend="sdwebui"),
                target=target,
                client=client,
            )
    finally:
        client.close()
