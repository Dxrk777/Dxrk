# SPDX-License-Identifier: MIT
"""Coverage 100 — dxrk/memory/ real behavior gaps (malla/backend/search/vectors/graph/policy/engine).

Stdlib + sqlite temporal only (tmp_path pattern). Every test asserts
observable behavior; no `assert True`, no coverage pragmas.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

import dxrk.memory.malla as pal
from dxrk.memory.backend import MallaRef, SqliteBackend
from dxrk.memory.backend.base import (
    BackendError,
    BaseBackend,
    BaseCollection,
    GetResult,
    QueryResult,
)
from dxrk.memory.policy import (
    CHECKSUM_SWEEP_WINDOW,
    POLICY_MIN_INTERVAL_SECONDS,
    POLICY_SCAN_LIMIT,
    RESCORE_STALE_DAYS,
    PolicyEngine,
)
from dxrk.memory.vectors import DIM as VEC_DIM


@pytest.fixture(autouse=True)
def _isolate_home(monkeypatch, tmp_path):
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_USER", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    yield


def _ref(tmp_path: Path, name: str = "pal") -> MallaRef:
    p = tmp_path / name
    return MallaRef(id=str(p), local_path=str(p))


def _col(tmp_path: Path, name: str = "c", cname: str = "col"):
    be = SqliteBackend()
    ref = _ref(tmp_path, name)
    col = be.get_collection(malla=ref, collection_name=cname, create=True)
    return be, ref, col


def _dm(tmp_path: Path, name: str = "malla", **kw):
    dm = pal.DxrkMemory(str(tmp_path / name), **kw)
    dm.init()
    return dm


def _content(seed: str, n: int = 12) -> str:
    return (seed + " ") * n


# ─── backend registry ─────────────────────────────────────────────────────


class TestBackendRegistry:
    def test_get_backend_sqlite(self):
        be = __import__("dxrk.memory.backend", fromlist=["get_backend"]).get_backend("sqlite")
        try:
            assert isinstance(be, SqliteBackend)
        finally:
            be.close()

    def test_get_backend_unknown_raises(self):
        from dxrk.memory.backend import get_backend

        with pytest.raises(BackendError, match="unknown backend"):
            get_backend("nope_xyz")

    def test_register_and_get_custom_backend(self):
        from dxrk.memory.backend import get_backend, register_backend

        class _Custom(SqliteBackend):
            name = "custom-test-only"  # type: ignore[assignment]

        register_backend("custom-test-only", _Custom)
        be = get_backend("custom-test-only")
        try:
            assert isinstance(be, _Custom)
        finally:
            be.close()


# ─── backend/base contract ────────────────────────────────────────────────


class _MemCol(BaseCollection):
    def __init__(self) -> None:
        self.docs: dict[str, str] = {}
        self.metas: dict[str, dict[str, object]] = {}

    def add(self, *, documents, ids, metadatas=None, embeddings=None) -> None:
        for doc, rid, meta in zip(documents, ids, metadatas or [{}] * len(ids)):
            if rid in self.docs:
                raise ValueError(f"duplicate id {rid!r}")
            self.docs[rid] = doc
            self.metas[rid] = dict(meta or {})

    def upsert(self, *, documents, ids, metadatas=None, embeddings=None) -> None:
        for doc, rid, meta in zip(documents, ids, metadatas or [{}] * len(ids)):
            self.docs[rid] = doc
            self.metas[rid] = dict(meta or {})

    def query(
        self, *, query_texts=None, query_embeddings=None, n_results=10, where=None, where_document=None, include=None
    ) -> QueryResult:
        ids = list(self.docs)[:n_results]
        return QueryResult(
            ids=[ids],
            documents=[[self.docs[i] for i in ids]],
            metadatas=[[self.metas[i] for i in ids]],
            distances=[[0.5] * len(ids)],
            embeddings=None,
        )

    def get(self, *, ids=None, where=None, where_document=None, limit=None, offset=None, include=None) -> GetResult:
        sel = [i for i in (ids if ids is not None else list(self.docs)) if i in self.docs]
        return GetResult(
            ids=sel,
            documents=[self.docs[i] for i in sel],
            metadatas=[self.metas[i] for i in sel],
            embeddings=None,
        )

    def delete(self, *, ids=None, where=None) -> None:
        for rid in ids or []:
            self.docs.pop(rid, None)
            self.metas.pop(rid, None)

    def count(self) -> int:
        return len(self.docs)


class _MemBackend(BaseBackend):
    name = "mem-test-only"  # type: ignore[assignment]

    def get_collection(self, *, malla, collection_name, create=False, options=None) -> BaseCollection:
        return _MemCol()


class TestBaseContract:
    def test_dict_compat_getitem(self):
        qr = QueryResult(ids=[["a"]], documents=[["d"]], metadatas=[[{}]], distances=[[0.1]])
        assert qr["ids"] == [["a"]]
        with pytest.raises(KeyError):
            qr["nope"]

    def test_dict_compat_get(self):
        qr = QueryResult(ids=[["a"]], documents=[["d"]], metadatas=[[{}]], distances=[[0.1]], embeddings=None)
        assert qr.get("ids") == [["a"]]
        assert qr.get("embeddings", "dflt") == "dflt"
        assert qr.get("unknown", "dflt") == "dflt"

    def test_dict_compat_contains(self):
        qr = QueryResult(ids=[["a"]], documents=[["d"]], metadatas=[[{}]], distances=[[0.1]])
        assert "ids" in qr
        assert "embeddings" not in qr
        assert 123 not in qr  # type: ignore[operator]

    def test_empty_results(self):
        qe = QueryResult.empty(num_queries=2, embeddings_requested=True)
        assert qe.ids == [[], []]
        assert qe.embeddings == [[], []]
        assert GetResult.empty().ids == []

    def test_collection_defaults(self):
        col = _MemCol()
        col.add(documents=["doc one"], ids=["a"], metadatas=[{"nodo": "w"}])
        assert col.estimated_count() == 1
        assert col.close() is None
        assert col.health().ok is True

    def test_abstract_bodies_execute(self):
        col = _MemCol()
        assert BaseCollection.add(col, documents=["x"], ids=["i"]) is None
        assert BaseCollection.upsert(col, documents=["x"], ids=["i"]) is None
        assert BaseCollection.query(col, query_texts=["x"]) is None
        assert BaseCollection.get(col, ids=["i"]) is None
        assert BaseCollection.delete(col, ids=["i"]) is None
        assert BaseCollection.count(col) is None

    def test_update_requires_fields(self):
        with pytest.raises(ValueError, match="at least one"):
            _MemCol().update(ids=["a"])

    def test_update_length_mismatch(self):
        col = _MemCol()
        col.add(documents=["d"], ids=["a"])
        with pytest.raises(ValueError, match="does not match"):
            col.update(ids=["a"], documents=["x", "y"])

    def test_update_merges_documents_only(self):
        col = _MemCol()
        col.add(documents=["old doc"], ids=["a"], metadatas=[{"nodo": "w", "k": 1}])
        col.update(ids=["a"], documents=["new doc"])
        got = col.get(ids=["a"])
        assert got.documents == ["new doc"]
        assert got.metadatas[0]["nodo"] == "w"

    def test_update_merges_metadatas_and_creates_missing(self):
        col = _MemCol()
        col.add(documents=["d"], ids=["a"], metadatas=[{"nodo": "w"}])
        col.update(ids=["a", "ghost"], metadatas=[{"celda": "r"}, {"nodo": "g"}])
        got = col.get(ids=["a", "ghost"])
        assert got.metadatas[0] == {"nodo": "w", "celda": "r"}
        assert got.documents[1] == ""
        assert got.metadatas[1] == {"nodo": "g"}

    def test_backend_defaults_and_detect(self):
        be = _MemBackend()
        ref = MallaRef(id="x")
        try:
            assert be.close_malla(ref) is None
            assert be.close() is None
            assert be.health(ref).ok is True
            assert _MemBackend.detect("/whatever") is False
            assert BaseBackend.get_collection(be, malla=ref, collection_name="c") is None
        finally:
            be.close()


# ─── backend/sqlite gaps ──────────────────────────────────────────────────


class TestSqliteGaps:
    def test_where_empty_dict_matches_all(self, tmp_path: Path):
        from dxrk.memory.backend.sqlite import _where_to_sql

        assert _where_to_sql({}) == ("", [])

    def test_stored_embedding_variants(self):
        from dxrk.memory.backend.sqlite import _stored_embedding

        assert _stored_embedding('{"_embedding": [1.0, 2.0]}') == [1.0, 2.0]
        assert _stored_embedding("{}") == []
        assert _stored_embedding("{bad json") == []

    def test_store_vector_error_never_fails(self, tmp_path: Path):
        from dxrk.memory.backend.sqlite import SqliteCollection

        bad_cur = mock.MagicMock()
        bad_cur.execute.side_effect = sqlite3.Error("boom")
        assert SqliteCollection._store_vector(bad_cur, 1, "doc") is None

    def test_pool_vectors_select_error_returns_zeros(self, tmp_path: Path):
        be, _, col = _col(tmp_path)
        real = col._conn  # type: ignore[attr-defined]
        try:
            fake = mock.MagicMock()
            fake.execute.side_effect = sqlite3.Error("boom")
            fake.cursor.side_effect = sqlite3.Error("boom")
            col._conn = fake  # type: ignore[attr-defined]
            out = col._pool_vectors([("i1", "hello world content here", "{}", 7)])
            assert out == [[0.0] * VEC_DIM]
        finally:
            col._conn = real  # type: ignore[attr-defined]
            be.close()

    def test_pool_vectors_backfill_insert_error_keeps_vec(self, tmp_path: Path):
        be, _, col = _col(tmp_path)
        try:
            fake = mock.MagicMock()
            sel = mock.MagicMock()
            sel.fetchall.return_value = []
            fake.execute.return_value = sel
            bad_cur = mock.MagicMock()
            bad_cur.execute.side_effect = sqlite3.Error("boom")
            fake.cursor.return_value = bad_cur
            with mock.patch.object(col, "_conn", fake):
                out = col._pool_vectors([("i1", "hello world content here", "{}", 7)])
            assert len(out) == 1 and len(out[0]) == VEC_DIM
            assert sum(out[0]) > 0.0
        finally:
            be.close()

    def test_query_bad_embedding_values_fall_back_neutral(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "qbad")
        try:
            col.add(documents=["alpha beta gamma"], ids=["e1"], metadatas=[{"nodo": "w"}])
            q = col.query(query_embeddings=[["oops"] * VEC_DIM], n_results=5)
            assert q.ids[0] == ["e1"]
            assert q.distances[0] == [0.5]
        finally:
            be.close()

    def test_fetch_pool_recent_rows_error_keeps_fts(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "recent")
        try:
            col.add(documents=["hello mars"], ids=["e1"], metadatas=[{"nodo": "w"}])
            real = col._conn  # type: ignore[attr-defined]

            class _Wrap:
                def execute(self, sql, params=()):
                    if "ORDER BY rowid DESC" in str(sql):
                        raise sqlite3.Error("recent boom")
                    return real.execute(sql, params)

                def cursor(self):
                    return real.cursor()

                def commit(self):
                    return real.commit()

            col._conn = _Wrap()  # type: ignore[attr-defined]
            try:
                q = col.query(query_texts=["hello"], n_results=5)
            finally:
                col._conn = real  # type: ignore[attr-defined]
            assert "e1" in q.ids[0]
        finally:
            be.close()

    def test_rank_pool_no_signal_zero_cosine(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "rank0")
        try:
            col.add(documents=["hello world"], ids=["e1"], metadatas=[{"nodo": "w"}])
            assert col._rank_pool([], "", None) == []  # type: ignore[attr-defined]
            pool = col._fetch_pool("hello", "", [], None, 5)  # type: ignore[attr-defined]
            ranked = col._rank_pool(pool, "", None)  # type: ignore[attr-defined]
            assert len(ranked) == len(pool)
            for _, dist in ranked:
                assert 0.0 <= dist <= 1.0
        finally:
            be.close()

    def test_delete_missing_doc_vectors_ok(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "delvec")
        try:
            col.add(documents=["doc one here"], ids=["a1"], metadatas=[{"nodo": "w"}])
            col.add(documents=["doc two here"], ids=["a2"], metadatas=[{"nodo": "w"}])
            col._conn.execute("DROP TABLE IF EXISTS doc_vectors")  # type: ignore[attr-defined]
            col._conn.commit()  # type: ignore[attr-defined]
            col.delete(ids=["a1"])
            assert col.count() == 1
            col.delete(where={"nodo": "w"})
            assert col.count() == 0
        finally:
            be.close()


# ─── vectors gaps ─────────────────────────────────────────────────────────


class TestVectorsGaps:
    def test_embed_text_empty_returns_zeros(self):
        from dxrk.memory import vectors as vecs

        out = vecs.embed_text("")
        assert len(out) == VEC_DIM
        assert all(v == 0.0 for v in out)
        assert vecs.embed_text("   ") == out

    def test_decode_rejects(self):
        from dxrk.memory import vectors as vecs

        assert vecs.decode("not-bytes") is None  # type: ignore[arg-type]
        assert vecs.decode(None) is None  # type: ignore[arg-type]
        assert vecs.decode(b"short") is None

    def test_decode_roundtrip(self):
        from dxrk.memory import vectors as vecs

        blob = vecs.encode([1.0, 2.0, 3.0])
        assert vecs.decode(blob, dim=3) == [1.0, 2.0, 3.0]

    def test_cosine_empty_side_zero(self):
        from dxrk.memory import vectors as vecs

        assert vecs.cosine([0.0, 0.0], [1.0, 2.0]) == 0.0
        assert vecs.cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


# ─── search gaps ──────────────────────────────────────────────────────────


class _FakeGlobuloCol(BaseCollection):
    def __init__(self, docs, metas, dists, ids=None):
        self._docs = docs
        self._metas = metas
        self._dists = dists
        self._ids = ids or [f"d{i}" for i in range(len(docs))]
        self.seen_kwargs: list[dict] = []

    def add(self, *, documents, ids, metadatas=None, embeddings=None) -> None:
        raise NotImplementedError

    def upsert(self, *, documents, ids, metadatas=None, embeddings=None) -> None:
        raise NotImplementedError

    def query(
        self, *, query_texts=None, query_embeddings=None, n_results=10, where=None, where_document=None, include=None
    ) -> QueryResult:
        self.seen_kwargs.append({"where": where})
        return QueryResult(
            ids=[self._ids],
            documents=[self._docs],
            metadatas=[self._metas],
            distances=[self._dists],
            embeddings=None,
        )

    def get(self, *, ids=None, where=None, where_document=None, limit=None, offset=None, include=None) -> GetResult:
        return GetResult.empty()

    def delete(self, *, ids=None, where=None) -> None:
        return None

    def count(self) -> int:
        return len(self._ids)


class _BrokenResultCol(_FakeGlobuloCol):
    class _Broken:
        @property
        def ids(self):
            raise AttributeError("gone")

        documents = [[]]
        metadatas = [[]]
        distances = [[]]

    def query(self, **kw) -> object:  # type: ignore[override]
        return _BrokenResultCol._Broken()


class _BoomQueryCol(_FakeGlobuloCol):
    def query(self, **kw) -> QueryResult:
        raise RuntimeError("closet down")


def _meta(src: str) -> dict[str, object]:
    return {"nodo": "w", "celda": "r", "source_file": src}


class TestSearchGaps:
    def test_bm25_empty_doc_scores_zero(self):
        from dxrk.memory.search import _bm25_scores

        scores = _bm25_scores("hello", ["", "hello world"])
        assert scores[0] == 0.0
        assert scores[1] > 0.0

    def test_hybrid_rank_bad_distance_zero_sim(self):
        from dxrk.memory.search import _hybrid_rank

        rows = [{"text": "hello world here", "distance": "bad"}]
        out = _hybrid_rank(rows, "hello")
        assert out[0]["bm25_score"] > 0.0

    def test_hybrid_rank_nudge_variants(self):
        from dxrk.memory.search import _hybrid_rank

        rows = [{"text": "hello world", "distance": 0.5}]
        out = _hybrid_rank([dict(r) for r in rows], "hello", rank_nudge=[5.0])
        assert out[0]["bm25_score"] >= 0.0
        out2 = _hybrid_rank([dict(r) for r in rows], "hello", rank_nudge=["bad"])
        assert out2[0]["bm25_score"] >= 0.0

    def test_hybrid_search_invalid_window_raises(self, tmp_path: Path):
        from dxrk.memory.search import hybrid_search

        be, _, col = _col(tmp_path, "sw")
        try:
            with pytest.raises(ValueError, match="since"):
                hybrid_search(col, "hello", since="nonsense-date")
        finally:
            be.close()

    def test_hybrid_search_empty_query_envelope(self, tmp_path: Path):
        from dxrk.memory.search import hybrid_search

        be, _, col = _col(tmp_path, "se")
        try:
            out = hybrid_search(col, "   ", where={"nodo": "w"}, since="2024-01-01", before="2024-02-01")
            assert out["results"] == []
            assert out["total_before_filter"] == 0
            assert out["filters"] == {"nodo": "w", "since": "2024-01-01", "before": "2024-02-01"}
            out2 = hybrid_search(col, "")
            assert out2["filters"] == {}
        finally:
            be.close()

    def test_hybrid_search_broken_result_envelope(self):
        from dxrk.memory.search import hybrid_search

        out = hybrid_search(_BrokenResultCol(["d"], [{}], [0.5]), "hello")  # type: ignore[arg-type]
        assert out["results"] == []
        assert out["total_before_filter"] == 0

    def test_hybrid_search_forwards_where_to_closet(self):
        from dxrk.memory.search import hybrid_search

        fragmento = _FakeGlobuloCol(["hello world"], [_meta("/p/a.md")], [0.5], ids=["d0"])
        closet = _FakeGlobuloCol(["other"], [_meta("/p/b.md")], [0.9], ids=["c0"])
        out = hybrid_search(fragmento, "hello", where={"nodo": "w"}, closet_collection=closet)
        assert closet.seen_kwargs and closet.seen_kwargs[0]["where"] == {"nodo": "w"}
        assert len(out["results"]) == 1

    def test_hybrid_search_bad_closet_distance_ignored(self):
        from dxrk.memory.search import hybrid_search

        fragmento = _FakeGlobuloCol(["hello world"], [_meta("/p/a.md")], [0.5], ids=["d0"])
        closet = _FakeGlobuloCol(["hello there"], [_meta("/p/a.md")], ["bad"], ids=["c0"])
        out = hybrid_search(fragmento, "hello", closet_collection=closet)
        assert out["results"][0]["matched_via"] == "fragmento"
        assert out["results"][0]["closet_boost"] == 0.0

    def test_hybrid_search_closet_failure_still_returns(self):
        from dxrk.memory.search import hybrid_search

        fragmento = _FakeGlobuloCol(["hello world"], [_meta("/p/a.md")], [0.5], ids=["d0"])
        out = hybrid_search(fragmento, "hello", closet_collection=_BoomQueryCol([], [], []))
        assert len(out["results"]) == 1

    def test_hybrid_search_non_dict_meta_tolerated(self):
        from dxrk.memory.search import hybrid_search

        fragmento = _FakeGlobuloCol(["hello world"], ["notadict"], [0.5], ids=["d0"])  # type: ignore[list-item]
        out = hybrid_search(fragmento, "hello")
        assert out["results"][0]["nodo"] == "unknown"

    def test_hybrid_search_bad_distance_defaults(self):
        from dxrk.memory.search import hybrid_search

        fragmento = _FakeGlobuloCol(["hello world"], [_meta("/p/a.md")], ["bad"], ids=["d0"])
        out = hybrid_search(fragmento, "hello")
        assert out["results"][0]["distance"] == 1.0
        assert out["results"][0]["similarity"] == 0.0

    def test_hybrid_search_closet_boost_applied(self):
        from dxrk.memory.search import CLOSET_RANK_BOOSTS, hybrid_search

        fragmento = _FakeGlobuloCol(["hello world"], [_meta("/p/a.md")], [0.5], ids=["d0"])
        closet = _FakeGlobuloCol(["hello again"], [_meta("/p/a.md")], [0.1], ids=["c0"])
        out = hybrid_search(fragmento, "hello", closet_collection=closet)
        hit = out["results"][0]
        assert hit["matched_via"] == "fragmento+closet"
        assert hit["closet_boost"] == round(CLOSET_RANK_BOOSTS[0], 3)
        assert hit["effective_distance"] == pytest.approx(0.1)

    def test_hybrid_search_non_sqlite_nudge_path(self):
        from dxrk.memory.search import hybrid_search

        fragmento = _FakeGlobuloCol(
            ["alpha beta gamma", "delta epsilon zeta"],
            [_meta("/p/a.md"), _meta("/p/b.md")],
            [0.4, 0.6],
            ids=["d0", "d1"],
        )
        out = hybrid_search(fragmento, "alpha", n_results=2)
        assert [h["id"] for h in out["results"]] == ["d0", "d1"]

    def test_hybrid_search_date_truncation_flag(self, tmp_path: Path):
        from dxrk.memory.search import hybrid_search

        be, _, col = _col(tmp_path, "trunc")
        try:
            for i in range(20):
                col.add(
                    documents=[f"unique vocab alpha beta {i} gamma delta"], ids=[f"t{i}"], metadatas=[{"nodo": "w"}]
                )
            out = hybrid_search(col, "alpha", n_results=1, since="2020-01-01", before="2030-01-01")
            assert out.get("date_filter_pool_truncated") is True
            assert out["results"] == []
        finally:
            be.close()


# ─── graph gaps ───────────────────────────────────────────────────────────


class TestGraphGaps:
    def test_effective_tenant_variants(self, monkeypatch):
        from dxrk.memory import graph as kgm

        assert kgm._effective_tenant_id("  t1  ") == "t1"
        monkeypatch.setattr("dxrk.tenant.migration.is_migrated", lambda: False)
        assert kgm._effective_tenant_id(None) == ""
        monkeypatch.setattr(
            "dxrk.tenant.migration.is_migrated",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert kgm._effective_tenant_id(None) == ""

    def test_resolve_kg_path_variants(self, monkeypatch, tmp_path):
        from dxrk.memory import graph as kgm

        assert kgm._resolve_kg_path(None, "/tmp/x/db.sqlite3") == "/tmp/x/db.sqlite3"
        assert kgm._resolve_kg_path(None, "") == ""
        assert kgm._resolve_kg_path(None, "memory-only") == "memory-only"
        monkeypatch.setenv("DXRK_TENANT", "t9")
        assert "t9" in kgm._resolve_kg_path(None, None)
        monkeypatch.setattr(
            "dxrk.tenant.migration.tenant_root",
            lambda tid: (_ for _ in ()).throw(OSError("ro")),
        )
        assert kgm._resolve_kg_path(None, None) == kgm.DEFAULT_KG_PATH
        monkeypatch.delenv("DXRK_TENANT")
        monkeypatch.setattr("dxrk.tenant.migration.is_migrated", lambda: True)
        monkeypatch.setattr("dxrk.tenant.migration.tenant_root", lambda tid: tmp_path / tid)
        assert "default" in kgm._resolve_kg_path(None, None)
        monkeypatch.setattr(
            "dxrk.tenant.migration.is_migrated",
            lambda: (_ for _ in ()).throw(OSError("ro")),
        )
        assert kgm._resolve_kg_path(None, None) == kgm.DEFAULT_KG_PATH

    def test_sanitize_iso_blank(self):
        from dxrk.memory import graph as kgm

        assert kgm._sanitize_iso("   ", "valid_from") is None
        assert kgm._sanitize_iso(None, "valid_from") is None

    def test_date_key_helpers(self):
        from dxrk.memory import graph as kgm

        assert kgm._is_date_only("2024-01-01") is True
        assert kgm._is_date_only("nope") is False
        assert kgm._start_key(None) is None
        assert kgm._end_key(None) is None
        assert kgm._start_key("2024-06-01") == "2024-06-01T00:00:00Z"
        assert kgm._end_key("2024-06-01") == "2024-06-01T23:59:59Z"
        assert kgm._start_key("2024-06-01T10:00:00") == "2024-06-01T10:00:00"
        assert kgm._end_key("2024-06-01T10:00:00") == "2024-06-01T10:00:00"

    def test_init_chmod_failures_ignored(self, tmp_path, monkeypatch):
        from dxrk.memory.graph import KnowledgeGraph

        monkeypatch.setattr(Path, "chmod", lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
        kg = KnowledgeGraph(str(tmp_path / "kg.sqlite3"))
        try:
            assert kg.stats()["entities"] == 0
        finally:
            kg.close()

    def test_init_migrates_legacy_schema(self, tmp_path):
        from dxrk.memory.graph import KnowledgeGraph

        db = tmp_path / "oldkg.sqlite3"
        conn = sqlite3.connect(str(db))
        conn.executescript(
            "CREATE TABLE entities (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "type TEXT DEFAULT 'unknown', properties TEXT DEFAULT '{}', "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP);"
            "CREATE TABLE triples (id TEXT PRIMARY KEY, subject TEXT NOT NULL, "
            "predicate TEXT NOT NULL, object TEXT NOT NULL, valid_from TEXT, "
            "valid_to TEXT, confidence REAL DEFAULT 1.0, source_closet TEXT, "
            "source_file TEXT, extracted_at TEXT DEFAULT CURRENT_TIMESTAMP);"
        )
        conn.commit()
        conn.close()
        kg = KnowledgeGraph(str(db))
        try:
            tid = kg.add_triple("Alice", "mentioned_in", "a.md", source_file="/p/a.md", source_fragmento_id="d1")
            rows = kg.triples_for_source("/p/a.md")
            assert any(r["id"] == tid and r["source_fragmento_id"] == "d1" for r in rows)
        finally:
            kg.close()

    def test_close_error_ignored(self, tmp_path):
        from dxrk.memory.graph import KnowledgeGraph

        kg = KnowledgeGraph(str(tmp_path / "kgc.sqlite3"))
        bad = mock.MagicMock()
        bad.close.side_effect = sqlite3.Error("boom")
        kg._conn = bad
        kg.close()
        assert kg._conn is None

    def test_context_manager_closes(self, tmp_path):
        from dxrk.memory.graph import KnowledgeGraph

        with KnowledgeGraph(str(tmp_path / "kgm.sqlite3")) as kg:
            assert kg.stats()["triples"] == 0
        assert kg._conn is None

    def test_all_episodes_bad_limit_falls_back(self, tmp_path):
        from dxrk.memory.graph import KnowledgeGraph

        kg = KnowledgeGraph(str(tmp_path / "kge.sqlite3"))
        try:
            kg.add_triple("Alice", "mentioned_in", "a.md", source_file="/p/a.md")
            rows = kg.all_episodes(limit="bad")  # type: ignore[arg-type]
            assert len(rows) == 1
            assert rows[0]["source_file"] == "/p/a.md"
        finally:
            kg.close()

    def test_query_relationship_as_of(self, tmp_path):
        from dxrk.memory.graph import KnowledgeGraph

        kg = KnowledgeGraph(str(tmp_path / "kgr.sqlite3"))
        try:
            kg.add_triple("Alice", "knows", "Bob", valid_from="2020-01-01", valid_to="2020-06-01")
            kg.add_triple("Alice", "knows", "Cara")
            assert len(kg.query_relationship("knows")) == 2
            assert len(kg.query_relationship("knows", as_of="2020-03-01")) == 2
            current = kg.query_relationship("knows", as_of="2021-01-01")
            assert [r["object"] for r in current] == ["Cara"]
        finally:
            kg.close()

    def test_traverse_cycle_terminates(self, tmp_path):
        from dxrk.memory.graph import KnowledgeGraph

        kg = KnowledgeGraph(str(tmp_path / "kgt.sqlite3"))
        try:
            kg.add_triple("Alice", "knows", "Bob")
            kg.add_triple("Bob", "knows", "Alice")
            out = kg.traverse("Alice", depth=3)
            assert len(out) == 2
            assert {e["object"] for e in out} == {"Bob", "Alice"}
        finally:
            kg.close()


# ─── policy gaps ──────────────────────────────────────────────────────────


def _stale(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


class TestPolicyGaps:
    def test_is_dead_variants(self):
        from dxrk.memory.policy import _is_dead

        assert _is_dead("notadict") is False
        assert _is_dead({}) is False
        assert _is_dead({"forgotten": True}) is True

    def test_init_bad_coercions_fall_back(self, tmp_path):
        dm = _dm(tmp_path, name="pinit")
        try:
            eng = PolicyEngine(
                dm,
                sweep_window="bad",
                stale_days="bad",  # type: ignore[arg-type]
                min_interval_seconds="bad",
                scan_limit="bad",
            )  # type: ignore[arg-type]
            assert eng._sweep_window == CHECKSUM_SWEEP_WINDOW
            assert eng._stale_days == RESCORE_STALE_DAYS
            assert eng._min_interval == POLICY_MIN_INTERVAL_SECONDS
            assert eng._scan_limit == POLICY_SCAN_LIMIT
        finally:
            dm.close()

    def test_run_named_invalid(self, tmp_path):
        dm = _dm(tmp_path, name="pnamed")
        try:
            with pytest.raises(ValueError, match="invalid policy trigger"):
                PolicyEngine(dm)._run_named("nope")
        finally:
            dm.close()

    def test_over_budget_list_nodos_failure(self, tmp_path):
        dm = _dm(tmp_path, name="pob")
        try:
            boom = mock.MagicMock()
            boom.list_nodos.side_effect = RuntimeError("boom")
            assert PolicyEngine(boom)._run_over_budget() == {"nodos_over": [], "evicted": 0}
            partial = mock.MagicMock()
            partial.list_nodos.return_value = ["w"]
            partial.nodo_usage.side_effect = RuntimeError("boom")
            assert PolicyEngine(partial)._run_over_budget() == {"nodos_over": [], "evicted": 0}
            over = mock.MagicMock()
            over.list_nodos.return_value = ["w"]
            over.nodo_usage.return_value = {"over": True}
            over.enforce_nodo_cap.side_effect = RuntimeError("boom")
            assert PolicyEngine(over)._run_over_budget() == {"nodos_over": ["w"], "evicted": 0}
        finally:
            dm.close()

    def test_rescore_scan_failure(self, tmp_path):
        dm = _dm(tmp_path, name="prs")
        try:
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "get", side_effect=RuntimeError("db down")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                assert PolicyEngine(dm)._run_rescore_stale() == {"scanned": 0, "rescored": 0}
        finally:
            dm.close()

    def test_rescore_skips_and_coercions(self, tmp_path):
        dm = _dm(tmp_path, name="prsc")
        try:
            d1 = dm.add_fragmento("w", "r", _content("live stale fragmento alpha"), "/s1.md", 0)
            d2 = dm.add_fragmento("w", "r", _content("dead fragmento beta"), "/s2.md", 0)
            d3 = dm.add_fragmento("w", "r", _content("untouched fragmento gamma"), "/s3.md", 0)
            d4 = dm.add_fragmento("w", "r", _content("ledger fragmento delta"), "/s4.md", 0)
            d5 = dm.add_fragmento("w", "r", _content("coercion fragmento epsilon"), "/s5.md", 0)
            col = dm._collection(create=False)
            old = _stale(40)
            col.update(ids=[d1], metadatas=[{"filed_at": old, "score_ledger": [], "score_ledger_dropped": 0}])
            dm.forget([d2])
            col.update(ids=[d3], metadatas=[{"filed_at": None}])
            col.update(
                ids=[d4],
                metadatas=[
                    {
                        "filed_at": old,
                        "score_ledger": [{"ts": datetime.now(UTC).isoformat()}],
                        "score_ledger_dropped": 0,
                    }
                ],
            )
            col.update(
                ids=[d5],
                metadatas=[{"filed_at": old, "S": "bad", "D": "bad", "score_ledger": [], "score_ledger_dropped": 0}],
            )
            out = PolicyEngine(dm)._run_rescore_stale()
            assert out["scanned"] == 5
            assert out["rescored"] == 2
            got = col.get(ids=[d1], include=["metadatas"])
            assert len(got.metadatas[0].get("score_ledger", [])) >= 1  # type: ignore[union-attr]
        finally:
            dm.close()

    def test_rescore_persist_failure(self, tmp_path):
        dm = _dm(tmp_path, name="prp")
        try:
            did = dm.add_fragmento("w", "r", _content("stale persist alpha"), "/p.md", 0)
            col = dm._collection(create=False)
            col.update(ids=[did], metadatas=[{"filed_at": _stale(40), "score_ledger": [], "score_ledger_dropped": 0}])
            with (
                mock.patch.object(col, "update", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                out = PolicyEngine(dm)._run_rescore_stale()
            assert out == {"scanned": 1, "rescored": 0}
        finally:
            dm.close()

    def test_checksum_scan_failure(self, tmp_path):
        dm = _dm(tmp_path, name="pcs")
        try:
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "get", side_effect=RuntimeError("db down")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                assert PolicyEngine(dm)._run_checksum_sweep() == {
                    "checked": 0,
                    "ok": 0,
                    "rehashed": 0,
                    "mismatches": [],
                }
        finally:
            dm.close()

    def test_checksum_rehash_and_mismatch(self, tmp_path):
        dm = _dm(tmp_path, name="pcr")
        try:
            d1 = dm.add_fragmento("w", "r", _content("checksum alpha keeper"), "/c1.md", 0)
            col = dm._collection(create=False)
            col.upsert(
                documents=[_content("legacy row no checksum")], ids=["leg1"], metadatas=[{"nodo": "w", "celda": "r"}]
            )
            out = PolicyEngine(dm)._run_checksum_sweep()
            assert out["checked"] == 2
            assert out["ok"] == 1
            assert out["rehashed"] == 1
            col._conn.execute(
                "UPDATE embeddings SET document=? WHERE id=?",  # type: ignore[attr-defined]
                ("tampered entirely different", d1),
            )
            col._conn.commit()  # type: ignore[attr-defined]
            out2 = PolicyEngine(dm)._run_checksum_sweep()
            assert out2["mismatches"] == [d1]
        finally:
            dm.close()

    def test_checksum_bad_cursor_falls_back(self, tmp_path):
        dm = _dm(tmp_path, name="pcb")
        try:
            dm.add_fragmento("w", "r", _content("cursor alpha keeper"), "/c1.md", 0)
            (Path(dm.malla_path) / ".policy_state.json").write_text('{"cursor": "bad"}')
            out = PolicyEngine(dm)._run_checksum_sweep()
            assert out["checked"] == 1
        finally:
            dm.close()

    def test_checksum_window_fetch_failure(self, tmp_path):
        dm = _dm(tmp_path, name="pcw")
        try:
            dm.add_fragmento("w", "r", _content("window alpha keeper"), "/c1.md", 0)
            col = dm._collection(create=False)
            orig = col.get

            def _g(*a, **k):
                if "ids" in k:
                    raise RuntimeError("window boom")
                return orig(*a, **k)

            with mock.patch.object(col, "get", side_effect=_g), mock.patch.object(dm, "_collection", return_value=col):
                out = PolicyEngine(dm)._run_checksum_sweep()
            assert out == {"checked": 0, "ok": 0, "rehashed": 0, "mismatches": []}
        finally:
            dm.close()

    def test_checksum_rehash_persist_failure(self, tmp_path):
        dm = _dm(tmp_path, name="pch")
        try:
            col = dm._collection(create=False)
            col.upsert(documents=[_content("legacy rehash fail")], ids=["leg1"], metadatas=[{"nodo": "w"}])
            with (
                mock.patch.object(col, "update", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                out = PolicyEngine(dm)._run_checksum_sweep()
            assert out["checked"] == 1
            assert out["rehashed"] == 0
        finally:
            dm.close()

    def test_quarantine_scan_failure(self, tmp_path):
        dm = _dm(tmp_path, name="pqs")
        try:
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "get", side_effect=RuntimeError("db down")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                assert PolicyEngine(dm)._run_quarantine_sweep() == {"scanned": 0, "quarantined": [], "reasons": {}}
        finally:
            dm.close()

    def test_quarantine_sweep_reasons(self, tmp_path):
        dm = _dm(tmp_path, name="pqr")
        try:
            did = dm.add_fragmento("w", "r", _content("quarantine alpha keeper"), "/q1.md", 0)
            col = dm._collection(create=False)
            col.upsert(documents=[""], ids=["empty1"], metadatas=[{"nodo": "w"}])
            out = PolicyEngine(dm)._run_quarantine_sweep()
            assert out["scanned"] == 2
            assert out["quarantined"] == ["empty1"]
            assert out["reasons"] == {"empty1": "empty_document"}
            out2 = PolicyEngine(dm)._run_quarantine_sweep()
            assert out2["quarantined"] == []
            assert dm.quarantine_fragmento(did) is True
            out3 = PolicyEngine(dm)._run_quarantine_sweep()
            assert did not in out3["quarantined"]
        finally:
            dm.close()

    def test_quarantine_sweep_invalid_metadata(self, tmp_path):
        dm = _dm(tmp_path, name="pqm")
        try:

            class _OddCol:
                def get(self, **kw):
                    return GetResult(
                        ids=["ghost"],
                        documents=[""],
                        metadatas=["bad"],  # type: ignore[list-item]
                        embeddings=None,
                    )

            with mock.patch.object(dm, "_collection", return_value=_OddCol()):
                out = PolicyEngine(dm)._run_quarantine_sweep()
            assert out == {"scanned": 1, "quarantined": [], "reasons": {}}
        finally:
            dm.close()

    def test_quarantine_sweep_persist_failure(self, tmp_path):
        dm = _dm(tmp_path, name="pqf")
        try:

            class _EmptyCol:
                def get(self, **kw):
                    return GetResult(ids=["e1"], documents=[""], metadatas=[{}], embeddings=None)

            with (
                mock.patch.object(dm, "_collection", return_value=_EmptyCol()),
                mock.patch.object(dm, "quarantine_fragmento", side_effect=RuntimeError("boom")),
            ):
                out = PolicyEngine(dm)._run_quarantine_sweep()
            assert out == {"scanned": 1, "quarantined": [], "reasons": {}}
        finally:
            dm.close()

    def test_state_sentinel_paths(self, tmp_path):
        dm = pal.DxrkMemory("memory-only")
        eng = PolicyEngine(dm)
        assert eng._state_path() is None
        assert eng._read_state() == {}
        assert eng._write_state({"a": 1}) is None

    def test_state_path_exception_returns_none(self, tmp_path):
        dm = _dm(tmp_path, name="pse")
        try:
            with mock.patch("dxrk.memory.policy.Path", side_effect=Exception("boom")):
                assert PolicyEngine(dm)._state_path() is None
        finally:
            dm.close()

    def test_read_state_bad_json(self, tmp_path):
        dm = _dm(tmp_path, name="psr")
        try:
            (Path(dm.malla_path) / ".policy_state.json").write_text("{bad json")
            assert PolicyEngine(dm)._read_state() == {}
            (Path(dm.malla_path) / ".policy_state.json").write_text("[1, 2]")
            assert PolicyEngine(dm)._read_state() == {}
        finally:
            dm.close()

    def test_write_state_oserror_ignored(self, tmp_path):
        dm = _dm(tmp_path, name="psw")
        try:
            eng = PolicyEngine(dm)
            fake = mock.MagicMock()
            fake.parent.mkdir.return_value = None
            fake.write_text.side_effect = OSError("ro")
            with mock.patch.object(PolicyEngine, "_state_path", return_value=fake):
                assert eng._write_state({"a": 1}) is None
        finally:
            dm.close()

    def test_due_variants(self, tmp_path):
        dm = _dm(tmp_path, name="pdu")
        try:
            eng = PolicyEngine(dm, min_interval_seconds=900.0)
            now = datetime.now(UTC)
            assert eng._due({}, "rescore_stale", now) is True
            assert eng._due({"last_run": "bad"}, "rescore_stale", now) is True
            assert eng._due({"last_run": {}}, "rescore_stale", now) is True
            past = (now - timedelta(hours=2)).isoformat()
            assert eng._due({"last_run": {"rescore_stale": past}}, "rescore_stale", now) is True
            assert eng._due({"last_run": {"rescore_stale": now.isoformat()}}, "rescore_stale", now) is False
        finally:
            dm.close()

    def test_maybe_run_rbac_denied(self, tmp_path):
        dm = _dm(tmp_path, name="prb")
        try:
            with mock.patch(
                "dxrk.security.enforcement.require_op", side_effect=PermissionError("RBAC_DENIED: role=x op=maintain")
            ):
                with pytest.raises(PermissionError, match="RBAC_DENIED"):
                    PolicyEngine(dm).maybe_run("write")
        finally:
            dm.close()


# ─── malla helpers ─────────────────────────────────────────────────────────


class TestSangreHelpers:
    def test_read_text_oserror_and_close_error(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        f = root / "r.txt"
        f.write_text("retry content here")
        with (
            mock.patch("os.fdopen", side_effect=OSError("fdopen boom")),
            mock.patch("os.close", side_effect=OSError("close boom")),
        ):
            assert pal._read_text_no_follow_malla(f, root) is None

    def test_resolve_tenant_path_migrated(self, tmp_path, monkeypatch):
        # tid is empty only while not migrated; the default-tenant fallback
        # below runs when migration flips between the two checks (TOCTOU-tolerant).
        calls = {"n": 0}

        def _flip():
            calls["n"] += 1
            return calls["n"] >= 2

        monkeypatch.setattr("dxrk.tenant.migration.is_migrated", _flip)
        monkeypatch.setattr("dxrk.tenant.migration.tenant_root", lambda tid: tmp_path / "ten" / tid)
        assert str(pal._resolve_tenant_path(None, None)) == str(tmp_path / "ten" / "default" / "malla")

    def test_resolve_tenant_path_not_migrated(self, monkeypatch):
        monkeypatch.setattr("dxrk.tenant.migration.is_migrated", lambda: False)
        assert str(pal._resolve_tenant_path(None, None)).endswith(os.path.join(".dxrk", "malla"))

    def test_resolve_tenant_path_oserror_fallback(self, monkeypatch):
        monkeypatch.setattr(
            "dxrk.tenant.migration.is_migrated",
            lambda: (_ for _ in ()).throw(OSError("ro")),
        )
        assert str(pal._resolve_tenant_path(None, None)).endswith(os.path.join(".dxrk", "malla"))

    def test_acquire_mine_lock_file_releases_on_error(self, tmp_path):
        lf = mock.MagicMock()
        with (
            mock.patch("dxrk.memory.malla._open_mine_lock_file", return_value=lf),
            mock.patch("dxrk.memory.malla._acquire_open_mine_lock_file", side_effect=RuntimeError("boom")),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                pal._acquire_mine_lock_file(str(tmp_path / "a.lock"))
        lf.close.assert_called_once()

    def test_acquire_mine_lock_file_retries_stale(self, tmp_path):
        lf = mock.MagicMock()
        with (
            mock.patch("dxrk.memory.malla._open_mine_lock_file", return_value=lf),
            mock.patch("dxrk.memory.malla._acquire_open_mine_lock_file", side_effect=[False, True]),
        ):
            assert pal._acquire_mine_lock_file(str(tmp_path / "b.lock")) is lf
        assert lf.close.call_count == 1

    def test_cleanup_race_file_vanished(self, tmp_path):
        lp = str(tmp_path / "race.lock")
        lf = pal._open_mine_lock_file(lp, create=True)
        pal._lock_mine_lock_file(lf, blocking=True)
        pal._unlock_mine_lock_file(lf)
        lf.close()
        with mock.patch("os.remove", side_effect=FileNotFoundError("gone")):
            pal._cleanup_mine_lock_file(lp)
        assert Path(lp).exists()
        pal._cleanup_mine_lock_file(lp)
        assert not Path(lp).exists()

    def test_maybe_reap_failure_ignored(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "locks")
        with mock.patch("dxrk.memory.malla.reap_stale_dxrk_locks", side_effect=RuntimeError("boom")):
            pal._maybe_reap_stale_mine_locks()
            pal._maybe_reap_stale_mine_locks(tenant_id="t")

    def test_mine_lock_close_failure_ignored(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "locks")
        lf = mock.MagicMock()
        lf.close.side_effect = OSError("boom")
        with (
            mock.patch("dxrk.memory.malla._acquire_mine_lock_file", return_value=lf),
            mock.patch("dxrk.memory.malla._cleanup_mine_lock_file", return_value=None),
            mock.patch("dxrk.memory.malla._maybe_reap_stale_mine_locks", return_value=None),
            mock.patch("dxrk.memory.malla._mine_lock_path", return_value=str(tmp_path / "x.lock")),
        ):
            with pal.mine_lock("src-a"):
                pass

    def test_build_fragmento_metadata_bad_importance(self):
        meta = pal._build_fragmento_metadata(
            "w", "r", "/a.txt", 0, "dxrk", _content("hello world"), None, importance="bad"
        )  # type: ignore[arg-type]
        assert "importance" not in meta
        meta2 = pal._build_fragmento_metadata("w", "r", "/a.txt", 0, "dxrk", _content("hello world"), None, importance=3.0)
        assert meta2["importance"] == 3.0

    def test_overlap_empty(self):
        assert pal._overlap_coeff(set(), set()) == 0.0
        assert pal._overlap_coeff({"a"}, set()) == 0.0

    def test_distill_fallback_and_caps(self):
        assert pal._distill_sentences([""], max_chars=10, max_sentences=3) == ""
        dup = "The deployment shipped on Friday morning. The deployment shipped on Friday morning."
        out = pal._distill_sentences([dup], max_chars=500, max_sentences=5)
        assert out == "The deployment shipped on Friday morning."
        many = (
            "Alpha release shipped Friday morning. Beta rollback finished Saturday noon. "
            "Gamma migration started Sunday evening. Delta deploy paused Monday dawn. "
            "Epsilon monitor recovered Tuesday midnight."
        )
        out2 = pal._distill_sentences([many], max_chars=500, max_sentences=2)
        assert len(pal._split_sentences(out2)) == 2
        out3 = pal._distill_sentences([many], max_chars=50, max_sentences=5)
        assert len(pal._split_sentences(out3)) == 1
        assert len(out3) <= 50

    def test_one_line_truncates(self):
        assert pal._one_line("hello world", 5) == "he..."
        assert pal._one_line("hi", 50) == "hi"

    def test_filed_before_variants(self):
        before = datetime(2024, 6, 1)
        assert pal._filed_before("2024-01-01T00:00:00+00:00", before) is True
        assert pal._filed_before("2024-07-01T00:00:00+00:00", before) is False
        assert pal._filed_before(123, before) is False
        assert pal._filed_before("garbage", before) is False
        assert pal._filed_before("", before) is False

    def test_classify_mid_overlap_distinct(self, monkeypatch):
        monkeypatch.setattr(pal, "_vec_similarity", lambda a, b: 0.95)
        new = "alpha beta gamma delta epsilon zeta"
        old = "alpha beta gamma delta kappa lambda"
        assert pal.classify_content_pair(new, old) == "distinct"
        assert pal.classify_content_pair(new, new) == "duplicate"

    def test_is_dead_meta_non_dict(self):
        assert pal._is_dead_meta(["x"]) is False
        assert pal._is_dead_meta(None) is False

    def test_apply_access_bad_casts(self):
        meta = {
            "S": "bad",
            "D": "bad",
            "rd": "bad",
            "s_updates": "bad",
            "access_count": "bad",
            "access_count_total": "bad",
        }
        out = pal._apply_access(dict(meta), "2026-01-01T00:00:00+00:00")
        assert isinstance(out["S"], float)
        assert out["s_updates"] == 1
        assert out["access_count"] == 1
        assert out["access_count_total"] == 1

    def test_lapse_bad_casts_and_failures(self, monkeypatch):
        meta = {"S": "bad", "D": "bad", "rd": "bad", "s_updates": "bad"}
        out = pal._lapse_meta_in_place(dict(meta), "forgotten")
        assert isinstance(out["S"], float)
        assert out["s_updates"] == 1
        monkeypatch.setattr(pal, "ledger_append", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        out2 = pal._lapse_meta_in_place({"S": 1.0}, "forgotten")
        assert out2["S"] <= 1.0
        monkeypatch.setattr(pal, "ensure_spine_defaults", lambda m: (_ for _ in ()).throw(RuntimeError("boom")))
        keep = {"S": 1.0}
        assert pal._lapse_meta_in_place(keep, "forgotten") is keep

    def test_nodo_snapshot_variants(self, tmp_path):
        dm = _dm(tmp_path, name="snap")
        try:
            col = dm._collection(create=False)

            class _SnapStub:
                def get(self, **kw):
                    return GetResult(
                        ids=["a", "b"],
                        documents=["doc a here", ""],
                        metadatas=["bad", {"nodo": "w", "quarantined": True}],  # type: ignore[list-item]
                        embeddings=None,
                    )

            snap = pal._nodo_snapshot(_SnapStub(), "w")  # type: ignore[arg-type]
            assert [e["id"] for e in snap] == ["a"]
            assert snap[0]["meta"] == {}

            class _BoomStub:
                def get(self, **kw):
                    raise RuntimeError("boom")

            assert pal._nodo_snapshot(_BoomStub(), "w") == []  # type: ignore[arg-type]
            assert pal._nodo_snapshot(col, "w") == []
        finally:
            dm.close()

    def test_best_lifecycle_branches(self):
        snap = [
            {"id": "skip", "doc": "quantum garden lunar festival", "meta": {"nodo": "w"}},
            {"id": "dead", "doc": "quantum garden lunar festival", "meta": {"nodo": "w", "valid_to": "x"}},
            {"id": "empty", "doc": "", "meta": {"nodo": "w"}},
            {"id": "exact", "doc": "target content repeated here", "meta": {"nodo": "w"}},
        ]
        best, sim = pal._best_lifecycle_candidate(snap, "target content repeated here", exclude_ids={"skip"})
        assert best is not None and best["id"] == "exact" and sim == 1.0
        assert pal._best_lifecycle_candidate([], "zzz") == (None, 0.0)

    def test_init_bad_max_entries(self, tmp_path):
        dm = pal.DxrkMemory(str(tmp_path / "badcap"), max_entries_per_nodo="bad")  # type: ignore[arg-type]
        assert dm._max_entries_per_nodo == pal.DEFAULT_MAX_ENTRIES_PER_NODO


# ─── malla fragmentos ─────────────────────────────────────────────────────────


class _BoomGetCol:
    def __init__(self, real):
        self._real = real

    def get(self, **kw):
        raise RuntimeError("read boom")

    def __getattr__(self, name):
        return getattr(self._real, name)


class _BadMetaCol:
    def __init__(self, real):
        self._real = real

    def get(self, **kw):
        return GetResult(
            ids=["x"],
            documents=["doc x"],
            metadatas=["bad"],  # type: ignore[list-item]
            embeddings=None,
        )

    def __getattr__(self, name):
        return getattr(self._real, name)


class TestSangreGlobulos:
    def test_add_fragmento_same_id_read_failure(self, tmp_path):
        dm = _dm(tmp_path, name="sameid")
        try:
            col = dm._collection(create=True)
            boom = _BoomGetCol(col)
            with mock.patch.object(dm, "_collection", return_value=boom):
                did = dm.add_fragmento("w", "r", _content("same id read fail alpha"), "/n1.md", 0)
            assert did.startswith("fragmento_")
            assert dm.get_fragmento(did) is not None
        finally:
            dm.close()

    def test_add_fragmento_dedupe_bad_seen_count(self, tmp_path):
        dm = _dm(tmp_path, name="dedupe")
        try:
            first = dm.add_fragmento("w", "r", _content("victim original text omega"), "/f1.md", 0)
            col = dm._collection(create=False)
            col.update(ids=[first], metadatas=[{"seen_count": "bad"}])
            did = dm.add_fragmento("w", "r", _content("victim original text omega"), "/f2.md", 0)
            assert did == first
            got = col.get(ids=[first], include=["metadatas"])
            assert got.metadatas[0]["seen_count"] == 1
        finally:
            dm.close()

    def test_add_fragmento_dedupe_touch_failure(self, tmp_path):
        dm = _dm(tmp_path, name="dedupf")
        try:
            first = dm.add_fragmento("w", "r", _content("touch fail victim sigma"), "/f1.md", 0)
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "update", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                did = dm.add_fragmento("w", "r", _content("touch fail victim sigma"), "/f2.md", 0)
            assert did == first
        finally:
            dm.close()

    def test_add_fragmento_contradiction_supersedes(self, tmp_path, monkeypatch):
        dm = _dm(tmp_path, name="contra")
        try:
            old = dm.add_fragmento("w", "r", _content("contradiction victim tau"), "/old.md", 0)
            col = dm._collection(create=False)
            victim = {
                "id": old,
                "doc": _content("contradiction victim tau"),
                "meta": dict(col.get(ids=[old], include=["metadatas"]).metadatas[0]),
            }
            monkeypatch.setattr(pal, "_best_lifecycle_candidate", lambda *a, **k: (victim, 0.99))
            monkeypatch.setattr(pal, "classify_content_pair", lambda *a, **k: "contradiction")
            new_id = dm.add_fragmento("w", "r", _content("brand new replacement text kappa"), "/new.md", 0)
            assert new_id != old
            assert col.get(ids=[old], include=["metadatas"]).metadatas[0]["valid_to"]
        finally:
            dm.close()

    def test_add_fragmento_distinct_with_best_inserts(self, tmp_path, monkeypatch):
        dm = _dm(tmp_path, name="dist")
        try:
            old = dm.add_fragmento("w", "r", _content("distinct victim iota keeper"), "/old.md", 0)
            col = dm._collection(create=False)
            victim = {
                "id": old,
                "doc": _content("distinct victim iota keeper"),
                "meta": dict(col.get(ids=[old], include=["metadatas"]).metadatas[0]),
            }
            monkeypatch.setattr(pal, "_best_lifecycle_candidate", lambda *a, **k: (victim, 0.99))
            monkeypatch.setattr(pal, "classify_content_pair", lambda *a, **k: "distinct")
            new_id = dm.add_fragmento("w", "r", _content("brand new distinct text lambda"), "/new.md", 0)
            assert new_id != old
            assert dm.get_fragmento(new_id) is not None
        finally:
            dm.close()

    def test_mark_superseded_variants(self, tmp_path):
        dm = _dm(tmp_path, name="marks")
        try:
            did = dm.add_fragmento("w", "r", _content("mark superseded alpha"), "/m.md", 0)
            col = dm._collection(create=False)
            marked, pre = pal.DxrkMemory._mark_superseded(col, did, "new1", "2026-01-01T00:00:00+00:00")
            assert marked is True
            assert "valid_to" not in pre
            marked2, _ = pal.DxrkMemory._mark_superseded(col, "missing_xyz", "new1", "2026-01-01T00:00:00+00:00")
            assert marked2 is False
            boom = _BoomGetCol(col)
            assert pal.DxrkMemory._mark_superseded(boom, did, "n", "t") == (False, None)  # type: ignore[arg-type]
            bad = _BadMetaCol(col)
            marked3, pre3 = pal.DxrkMemory._mark_superseded(bad, "x", "y", "2026-01-01T00:00:00+00:00")  # type: ignore[arg-type]
            assert marked3 is True and pre3 == {}
            fresh = dm.add_fragmento("w", "r", _content("mark fail target beta"), "/m2.md", 0)
            with mock.patch.object(col, "update", side_effect=RuntimeError("boom")):
                marked4, _ = pal.DxrkMemory._mark_superseded(col, fresh, "n2", "2026-01-01T00:00:00+00:00")
                assert marked4 is False
        finally:
            dm.close()

    def test_nodo_cap_scan_failure(self, tmp_path):
        dm = _dm(tmp_path, name="wcap")
        try:
            col = dm._collection(create=False)
            boom = _BoomGetCol(col)
            assert dm._enforce_nodo_cap_once(boom, "w", 10) == (0, 0, False)  # type: ignore[arg-type]
        finally:
            dm.close()

    def test_nodo_cap_delete_failure_keeps_rows(self, tmp_path):
        dm = _dm(tmp_path, name="wcapd")
        try:
            dm.add_fragmento("w", "r", _content("cap row alpha one"), "/a1.md", 0)
            dm.add_fragmento("w", "r", _content("cap row beta two"), "/a2.md", 0)
            dm._max_entries_per_nodo = 1
            col = dm._collection(create=False)
            with mock.patch.object(col, "delete", side_effect=RuntimeError("boom")):
                assert dm._enforce_nodo_cap(col, "w") == 0
            assert col.count() == 2
        finally:
            dm.close()

    def test_consolidate_read_failure(self, tmp_path):
        dm = _dm(tmp_path, name="conr")
        try:
            col = dm._collection(create=True)
            with (
                mock.patch.object(col, "get", side_effect=RuntimeError("db down")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                with pytest.raises(ValueError, match="consolidate read failed"):
                    dm.consolidate_fragmentos(["a", "b"])
        finally:
            dm.close()

    def test_consolidate_empty_distillate(self, tmp_path, monkeypatch):
        dm = _dm(tmp_path, name="cone")
        try:
            d1 = dm.add_fragmento("w", "r", _content("consolidate source alpha"), "/ca.md", 0)
            d2 = dm.add_fragmento("w", "r", _content("consolidate source beta"), "/cb.md", 0)
            monkeypatch.setattr(pal, "_distill_sentences", lambda texts, **k: "")
            with pytest.raises(ValueError, match="empty distillate"):
                dm.consolidate_fragmentos([d1, d2])
        finally:
            dm.close()

    def test_consolidate_bad_importance_tolerated(self, tmp_path):
        dm = _dm(tmp_path, name="coni")
        try:
            d1 = dm.add_fragmento("w", "r", "The migration shipped on Friday. Rollback plan approved. " * 6, "/ca.md", 0)
            d2 = dm.add_fragmento("w", "r", "The migration shipped on Friday. Monitoring enabled after. " * 6, "/cb.md", 0)
            col = dm._collection(create=False)
            col.update(ids=[d1], metadatas=[{"importance": "bad"}])
            out = dm.consolidate_fragmentos([d1, d2])
            assert out["sources"] == 2
        finally:
            dm.close()

    def test_forget_ids_read_failure(self, tmp_path):
        dm = _dm(tmp_path, name="forg")
        try:
            did = dm.add_fragmento("w", "r", _content("forget read fail alpha"), "/g.md", 0)
            col = dm._collection(create=False)
            orig = col.get

            def _g(*a, **k):
                if "ids" in k:
                    raise RuntimeError("read boom")
                return orig(*a, **k)

            with mock.patch.object(col, "get", side_effect=_g), mock.patch.object(dm, "_collection", return_value=col):
                out = dm.forget(fragmento_ids=[did])
            assert out["matched"] == 0
        finally:
            dm.close()

    def test_forget_hard_delete_failure(self, tmp_path):
        dm = _dm(tmp_path, name="forgh")
        try:
            did = dm.add_fragmento("w", "r", _content("forget hard fail alpha"), "/h.md", 0)
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "delete", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                out = dm.forget(fragmento_ids=[did], hard=True)
            assert out["matched"] == 1
            assert out["deleted"] == 0
        finally:
            dm.close()

    def test_forget_soft_mark_failure(self, tmp_path):
        dm = _dm(tmp_path, name="forgs")
        try:
            did = dm.add_fragmento("w", "r", _content("forget soft fail alpha"), "/s.md", 0)
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "update", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                out = dm.forget(fragmento_ids=[did])
            assert out["matched"] == 1
            assert out["soft_forgotten"] == 0
        finally:
            dm.close()

    def test_forget_kg_failures_ignored(self, tmp_path):
        dm = _dm(tmp_path, name="forgk")
        try:
            did = dm.add_fragmento("w", "r", _content("forget kg fail alpha"), "/k.md", 0)
            kgm = mock.MagicMock()
            kgm.supersede_source.side_effect = RuntimeError("kg boom")
            kgm.close.side_effect = RuntimeError("close boom")
            with mock.patch.object(dm, "_kg_or_none", return_value=kgm):
                out = dm.forget(fragmento_ids=[did], include_kg=True)
            assert out["matched"] == 1
            assert out["kg_superseded"] == 0
            dm2 = pal.DxrkMemory(str(tmp_path / "nokg"), auto_kg=False)
            dm2.init()
            try:
                out2 = dm2.forget(fragmento_ids=["x"], include_kg=True)
                assert out2["kg_superseded"] == 0
            finally:
                dm2.close()
        finally:
            dm.close()

    def test_pin_unpin_quarantine_lapse_read_failures(self, tmp_path):
        dm = _dm(tmp_path, name="pinx")
        try:
            col = dm._collection(create=False)
            boom = _BoomGetCol(col)
            with mock.patch.object(dm, "_collection", return_value=boom):
                assert dm.pin_fragmento("x") is False
                assert dm.unpin_fragmento("x") is False
                assert dm.quarantine_fragmento("x") is False
                assert dm.unquarantine_fragmento("x") is False
                assert dm.record_lapse("x") is False
        finally:
            dm.close()

    def test_pin_idempotent_and_failures(self, tmp_path):
        dm = _dm(tmp_path, name="pini")
        try:
            did = dm.add_fragmento("w", "r", _content("pin idempotent alpha"), "/p.md", 0)
            assert dm.pin_fragmento(did) is True
            assert dm.pin_fragmento(did) is True
            assert dm.pin_fragmento("missing_xyz") is False
            did2 = dm.add_fragmento("w", "r", _content("pin fail beta keeper"), "/p2.md", 0)
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "upsert", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                assert dm.pin_fragmento(did2) is False
                assert dm.unpin_fragmento(did) is False
        finally:
            dm.close()

    def test_pin_unpin_non_dict_meta(self, tmp_path):
        dm = _dm(tmp_path, name="pinn")
        try:
            col = dm._collection(create=False)
            bad = _BadMetaCol(col)
            with mock.patch.object(dm, "_collection", return_value=bad):
                assert dm.pin_fragmento("x") is True
                assert dm.unpin_fragmento("x") is True
        finally:
            dm.close()

    def test_quarantine_idempotent_and_failures(self, tmp_path):
        dm = _dm(tmp_path, name="quar")
        try:
            did = dm.add_fragmento("w", "r", _content("quarantine idempotent alpha"), "/q.md", 0)
            assert dm.quarantine_fragmento(did, reason="r1") is True
            assert dm.quarantine_fragmento(did, reason="r2") is True
            assert dm.quarantine_fragmento("missing_xyz") is False
            did2 = dm.add_fragmento("w", "r", _content("quarantine fail beta"), "/q2.md", 0)
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "upsert", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                assert dm.quarantine_fragmento(did2) is False
        finally:
            dm.close()

    def test_unquarantine_variants(self, tmp_path):
        dm = _dm(tmp_path, name="unq")
        try:
            did = dm.add_fragmento("w", "r", _content("unquarantine alpha keeper"), "/u.md", 0)
            assert dm.unquarantine_fragmento(did) is True
            assert dm.unquarantine_fragmento("missing_xyz") is False
            assert dm.quarantine_fragmento(did, reason="r") is True
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "upsert", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                assert dm.unquarantine_fragmento(did) is False
            assert dm.unquarantine_fragmento(did) is True
            got = dm.get_fragmento(did)
            assert got is not None and got["document"] != ""
        finally:
            dm.close()

    def test_record_lapse_variants(self, tmp_path):
        dm = _dm(tmp_path, name="lapse")
        try:
            did = dm.add_fragmento("w", "r", _content("lapse alpha keeper"), "/l.md", 0)
            assert dm.record_lapse(did) is True
            assert dm.record_lapse("missing_xyz") is False
            got = dm.get_fragmento(did)
            assert got is not None
            assert len(got["metadata"].get("score_ledger", [])) >= 2  # type: ignore[union-attr]
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "upsert", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                assert dm.record_lapse(did) is False
        finally:
            dm.close()

    def test_list_fragmentos_variants(self, tmp_path):
        dm = _dm(tmp_path, name="listd")
        try:
            d1 = dm.add_fragmento("w", "r1", _content("list alpha keeper"), "/l1.md", 0)
            dm.add_fragmento("w", "r2", _content("list beta keeper"), "/l2.md", 0)
            assert len(dm.list_fragmentos(nodo="w", celda="r1")) == 1
            assert len(dm.list_fragmentos(celda="r2")) == 1
            assert len(dm.list_fragmentos(limit="bad")) == 2  # type: ignore[arg-type]
            assert dm.quarantine_fragmento(d1) is True
            assert all(r["id"] != d1 for r in dm.list_fragmentos())
            inc = dm.list_fragmentos(include_quarantined=True)
            stub = next(r for r in inc if r["id"] == d1)
            assert stub["quarantined"] is True
            assert "document" not in stub
            col = dm._collection(create=False)
            boom = _BoomGetCol(col)
            with mock.patch.object(dm, "_collection", return_value=boom):
                assert dm.list_fragmentos() == []
        finally:
            dm.close()

    def test_pins_path_exception(self, tmp_path):
        dm = _dm(tmp_path, name="pinp")
        try:
            dm.malla_path = 123  # type: ignore[assignment]
            assert dm._pins_path() is None
        finally:
            dm.close()

    def test_pins_roundtrip_and_failures(self, tmp_path):
        dm = _dm(tmp_path, name="pins")
        try:
            (Path(dm.malla_path) / "pins.json").write_text("{bad")
            assert dm._read_pins() == {}
            (Path(dm.malla_path) / "pins.json").write_text("[1]")
            assert dm._read_pins() == {}
            rec = dm.pin_identity()
            assert rec["scope"] == "identity"
            assert dm.unpin_identity() is True
            assert dm.unpin_identity() is False
            rec = dm.pin_identity()
            with mock.patch.object(Path, "write_text", side_effect=OSError("ro")):
                rec2 = dm.pin_identity()
                assert "sidecar write failed" in str(rec2.get("note", ""))
                assert dm.unpin_identity() is False
            mem = pal.DxrkMemory("memory-only")
            assert "note" in mem.pin_identity()
            assert mem.unpin_identity() is False
        finally:
            dm.close()

    def test_spine_counters_variants(self, tmp_path):
        dm = _dm(tmp_path, name="spc")
        try:
            assert dm.spine_counters() == {"checksum_mismatches": 0}
            assert dm._bump_spine_counter("checksum_mismatches") == 1
            assert dm._bump_spine_counter("checksum_mismatches") == 2
            (Path(dm.malla_path) / "spine_counters.json").write_text("{bad")
            assert dm._read_spine_counters() == {}
            (Path(dm.malla_path) / "spine_counters.json").write_text("[1]")
            assert dm._read_spine_counters() == {}
            (Path(dm.malla_path) / "spine_counters.json").write_text('{"a": "bad", "b": 2}')
            assert dm._read_spine_counters() == {"b": 2}
            mem = pal.DxrkMemory("memory-only")
            assert mem._bump_spine_counter("x") == 0
            with mock.patch.object(Path, "write_text", side_effect=OSError("ro")):
                assert dm._bump_spine_counter("x") == 0
        finally:
            dm.close()

    def test_usage_budgets_status_mix(self, tmp_path):
        dm = _dm(tmp_path, name="mix")
        try:
            d_pin = dm.add_fragmento("w", "r", _content("mix pinned alpha keeper"), "/p.md", 0)
            d_sup = dm.add_fragmento("w", "r", _content("mix superseded beta keeper"), "/s.md", 0)
            dm.add_fragmento("w", "r", _content("mix replacement gamma keeper"), "/s2.md", 0, supersedes=d_sup)
            d_for = dm.add_fragmento("w", "r", _content("mix forgotten delta keeper"), "/f.md", 0)
            dm.forget([d_for])
            d_qua = dm.add_fragmento("w", "r", _content("mix quarantined epsilon keeper"), "/q.md", 0)
            dm.quarantine_fragmento(d_qua)
            assert dm.pin_fragmento(d_pin) is True
            col = dm._collection(create=False)
            col.upsert(
                documents=[_content("mix legacy zeta keeper")], ids=["legacy1"], metadatas=[{"nodo": "w", "celda": "r"}]
            )
            u = dm.nodo_usage("w")
            assert u["count"] == 6
            assert u["pinned"] == 1
            assert u["superseded"] == 2
            assert u["forgotten"] == 1
            assert u["quarantined"] == 1
            assert u["needs_rehash"] == 1
            b = dm.budgets()
            assert b["w"]["count"] == 6
            assert b["w"]["needs_rehash"] == 1
            st = dm.status()
            assert st["count"] == 6
            assert st["quarantine_warning"] is True
            assert len(st["merkle_root"]) == 64
            col.upsert(documents=["odd"], ids=["odd1"], metadatas=[{"nodo": 123}])  # type: ignore[dict-item]
            assert 123 not in dm.budgets()
        finally:
            dm.close()

    def test_usage_budgets_status_failures(self, tmp_path):
        dm = _dm(tmp_path, name="mixf")
        try:
            dm.add_fragmento("w", "r", _content("mix fail alpha keeper"), "/a.md", 0)
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "get", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                u = dm.nodo_usage("w")
                assert u["count"] == 0
                assert dm.budgets() == {}
                st = dm.status()
                assert st["count"] == 0
                assert st["merkle_root"] == ""
        finally:
            dm.close()

    def test_get_fragmento_checksum_mismatch_quarantines(self, tmp_path):
        dm = _dm(tmp_path, name="chk")
        try:
            did = dm.add_fragmento("w", "r", _content("checksum tamper alpha keeper"), "/o.md", 0)
            col = dm._collection(create=False)
            col._conn.execute(
                "UPDATE embeddings SET document=? WHERE id=?",  # type: ignore[attr-defined]
                ("tampered entirely different", did),
            )
            col._conn.commit()  # type: ignore[attr-defined]
            got = dm.get_fragmento(did)
            assert got is not None
            assert got["quarantined"] is True
            assert got["quarantine_reason"] == "checksum_mismatch"
            assert "document" not in got
        finally:
            dm.close()

    def test_get_fragmento_quarantine_persist_failure(self, tmp_path):
        dm = _dm(tmp_path, name="chkf")
        try:
            did = dm.add_fragmento("w", "r", _content("quarantine persist alpha"), "/o.md", 0)
            col = dm._collection(create=False)
            col._conn.execute(
                "UPDATE embeddings SET document=? WHERE id=?",  # type: ignore[attr-defined]
                ("tampered entirely different", did),
            )
            col._conn.commit()  # type: ignore[attr-defined]
            with (
                mock.patch.object(col, "update", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                got = dm.get_fragmento(did)
            assert got is not None and got["quarantined"] is True
        finally:
            dm.close()

    def test_get_fragmento_access_fallback(self, tmp_path):
        dm = _dm(tmp_path, name="acc")
        try:
            did = dm.add_fragmento("w", "r", _content("access fallback alpha keeper"), "/a.md", 0)
            col = dm._collection(create=False)
            col.update(ids=[did], metadatas=[{"access_count": "bad"}])
            with mock.patch("dxrk.memory.malla._apply_access", side_effect=RuntimeError("boom")):
                got = dm.get_fragmento(did)
            assert got is not None
            assert got["document"] == _content("access fallback alpha keeper")
            assert got["metadata"]["access_count"] == 1
        finally:
            dm.close()

    def test_get_fragmento_access_bump_failure(self, tmp_path):
        dm = _dm(tmp_path, name="accb")
        try:
            did = dm.add_fragmento("w", "r", _content("access bump fail alpha keeper"), "/a.md", 0)
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "update", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                got = dm.get_fragmento(did)
            assert got is not None and got["document"] != ""
        finally:
            dm.close()

    def test_get_fragmento_dead_writeback_failure(self, tmp_path):
        dm = _dm(tmp_path, name="dead")
        try:
            old = dm.add_fragmento("w", "r", _content("dead writeback alpha keeper"), "/o.md", 0)
            dm.add_fragmento("w", "r", _content("dead replacement beta keeper"), "/n.md", 0, supersedes=old)
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "update", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                got = dm.get_fragmento(old)
            assert got is not None
            assert got["document"] == _content("dead writeback alpha keeper")
        finally:
            dm.close()


# ─── malla mine / timeline / kg ────────────────────────────────────────────


class TestSangreMineTimeline:
    def _proj(self, tmp_path: Path, name: str = "proj") -> Path:
        proj = tmp_path / name
        proj.mkdir(exist_ok=True)
        (proj / "n.md").write_text(_content("fresh file content omega", 30))
        return proj

    def test_mine_closets_fetch_failure(self, tmp_path):
        from dxrk.memory.backend.base import CollectionNotInitializedError

        proj = self._proj(tmp_path)
        dm = _dm(tmp_path, name="mclos")
        try:
            real = dm._collection

            def _fake(name="dxrk_fragmentos", *, create=True):
                if name == "dxrk_closets":
                    raise CollectionNotInitializedError("no closets")
                return real(name, create=create)

            with mock.patch.object(dm, "_collection", side_effect=_fake):
                out = dm.mine(str(proj))
            assert out["files_mined"] == 1
        finally:
            dm.close()

    def test_mine_closet_purge_failure_ignored(self, tmp_path):
        proj = self._proj(tmp_path)
        dm = _dm(tmp_path, name="mclos2")
        try:
            real = dm._collection
            closets = mock.MagicMock()
            closets.delete.side_effect = RuntimeError("closet purge boom")

            def _fake(name="dxrk_fragmentos", *, create=True):
                if name == "dxrk_closets":
                    return closets
                return real(name, create=create)

            with mock.patch.object(dm, "_collection", side_effect=_fake):
                out = dm.mine(str(proj))
            assert out["files_mined"] == 1
        finally:
            dm.close()

    def test_mine_dedupe_bad_seen_count(self, tmp_path, monkeypatch):
        proj = self._proj(tmp_path)
        dm = _dm(tmp_path, name="mded")
        try:
            vdid = dm.add_fragmento("w", "r", _content("mine victim omega keeper"), "/victim.md", 0)
            col = dm._collection(create=True)
            col.update(ids=[vdid], metadatas=[{"seen_count": "bad"}])
            victim = {
                "id": vdid,
                "doc": _content("mine victim omega keeper"),
                "meta": {"nodo": "w", "seen_count": "bad"},
            }
            monkeypatch.setattr(pal, "_best_lifecycle_candidate", lambda *a, **k: (victim, 0.99))
            monkeypatch.setattr(pal, "classify_content_pair", lambda *a, **k: "duplicate")
            out = dm.mine(str(proj), nodo="w", celda="r")
            assert out["fragmentos_deduped"] == 1
            assert col.get(ids=[vdid], include=["metadatas"]).metadatas[0]["seen_count"] == 1
        finally:
            dm.close()

    def test_mine_dedupe_touch_failure_counted(self, tmp_path, monkeypatch):
        proj = self._proj(tmp_path)
        dm = _dm(tmp_path, name="mded2")
        try:
            vdid = dm.add_fragmento("w", "r", _content("mine touch victim sigma"), "/victim.md", 0)
            col = dm._collection(create=True)
            victim = {"id": vdid, "doc": _content("mine touch victim sigma"), "meta": {"nodo": "w"}}
            monkeypatch.setattr(pal, "_best_lifecycle_candidate", lambda *a, **k: (victim, 0.99))
            monkeypatch.setattr(pal, "classify_content_pair", lambda *a, **k: "duplicate")
            with (
                mock.patch.object(col, "update", side_effect=RuntimeError("boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                out = dm.mine(str(proj), nodo="w", celda="r")
            assert out["fragmentos_deduped"] == 1
        finally:
            dm.close()

    def test_mine_kg_sync_failure_keeps_mining(self, tmp_path):
        proj = self._proj(tmp_path)
        dm = _dm(tmp_path, name="mkg")
        try:
            kgm = mock.MagicMock()
            kgm.triples_for_source.side_effect = RuntimeError("kg boom")
            with mock.patch.object(dm, "_kg_or_none", return_value=kgm):
                out = dm.mine(str(proj))
            assert out["files_mined"] == 1
            assert out["kg_triples"] == 0
        finally:
            dm.close()

    def test_mine_kg_close_failure_ignored(self, tmp_path):
        proj = self._proj(tmp_path)
        dm = _dm(tmp_path, name="mkg2")
        try:
            kgm = mock.MagicMock()
            kgm.triples_for_source.return_value = []
            kgm.close.side_effect = RuntimeError("close boom")
            with mock.patch.object(dm, "_kg_or_none", return_value=kgm):
                out = dm.mine(str(proj))
            assert out["files_mined"] == 1
        finally:
            dm.close()

    def test_mine_rollback_read_failure_reraises(self, tmp_path, monkeypatch):
        proj = self._proj(tmp_path)
        dm = _dm(tmp_path, name="mrb")
        try:
            old_content = _content("rollback victim tau keeper", 10)
            old_id = dm.add_fragmento("w", "r", old_content, "/victim.md", 0)
            col = dm._collection(create=True)
            victim = {
                "id": old_id,
                "doc": old_content,
                "meta": dict(col.get(ids=[old_id], include=["metadatas"]).metadatas[0]),
            }
            monkeypatch.setattr(pal, "_best_lifecycle_candidate", lambda *a, **k: (victim, 0.99))
            monkeypatch.setattr(pal, "classify_content_pair", lambda *a, **k: "contradiction")
            state = {"armed": False}
            orig_get = col.get
            orig_upsert = col.upsert

            def _get(*a, **k):
                if state["armed"] and k.get("include") == ["documents", "metadatas"]:
                    raise RuntimeError("rollback read boom")
                return orig_get(*a, **k)

            def _boom(*a, **k):
                ids = k.get("ids", [])
                if old_id in [str(i) for i in ids]:
                    return orig_upsert(*a, **k)
                state["armed"] = True
                raise RuntimeError("batch upsert boom")

            with (
                mock.patch.object(col, "get", side_effect=_get),
                mock.patch.object(col, "upsert", side_effect=_boom),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                with pytest.raises(RuntimeError, match="batch upsert boom"):
                    dm.mine(str(proj), nodo="w", celda="r")
            after = col.get(ids=[old_id], include=["metadatas"])
            assert after.metadatas[0].get("superseded_by") is not None
        finally:
            dm.close()

    def test_timeline_bad_limit_and_empty(self, tmp_path):
        dm = _dm(tmp_path, name="tl")
        try:
            assert dm.timeline(limit="bad") == []  # type: ignore[arg-type]
            col = dm._collection(create=False)
            boom = _BoomGetCol(col)
            with (
                mock.patch.object(dm, "_collection", return_value=boom),
                mock.patch.object(dm, "_kg_or_none", return_value=None),
            ):
                assert dm.timeline() == []
        finally:
            dm.close()

    def test_timeline_session_pin_and_filters(self, tmp_path):
        dm = _dm(tmp_path, name="tl2")
        try:
            ds = dm.add_fragmento("w", "r", _content("session summary alpha keeper"), "session:abc", 0)
            col = dm._collection(create=False)
            col.update(ids=[ds], metadatas=[{"filed_at": "2024-05-01T10:00:00+00:00"}])
            dn = dm.add_fragmento("w", "r", _content("session nodate beta keeper"), "session:nodate", 0)
            col.update(ids=[dn], metadatas=[{"filed_at": ""}])
            dp = dm.add_fragmento("w", "r", _content("pinned fragmento gamma keeper"), "/p.md", 0)
            assert dm.pin_fragmento(dp) is True
            dq = dm.add_fragmento("w", "r", _content("quarantined delta keeper"), "/q.md", 0)
            assert dm.quarantine_fragmento(dq) is True
            entries = dm.timeline()
            refs = {e["ref"] for e in entries}
            assert ds in refs
            assert dn not in refs
            assert dp in refs
            assert dq not in refs
            kinds = {e["ref"]: e["kind"] for e in entries}
            assert kinds[ds] == "session"
            assert kinds[dp] == "pin"
            assert dm.timeline(nodo="other") == []
            assert dm.timeline(since="2030-01-01", before="2031-01-01") == []
        finally:
            dm.close()

    def test_timeline_kg_episodes(self, tmp_path):
        dm = _dm(tmp_path, name="tl3")
        try:
            did = dm.add_fragmento("w", "r", _content("kg linked alpha keeper"), "/p/f.md", 0)
            eps = [
                "notadict",
                {
                    "source_file": "",
                    "valid_from": "2024-01-01",
                    "extracted_at": "2024-01-01",
                    "subject": "A",
                    "predicate": "p",
                    "object": "B",
                    "current": True,
                },
                {
                    "source_file": "/p/f.md",
                    "valid_from": "",
                    "extracted_at": "",
                    "subject": "A",
                    "predicate": "p",
                    "object": "B",
                    "current": True,
                },
                {
                    "source_file": "/p/f.md",
                    "valid_from": "2024-02-01",
                    "extracted_at": "2024-02-01",
                    "subject": "A",
                    "predicate": "p",
                    "object": "B",
                    "current": True,
                    "source_fragmento_id": did,
                },
                {
                    "source_file": "/p/g.md",
                    "valid_from": "2024-03-01",
                    "extracted_at": "2024-03-01",
                    "subject": "C",
                    "predicate": "q",
                    "object": "D",
                    "current": False,
                },
            ]
            kgm = mock.MagicMock()
            kgm.all_episodes.return_value = eps
            with mock.patch.object(dm, "_kg_or_none", return_value=kgm):
                entries = dm.timeline()
            files = {e["ref"]: e for e in entries if e["kind"] == "file"}
            assert set(files) == {"/p/f.md", "/p/g.md"}
            assert files["/p/f.md"]["nodo"] == "w"
            assert files["/p/g.md"]["nodo"] is None
            assert files["/p/f.md"]["current"] is True
        finally:
            dm.close()

    def test_timeline_kg_failures(self, tmp_path):
        dm = _dm(tmp_path, name="tl4")
        try:
            ds = dm.add_fragmento("w", "r", _content("kg fail session alpha"), "session:z", 0)
            col = dm._collection(create=False)
            col.update(ids=[ds], metadatas=[{"filed_at": "2024-05-01T10:00:00+00:00"}])
            kgm = mock.MagicMock()
            kgm.all_episodes.side_effect = RuntimeError("kg boom")
            with mock.patch.object(dm, "_kg_or_none", return_value=kgm):
                entries = dm.timeline()
            assert any(e["ref"] == ds for e in entries)
            assert not [e for e in entries if e["kind"] == "file"]
            kgm2 = mock.MagicMock()
            kgm2.all_episodes.return_value = []
            kgm2.close.side_effect = RuntimeError("close boom")
            with mock.patch.object(dm, "_kg_or_none", return_value=kgm2):
                assert any(e["ref"] == ds for e in dm.timeline())
        finally:
            dm.close()

    def test_timeline_identity_pin(self, tmp_path):
        dm = _dm(tmp_path, name="tl5")
        try:
            dm.pin_identity()
            entries = dm.timeline()
            assert any(e["ref"] == "identity" and e["kind"] == "pin" for e in entries)
        finally:
            dm.close()

    def test_kg_or_none_variants(self, tmp_path, monkeypatch):
        dm = _dm(tmp_path, name="kgv")
        try:
            assert pal.DxrkMemory(str(tmp_path / "x"), auto_kg=False)._kg_or_none() is None
            assert pal.DxrkMemory("memory-only")._kg_or_none() is None
            monkeypatch.setattr(
                "dxrk.memory.graph.KnowledgeGraph", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            )
            assert dm._kg_or_none() is None
            dm2 = pal.DxrkMemory(str(tmp_path / "y"), kg_path=str(tmp_path / "k.db"))
            assert dm2._kg_or_none() is None
        finally:
            dm.close()


# ─── engine smoke ───────────────────────────────────────────────────────────


class TestEngineSmoke:
    def test_engine_reexports_malla(self):
        from dxrk.memory import engine as eng
        from dxrk.memory import malla as palmod

        assert eng.DxrkMemory is palmod.DxrkMemory
        assert eng.Malla is palmod.Malla
        assert eng.chunk_text is palmod.chunk_text


# ─── round 2: branch-level remainders ───────────────────────────────────────


class TestSqliteRound2:
    def test_pool_vectors_corrupt_blob_backfills(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "corrupt")
        try:
            col.add(documents=["hello world content"], ids=["e1"], metadatas=[{"nodo": "w"}])
            col._conn.execute("UPDATE doc_vectors SET vec=?", (b"short",))  # type: ignore[attr-defined]
            col._conn.commit()  # type: ignore[attr-defined]
            pool = col._fetch_pool("hello", "", [], None, 5)  # type: ignore[attr-defined]
            ranked = col._rank_pool(pool, "hello", None)  # type: ignore[attr-defined]
            assert len(ranked) == len(pool) == 1
            assert ranked[0][0][0] == "e1"
        finally:
            be.close()


class TestSearchRound2:
    def test_closet_two_docs_iterates(self):
        from dxrk.memory.search import hybrid_search

        fragmento = _FakeGlobuloCol(["hello world"], [_meta("/p/a.md")], [0.5], ids=["d0"])
        closet = _FakeGlobuloCol(
            ["hello again", "hello more", ""],
            [_meta("/p/a.md"), _meta("/p/b.md"), _meta("")],
            [0.1, 0.2, 0.3],
            ids=["c0", "c1", "c2"],
        )
        out = hybrid_search(fragmento, "hello", closet_collection=closet)
        assert out["results"][0]["matched_via"] == "fragmento+closet"


class TestGraphRound2:
    def test_resolve_kg_path_not_migrated(self, monkeypatch):
        from dxrk.memory import graph as kgm

        monkeypatch.setattr("dxrk.tenant.migration.is_migrated", lambda: False)
        assert kgm._resolve_kg_path(None, None) == kgm.DEFAULT_KG_PATH

    def test_resolve_kg_path_explicit_empty_tenant(self, tmp_path, monkeypatch):
        from dxrk.memory import graph as kgm

        calls = {"n": 0}

        def _flip():
            calls["n"] += 1
            return calls["n"] >= 2

        monkeypatch.setattr("dxrk.tenant.migration.is_migrated", _flip)
        monkeypatch.setattr("dxrk.tenant.migration.tenant_root", lambda tid: tmp_path / tid)
        assert kgm._resolve_kg_path("", None) == str(tmp_path / "default" / "knowledge_graph.sqlite3")

    def test_double_close_ok(self, tmp_path):
        from dxrk.memory.graph import KnowledgeGraph

        kg = KnowledgeGraph(str(tmp_path / "kgd.sqlite3"))
        kg.close()
        kg.close()
        assert kg._conn is None

    def test_traverse_diamond_revisits(self, tmp_path):
        from dxrk.memory.graph import KnowledgeGraph

        kg = KnowledgeGraph(str(tmp_path / "kgdia.sqlite3"))
        try:
            kg.add_triple("Alice", "knows", "Bob")
            kg.add_triple("Alice", "knows", "Cara")
            kg.add_triple("Bob", "knows", "Dave")
            kg.add_triple("Cara", "knows", "Dave")
            out = kg.traverse("Alice", depth=5)
            assert len(out) == 4
        finally:
            kg.close()

    def test_init_db_migrate_failure_ignored(self, tmp_path):
        import threading

        from dxrk.memory.graph import KnowledgeGraph

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg.tenant_id = ""
        kg.db_path = str(tmp_path / "x.sqlite3")
        kg._lock = threading.RLock()
        real_conn = sqlite3.connect(str(tmp_path / "real.sqlite3"))
        try:
            fake = mock.MagicMock()
            fake.executescript.side_effect = lambda sql: real_conn.executescript(sql)
            fake.execute.side_effect = sqlite3.Error("pragma boom")
            fake.commit.side_effect = lambda: real_conn.commit()
            kg._conn_or_create = lambda: fake  # type: ignore[method-assign]
            kg._init_db()
            tables = {r[0] for r in real_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            assert "triples" in tables
        finally:
            real_conn.close()


class TestPolicyRound2:
    def test_over_budget_two_nodos(self, tmp_path):
        dm = _dm(tmp_path, name="pob2")
        try:
            p = mock.MagicMock()
            p.list_nodos.return_value = ["a", "b"]
            p.nodo_usage.side_effect = [{"over": False}, {"over": True}]
            p.enforce_nodo_cap.return_value = 2
            assert PolicyEngine(p)._run_over_budget() == {"nodos_over": ["b"], "evicted": 2}
        finally:
            dm.close()

    def test_rescore_ledger_ts_variants(self, tmp_path):
        dm = _dm(tmp_path, name="plts")
        try:
            d1 = dm.add_fragmento("w", "r", _content("ledger garbage ts alpha"), "/g.md", 0)
            d2 = dm.add_fragmento("w", "r", _content("ledger naive ts beta"), "/n.md", 0)
            col = dm._collection(create=False)
            old = _stale(40)
            naive_old = (datetime.now(UTC) - timedelta(days=40)).replace(tzinfo=None).isoformat()
            col.update(
                ids=[d1], metadatas=[{"filed_at": old, "score_ledger": [{"ts": "garbage"}], "score_ledger_dropped": 0}]
            )
            col.update(
                ids=[d2], metadatas=[{"filed_at": old, "score_ledger": [{"ts": naive_old}], "score_ledger_dropped": 0}]
            )
            out = PolicyEngine(dm)._run_rescore_stale()
            assert out == {"scanned": 2, "rescored": 2}
        finally:
            dm.close()


class TestSangreRound2:
    def test_mine_distinct_with_best_inserts(self, tmp_path, monkeypatch):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "n.md").write_text(_content("fresh distinct file content", 30))
        dm = _dm(tmp_path, name="mdist")
        try:
            vdid = dm.add_fragmento("w", "r", _content("mine distinct victim rho"), "/victim.md", 0)
            victim = {"id": vdid, "doc": _content("mine distinct victim rho"), "meta": {"nodo": "w"}}
            monkeypatch.setattr(pal, "_best_lifecycle_candidate", lambda *a, **k: (victim, 0.99))
            monkeypatch.setattr(pal, "classify_content_pair", lambda *a, **k: "distinct")
            out = dm.mine(str(proj), nodo="w", celda="r")
            assert out["fragmentos_added"] == 2
            assert out["fragmentos_deduped"] == 0
        finally:
            dm.close()

    def _contradiction_setup(self, tmp_path, monkeypatch, name):
        proj = tmp_path / "proj"
        proj.mkdir(exist_ok=True)
        (proj / "new.md").write_text(_content("brand new file content tau", 30))
        dm = _dm(tmp_path, name=name)
        old_content = _content("rollback victim tau keeper", 10)
        old_id = dm.add_fragmento("w", "r", old_content, "/victim.md", 0)
        col = dm._collection(create=True)
        victim = {
            "id": old_id,
            "doc": old_content,
            "meta": dict(col.get(ids=[old_id], include=["metadatas"]).metadatas[0]),
        }
        monkeypatch.setattr(pal, "_best_lifecycle_candidate", lambda *a, **k: (victim, 0.99))
        monkeypatch.setattr(pal, "classify_content_pair", lambda *a, **k: "contradiction")
        return dm, proj, col, old_id

    def test_mine_rollback_get_empty_skips(self, tmp_path, monkeypatch):
        from dxrk.memory.backend.base import CollectionNotInitializedError

        dm, proj, col, old_id = self._contradiction_setup(tmp_path, monkeypatch, "mrbe")
        try:
            orig_get = col.get
            orig_upsert = col.upsert
            state = {"armed": False}

            def _coll(name="dxrk_fragmentos", *, create=True):
                if name == "dxrk_closets":
                    raise CollectionNotInitializedError("no closets")
                return col

            def _get(*a, **k):
                if state["armed"]:
                    return GetResult.empty()
                return orig_get(*a, **k)

            def _boom(*a, **k):
                if old_id in [str(i) for i in k.get("ids", [])]:
                    return orig_upsert(*a, **k)
                state["armed"] = True
                raise RuntimeError("batch upsert boom")

            with (
                mock.patch.object(col, "get", side_effect=_get),
                mock.patch.object(col, "upsert", side_effect=_boom),
                mock.patch.object(dm, "_collection", side_effect=_coll),
            ):
                with pytest.raises(RuntimeError, match="batch upsert boom"):
                    dm.mine(str(proj), nodo="w", celda="r")
        finally:
            dm.close()

    def test_mine_rollback_superseded_mismatch_skips(self, tmp_path, monkeypatch):
        dm, proj, col, old_id = self._contradiction_setup(tmp_path, monkeypatch, "mrbm")
        try:
            orig_get = col.get
            orig_upsert = col.upsert
            state = {"armed": False}

            def _get(*a, **k):
                out = orig_get(*a, **k)
                if state["armed"] and out.ids:
                    out.metadatas[0]["superseded_by"] = "someone-else"
                return out

            def _boom(*a, **k):
                if old_id in [str(i) for i in k.get("ids", [])]:
                    return orig_upsert(*a, **k)
                state["armed"] = True
                raise RuntimeError("batch upsert boom")

            with (
                mock.patch.object(col, "get", side_effect=_get),
                mock.patch.object(col, "upsert", side_effect=_boom),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                with pytest.raises(RuntimeError, match="batch upsert boom"):
                    dm.mine(str(proj), nodo="w", celda="r")
        finally:
            dm.close()

    def test_mine_no_kg(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "n.md").write_text(_content("no kg file content", 30))
        dm = pal.DxrkMemory(str(tmp_path / "nkg"), auto_kg=False)
        dm.init()
        try:
            out = dm.mine(str(proj))
            assert out["files_mined"] == 1
            assert out["kg_triples"] == 0
        finally:
            dm.close()

    def test_forget_scope_variants(self, tmp_path):
        dm = _dm(tmp_path, name="fsc")
        try:
            dm.add_fragmento("w", "r1", _content("forget scope alpha keeper"), "/a.md", 0)
            dm.add_fragmento("w", "r2", _content("forget scope beta keeper"), "/b.md", 0)
            out = dm.forget(nodo="w", celda="r1")
            assert out["matched"] == 1
            assert out["soft_forgotten"] == 1
            out2 = dm.forget(celda="r2")
            assert out2["matched"] == 1
            col = dm._collection(create=False)
            with (
                mock.patch.object(col, "get", side_effect=RuntimeError("scan boom")),
                mock.patch.object(dm, "_collection", return_value=col),
            ):
                assert dm.forget(nodo="w")["matched"] == 0
            assert dm.forget(nodo="no_nodo_xyz")["matched"] == 0
            assert dm.forget(nodo="w", before="2020-01-01")["matched"] == 0
        finally:
            dm.close()

    def test_forget_kg_none_with_match(self, tmp_path):
        dm = pal.DxrkMemory(str(tmp_path / "nkg2"), auto_kg=False)
        dm.init()
        try:
            did = dm.add_fragmento("w", "r", _content("nokg matched alpha keeper"), "/k.md", 0)
            out = dm.forget(fragmento_ids=[did], include_kg=True)
            assert out["matched"] == 1
            assert out["kg_superseded"] == 0
        finally:
            dm.close()

    def test_counters_path_exception(self, tmp_path):
        dm = _dm(tmp_path, name="cpe")
        try:
            dm.malla_path = 123  # type: ignore[assignment]
            assert dm._counters_path() is None
            assert dm._read_spine_counters() == {}
            assert dm._bump_spine_counter("x") == 0
        finally:
            dm.close()

    def test_timeline_pinned_without_date_skipped(self, tmp_path):
        dm = _dm(tmp_path, name="tlnd")
        try:
            dp = dm.add_fragmento("w", "r", _content("pinned nodate alpha keeper"), "/p.md", 0)
            assert dm.pin_fragmento(dp) is True
            col = dm._collection(create=False)
            col.update(ids=[dp], metadatas=[{"pinned_at": "", "filed_at": ""}])
            assert all(e["ref"] != dp for e in dm.timeline())
        finally:
            dm.close()

    def test_timeline_ghost_fragmento_episode(self, tmp_path):
        dm = _dm(tmp_path, name="tlgh")
        try:
            eps = [
                {
                    "source_file": "/p/ghost.md",
                    "valid_from": "2024-03-01",
                    "extracted_at": "2024-03-01",
                    "subject": "C",
                    "predicate": "q",
                    "object": "D",
                    "current": True,
                    "source_fragmento_id": "ghost_fragmento",
                },
            ]
            kgm = mock.MagicMock()
            kgm.all_episodes.return_value = eps
            with mock.patch.object(dm, "_kg_or_none", return_value=kgm):
                entries = dm.timeline()
            files = [e for e in entries if e["kind"] == "file"]
            assert len(files) == 1
            assert files[0]["nodo"] is None
        finally:
            dm.close()

    def test_timeline_identity_pin_variants(self, tmp_path):
        dm = _dm(tmp_path, name="tlip")
        try:
            (Path(dm.malla_path) / "pins.json").write_text('{"identity": {"scope": "identity"}}')
            assert not [e for e in dm.timeline() if e["ref"] == "identity"]
            dm.pin_identity()
            assert any(e["ref"] == "identity" for e in dm.timeline())
            assert not [e for e in dm.timeline(since="2030-01-01", before="2031-01-01") if e["ref"] == "identity"]
        finally:
            dm.close()


class TestSangreRound3:
    def _fake_msvcrt(self, monkeypatch):
        import sys

        fake = mock.MagicMock()
        fake.LK_NBLCK = 1
        fake.LK_UNLCK = 2
        fake.LK_LOCK = 3
        fake.locking.return_value = None
        monkeypatch.setitem(sys.modules, "msvcrt", fake)
        return fake

    def test_cleanup_nt_unlock_failure(self, tmp_path, monkeypatch):
        import os as os_mod

        lp = str(tmp_path / "nt1.lock")
        lf = pal._open_mine_lock_file(lp, create=True)
        pal._lock_mine_lock_file(lf, blocking=True)
        lf.close()
        self._fake_msvcrt(monkeypatch)
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setattr(
            "dxrk.memory.malla._unlock_mine_lock_file",
            lambda f: (_ for _ in ()).throw(OSError("unlock down")),
        )
        pal._cleanup_mine_lock_file(lp)
        assert os_mod.path.exists(lp)

    def test_cleanup_nt_remove_failure_ignored(self, tmp_path, monkeypatch):
        import os as os_mod

        lp = str(tmp_path / "nt2.lock")
        lf = pal._open_mine_lock_file(lp, create=True)
        lf.close()
        self._fake_msvcrt(monkeypatch)
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setattr("dxrk.memory.malla._lock_mine_lock_file", lambda f, blocking: True)
        monkeypatch.setattr("dxrk.memory.malla._mine_lock_file_is_current", lambda f, p: True)
        monkeypatch.setattr("dxrk.memory.malla._unlock_mine_lock_file", lambda f: None)
        monkeypatch.setattr(os_mod, "remove", lambda p: (_ for _ in ()).throw(OSError("ro")))
        pal._cleanup_mine_lock_file(lp)
        assert os_mod.path.exists(lp)

    def test_mine_malla_lock_nt_acquire_release(self, tmp_path, monkeypatch):
        import pathlib as pathlib_mod

        fake = self._fake_msvcrt(monkeypatch)
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setattr(pal, "Path", pathlib_mod.PosixPath)
        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "locks")
        with pal.mine_malla_lock(str(tmp_path / "malla-nt")):
            pass
        assert fake.locking.call_count >= 2

    def test_mine_malla_lock_nt_contention(self, tmp_path, monkeypatch):
        import pathlib as pathlib_mod

        import pytest

        fake = self._fake_msvcrt(monkeypatch)
        fake.locking.side_effect = OSError("held by another")
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setattr(pal, "Path", pathlib_mod.PosixPath)
        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "locks")
        with pytest.raises(RuntimeError, match="held by another writer"):
            with pal.mine_malla_lock(str(tmp_path / "malla-nt-busy")):
                pass

    def test_nodo_cap_exhausts_max_passes(self, tmp_path):
        dm = _dm(tmp_path, name="wexh")
        try:
            col = dm._collection(create=False)
            calls = {"n": 0}

            def _always_full(c, nodo, cap):
                calls["n"] += 1
                return 1, cap + 5, True

            with mock.patch.object(dm, "_enforce_nodo_cap_once", side_effect=_always_full):
                total = dm._enforce_nodo_cap(col, "w")
            assert total == pal._NODO_CAP_MAX_PASSES
            assert calls["n"] == pal._NODO_CAP_MAX_PASSES
        finally:
            dm.close()

    def test_consolidate_self_collision_skips_mark(self, tmp_path, monkeypatch):
        dm = _dm(tmp_path, name="cself")
        try:
            d1 = dm.add_fragmento("w", "r", _content("self collision alpha keeper one"), "/sa.md", 0)
            d2 = dm.add_fragmento("w", "r", _content("self collision beta keeper two"), "/sb.md", 0)
            monkeypatch.setattr(pal.FragmentoRecord, "make_id", staticmethod(lambda *a, **k: d1))
            out = dm.consolidate_fragmentos([d1, d2])
            assert out["fragmento_id"] == d1
            assert out["sources"] == 2
        finally:
            dm.close()
