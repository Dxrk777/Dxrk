# SPDX-License-Identifier: MIT
"""Spine quarantine — fail-closed isolation with reason preservation."""

from __future__ import annotations

from pathlib import Path


def _dm(tmp_path: Path, **kwargs):  # type: ignore[no-untyped-def]
    from dxrk.memory.palace import DxrkMemory

    dm = DxrkMemory(str(tmp_path / "palace"), **kwargs)
    dm.init()
    return dm


DOC_A = "Quarantine target alpha holds unique zephyrquinox content for isolation."
DOC_B = "Quarantine target beta holds unique quixoticbadger content for isolation."


class TestQuarantineRoundtrip:
    def test_quarantine_unquarantine(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            assert dm.quarantine_drawer(did, reason="manual review") is True
            got = dm.get_drawer(did)
            assert got is not None
            assert "document" not in got
            assert got.get("quarantined") is True
            assert got.get("quarantine_reason") == "manual review"
            assert dm.unquarantine_drawer(did) is True
            back = dm.get_drawer(did)
            assert back is not None and back.get("document") == DOC_A
            assert back["metadata"].get("quarantined") is False
        finally:
            dm.close()

    def test_missing_drawer(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        try:
            assert dm.quarantine_drawer("drawer_missing") is False
            assert dm.unquarantine_drawer("drawer_missing") is False
        finally:
            dm.close()

    def test_quarantine_preserves_valid_to_and_applies_lapse(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        try:
            old = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            dm.add_drawer("w", "r", DOC_B, "/b.md", 0, supersedes=old)
            col = dm._collection(create=False)
            s_before = float(col.get(ids=[old], include=["metadatas"]).metadatas[0]["S"])  # type: ignore[index]
            assert dm.quarantine_drawer(old, reason="stale lineage") is True
            meta = col.get(ids=[old], include=["metadatas"]).metadatas[0]
            assert isinstance(meta, dict)
            assert meta.get("valid_to")  # original supersede stamp preserved
            assert meta.get("quarantined") is True
            assert float(meta["S"]) < s_before  # type: ignore[arg-type]  # lapse dynamics applied
        finally:
            dm.close()


class TestQuarantineInvisibility:
    def _setup(self, tmp_path: Path):  # type: ignore[no-untyped-def]
        dm = _dm(tmp_path)
        keep = dm.add_drawer("w", "r", "Kept drawer about zephyrquinox gardening ledger.", "/keep.md", 0)
        quar = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
        assert dm.quarantine_drawer(quar, reason="test isolation") is True
        return dm, keep, quar

    def test_search_hides_quarantined(self, tmp_path: Path) -> None:
        dm, _keep, _quar = self._setup(tmp_path)
        try:
            res = dm.search("zephyrquinox", wing="w", n_results=5)
            texts = [str(h.get("text", "")) for h in res.get("results", [])]
            assert all("unique zephyrquinox content" not in t for t in texts)
        finally:
            dm.close()

    def test_layers_hide_quarantined(self, tmp_path: Path) -> None:
        from dxrk.memory.layers import Layer1, Layer2

        dm, _keep, _quar = self._setup(tmp_path)
        try:
            l1 = Layer1(str(tmp_path / "palace")).generate(wing="w")
            assert "unique zephyrquinox content" not in l1
            l2 = Layer2(str(tmp_path / "palace")).retrieve(wing="w")
            assert "unique zephyrquinox content" not in l2
        finally:
            dm.close()

    def test_snapshot_and_cap_exclude_quarantined(self, tmp_path: Path) -> None:
        from dxrk.memory.palace import _wing_snapshot

        dm = _dm(tmp_path, max_entries_per_wing=0)
        try:
            keep = dm.add_drawer("w", "r", DOC_B, "/keep.md", 0)
            quar = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            assert dm.quarantine_drawer(quar, reason="cap exclusion") is True
            col = dm._collection(create=False)
            # Quarantined rows are invisible to lifecycle scans ...
            assert all(e["id"] != quar for e in _wing_snapshot(col, "w"))
            # ... and never cap victims: with cap=1 the live row goes instead.
            dm._max_entries_per_wing = 1  # type: ignore[attr-defined]
            dm.enforce_wing_cap("w")
            assert col.get(ids=[quar], include=["metadatas"]).ids == [quar]
            assert col.get(ids=[keep], include=["metadatas"]).ids == []
        finally:
            dm.close()

    def test_list_drawers_filters_by_default(self, tmp_path: Path) -> None:
        dm, keep, quar = self._setup(tmp_path)
        try:
            default_ids = [d["id"] for d in dm.list_drawers(wing="w")]
            assert keep in default_ids
            assert quar not in default_ids
            opened = dm.list_drawers(wing="w", include_quarantined=True)
            by_id = {d["id"]: d for d in opened}
            assert quar in by_id
            assert "document" not in by_id[quar]  # fail-closed even when listed
            assert by_id[quar].get("quarantine_reason") == "test isolation"
        finally:
            dm.close()
