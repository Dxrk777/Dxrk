# SPDX-License-Identifier: MIT
"""Ranker unification (RDU everywhere) + spine status surface."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace


def _dm(tmp_path: Path, **kwargs):  # type: ignore[no-untyped-def]
    from dxrk.memory.palace import DxrkMemory

    dm = DxrkMemory(str(tmp_path / "palace"), **kwargs)
    dm.init()
    return dm


def _iso_days_ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


class TestLayer1Rdu:
    def test_fresh_outranks_stale_despite_importance(self, tmp_path: Path) -> None:
        from dxrk.memory.layers import Layer1

        dm = _dm(tmp_path)
        try:
            col = dm._collection(create=True)
            col.upsert(
                documents=["stale filler " * 10, "fresh filler " * 10],
                ids=["d-stale", "d-fresh"],
                metadatas=[
                    {
                        "wing": "w",
                        "room": "r",
                        "source_file": "/s.txt",
                        "filed_at": _iso_days_ago(60),
                        "accessed_at": _iso_days_ago(60),
                        "importance": 4.5,
                    },
                    {
                        "wing": "w",
                        "room": "r",
                        "source_file": "/f.txt",
                        "filed_at": _iso_days_ago(0),
                        "accessed_at": _iso_days_ago(0),
                        "importance": 0.5,
                    },
                ],
            )
            out = Layer1(str(tmp_path / "palace")).generate(wing="w")
            assert out.index("fresh filler") < out.index("stale filler")
        finally:
            dm.close()


class TestHybridRankNudge:
    def _stub(self, docs: list[str], metas: list[dict], dists: list[float]):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            documents=[docs],
            metadatas=[metas],
            distances=[dists],
        )

    def _stale_meta(self) -> dict[str, object]:
        return {
            "wing": "w",
            "room": "r",
            "source_file": "/s.txt",
            "filed_at": _iso_days_ago(400),
            "schema_version": 2,
            "S": 1.0,
            "D": 5.0,
            "rd": 350.0,
            "accessed_at": _iso_days_ago(400),
            "access_count": 0,
            "access_count_total": 0,
        }

    def _fresh_meta(self) -> dict[str, object]:
        return {
            "wing": "w",
            "room": "r",
            "source_file": "/f.txt",
            "filed_at": _iso_days_ago(0),
            "schema_version": 2,
            "S": 60.0,
            "D": 5.0,
            "rd": 350.0,
            "accessed_at": _iso_days_ago(0),
            "access_count": 12,
            "access_count_total": 12,
        }

    def test_nudge_param_applies(self) -> None:
        from dxrk.memory.search import _hybrid_rank

        results = [
            {"text": "apples ledger reconciliation", "distance": 0.1},
            {"text": "apples ledger reconciliation", "distance": 0.4},
        ]
        plain = _hybrid_rank([dict(r) for r in results], "apples ledger")
        assert plain[0]["distance"] == 0.1
        nudged = _hybrid_rank([dict(r) for r in results], "apples ledger", rank_nudge=[0.0, 0.5])
        assert nudged[0]["distance"] == 0.4

    def test_non_sqlite_backend_gets_score_nudge(self) -> None:
        from dxrk.memory.search import hybrid_search

        doc = "apples ledger reconciliation"
        stub = SimpleNamespace(
            query=lambda **kw: self._stub([doc, doc], [self._stale_meta(), self._fresh_meta()], [0.1, 0.16]),
        )
        res = hybrid_search(stub, "apples ledger", n_results=2)  # type: ignore[arg-type]
        hits = res["results"]
        assert isinstance(hits, list) and len(hits) == 2
        # Same text, closer vector (stale) loses to the RDU-nudged fresh hit.
        assert hits[0]["source_file"] == "f.txt"

    def test_sqlite_backend_order_unchanged_without_nudge(self, tmp_path: Path) -> None:
        from dxrk.memory.backend import PalaceRef, SqliteBackend
        from dxrk.memory.search import hybrid_search

        be = SqliteBackend()
        try:
            ref = PalaceRef(id=str(tmp_path), local_path=str(tmp_path))
            col = be.get_collection(palace=ref, collection_name="nounudge", create=True)
            col.add(
                documents=["apples ledger reconciliation", "apples ledger reconciliation"],
                ids=["a", "b"],
                metadatas=[self._stale_meta(), self._fresh_meta()],
            )
            res = hybrid_search(col, "apples ledger", n_results=2)
            hits = res["results"]
            assert isinstance(hits, list) and len(hits) == 2
        finally:
            be.close()


class TestPublicMeta:
    def test_query_hides_raw_access_history(self, tmp_path: Path) -> None:
        from dxrk.memory.backend import PalaceRef, SqliteBackend

        be = SqliteBackend()
        try:
            ref = PalaceRef(id=str(tmp_path), local_path=str(tmp_path))
            col = be.get_collection(palace=ref, collection_name="pubmeta", create=True)
            col.add(
                documents=["history hiding body text here."],
                ids=["h1"],
                metadatas=[{"wing": "w", "access_history": ["2026-01-01T00:00:00+00:00"] * 3}],
            )
            q = col.query(query_texts=["history hiding"], n_results=5)
            meta = q.metadatas[0][0]
            assert isinstance(meta, dict)
            assert "access_history" not in meta
            assert meta.get("access_history_len") == 3
        finally:
            be.close()


class TestSpineStatus:
    def test_status_keys_and_merkle(self, tmp_path: Path) -> None:
        import hashlib

        dm = _dm(tmp_path)
        try:
            d1 = dm.add_drawer("w", "r", "Status alpha drawer body text here.", "/a.md", 0)
            d2 = dm.add_drawer("w", "r", "Status beta drawer body text here.", "/b.md", 0)
            assert dm.quarantine_drawer(d2, reason="status check") is True
            st = dm.status()
            assert st["count"] == 2
            assert st["quarantined"] == 1
            assert st["quarantine_warning"] is True
            assert st["checksum_mismatches"] == 0
            assert st["needs_rehash"] == 0
            col = dm._collection(create=False)
            shas = sorted(
                m["content_sha256"]
                for m in (
                    col.get(ids=[d1], include=["metadatas"]).metadatas[0],
                    col.get(ids=[d2], include=["metadatas"]).metadatas[0],
                )
                if isinstance(m, dict)
            )
            assert st["merkle_root"] == hashlib.sha256("".join(shas).encode()).hexdigest()
            usage = dm.wing_usage("w")
            assert usage["quarantined"] == 1
            assert usage["needs_rehash"] == 0
            assert dm.budgets()["w"]["quarantined"] == 1
        finally:
            dm.close()

    def test_timeline_skips_quarantined(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", "Pinned but quarantined drawer body.", "/p.md", 0)
            assert dm.pin_drawer(did) is True
            assert any(e["ref"] == did for e in dm.timeline())
            assert dm.quarantine_drawer(did, reason="timeline check") is True
            assert all(e["ref"] != did for e in dm.timeline())
        finally:
            dm.close()
