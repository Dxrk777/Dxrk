# SPDX-License-Identifier: MIT
"""Tests for the Omni contact-sheet builder."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from scripts.omni_media import contact_sheet


def _image(path: Path, size: tuple[int, int] = (64, 96), color=(10, 200, 180)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def test_build_contact_sheet_grid_and_labels(tmp_path: Path) -> None:
    images = [_image(tmp_path / f"image_{index}.jpg") for index in range(5)]
    out = tmp_path / "sheet.png"
    result = contact_sheet.build_contact_sheet(
        images,
        out,
        columns=3,
        thumb_width=80,
        thumb_height=120,
        labels=True,
    )
    assert result == out
    with Image.open(out) as sheet:
        assert sheet.size == (240, 2 * (120 + 28))
        assert sheet.getpixel((0, 0)) != (18, 18, 24)


def test_build_contact_sheet_without_labels_and_missing_image(tmp_path: Path) -> None:
    good = _image(tmp_path / "good.jpg")
    missing = tmp_path / "missing.jpg"
    out = tmp_path / "sheet.png"
    contact_sheet.build_contact_sheet(
        [good, missing],
        out,
        columns=2,
        thumb_width=60,
        thumb_height=90,
        labels=False,
    )
    with Image.open(out) as sheet:
        assert sheet.size == (120, 90)


def test_build_contact_sheet_validates_input(tmp_path: Path) -> None:
    image = _image(tmp_path / "image.jpg")
    with pytest.raises(contact_sheet.ContactSheetError, match="columns"):
        contact_sheet.build_contact_sheet([image], tmp_path / "out.png", columns=0)
    with pytest.raises(contact_sheet.ContactSheetError, match="tamaño"):
        contact_sheet.build_contact_sheet([image], tmp_path / "out.png", thumb_width=0)
    with pytest.raises(contact_sheet.ContactSheetError, match="no hay imágenes"):
        contact_sheet.build_contact_sheet([], tmp_path / "out.png")


def test_contact_sheet_for_run_prefers_upscaled_and_ignores_sheet(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    base = _image(assets / "scene_01.jpg", color=(200, 10, 10))
    upscaled = _image(assets / "scene_01_upscaled.jpg", color=(10, 200, 10))
    _image(assets / "nested" / "scene_02.png")
    _image(assets / "contact_sheet.png")
    result = contact_sheet.contact_sheet_for_run(
        tmp_path,
        columns=2,
        thumb_width=40,
        thumb_height=60,
    )
    assert result == tmp_path / "contact_sheet.png"
    assert result.exists()
    with Image.open(result) as sheet:
        assert sheet.size == (80, 60 + 28)
    assert upscaled.exists()
    assert base.exists()


def test_contact_sheet_for_run_without_images(tmp_path: Path) -> None:
    with pytest.raises(contact_sheet.ContactSheetError, match="no encontré"):
        contact_sheet.contact_sheet_for_run(tmp_path)


def test_build_contact_sheet_without_default_font(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = _image(tmp_path / "image.jpg")
    missing = tmp_path / "missing.jpg"
    out = tmp_path / "sheet.png"
    monkeypatch.setattr(
        contact_sheet._pillow()[2],
        "load_default",
        lambda: (_ for _ in ()).throw(RuntimeError("no font")),
    )
    contact_sheet.build_contact_sheet([image, missing], out, columns=2, labels=True)
    assert out.exists()
