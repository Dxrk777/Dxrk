# SPDX-License-Identifier: MIT
"""Score ledger wiring — lapse hooks, record_lapse, capping, chain verify."""

from __future__ import annotations

from pathlib import Path


def _dm(tmp_path: Path, **kwargs):  # type: ignore[no-untyped-def]
    from dxrk.memory.palace import DxrkMemory

    dm = DxrkMemory(str(tmp_path / "palace"), **kwargs)
    dm.init()
    return dm


DOC_A = "Ledger alpha drawer with zephyrquinox content for lapse dynamics."
DOC_B = "Ledger beta drawer with quixoticbadger content for lapse dynamics."


def _raw_meta(dm, did: str) -> dict:  # type: ignore[no-untyped-def]
    got = dm._collection(create=False).get(ids=[did], include=["metadatas"])
    meta = got.metadatas[0]
    assert isinstance(meta, dict)
    return meta


class TestRecordLapse:
    def test_lapse_updates_state_and_appends_ledger(self, tmp_path: Path) -> None:
        from dxrk.memory.migrate import verify_chain

        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            # Lower rd off its 350 ceiling so the lapse bump is observable.
            col = dm._collection(create=False)
            seeded = dict(_raw_meta(dm, did))
            seeded["rd"] = 100.0
            seeded["S"] = 60.0
            col.upsert(documents=[DOC_A], ids=[did], metadatas=[seeded])  # type: ignore[arg-type]
            before = _raw_meta(dm, did)
            s0, d0, rd0 = float(before["S"]), float(before["D"]), float(before["rd"])
            assert dm.record_lapse(did, reason="contradiction") is True
            after = _raw_meta(dm, did)
            assert float(after["S"]) < s0
            assert float(after["D"]) > d0
            assert float(after["rd"]) > rd0
            ledger = after["score_ledger"]
            assert isinstance(ledger, list) and len(ledger) == 1
            assert ledger[0]["reason"] == "contradiction"
            ok, _idx = verify_chain(after)
            assert ok is True
        finally:
            dm.close()

    def test_missing_drawer(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        try:
            assert dm.record_lapse("drawer_missing") is False
        finally:
            dm.close()

    def test_ledger_caps_at_20_with_dropped_counter(self, tmp_path: Path) -> None:
        from dxrk.memory.migrate import LEDGER_CAP, verify_chain

        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            for _ in range(LEDGER_CAP + 5):
                assert dm.record_lapse(did, reason="repeated") is True
            after = _raw_meta(dm, did)
            assert len(after["score_ledger"]) == LEDGER_CAP
            assert after["score_ledger_dropped"] == 5
            ok, _idx = verify_chain(after)
            assert ok is True  # chain verifies from oldest present entry
        finally:
            dm.close()


class TestLapseHooks:
    def test_supersede_path_lapses_old_row(self, tmp_path: Path) -> None:
        from dxrk.memory.migrate import verify_chain

        dm = _dm(tmp_path)
        try:
            old = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            s0 = float(_raw_meta(dm, old)["S"])
            dm.add_drawer("w", "r", DOC_B, "/b.md", 0, supersedes=old)
            meta = _raw_meta(dm, old)
            assert meta.get("valid_to")
            assert float(meta["S"]) < s0
            ledger = meta["score_ledger"]
            assert isinstance(ledger, list) and len(ledger) >= 1
            assert ledger[-1]["reason"] == "superseded"
            ok, _idx = verify_chain(meta)
            assert ok is True
        finally:
            dm.close()

    def test_forget_path_lapses_row(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            s0 = float(_raw_meta(dm, did)["S"])
            res = dm.forget(drawer_ids=[did])
            assert res["soft_forgotten"] == 1
            meta = _raw_meta(dm, did)
            assert meta.get("forgotten") is True
            assert float(meta["S"]) < s0
            ledger = meta["score_ledger"]
            assert isinstance(ledger, list) and len(ledger) >= 1
            assert ledger[-1]["reason"] == "forgotten"
        finally:
            dm.close()
