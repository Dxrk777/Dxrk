# SPDX-License-Identifier: MIT
"""Deprecated compatibility shim for the crypt → malla vocabulary rename.

Import :mod:`dxrk.memory.malla` instead. This module re-exports the canonical
engine and maps the old public names so existing integrations keep working.
"""

from __future__ import annotations

import warnings

from . import malla as _malla
from .backend import MallaNotFoundError, MallaRef
from .legacy import migrate_legacy_crypt  # noqa: F401 (public legacy alias)
from .malla import *  # noqa: F403
from .types import RecallRecord as RelicRecord  # noqa: F401 (public legacy alias)

warnings.warn(
    "dxrk.memory.crypt is deprecated; import from dxrk.memory.malla instead",
    DeprecationWarning,
    stacklevel=2,
)

Crypt = _malla.Malla
DxrkCrypt = _malla.DxrkMalla
CryptConfig = _malla.MallaConfig
mine_crypt_lock = _malla.mine_malla_lock
CryptRef = MallaRef
CryptNotFoundError = MallaNotFoundError

_LEGACY_ALIASES: dict[str, str] = {
    "Crypt": "Malla",
    "DxrkCrypt": "DxrkMalla",
    "CryptConfig": "MallaConfig",
    "mine_crypt_lock": "mine_malla_lock",
}


def __getattr__(name: str) -> object:
    target = _LEGACY_ALIASES.get(name)
    if target is None:
        return getattr(_malla, name)
    return getattr(_malla, target)
