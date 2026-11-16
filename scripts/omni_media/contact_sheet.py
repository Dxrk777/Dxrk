# SPDX-License-Identifier: MIT
"""Contact-sheet generation for Dxrk Omni previews."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any


class ContactSheetError(RuntimeError):
    """A contact sheet could not be built."""


def _pillow() -> tuple[Any, Any, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise ContactSheetError("Pillow no está instalado") from exc
    return Image, ImageDraw, ImageFont


def build_contact_sheet(
    images: Sequence[Path],
    out: Path,
    *,
    columns: int = 3,
    thumb_width: int = 360,
    thumb_height: int = 640,
    labels: bool = True,
) -> Path:
    """Compose ``images`` into a labelled grid and save it as PNG."""
    if columns < 1:
        raise ContactSheetError("columns debe ser mayor que cero")
    if thumb_width < 1 or thumb_height < 1:
        raise ContactSheetError("el tamaño de las miniaturas debe ser positivo")
    paths = [Path(image) for image in images]
    if not paths:
        raise ContactSheetError("no hay imágenes para el contact sheet")
    Image, ImageDraw, ImageFont = _pillow()
    label_height = 28 if labels else 0
    rows = (len(paths) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_width, rows * (thumb_height + label_height)), (18, 18, 24))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover - very old Pillow
        font = None
    for index, path in enumerate(paths):
        row, column = divmod(index, columns)
        x = column * thumb_width
        y = row * (thumb_height + label_height)
        try:
            with Image.open(path) as image:
                thumb = ImageOps_fit(image.convert("RGB"), (thumb_width, thumb_height))
                sheet.paste(thumb, (x, y))
        except Exception:
            draw.rectangle([x, y, x + thumb_width - 1, y + thumb_height - 1], fill=(40, 20, 30))
            if font is not None:
                draw.text((x + 12, y + 12), "missing", font=font, fill=(255, 120, 120))
        if labels:
            draw.rectangle([x, y + thumb_height, x + thumb_width, y + thumb_height + label_height], fill=(10, 10, 16))
            if font is not None:
                draw.text((x + 8, y + thumb_height + 6), path.name[:40], font=font, fill=(220, 220, 230))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "PNG")
    return out


def ImageOps_fit(image: Any, size: tuple[int, int]) -> Any:
    """Small Pillow helper kept separate so tests can monkeypatch it if needed."""
    from PIL import Image, ImageOps

    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)


def contact_sheet_for_run(
    workdir: Path,
    out: Path | None = None,
    *,
    columns: int = 3,
    thumb_width: int = 360,
    thumb_height: int = 640,
    labels: bool = True,
) -> Path:
    """Find the final generated images under ``workdir/assets`` and compose them."""
    workdir = Path(workdir)
    assets = workdir / "assets"
    candidates: dict[str, Path] = {}
    for suffix in ("*.jpg", "*.jpeg", "*.png"):
        for path in assets.rglob(suffix):
            if path.name == "contact_sheet.png":
                continue
            key = path.with_name(path.name.replace("_upscaled", "")).as_posix()
            if key not in candidates or "_upscaled" in path.name:
                candidates[key] = path
    images = [candidates[key] for key in sorted(candidates)]
    if not images:
        raise ContactSheetError("no encontré imágenes generadas para el contact sheet")
    destination = out or workdir / "contact_sheet.png"
    return build_contact_sheet(
        images,
        destination,
        columns=columns,
        thumb_width=thumb_width,
        thumb_height=thumb_height,
        labels=labels,
    )


__all__ = ["ContactSheetError", "build_contact_sheet", "contact_sheet_for_run"]
