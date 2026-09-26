# SPDX-License-Identifier: MIT
"""Tests para dxrk.memory.engine — entry point canónico (re-export de palace)."""

from __future__ import annotations


def test_engine_reexports_canonical_symbols() -> None:
    import dxrk.memory.engine as engine
    import dxrk.memory.palace as palace

    assert engine.DxrkMemory is palace.DxrkMemory
    assert engine.Palace is palace.Palace
    assert engine.DxrkPalace is palace.DxrkPalace
    assert engine.PalaceConfig is palace.PalaceConfig


def test_engine_all_contains_canonical_names() -> None:
    import dxrk.memory.engine as engine

    assert engine.__all__ == ["DxrkMemory", "Palace", "DxrkPalace", "PalaceConfig"]


def test_engine_reexports_helpers_and_constants() -> None:
    import dxrk.memory.engine as engine
    import dxrk.memory.palace as palace

    assert engine.CHUNK_SIZE == palace.CHUNK_SIZE
    assert engine.CHUNK_OVERLAP == palace.CHUNK_OVERLAP
    assert engine.chunk_text is palace.chunk_text
    assert engine.mine_lock is palace.mine_lock
    assert engine.mine_palace_lock is palace.mine_palace_lock
    assert engine.mine_global_lock is palace.mine_global_lock
    assert engine.reap_stale_dxrk_locks is palace.reap_stale_dxrk_locks
    assert engine.reap_stale_mine_locks is palace.reap_stale_mine_locks
    assert engine._detect_hall is palace._detect_hall
    assert engine._extract_entities is palace._extract_entities
    assert engine._build_drawer_metadata is palace._build_drawer_metadata


def test_engine_import_path_equivalence() -> None:
    from dxrk.memory.engine import DxrkMemory as FromEngine
    from dxrk.memory.palace import DxrkMemory as FromPalace

    assert FromEngine is FromPalace
