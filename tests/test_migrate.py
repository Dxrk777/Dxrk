# SPDX-License-Identifier: MIT
"""Lazy spine migration (schema v2) — ensure_spine_defaults + palace wiring."""

from __future__ import annotations

import math
from pathlib import Path


def _dm(tmp_path: Path, **kwargs):  # type: ignore[no-untyped-def]
    from dxrk.memory.palace import DxrkMemory

    dm = DxrkMemory(str(tmp_path / "palace"), **kwargs)
    dm.init()
    return dm


def _legacy_meta(n: int = 4) -> dict[str, object]:
    from datetime import UTC, datetime

    return {
        "wing": "w",
        "room": "r",
        "source_file": "/legacy.md",
        "chunk_index": 0,
        "filed_at": datetime.now(UTC).isoformat(),
        "accessed_at": datetime.now(UTC).isoformat(),
        "access_count": n,
        "importance": 2.0,
    }


class TestEnsureSpineDefaults:
    def test_legacy_row_gets_migrated_priors(self) -> None:
        from dxrk.memory.migrate import SCHEMA_VERSION, ensure_spine_defaults

        meta = ensure_spine_defaults(_legacy_meta(n=4))
        assert meta["schema_version"] == SCHEMA_VERSION
        assert float(meta["S"]) == math.log1p(4) + 1.0  # type: ignore[arg-type]
        assert float(meta["D"]) == 5.0  # type: ignore[arg-type]
        assert float(meta["rd"]) == 350.0 / 5.0  # type: ignore[arg-type]
        assert meta["s_updates"] == 0
        assert meta["content_sha256"] == ""
        assert meta["access_history"] == [meta["accessed_at"]]
        assert meta["access_count_total"] == 4
        assert meta["score_ledger"] == []
        assert meta["score_ledger_dropped"] == 0
        assert meta["quarantined"] is False

    def test_legacy_row_without_access_signals(self) -> None:
        from dxrk.memory.migrate import ensure_spine_defaults

        meta = ensure_spine_defaults({"wing": "w"})
        assert meta["schema_version"] == 2
        assert float(meta["S"]) == 1.0  # type: ignore[arg-type]
        assert float(meta["rd"]) == 350.0  # type: ignore[arg-type]
        assert meta["access_history"] == []
        assert meta["access_count_total"] == 0

    def test_idempotent(self) -> None:
        from dxrk.memory.migrate import ensure_spine_defaults

        first = ensure_spine_defaults(_legacy_meta(n=2))
        snapshot = dict(first)
        assert ensure_spine_defaults(first) == snapshot

    def test_v2_row_keeps_learned_state(self) -> None:
        from dxrk.memory.migrate import ensure_spine_defaults

        meta = ensure_spine_defaults(
            {"schema_version": 2, "S": 42.0, "D": 6.0, "rd": 120.0, "access_count_total": 9, "content_sha256": "x"}
        )
        assert float(meta["S"]) == 42.0  # type: ignore[arg-type]
        assert float(meta["D"]) == 6.0  # type: ignore[arg-type]
        assert float(meta["rd"]) == 120.0  # type: ignore[arg-type]
        assert meta["content_sha256"] == "x"

    def test_needs_rehash(self) -> None:
        from dxrk.memory.migrate import ensure_spine_defaults, needs_rehash

        assert needs_rehash(ensure_spine_defaults({"wing": "w"})) is True
        assert needs_rehash({"content_sha256": "abc"}) is False


class TestPalaceMigrationWiring:
    def test_add_drawer_stamps_spine_keys(self, tmp_path: Path) -> None:
        import hashlib

        from dxrk.memory.migrate import SCHEMA_VERSION

        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", "Migration stamps spine keys on new drawers here.", "/n.md", 0)
            col = dm._collection(create=False)
            got = col.get(ids=[did], include=["metadatas"])
            meta = got.metadatas[0]
            assert isinstance(meta, dict)
            assert meta["schema_version"] == SCHEMA_VERSION
            assert float(meta["S"]) == 1.0  # type: ignore[arg-type]
            assert float(meta["D"]) == 5.0  # type: ignore[arg-type]
            assert float(meta["rd"]) == 350.0  # type: ignore[arg-type]
            assert meta["s_updates"] == 0
            assert meta["access_count_total"] == 0
            assert meta["access_history"] == []
            assert meta["score_ledger"] == []
            assert meta["quarantined"] is False
            doc = col.get(ids=[did], include=["documents"]).documents[0]
            assert meta["content_sha256"] == hashlib.sha256(doc.encode()).hexdigest()
        finally:
            dm.close()

    def test_get_drawer_migrates_legacy_row(self, tmp_path: Path) -> None:
        from dxrk.memory.migrate import needs_rehash

        dm = _dm(tmp_path)
        try:
            col = dm._collection(create=True)
            col.upsert(
                documents=["legacy drawer body text here for migration."],
                ids=["drawer_w_r_deadbeef00000000000000"],
                metadatas=[_legacy_meta(n=3)],
            )
            raw_before = col.get(ids=["drawer_w_r_deadbeef00000000000000"], include=["metadatas"]).metadatas[0]
            assert isinstance(raw_before, dict) and "schema_version" not in raw_before
            assert needs_rehash(raw_before) is True
            got = dm.get_drawer("drawer_w_r_deadbeef00000000000000")
            assert got is not None
            assert got["metadata"]["schema_version"] == 2
            assert float(got["metadata"]["S"]) == math.log1p(3) + 1.0  # type: ignore[arg-type]
            raw_after = col.get(ids=["drawer_w_r_deadbeef00000000000000"], include=["metadatas"]).metadatas[0]
            assert isinstance(raw_after, dict)
            assert raw_after["schema_version"] == 2  # migration persisted (lazy write-back)
        finally:
            dm.close()

    def test_wing_snapshot_ensures_spine_in_memory(self, tmp_path: Path) -> None:
        from dxrk.memory.palace import _wing_snapshot

        dm = _dm(tmp_path)
        try:
            col = dm._collection(create=True)
            col.upsert(
                documents=["legacy snapshot body text here for the scan."],
                ids=["drawer_w_r_0000000000000000000001"],
                metadatas=[_legacy_meta(n=1)],
            )
            snap = _wing_snapshot(col, "w")
            assert len(snap) == 1
            meta = snap[0]["meta"]
            assert isinstance(meta, dict)
            assert meta["schema_version"] == 2
        finally:
            dm.close()
