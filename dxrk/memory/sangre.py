# SPDX-License-Identifier: MIT
"""Deprecated compatibility shim for the sangre → malla vocabulary rename.

Import :mod:`dxrk.memory.malla` instead. This module re-exports the canonical
engine and maps the old public names so existing integrations keep working.
"""

from __future__ import annotations

import warnings

from . import malla as _malla
from .backend import MallaNotFoundError, MallaRef
from .malla import *  # noqa: F403
from .types import RecallRecord as GlobuloRecord  # noqa: F401 (public legacy alias)

warnings.warn(
    "dxrk.memory.sangre is deprecated; import from dxrk.memory.malla instead",
    DeprecationWarning,
    stacklevel=2,
)

Sangre = _malla.Malla
DxrkSangre = _malla.DxrkMalla
SangreConfig = _malla.MallaConfig
mine_sangre_lock = _malla.mine_malla_lock
SangreRef = MallaRef
SangreNotFoundError = MallaNotFoundError

_LEGACY_ALIASES: dict[str, str] = {
    "Sangre": "Malla",
    "DxrkSangre": "DxrkMalla",
    "SangreConfig": "MallaConfig",
    "mine_sangre_lock": "mine_malla_lock",
}


def __getattr__(name: str) -> object:
    target = _LEGACY_ALIASES.get(name)
    if target is None:
        return getattr(_malla, name)
    return getattr(_malla, target)
