# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

if sys.platform == "win32":  # pragma: no cover - solo CI Windows
    # ntpath.expanduser ignora HOME (usa USERPROFILE); los tests aíslan el
    # home con monkeypatch.setenv("HOME", tmp). Este shim honra HOME cuando
    # está definido, de modo que Path.home() y os.path.expanduser("~")
    # resuelven al home falso también en Windows. Sin HOME definido delega
    # al comportamiento original (cero cambios fuera de tests aislados).
    _real_expanduser = os.path.expanduser

    def _expanduser_home_first(path: str | os.PathLike[str]) -> str:
        text = os.fspath(path)
        fake = os.environ.get("HOME")
        if fake and (text == "~" or text.startswith("~/") or text.startswith("~\\")):
            return fake + text[1:]
        return _real_expanduser(path)

    os.path.expanduser = _expanduser_home_first  # type: ignore[assignment]


@pytest.fixture
def temp_dir() -> Path:
    with TemporaryDirectory() as d:
        yield Path(d)
