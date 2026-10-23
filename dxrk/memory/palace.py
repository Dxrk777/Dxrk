# SPDX-License-Identifier: MIT
"""Deprecated compatibility shim for the palace → malla vocabulary rename.

Import :mod:`dxrk.memory.malla` instead. This module re-exports the canonical
engine and maps the old public names so existing integrations keep working.
"""

from __future__ import annotations

import warnings

from . import malla as _malla
from .malla import *  # noqa: F403
from .types import RecallRecord as DrawerRecord  # noqa: F401 (public legacy alias)

warnings.warn(
    "dxrk.memory.palace is deprecated; import from dxrk.memory.malla instead",
    DeprecationWarning,
    stacklevel=2,
)

Palace = _malla.Malla
DxrkPalace = _malla.DxrkMalla
PalaceConfig = _malla.MallaConfig
mine_palace_lock = _malla.mine_malla_lock

_LEGACY_ALIASES: dict[str, str] = {
    "Palace": "Malla",
    "DxrkPalace": "DxrkMalla",
    "PalaceConfig": "MallaConfig",
    "mine_palace_lock": "mine_malla_lock",
}


def __getattr__(name: str) -> object:
    target = _LEGACY_ALIASES.get(name)
    if target is None:
        return getattr(_malla, name)
    return getattr(_malla, target)
