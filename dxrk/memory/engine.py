# SPDX-License-Identifier: MIT
"""DxrkMemory engine — canonical entry point.

This module is the proprietary DxrkMemory engine. It re-exports the
canonical :class:`DxrkMemory` class from :mod:`dxrk.memory.palace` (kept
as legacy alias) so that ``from dxrk.memory.engine import DxrkMemory``
and ``from dxrk.memory import DxrkMemory`` are the canonical imports.

All new code should import from :mod:`dxrk.memory.engine` or
:mod:`dxrk.memory`. Old ``palace`` import remains for compatibility.
"""

from __future__ import annotations

from .palace import (  # noqa: F401
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DRAWER_UPSERT_BATCH_SIZE,
    ENTITY_EXTRACT_WINDOW,
    ENTITY_METADATA_LIMIT,
    MAX_FILE_SIZE,
    MIN_CHUNK_SIZE,
    NORMALIZE_VERSION,
    DxrkMemory,
    DxrkPalace,
    Palace,
    PalaceConfig,
    _build_drawer_metadata,
    _detect_hall,
    _extract_entities,
    chunk_text,
    mine_global_lock,
    mine_lock,
    mine_palace_lock,
    reap_stale_dxrk_locks,
    reap_stale_mine_locks,
)

__all__ = [
    "DxrkMemory",
    "Palace",
    "DxrkPalace",
    "PalaceConfig",
]
