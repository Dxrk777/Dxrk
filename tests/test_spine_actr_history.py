# SPDX-License-Identifier: MIT
"""Access history and success dynamics on get_drawer (RDU read path)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path


def _dm(tmp_path: Path, **kwargs):  # type: ignore[no-untyped-def]
    from dxrk.memory.palace import DxrkMemory

    dm = DxrkMemory(str(tmp_path / "palace"), **kwargs)
    dm.init()
    return dm


DOC = "Access history drawer with zephyrquinox content for read dynamics."


def _raw_meta(dm, did: str) -> dict:  # type: ignore[no-untyped-def]
    got = dm._collection(create=False).get(ids=[did], include=["metadatas"])
    meta = got.metadatas[0]
    assert isinstance(meta, dict)
    return meta


class TestAccessHistory:
    def test_get_appends_history_counters_and_success_update(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC, "/a.md", 0)
            for _ in range(3):
                got = dm.get_drawer(did)
                assert got is not None and "document" in got
            meta = _raw_meta(dm, did)
            history = meta["access_history"]
            assert isinstance(history, list) and len(history) == 3
            assert all(isinstance(ts, str) and ts for ts in history)
            assert meta["access_count_total"] == 3
            assert meta["access_count"] == 3  # legacy counter preserved
            assert meta["s_updates"] == 3
            assert float(meta["S"]) >= 1.0
            assert float(meta["rd"]) < 350.0  # success decays rd
            reasons = [e["reason"] for e in meta["score_ledger"]]
            assert reasons == ["access", "access", "access"]
        finally:
            dm.close()

    def test_idle_read_grows_stability(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC, "/a.md", 0)
            col = dm._collection(create=False)
            seeded = dict(_raw_meta(dm, did))
            seeded["S"] = 10.0
            seeded["accessed_at"] = (datetime.now(UTC) - timedelta(days=3)).isoformat()
            col.upsert(documents=[DOC], ids=[did], metadatas=[seeded])  # type: ignore[arg-type]
            dm.get_drawer(did)
            assert float(_raw_meta(dm, did)["S"]) > 10.0
        finally:
            dm.close()

    def test_history_caps_at_20_while_total_keeps_counting(self, tmp_path: Path) -> None:
        from dxrk.memory.migrate import ACCESS_HISTORY_CAP

        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC, "/a.md", 0)
            col = dm._collection(create=False)
            seeded = dict(_raw_meta(dm, did))
            seeded["access_history"] = [f"2020-01-01T00:00:{i:02d}+00:00" for i in range(ACCESS_HISTORY_CAP)]
            seeded["access_count_total"] = ACCESS_HISTORY_CAP
            seeded["access_count"] = ACCESS_HISTORY_CAP
            col.upsert(documents=[DOC], ids=[did], metadatas=[seeded])  # type: ignore[arg-type]
            dm.get_drawer(did)
            meta = _raw_meta(dm, did)
            assert len(meta["access_history"]) == ACCESS_HISTORY_CAP
            assert meta["access_history"][-1] != "2020-01-01T00:00:00+00:00"  # oldest dropped
            assert meta["access_count_total"] == ACCESS_HISTORY_CAP + 1
        finally:
            dm.close()

    def test_dead_rows_do_not_accrue(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        try:
            old = dm.add_drawer("w", "r", DOC, "/a.md", 0)
            dm.add_drawer("w", "r", "Replacement drawer text here for supersede.", "/b.md", 0, supersedes=old)
            got = dm.get_drawer(old)
            assert got is not None and "document" in got
            meta = _raw_meta(dm, old)
            assert meta.get("access_history", []) == []
            assert meta.get("access_count_total", 0) == 0
        finally:
            dm.close()
