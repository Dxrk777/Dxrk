# SPDX-License-Identifier: MIT
"""Theme component — ports internal/components/theme/.

Theme injection into agent settings files.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dxrk.components import filemerge


@dataclass
class InjectionResult:
    Changed: bool = False
    Files: list[str] = field(default_factory=list)


_THEME_OVERLAY_JSON = b'{\n  "theme": "dxrk-kanagawa"\n}\n'


def inject(home_dir: str, adapter) -> InjectionResult:
    settings_path = adapter.settings_path(home_dir)
    if not settings_path:
        return InjectionResult()

    wr, _ = _merge_json_file(settings_path, _THEME_OVERLAY_JSON)
    return InjectionResult(Changed=wr.Changed, Files=[settings_path])


def _merge_json_file(
    path: str, overlay: bytes
) -> tuple[filemerge.WriteResult, bytes | None]:
    base_json = _os_read_file(path)
    merged = filemerge.merge_json_objects(base_json, overlay)
    wr = filemerge.write_file_atomic(path, merged, 0o644)
    return wr, merged


def _os_read_file(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return b""
