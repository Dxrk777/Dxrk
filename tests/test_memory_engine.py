# SPDX-License-Identifier: MIT
"""Tests para dxrk.memory.engine — entry point canónico (re-export de malla)."""

from __future__ import annotations


def test_engine_reexports_canonical_symbols() -> None:
    import dxrk.memory.engine as engine
    import dxrk.memory.malla as malla

    assert engine.DxrkMemory is malla.DxrkMemory
    assert engine.Malla is malla.Malla
    assert engine.DxrkMalla is malla.DxrkMalla
    assert engine.MallaConfig is malla.MallaConfig


def test_engine_all_contains_canonical_names() -> None:
    import dxrk.memory.engine as engine

    assert engine.__all__ == ["DxrkMemory", "Malla", "DxrkMalla", "MallaConfig"]


def test_engine_reexports_helpers_and_constants() -> None:
    import dxrk.memory.engine as engine
    import dxrk.memory.malla as malla

    assert engine.CHUNK_SIZE == malla.CHUNK_SIZE
    assert engine.CHUNK_OVERLAP == malla.CHUNK_OVERLAP
    assert engine.chunk_text is malla.chunk_text
    assert engine.mine_lock is malla.mine_lock
    assert engine.mine_malla_lock is malla.mine_malla_lock
    assert engine.mine_global_lock is malla.mine_global_lock
    assert engine.reap_stale_dxrk_locks is malla.reap_stale_dxrk_locks
    assert engine.reap_stale_mine_locks is malla.reap_stale_mine_locks
    assert engine._detect_hall is malla._detect_hall
    assert engine._extract_entities is malla._extract_entities
    assert engine._build_recall_metadata is malla._build_recall_metadata


def test_engine_import_path_equivalence() -> None:
    from dxrk.memory.engine import DxrkMemory as FromEngine
    from dxrk.memory.malla import DxrkMemory as FromSangre

    assert FromEngine is FromSangre
