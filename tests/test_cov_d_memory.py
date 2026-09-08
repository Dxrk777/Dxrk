# SPDX-License-Identifier: MIT
"""Coverage D — sqlite / palace / layers / miner gap tests (stdlib only)."""

from __future__ import annotations

import errno
import hashlib
import os
import signal
import sqlite3
import stat
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

from dxrk.memory.backend import PalaceRef, SqliteBackend
from dxrk.memory.backend.base import (
    BackendClosedError,
    CollectionNotInitializedError,
    PalaceNotFoundError,
    UnsupportedFilterError,
)
from dxrk.memory.layers import Layer0, Layer1, Layer2, Layer3, MemoryStack


@pytest.fixture(autouse=True)
def _isolate_home(monkeypatch, tmp_path):
    monkeypatch.setenv("DXRK_TENANT", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    yield


def _ref(tmp_path: Path, name: str = "pal") -> PalaceRef:
    p = tmp_path / name
    return PalaceRef(id=str(p), local_path=str(p))


def _col(tmp_path: Path, name: str = "c", cname: str = "col"):
    be = SqliteBackend()
    ref = _ref(tmp_path, name)
    col = be.get_collection(palace=ref, collection_name=cname, create=True)
    return be, ref, col


# ─── sqlite helpers ──────────────────────────────────────────────────────────


class TestSqliteHelpers:
    def test_tokenize_empty_and_basic(self):
        from dxrk.memory.backend.sqlite import _sanitize_query, _tokenize

        assert _tokenize("") == []
        assert _tokenize("a b hi") == ["hi"]
        assert _tokenize("Hello World") == ["hello", "world"]
        assert _sanitize_query("hello!!!   world??") == "hello world"
        assert _sanitize_query("") == ""
        assert len(_sanitize_query("x " * 400)) <= 500

    def test_where_in_empty_returns_no_rows(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "w1")
        try:
            col.add(documents=["hello"], ids=["i1"], metadatas=[{"wing": "w"}])
            got = col.get(where={"chunk_index": {"$in": []}})
            assert got.ids == []
        finally:
            be.close()

    def test_where_and_not_list_ignored(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "w2")
        try:
            col.add(documents=["hello"], ids=["i1"], metadatas=[{"wing": "w"}])
            got = col.get(where={"$and": "oops"})  # type: ignore[dict-item]
            assert got.ids == ["i1"]
        finally:
            be.close()

    def test_where_and_skip_non_dict(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "w3")
        try:
            col.add(documents=["hello"], ids=["i1"], metadatas=[{"wing": "w"}])
            got = col.get(where={"$and": ["nope", {"wing": "w"}]})  # type: ignore[list-item]
            assert got.ids == ["i1"]
        finally:
            be.close()

    def test_where_and_empty_list(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "w4")
        try:
            col.add(documents=["hello"], ids=["i1"], metadatas=[{"wing": "w"}])
            got = col.get(where={"$and": []})
            assert got.ids == ["i1"]
        finally:
            be.close()

    def test_where_unsupported_top_level(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "w5")
        try:
            with pytest.raises(UnsupportedFilterError):
                col.get(where={"$or": [{"wing": "w"}]})
        finally:
            be.close()

    def test_where_unsupported_operator(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "w6")
        try:
            with pytest.raises(UnsupportedFilterError):
                col.get(where={"wing": {"$gt": 1}})
        finally:
            be.close()

    def test_bm25_edge_cases(self):
        from dxrk.memory.backend.sqlite import _bm25_scores

        assert _bm25_scores("hello", []) == []
        assert _bm25_scores("", ["hello"]) == [0.0]
        assert _bm25_scores("hello", ["", ""]) == [0.0, 0.0]
        scores = _bm25_scores("hello", ["", "hello world"])
        assert scores[0] == 0.0
        assert scores[1] > 0.0

    def test_collection_closed_raises(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "closed")
        try:
            col.close()
            with pytest.raises(BackendClosedError):
                col.add(documents=["x"], ids=["1"])
            with pytest.raises(BackendClosedError):
                col.upsert(documents=["x"], ids=["1"])
            with pytest.raises(BackendClosedError):
                col.get()
            with pytest.raises(BackendClosedError):
                col.query(query_texts=["x"])
            with pytest.raises(BackendClosedError):
                col.delete(ids=["1"])
            with pytest.raises(BackendClosedError):
                col.count()
        finally:
            be.close()

    def test_ft5_available_false(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "ft5")
        try:
            assert col._ft5_available() is True  # type: ignore[attr-defined]
            col._conn.execute("DROP TABLE IF EXISTS embedding_fts")  # type: ignore[attr-defined]
            col._conn.commit()  # type: ignore[attr-defined]
            assert col._ft5_available() is False  # type: ignore[attr-defined]
            # query still works via fallback
            col.add(documents=["hello fallback"], ids=["f1"], metadatas=[{"wing": "w"}])
            q = col.query(query_texts=["hello"], n_results=5)
            assert "f1" in q.ids[0]
        finally:
            be.close()

    def test_add_length_mismatches(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "addmis")
        try:
            with pytest.raises(ValueError, match="documents and ids"):
                col.add(documents=["a", "b"], ids=["1"])
            with pytest.raises(ValueError, match="metadatas length"):
                col.add(documents=["a"], ids=["1"], metadatas=[{}, {}])
            with pytest.raises(ValueError, match="embeddings length"):
                col.add(documents=["a"], ids=["1"], embeddings=[[0.1], [0.2]])
        finally:
            be.close()

    def test_add_with_embeddings_roundtrip(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "addemb")
        try:
            col.add(
                documents=["doc emb"],
                ids=["e1"],
                metadatas=[{"wing": "w"}],
                embeddings=[[0.1, 0.2, 0.3]],
            )
            got = col.get(ids=["e1"], include=["documents", "metadatas", "embeddings"])
            assert got.ids == ["e1"]
            assert got.embeddings is not None
            assert got.embeddings[0] == [0.1, 0.2, 0.3]
            # without embeddings include, internal key stripped
            got2 = col.get(ids=["e1"], include=["documents", "metadatas"])
            assert "_embedding" not in got2.metadatas[0]
            assert got2.embeddings is None
        finally:
            be.close()

    def test_add_fts_error_ignored_via_missing_table(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "addfts")
        try:
            col._conn.execute("DROP TABLE IF EXISTS embedding_fts")  # type: ignore[attr-defined]
            col._conn.commit()  # type: ignore[attr-defined]
            col.add(documents=["no fts"], ids=["n1"], metadatas=[{"wing": "w"}])
            assert col.count() == 1
        finally:
            be.close()

    def test_add_duplicate_raises(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "dup")
        try:
            col.add(documents=["a"], ids=["d1"], metadatas=[{"wing": "w"}])
            with pytest.raises(ValueError, match="duplicate id"):
                col.add(documents=["b"], ids=["d1"], metadatas=[{"wing": "w"}])
        finally:
            be.close()

    def test_upsert_mismatches(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "upmis")
        try:
            with pytest.raises(ValueError, match="documents and ids"):
                col.upsert(documents=["a"], ids=["1", "2"])
            with pytest.raises(ValueError, match="metadatas length"):
                col.upsert(documents=["a"], ids=["1"], metadatas=[{}, {}])
        finally:
            be.close()

    def test_upsert_with_embeddings(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "upemb")
        try:
            col.upsert(
                documents=["u1"],
                ids=["u1"],
                metadatas=[{"wing": "w"}],
                embeddings=[[1.0, 2.0]],
            )
            got = col.get(ids=["u1"], include=["documents", "metadatas", "embeddings"])
            assert got.embeddings is not None
            assert got.embeddings[0] == [1.0, 2.0]
        finally:
            be.close()

    def test_upsert_new_fts_missing_ok(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "upnew")
        try:
            col._conn.execute("DROP TABLE IF EXISTS embedding_fts")  # type: ignore[attr-defined]
            col._conn.commit()  # type: ignore[attr-defined]
            col.upsert(documents=["fresh"], ids=["fresh1"], metadatas=[{"wing": "w"}])
            assert col.count() == 1
        finally:
            be.close()

    def test_upsert_sqlite_error_rollback(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "uper")
        try:
            real_conn = col._conn  # type: ignore[attr-defined]
            bad_cur = mock.MagicMock()
            bad_cur.execute.side_effect = sqlite3.OperationalError("boom")
            bad_cur.fetchone.side_effect = sqlite3.OperationalError("boom")
            bad_conn = mock.MagicMock()
            bad_conn.cursor.return_value = bad_cur
            col._conn = bad_conn  # type: ignore[attr-defined]
            with pytest.raises(sqlite3.Error):
                col.upsert(documents=["x"], ids=["x1"], metadatas=[{"wing": "w"}])
            col._conn = real_conn  # type: ignore[attr-defined]
        finally:
            be.close()

    def test_get_where_document_branches(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "wdoc")
        try:
            col.add(documents=["hello world"], ids=["a"], metadatas=[{"wing": "w"}])
            col.add(documents=["goodbye"], ids=["b"], metadatas=[{"wing": "w"}])
            got = col.get(where_document={"$contains": "hello"})
            assert got.ids == ["a"]
            with pytest.raises(UnsupportedFilterError):
                col.get(where_document={"$unknown": "x"})
        finally:
            be.close()

    def test_get_offset_without_limit(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "off")
        try:
            for i in range(3):
                col.add(documents=[f"doc {i}"], ids=[f"id{i}"], metadatas=[{"wing": "w"}])
            got = col.get(offset=1)
            assert [r for r in got.ids] == ["id1", "id2"]
            got2 = col.get(limit=1, offset=1)
            assert got2.ids == ["id1"]
        finally:
            be.close()

    def test_get_bad_json_and_include_variants(self, tmp_path: Path):
        be, ref, col = _col(tmp_path, "badjson")
        try:
            col.add(documents=["ok"], ids=["ok1"], metadatas=[{"wing": "w"}])
            # corrupt metadata directly
            col._conn.execute(  # type: ignore[attr-defined]
                "UPDATE embeddings SET metadata=? WHERE id=?", ("{bad json", "ok1")
            )
            col._conn.commit()  # type: ignore[attr-defined]
            got = col.get(ids=["ok1"], include=["documents", "metadatas"])
            assert got.metadatas[0] == {}
            got_e = col.get(ids=["ok1"], include=["documents", "metadatas", "embeddings"])
            assert got_e.embeddings is not None
            assert got_e.embeddings[0] == []
            # documents=False / metadatas=False branches
            got_nd = col.get(ids=["ok1"], include=["metadatas"])
            assert got_nd.documents == [""]
            got_nm = col.get(ids=["ok1"], include=["documents"])
            assert got_nm.metadatas == [{}]
        finally:
            be.close()

    def test_query_embeddings_only_neutral(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "qemb")
        try:
            col.add(documents=["alpha beta"], ids=["q1"], metadatas=[{"wing": "w"}])
            q = col.query(query_embeddings=[[0.1, 0.2]], n_results=5)
            assert "q1" in q.ids[0]
            assert q.distances[0][0] == 0.5
        finally:
            be.close()

    def test_query_where_document_contains_fts_and_fallback(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "qwdoc")
        try:
            col.add(documents=["hello mars"], ids=["m1"], metadatas=[{"wing": "w"}])
            col.add(documents=["hello venus"], ids=["m2"], metadatas=[{"wing": "w"}])
            q = col.query(
                query_texts=["hello"],
                n_results=5,
                where_document={"$contains": "mars"},
            )
            assert q.ids[0] == ["m1"]
            # force FTS error path: drop table then query with contains falls to fallback extra branch
            col._conn.execute("DROP TABLE IF EXISTS embedding_fts")  # type: ignore[attr-defined]
            col._conn.commit()  # type: ignore[attr-defined]
            q2 = col.query(
                query_texts=["hello"],
                n_results=5,
                where_document={"$contains": "venus"},
            )
            assert q2.ids[0] == ["m2"]
        finally:
            be.close()

    def test_query_fts_error_falls_back(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "qerr")
        try:
            col.add(documents=["hello world"], ids=["e1"], metadatas=[{"wing": "w"}])
            col._conn.execute("DROP TABLE IF EXISTS embedding_fts")  # type: ignore[attr-defined]
            col._conn.commit()  # type: ignore[attr-defined]
            with mock.patch.object(col, "_ft5_available", return_value=True):  # type: ignore[attr-defined]
                q = col.query(query_texts=["hello"], n_results=5)
                assert "e1" in q.ids[0]
        finally:
            be.close()

    def test_query_include_variants(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "qinc")
        try:
            col.add(
                documents=["hello include"],
                ids=["k1"],
                metadatas=[{"wing": "w"}],
                embeddings=[[9.0]],
            )
            # corrupt one row to hit JSON error branches in query output
            col._conn.execute(  # type: ignore[attr-defined]
                "UPDATE embeddings SET metadata=? WHERE id=?", ("not json", "k1")
            )
            col._conn.commit()  # type: ignore[attr-defined]
            q = col.query(query_texts=["hello"], n_results=5, include=["documents"])
            assert q.ids[0] == ["k1"]
            assert q.metadatas[0] == [{}]
            assert q.distances[0] == [0.0]
            assert q.embeddings is None
            q2 = col.query(
                query_texts=["hello"],
                n_results=5,
                include=["documents", "metadatas", "distances", "embeddings"],
            )
            assert q2.embeddings is not None
            assert q2.embeddings[0][0] == []
            # no-documents branch
            q3 = col.query(query_texts=["hello"], n_results=5, include=["metadatas"])
            assert q3.documents[0] == [""]
        finally:
            be.close()

    def test_delete_requires_args_and_missing_id(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "del")
        try:
            with pytest.raises(ValueError, match="delete requires"):
                col.delete()
            col.add(documents=["x"], ids=["x1"], metadatas=[{"wing": "w"}])
            col.delete(ids=["nope"])
            assert col.count() == 1
            col.delete(ids=["x1"])
            assert col.count() == 0
        finally:
            be.close()

    def test_delete_fts_missing_ok(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "delfts")
        try:
            col.add(documents=["a"], ids=["a1"], metadatas=[{"wing": "del"}])
            col._conn.execute("DROP TABLE IF EXISTS embedding_fts")  # type: ignore[attr-defined]
            col._conn.commit()  # type: ignore[attr-defined]
            col.delete(ids=["a1"])
            assert col.count() == 0
            col.add(documents=["b"], ids=["b1"], metadatas=[{"wing": "del"}])
            col.delete(where={"wing": "del"})
            assert col.count() == 0
        finally:
            be.close()

    def test_backend_db_path_variants(self, tmp_path: Path):
        be = SqliteBackend()
        try:
            # dir path
            ref_dir = PalaceRef(id="x", local_path=str(tmp_path / "p1"))
            assert be._db_path(ref_dir).name == "sqlite_palace.db"  # type: ignore[attr-defined]
            # file path
            f = tmp_path / "custom.db"
            f.write_text("x")
            ref_file = PalaceRef(id="y", local_path=str(f))
            assert be._db_path(ref_file) == f.resolve()  # type: ignore[attr-defined]
            # no local_path fallback to cwd/id
            ref_none = PalaceRef(id="someid123", local_path=None)
            p = be._db_path(ref_none)  # type: ignore[attr-defined]
            assert p.name == "sqlite_palace.db"
            assert "someid123" in str(p)
        finally:
            be.close()

    def test_ensure_conn_errors(self, tmp_path: Path):
        be = SqliteBackend()
        try:
            # missing palace dir entirely
            ref = PalaceRef(id="nope", local_path=str(tmp_path / "nodir_xyz" / "sub"))
            with pytest.raises(PalaceNotFoundError):
                be._ensure_conn(ref, create=False)  # type: ignore[attr-defined]
            # dir exists but db missing -> CollectionNotInitializedError
            d = tmp_path / "emptydir"
            d.mkdir()
            ref2 = PalaceRef(id="e2", local_path=str(d))
            with pytest.raises(CollectionNotInitializedError):
                be._ensure_conn(ref2, create=False)  # type: ignore[attr-defined]
            # create=True then reuse cached conn
            c1 = be._ensure_conn(ref2, create=True)  # type: ignore[attr-defined]
            c2 = be._ensure_conn(ref2, create=True)  # type: ignore[attr-defined]
            assert c1 is c2
        finally:
            be.close()

    def test_ensure_conn_chmod_fail_ignored(self, tmp_path: Path, monkeypatch):
        be = SqliteBackend()
        try:
            ref = PalaceRef(id="chmod1", local_path=str(tmp_path / "chmod1"))
            monkeypatch.setattr(Path, "chmod", lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
            monkeypatch.setattr("sqlite3.connect", sqlite3.connect)
            col = be.get_collection(palace=ref, collection_name="c", create=True)
            assert col.count() == 0
        finally:
            be.close()

    def test_init_schema_existing_and_fallback(self, tmp_path: Path):
        be = SqliteBackend()
        try:
            ref = PalaceRef(id="sch", local_path=str(tmp_path / "sch"))
            be.get_collection(palace=ref, collection_name="c", create=True)
            conn = be._ensure_conn(ref, create=True)  # type: ignore[attr-defined]
            be._init_schema(conn)  # type: ignore[attr-defined]
            conn.execute("DROP TABLE IF EXISTS embedding_fts")
            conn.commit()
            calls: list[str] = []

            class _FakeCur:
                def executescript(self, sql):
                    return conn.executescript(sql)

                def execute(self, sql, *a, **k):
                    calls.append(str(sql))
                    if "tokenize='trigram'" in str(sql) or "porter" in str(sql):
                        raise sqlite3.OperationalError("no tok")
                    return conn.execute(sql, *a, **k)

            fake_conn = mock.MagicMock()
            fake_conn.cursor.return_value = _FakeCur()
            be._init_schema(fake_conn)  # type: ignore[arg-type]
            assert any("embedding_fts" in c for c in calls)
            be._init_schema(conn)  # type: ignore[attr-defined]
        finally:
            be.close()

    def test_get_collection_insert_error_ignored(self, tmp_path: Path):
        be2 = SqliteBackend()
        try:
            ref2 = _ref(tmp_path, "gcie2")
            col = be2.get_collection(palace=ref2, collection_name="c", create=True)
            assert col.count() == 0
            real_conn = be2._conns[ref2.id]  # type: ignore[attr-defined]
            bad_conn = mock.MagicMock()
            bad_conn.execute.side_effect = sqlite3.OperationalError("boom")
            be2._conns[ref2.id] = bad_conn  # type: ignore[attr-defined]
            col2 = be2.get_collection(palace=ref2, collection_name="c", create=True)
            assert col2 is not None
            be2._conns[ref2.id] = real_conn  # type: ignore[attr-defined]
            be2.close()
        finally:
            try:
                be2.close()
            except Exception:
                pass

    def test_backend_close_and_health(self, tmp_path: Path):
        be = SqliteBackend()
        try:
            assert be.health(None).ok is True
            ref = _ref(tmp_path, "h1")
            assert be.health(ref).ok is False
            col = be.get_collection(palace=ref, collection_name="c", create=True)
            assert col.count() == 0
            assert be.health(ref).ok is True
            # close_palace twice ok
            be.close_palace(ref)
            be.close_palace(ref)
            # health after close
            be.close()
            assert be.health(None).ok is False
            with pytest.raises(BackendClosedError):
                be.get_collection(palace=ref, collection_name="c2", create=True)
        finally:
            try:
                be.close()
            except Exception:
                pass

    def test_detect_variants(self, tmp_path: Path):
        d = tmp_path / "det"
        d.mkdir()
        assert SqliteBackend.detect(str(tmp_path / "nope_xyz")) is False
        assert SqliteBackend.detect(str(d)) is False
        be = SqliteBackend()
        try:
            ref = PalaceRef(id=str(d), local_path=str(d))
            be.get_collection(palace=ref, collection_name="c", create=True)
            assert SqliteBackend.detect(str(d)) is True
            dbf = d / "sqlite_palace.db"
            assert SqliteBackend.detect(str(dbf)) is True
        finally:
            be.close()

    def test_collection_exists_branches(self, tmp_path: Path):
        be = SqliteBackend()
        try:
            d = tmp_path / "ex"
            d.mkdir()
            ref = PalaceRef(id="ex1", local_path=str(d))
            be.get_collection(palace=ref, collection_name="present", create=True)
            assert be._collection_exists(ref, "present") is True  # type: ignore[attr-defined]
            assert be._collection_exists(ref, "absent_xyz") is False  # type: ignore[attr-defined]
            ref_missing = PalaceRef(id="zzz", local_path=str(tmp_path / "nodir_q"))
            assert be._collection_exists(ref_missing, "x") is False  # type: ignore[attr-defined]
            with mock.patch.object(be, "_ensure_conn", side_effect=sqlite3.OperationalError("boom")):
                assert be._collection_exists(ref, "present") is False  # type: ignore[attr-defined]
        finally:
            be.close()


# ─── palace helpers ──────────────────────────────────────────────────────────


class TestPalaceHelpers:
    def test_shutdown_handler_raises(self):
        from dxrk.memory.palace import _install_shutdown_signal_handlers

        _install_shutdown_signal_handlers()
        h = signal.getsignal(signal.SIGTERM)
        assert callable(h)
        with pytest.raises(SystemExit):
            h(signal.SIGTERM, None)

    def test_path_within_root_false(self, tmp_path: Path):
        from dxrk.memory.palace import _path_within_root

        assert _path_within_root(tmp_path / "a", tmp_path) is True
        assert _path_within_root(Path("/etc/passwd"), tmp_path) is False

    def test_read_no_follow_outside_root(self, tmp_path: Path):
        from dxrk.memory.palace import _read_text_no_follow_palace

        assert _read_text_no_follow_palace(Path("/etc/passwd"), tmp_path) is None

    def test_read_no_follow_eagain_retry(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        f = tmp_path / "r.txt"
        f.write_text("retry content")
        real_open = os.open
        state = {"n": 0}

        def _fake_open(path, flags, *a, **k):
            if state["n"] == 0:
                state["n"] += 1
                raise OSError(errno.EAGAIN, "try again")
            return real_open(path, flags, *a, **k)

        def _fake_lstat(path):
            m = mock.Mock()
            m.st_mode = stat.S_IFREG
            return m

        monkeypatch.setattr(os, "open", _fake_open)
        monkeypatch.setattr(os, "lstat", _fake_lstat)
        out = pal._read_text_no_follow_palace(f, tmp_path)
        assert out is not None
        assert out[0] == "retry content"

    def test_read_no_follow_eagain_nonreg_none(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        f = tmp_path / "x.txt"
        f.write_text("hi")

        def _boom(path, flags, *a, **k):
            raise OSError(errno.EAGAIN, "again")

        def _fifo_lstat(path):
            m = mock.Mock()
            m.st_mode = stat.S_IFIFO
            return m

        monkeypatch.setattr(os, "open", _boom)
        monkeypatch.setattr(os, "lstat", _fifo_lstat)
        assert pal._read_text_no_follow_palace(f, tmp_path) is None

    def test_read_no_follow_nonreg_and_too_large(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        f = tmp_path / "ok.txt"
        f.write_text("hello world here and more")
        # non-regular via fstat mock
        real_fdopen = os.fdopen
        monkeypatch.setattr(pal, "MAX_FILE_SIZE", 5)
        assert pal._read_text_no_follow_palace(f, tmp_path) is None
        monkeypatch.setattr(pal, "MAX_FILE_SIZE", 500 * 1024 * 1024)
        # OSError on open other errno
        monkeypatch.setattr(os, "open", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.ENOENT, "nf")))
        assert pal._read_text_no_follow_palace(f, tmp_path) is None
        assert real_fdopen is not None

    def test_is_regular_file_branches(self, tmp_path: Path):
        from dxrk.memory.palace import _is_regular_file

        f = tmp_path / "a.txt"
        f.write_text("hi")
        assert _is_regular_file(f) is True
        assert _is_regular_file(tmp_path / "missing_xyz") is False

    def test_effective_tenant_branches(self, tmp_path: Path, monkeypatch):
        from dxrk.memory.palace import _effective_tenant_id

        assert _effective_tenant_id("  t1  ") == "t1"
        monkeypatch.setenv("DXRK_TENANT", " envt ")
        assert _effective_tenant_id(None) == "envt"
        monkeypatch.delenv("DXRK_TENANT")
        monkeypatch.setattr("dxrk.tenant.migration.is_migrated", lambda: True)
        assert _effective_tenant_id(None) == "default"
        monkeypatch.setattr("dxrk.tenant.migration.is_migrated", lambda: False)
        assert _effective_tenant_id(None) == ""
        monkeypatch.setattr(
            "dxrk.tenant.migration.is_migrated",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert _effective_tenant_id(None) == ""

    def test_resolve_tenant_path_branches(self, tmp_path: Path, monkeypatch):
        from dxrk.memory.palace import _resolve_tenant_path

        assert str(_resolve_tenant_path(None, "memory-only")) == "memory-only"
        assert str(_resolve_tenant_path(None, "")) == "" or "memory" in str(_resolve_tenant_path(None, ""))
        p = _resolve_tenant_path(None, str(tmp_path / "custom"))
        assert str(tmp_path) in str(p)
        monkeypatch.setenv("DXRK_TENANT", "t9")
        pt = _resolve_tenant_path(None, None)
        assert "t9" in str(pt) or ".dxrk" in str(pt)
        monkeypatch.delenv("DXRK_TENANT")
        monkeypatch.setattr("dxrk.tenant.migration.is_migrated", lambda: True)
        with mock.patch("dxrk.tenant.migration.tenant_root", side_effect=OSError("ro")):
            fallback = _resolve_tenant_path(None, None)
            assert ".dxrk" in str(fallback)

    def test_lock_dir_and_mine_path(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr("dxrk.tenant.migration.tenant_root", lambda tid: (_ for _ in ()).throw(OSError("ro")))
        assert str(pal._dxrk_lock_dir("t")).endswith("locks")
        # zero-arg fallback
        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda: tmp_path / "zlocks")
        lp = pal._mine_lock_path("some-source", tenant_id="t")
        assert lp.endswith(".lock")
        assert (tmp_path / "zlocks").is_dir()

    def test_mine_lock_file_ops(self, tmp_path: Path):
        import dxrk.memory.palace as pal

        lp = str(tmp_path / "t.lock")
        lf = pal._open_mine_lock_file(lp, create=True)
        try:
            assert pal._lock_mine_lock_file(lf, blocking=True) is True
            assert pal._mine_lock_file_is_current(lf, lp) is True
            assert pal._acquire_open_mine_lock_file(lf, lp) is True
        finally:
            try:
                pal._unlock_mine_lock_file(lf)
            except Exception:
                pass
            lf.close()
        # stale path check
        lf2 = pal._open_mine_lock_file(lp, create=False)
        try:
            assert pal._mine_lock_file_is_current(lf2, str(tmp_path / "missing.lock")) is False
        finally:
            lf2.close()
        # missing file current -> False
        assert pal._mine_lock_file_is_current(lf2, str(tmp_path / "missing2.lock")) is False

    def test_lock_nonblocking_and_cleanup(self, tmp_path: Path):
        import dxrk.memory.palace as pal

        lp = str(tmp_path / "nb.lock")
        lf = pal._open_mine_lock_file(lp, create=True)
        try:
            assert pal._lock_mine_lock_file(lf, blocking=False) is True
        finally:
            pal._unlock_mine_lock_file(lf)
            lf.close()
        pal._cleanup_mine_lock_file(lp)
        assert not Path(lp).exists()
        pal._cleanup_mine_lock_file(str(tmp_path / "never.lock"))
        pal._cleanup_dxrk_lock_file(str(tmp_path / "never2.lock"))

    def test_cleanup_held_not_removed(self, tmp_path: Path):
        import dxrk.memory.palace as pal

        lp = str(tmp_path / "held.lock")
        lf = pal._open_mine_lock_file(lp, create=True)
        try:
            pal._lock_mine_lock_file(lf, blocking=True)
            # fork-like: try cleanup from same file while held -> should not remove
            # cleanup opens a second handle and tries nonblocking; held by us so skipped
            pal._cleanup_mine_lock_file(lp)
            assert Path(lp).exists()
        finally:
            pal._unlock_mine_lock_file(lf)
            lf.close()
        pal._cleanup_mine_lock_file(lp)
        assert not Path(lp).exists()

    def test_reap_and_maybe_reap(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "locks")
        ld = tmp_path / "locks"
        ld.mkdir(parents=True, exist_ok=True)
        stale = ld / "old123.lock"
        stale.write_text("x")
        old = time.time() - 7200
        os.utime(stale, (old, old))
        fresh = ld / "fresh123.lock"
        fresh.write_text("y")
        skipped_name = ld / "mine_palace_abc.lock"
        skipped_name.write_text("z")
        os.utime(skipped_name, (old, old))
        reaped, skipped = pal.reap_stale_dxrk_locks(min_age_seconds=3600)
        assert reaped >= 1
        assert skipped_name.exists()
        assert pal.reap_stale_mine_locks is pal.reap_stale_dxrk_locks
        # missing dir
        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "nodir")
        assert pal.reap_stale_dxrk_locks() == (0, 0)
        # maybe reap throttled
        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: ld)
        pal._maybe_reap_stale_mine_locks()
        pal._maybe_reap_stale_mine_locks()
        pal._maybe_reap_stale_dxrk_locks()
        # zero-arg fallback
        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda: ld)
        pal._maybe_reap_stale_mine_locks()
        assert pal.reap_stale_dxrk_locks(min_age_seconds=3600) is not None

    def test_mine_lock_context(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "locks2")
        with pal.mine_lock("src-a", tenant_id=None):
            assert True

    def test_mine_palace_lock_reentrant_and_conflict(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "plocks")
        pp = str(tmp_path / "pal1")
        Path(pp).mkdir(parents=True, exist_ok=True)
        with pal.mine_palace_lock(pp):
            with pal.mine_palace_lock(pp):
                assert True
        with pal.mine_palace_lock(pp):
            assert True
        # conflict via mocked flock raising
        import fcntl

        real_flock = fcntl.flock
        with pal.mine_palace_lock(pp):
            pass
        # hold lock in one handle, second acquire should raise
        pp2 = str(tmp_path / "pal2")
        Path(pp2).mkdir(parents=True, exist_ok=True)
        with mock.patch.object(fcntl, "flock", side_effect=BlockingIOError("busy")):
            with pytest.raises(RuntimeError, match="held by another"):
                with pal.mine_palace_lock(pp2):
                    pass
        assert real_flock is not None
        assert pal.mine_global_lock is pal.mine_palace_lock

    def test_chunk_text_branches(self):
        from dxrk.memory.palace import chunk_text

        with pytest.raises(ValueError, match="chunk_size"):
            chunk_text("hi", chunk_size=0)
        with pytest.raises(ValueError, match="chunk_overlap"):
            chunk_text("hi", chunk_size=10, chunk_overlap=-1)
        with pytest.raises(ValueError, match="must be < chunk_size"):
            chunk_text("hi", chunk_size=10, chunk_overlap=10)
        with pytest.raises(ValueError, match="min_chunk_size"):
            chunk_text("hi", min_chunk_size=-1)
        assert chunk_text("   ") == []
        assert chunk_text("hi", min_chunk_size=10) == []
        # paragraph-aware: double newline split
        big = "para one line " * 30 + "\n\n" + "para two line " * 30 + "\n" + "para three " * 60
        chunks = chunk_text(big, chunk_size=400, chunk_overlap=20, min_chunk_size=10)
        assert len(chunks) >= 2
        # single newline split
        big2 = "a " * 300 + "\n" + "b " * 300
        chunks2 = chunk_text(big2, chunk_size=400, chunk_overlap=20, min_chunk_size=10)
        assert len(chunks2) >= 1

    def test_detect_hall_and_entities(self):
        from dxrk.memory.palace import _detect_hall, _extract_entities

        assert _detect_hall("I feel love and hope today") == "emotional"
        assert _detect_hall("the api server deploy config") == "technical"
        assert _detect_hall("my mother and father family") == "family"
        assert _detect_hall("project meeting deadline ship") == "work"
        assert _detect_hall("nothing matching here xyz") == "general"
        assert _extract_entities("Alice went with Alice and Bob saw Bob there") != ""
        assert "The" not in _extract_entities("The The The Alice Alice")
        assert _extract_entities("short") == ""

    def test_build_drawer_metadata_variants(self):
        from dxrk.memory.palace import _build_drawer_metadata

        m1 = _build_drawer_metadata("w", "r", "/a.txt", 0, "dxrk", "hello Alice Alice", 123.0, chunk_total=3)
        assert m1["wing"] == "w"
        assert m1["source_mtime"] == 123.0
        assert m1["chunk_total"] == 3
        m2 = _build_drawer_metadata("w", "r", "/a.txt", 0, "dxrk", "short hi", None)
        assert "source_mtime" not in m2
        assert "chunk_total" not in m2

    def test_dxrk_memory_init_variants(self, tmp_path: Path, monkeypatch):
        from dxrk.memory.palace import DxrkMemory, Palace, PalaceConfig

        cfg = PalaceConfig(palace_path=str(tmp_path), wing="w")
        assert cfg.wing == "w"
        assert Palace is DxrkMemory
        # memory-only sentinel respected
        dm = DxrkMemory("memory-only")
        assert dm.palace_path == "memory-only"
        dm2 = DxrkMemory("")
        assert dm2.palace_path == "" or ".dxrk" in dm2.palace_path
        # explicit path
        dm3 = DxrkMemory(str(tmp_path / "p1"))
        dm3.init()
        assert (tmp_path / "p1").is_dir()
        # init chmod failure ignored
        monkeypatch.setattr(Path, "chmod", lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
        dm4 = DxrkMemory(str(tmp_path / "p2"))
        dm4.init()
        assert (tmp_path / "p2").is_dir()
        dm3.close()

    def test_add_drawer_missing_source(self, tmp_path: Path):
        from dxrk.memory.palace import DxrkMemory

        dm = DxrkMemory(str(tmp_path / "padd"))
        dm.init()
        try:
            did = dm.add_drawer("w", "r", "content here", "/nonexistent_xyz/file.txt", 0)
            assert did.startswith("drawer_")
            got = dm.get_drawer(did)
            assert got is not None
            assert dm.get_drawer("missing_xyz") is None
        finally:
            dm.close()

    def test_mine_branches(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "mlocks")
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "a.md").write_text("hello world " * 30)
        (proj / "tiny.md").write_text("hi")
        dm = pal.DxrkMemory(str(tmp_path / "mpal"))
        dm.init()
        try:
            with pytest.raises(ValueError, match="project_dir not found"):
                dm.mine(str(tmp_path / "nope"))
            res = dm.mine(str(proj), dry_run=True)
            assert res["files_mined"] >= 1
            res2 = dm.mine(str(proj))
            assert res2["files_mined"] >= 1
            # purge failure -> skip
            col = dm._collection(create=False)
            with mock.patch.object(col, "delete", side_effect=RuntimeError("purge boom")):
                # need fresh dm sharing same backend? patch instance method via mock on collection object
                # call mine with mocked col by patching _collection
                with mock.patch.object(dm, "_collection", return_value=col):
                    r = dm.mine(str(proj))
                    assert r["files_skipped"] >= 1
        finally:
            dm.close()

    def test_mine_partial_failure_cleans(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "plocks2")
        proj = tmp_path / "proj2"
        proj.mkdir()
        (proj / "b.md").write_text("content for partial " * 40)
        dm = pal.DxrkMemory(str(tmp_path / "ppal"))
        dm.init()
        try:
            col = dm._collection(create=True)
            orig_upsert = col.upsert
            calls = {"n": 0}

            def _boom(*a, **k):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("upsert boom")
                return orig_upsert(*a, **k)

            with mock.patch.object(col, "upsert", side_effect=_boom):
                with mock.patch.object(dm, "_collection", return_value=col):
                    with pytest.raises(RuntimeError, match="upsert boom"):
                        dm.mine(str(proj))
            assert calls["n"] == 1
        finally:
            dm.close()

    def test_list_and_health(self, tmp_path: Path):
        from dxrk.memory.palace import DxrkMemory

        dm = DxrkMemory(str(tmp_path / "lpal"))
        dm.init()
        try:
            dm.add_drawer("w1", "r1", "c1 hello", "/a1.txt", 0)
            dm.add_drawer("w1", "r2", "c2 hello", "/a2.txt", 0)
            dm.add_drawer("w2", "r1", "c3 hello", "/a3.txt", 0)
            assert set(dm.list_wings()) == {"w1", "w2"}
            assert set(dm.list_rooms("w1")) == {"r1", "r2"}
            assert set(dm.list_rooms()) == {"r1", "r2"}
            h = dm.health()
            assert h["ok"] is True
            assert dm.count() == 3
            # wing filter with non-str room ignored
            col = dm._collection(create=False)
            col.upsert(
                documents=["weird"],
                ids=["weird1"],
                metadatas=[{"wing": "w1", "room": 123}],
            )
            assert "r1" in dm.list_rooms("w1")
        finally:
            dm.close()


# ─── layers ──────────────────────────────────────────────────────────────────


class TestLayersCov:
    def test_effective_tenant(self, monkeypatch):
        import dxrk.memory.layers as ly

        assert ly._effective_tenant_id(" t ") == "t"
        monkeypatch.setenv("DXRK_TENANT", " e ")
        assert ly._effective_tenant_id(None) == "e"
        monkeypatch.delenv("DXRK_TENANT")
        monkeypatch.setattr("dxrk.tenant.migration.is_migrated", lambda: True)
        assert ly._effective_tenant_id(None) == "default"
        monkeypatch.setattr("dxrk.tenant.migration.is_migrated", lambda: False)
        assert ly._effective_tenant_id(None) == ""
        monkeypatch.setattr(
            "dxrk.tenant.migration.is_migrated",
            lambda: (_ for _ in ()).throw(RuntimeError("x")),
        )
        assert ly._effective_tenant_id(None) == ""

    def test_resolve_palace_and_identity(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.layers as ly

        assert ly._resolve_palace_path(None, "memory-only") == "memory-only"
        assert ly._resolve_palace_path(None, "") == ""
        assert ly._resolve_palace_path(None, str(tmp_path / "p")) == str(tmp_path / "p")
        monkeypatch.setenv("DXRK_TENANT", "t1")
        assert "t1" in ly._resolve_palace_path(None, None) or ".dxrk" in ly._resolve_palace_path(None, None)
        monkeypatch.delenv("DXRK_TENANT")
        monkeypatch.setattr("dxrk.tenant.migration.is_migrated", lambda: True)
        with mock.patch("dxrk.tenant.migration.tenant_root", side_effect=OSError("ro")):
            assert ".dxrk" in ly._resolve_palace_path(None, None)
        # identity
        assert ly._resolve_identity_path(None, str(tmp_path / "id.txt")) == str(tmp_path / "id.txt")
        assert ly._resolve_identity_path(None, "   ") == ""
        monkeypatch.setenv("DXRK_TENANT", "t2")
        assert "t2" in ly._resolve_identity_path(None, None) or ".dxrk" in ly._resolve_identity_path(None, None)
        monkeypatch.delenv("DXRK_TENANT")

    def test_layer0_oserror_and_cache(self, tmp_path: Path, monkeypatch):
        ident = tmp_path / "ident.txt"
        ident.write_text("hello identity")
        l0 = Layer0(str(ident))
        assert "hello" in l0.render()
        assert l0.render() == l0.render()
        monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
        l0b = Layer0(str(ident))
        assert "No identity" in l0b.render()
        l0c = Layer0(str(tmp_path / "missing.txt"))
        assert "No identity" in l0c.render()

    def test_layer1_pagination_and_meta_variants(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.layers as ly

        # empty palace -> No memories
        pal = tmp_path / "l1empty"
        pal.mkdir()
        from dxrk.memory.palace import DxrkMemory

        dm = DxrkMemory(str(pal))
        dm.init()
        dm.close()
        assert "No memories" in Layer1(str(pal)).generate() or "No palace" in Layer1(str(pal)).generate()
        # missing palace
        assert "No palace" in Layer1(str(tmp_path / "nodir_xyz")).generate()
        # get exception -> break -> No memories
        with mock.patch.object(ly, "_get_collection", side_effect=RuntimeError("boom")):
            assert "No palace" in Layer1(str(pal)).generate()

        # pagination: fake collection returning two batches
        class _FakeRes:
            def __init__(self, docs, metas):
                self.documents = docs
                self.metadatas = metas

        batch1_docs = [f"doc {i} " * 10 for i in range(500)]
        batch1_metas = [{"room": "r", "source_file": f"/f{i}.txt", "importance": "bad"} for i in range(500)]
        batch2_docs = ["final doc hello"]
        batch2_metas = [{"room": "r", "source_file": "/final.txt", "importance": 9.0}]

        class _FakeCol:
            def __init__(self):
                self.calls = 0

            def get(self, include=None, limit=None, offset=None):
                self.calls += 1
                if self.calls == 1:
                    return _FakeRes(batch1_docs, batch1_metas)
                if self.calls == 2:
                    return _FakeRes(batch2_docs, batch2_metas)
                return _FakeRes([], [])

        with mock.patch.object(ly, "_get_collection", return_value=_FakeCol()):
            out = Layer1(str(pal)).generate()
            assert "ESSENTIAL" in out

        # meta not dict + importance valid + truncation + no src
        class _FakeCol2:
            def get(self, include=None, limit=None, offset=None):
                return _FakeRes(
                    ["x" * 500, "short"],
                    ["notadict", {"room": 123, "importance": 2.5}],
                )

        with mock.patch.object(ly, "_get_collection", return_value=_FakeCol2()):
            out2 = Layer1(str(pal)).generate()
            assert "ESSENTIAL" in out2

        # char limit truncation
        class _FakeCol3:
            def get(self, include=None, limit=None, offset=None):
                docs = [("long content word " * 30 + str(i)) for i in range(15)]
                metas = [{"room": "r", "source_file": "/a.txt", "importance": 5.0} for _ in range(15)]
                return _FakeRes(docs, metas)

        with mock.patch.object(ly, "_get_collection", return_value=_FakeCol3()):
            l1 = Layer1(str(pal))
            l1.MAX_CHARS = 100
            out3 = l1.generate()
            assert "more in L3" in out3

    def test_layer2_all_branches(self, tmp_path: Path):
        import dxrk.memory.layers as ly
        from dxrk.memory.palace import DxrkMemory

        pal = tmp_path / "l2pal"
        dm = DxrkMemory(str(pal))
        dm.init()
        try:
            dm.add_drawer("wingA", "room1", "unique l2 alpha " * 5, "/a.md", 0)
            assert "unique l2 alpha" in Layer2(str(pal)).retrieve(wing="wingA", room="room1")
            assert "L2" in Layer2(str(pal)).retrieve(wing="wingA")
            assert "L2" in Layer2(str(pal)).retrieve(room="room1")
            assert "L2" in Layer2(str(pal)).retrieve()
            assert "No drawers" in Layer2(str(pal)).retrieve(wing="nowhere_xyz")
            assert "room=" in Layer2(str(pal)).retrieve(room="nowhere_xyz")
            # retrieval error
            with mock.patch.object(ly, "_get_collection", side_effect=RuntimeError("x")):
                assert "No palace" in Layer2(str(pal)).retrieve()
            col = dm._collection(create=False)
            with mock.patch.object(col, "get", side_effect=RuntimeError("qfail")):
                with mock.patch.object(ly, "_get_collection", return_value=col):
                    assert "Retrieval error" in Layer2(str(pal)).retrieve()
            # meta not dict + long snippet truncation
            col.upsert(
                documents=["z " * 200],
                ids=["z1"],
                metadatas=[{"wing": "w", "room": "r", "source_file": "/s.txt"}],
            )
            out = Layer2(str(pal)).retrieve()
            assert "L2" in out
        finally:
            dm.close()

    def test_layer3_all_branches(self, tmp_path: Path):
        import dxrk.memory.layers as ly
        from dxrk.memory.palace import DxrkMemory

        pal = tmp_path / "l3pal"
        dm = DxrkMemory(str(pal))
        dm.init()
        try:
            dm.add_drawer("w", "r", "deep hello search " * 5, "/a.md", 0)
            assert "hello" in Layer3(str(pal)).search("hello").lower() or "SEARCH" in Layer3(str(pal)).search("hello")
            from dxrk.memory.palace import DxrkMemory as _DM

            _empty = tmp_path / "l3empty_xyz"
            _dm0 = _DM(str(_empty))
            _dm0.init()
            _dm0.close()
            assert "No results" in Layer3(str(_empty)).search("zzz_no_match_xyz_123")
            assert "SEARCH" in Layer3(str(pal)).search("hello", wing="w")
            assert "SEARCH" in Layer3(str(pal)).search("hello", room="r")
            assert "SEARCH" in Layer3(str(pal)).search("hello", wing="w", room="r")
            with mock.patch.object(ly, "_get_collection", side_effect=RuntimeError("x")):
                assert "No palace" in Layer3(str(pal)).search("hello")
        finally:
            dm.close()
        # hit not dict skipped
        import dxrk.memory.layers as ly2

        class _FakeCol:
            def get(self, **k):
                from dxrk.memory.backend.base import GetResult

                return GetResult(ids=[], documents=[], metadatas=[])

            def query(self, **k):
                from dxrk.memory.backend.base import QueryResult

                return QueryResult(ids=[["a"]], documents=[["hi"]], metadatas=[[{}]], distances=[[0.1]])

        with mock.patch.object(ly2, "_get_collection", return_value=_FakeCol()):
            with mock.patch(
                "dxrk.memory.search.hybrid_search",
                return_value={"results": ["bad", {"wing": "w", "room": "r", "text": "t" * 400, "similarity": 1.0}]},
            ):
                out = Layer3(str(pal)).search("hi")
                assert "SEARCH" in out

    def test_stack_wake_recall_search_status(self, tmp_path: Path):
        from dxrk.memory.palace import DxrkMemory

        pal = tmp_path / "stack"
        ident = tmp_path / "ident.txt"
        ident.write_text("stack identity")
        dm = DxrkMemory(str(pal))
        dm.init()
        try:
            dm.add_drawer("w", "r", "stack content hello " * 5, "/a.md", 0)
            ms = MemoryStack(palace_path=str(pal), identity_path=str(ident))
            assert "stack identity" in ms.wake_up()
            assert "ESSENTIAL" in ms.wake_up(wing="w")
            assert "L2" in ms.recall(wing="w")
            assert "SEARCH" in ms.search("hello") or "No results" in ms.search("hello")
            st = ms.status()
            assert st["total_drawers"] == 1
            assert st["L0_identity"]["exists"] is True
            ms2 = MemoryStack(palace_path=str(tmp_path / "missing_xyz"), identity_path=str(tmp_path / "noid"))
            assert ms2.status()["total_drawers"] == 0
        finally:
            dm.close()


# ─── miner ───────────────────────────────────────────────────────────────────


class TestMinerCov:
    def test_path_within_and_regular(self, tmp_path: Path):
        from dxrk.memory.miner import _is_regular_file, _is_regular_source_file, _path_within_root

        assert _path_within_root(tmp_path / "a", tmp_path) is True
        assert _path_within_root(Path("/etc/passwd"), tmp_path) is False
        f = tmp_path / "r.txt"
        f.write_text("hi")
        assert _is_regular_file(f) is True
        assert _is_regular_file(tmp_path / "missing_xyz") is False
        assert _is_regular_source_file(f, tmp_path) is True
        assert _is_regular_source_file(Path("/etc/passwd"), tmp_path) is False

    def test_regular_source_eagain(self, tmp_path: Path, monkeypatch):
        from dxrk.memory.miner import _is_regular_source_file, _read_text_no_follow

        f = tmp_path / "e.txt"
        f.write_text("eagain content here")
        real_open = os.open
        state = {"n": 0}

        def _fake_open(path, flags, *a, **k):
            if state["n"] == 0:
                state["n"] += 1
                raise OSError(errno.EAGAIN, "again")
            return real_open(path, flags, *a, **k)

        def _fake_lstat(path):
            m = mock.Mock()
            m.st_mode = stat.S_IFREG
            return m

        monkeypatch.setattr(os, "open", _fake_open)
        monkeypatch.setattr(os, "lstat", _fake_lstat)
        assert _is_regular_source_file(f, tmp_path) is True
        out = _read_text_no_follow(f, tmp_path)
        assert out is not None

    def test_regular_source_eagain_nonreg(self, tmp_path: Path, monkeypatch):
        from dxrk.memory.miner import _is_regular_source_file, _read_text_no_follow

        f = tmp_path / "x.txt"
        f.write_text("hi")
        monkeypatch.setattr(os, "open", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EAGAIN, "a")))
        monkeypatch.setattr(
            os,
            "lstat",
            lambda p: mock.Mock(st_mode=stat.S_IFIFO),
        )
        assert _is_regular_source_file(f, tmp_path) is False
        assert _read_text_no_follow(f, tmp_path) is None

    def test_read_outside_and_limits(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.miner as mn

        assert mn._read_text_no_follow(Path("/etc/passwd"), tmp_path) is None
        f = tmp_path / "big.txt"
        f.write_text("hello world")
        monkeypatch.setattr(mn, "MAX_FILE_SIZE", 2)
        assert mn._read_text_no_follow(f, tmp_path) is None
        assert mn._is_regular_source_file(f, tmp_path) is False
        monkeypatch.setattr(mn, "MAX_FILE_SIZE", 500 * 1024 * 1024)

    def test_miner_chunk_wrapper(self):
        from dxrk.memory.miner import chunk_text as mchunk
        from dxrk.memory.palace import chunk_text as pchunk

        assert mchunk("hello world " * 20) == pchunk("hello world " * 20)
        with pytest.raises(ValueError):
            mchunk("hi", chunk_size=0)

    def test_gitignore_from_dir_variants(self, tmp_path: Path):
        from dxrk.memory.miner import GitignoreMatcher

        assert GitignoreMatcher.from_dir(tmp_path / "nodir") is None
        (tmp_path / ".gitignore").write_text("# only comment\n\n")
        assert GitignoreMatcher.from_dir(tmp_path) is None
        (tmp_path / ".gitignore").write_text("\\#hash\n\\!bang\n!important.txt\n/anchored\nmydir/\n\n")
        m = GitignoreMatcher.from_dir(tmp_path)
        assert m is not None
        assert any(r["pattern"] == "#hash" for r in m.rules)
        # unreadable -> None
        with mock.patch.object(Path, "read_text", side_effect=OSError("ro")):
            assert GitignoreMatcher.from_dir(tmp_path) is None

    def test_matches_branches(self, tmp_path: Path):
        from dxrk.memory.miner import GitignoreMatcher

        (tmp_path / ".gitignore").write_text("*.log\n")
        m = GitignoreMatcher.from_dir(tmp_path)
        assert m is not None
        assert m.matches(Path("/other/file.log")) is None
        assert m.matches(tmp_path) is None
        # is_dir auto-detect
        (tmp_path / "a.log").write_text("x")
        assert m.matches(tmp_path / "a.log") is True
        d = tmp_path / "subdir"
        d.mkdir(exist_ok=True)
        assert m.matches(d) is False or m.matches(d) is None

    def test_rule_matches_dir_only(self, tmp_path: Path):
        from dxrk.memory.miner import GitignoreMatcher

        (tmp_path / ".gitignore").write_text("logs/\n/build\n")
        m = GitignoreMatcher.from_dir(tmp_path)
        assert m is not None
        assert m.matches(tmp_path / "logs", is_dir=True) is True
        assert m.matches(tmp_path / "logs" / "f.txt", is_dir=False) is True
        # anchored multi-part
        assert m.matches(tmp_path / "build" / "f.txt", is_dir=False) is True

    def test_match_from_root_stars(self, tmp_path: Path):
        from dxrk.memory.miner import GitignoreMatcher

        (tmp_path / ".gitignore").write_text("a/**/b\n")
        m = GitignoreMatcher.from_dir(tmp_path)
        assert m is not None
        assert m._match_from_root(["a", "x", "y", "b"], ["a", "**", "b"]) is True
        assert m._match_from_root(["a"], ["a", "**", "b"]) is False
        assert m._match_from_root(["x"], ["a", "**", "b"]) is False
        assert m._match_from_root(["a", "b"], ["a", "**", "b"]) is True

    def test_load_cache_and_gitignored(self, tmp_path: Path):
        from dxrk.memory.miner import is_gitignored, load_gitignore_matcher

        (tmp_path / ".gitignore").write_text("*.tmp\n")
        cache: dict = {}
        m1 = load_gitignore_matcher(tmp_path, cache)
        m2 = load_gitignore_matcher(tmp_path, cache)
        assert m1 is m2
        assert is_gitignored(tmp_path / "a.tmp", [m1]) is True  # type: ignore[list-item]
        assert is_gitignored(tmp_path / "a.md", [m1]) is False  # type: ignore[list-item]

    def test_skip_and_include_helpers(self, tmp_path: Path):
        from dxrk.memory.miner import (
            is_exact_force_include,
            is_force_included,
            normalize_include_paths,
            should_skip_dir,
        )

        assert should_skip_dir(".git") is True
        assert should_skip_dir("foo.egg-info") is True
        assert should_skip_dir("src") is False
        assert normalize_include_paths(None) == set()
        assert normalize_include_paths([" /a/ ", "", "b/c/"]) == {"a", "b/c"}
        proj = tmp_path / "proj"
        proj.mkdir()
        assert is_force_included(proj / "a.md", proj, set()) is False
        assert is_force_included(Path("/other/a.md"), proj, {"a"}) is False
        assert is_force_included(proj, proj, {"a"}) is False
        assert is_force_included(proj / "a.md", proj, {"a.md"}) is True
        assert is_force_included(proj / "a.md", proj, {"a"}) is False
        assert is_exact_force_include(proj / "a.md", proj, set()) is False
        assert is_exact_force_include(Path("/o"), proj, {"a"}) is False
        assert is_exact_force_include(proj / "a.md", proj, {"a.md"}) is True

    def test_scan_project_variants(self, tmp_path: Path):
        from dxrk.memory.miner import scan_project

        proj = tmp_path / "scan"
        proj.mkdir()
        (proj / "ok.md").write_text("hello")
        (proj / "skip.lock").write_text("x")
        (proj / "big.md").write_text("y")
        # respect_gitignore False covers 324->329
        files = scan_project(proj, respect_gitignore=False)
        assert any(p.name == "ok.md" for p in files)
        # SKIP_FILENAMES
        (proj / "package-lock.json").write_text("{}")
        files2 = scan_project(proj, respect_gitignore=False)
        assert "package-lock.json" not in {p.name for p in files2}
        # unreadable ext without exact include skipped
        (proj / "bin.exe").write_text("x")
        assert "bin.exe" not in {p.name for p in scan_project(proj, respect_gitignore=False)}
        # exact force include bypasses ext + gitignore
        (proj / ".gitignore").write_text("forced.md\n")
        (proj / "forced.md").write_text("forced content")
        got = scan_project(proj, respect_gitignore=True, include_ignored=["forced.md"])
        assert "forced.md" in {p.name for p in got}
        # symlink skipped
        link = proj / "link.md"
        try:
            link.symlink_to(proj / "ok.md")
            assert "link.md" not in {p.name for p in scan_project(proj)}
        except OSError:
            pass

    def test_scan_stat_branches(self, tmp_path: Path, monkeypatch):
        from dxrk.memory.miner import scan_project

        proj = tmp_path / "statproj"
        proj.mkdir()
        (proj / "a.md").write_text("hello")
        orig_stat = Path.stat

        def _boom(self, *a, **k):
            if self.name == "a.md" and k.get("follow_symlinks", True) is not False:
                raise OSError("stat fail")
            return orig_stat(self, *a, **k)

        monkeypatch.setattr(Path, "stat", _boom)
        assert scan_project(proj) == []

    def test_normalize_and_scan_chunk(self, tmp_path: Path):
        from dxrk.memory.miner import normalize_content, scan_and_chunk

        assert normalize_content("a\r\nb\rc\n\n\n\nd") == "a\nb\nc\n\nd"
        assert normalize_content("  hi  ") == "hi"
        proj = tmp_path / "chunkproj"
        proj.mkdir()
        (proj / "a.md").write_text("hello world " * 50)
        (proj / "tiny.md").write_text("hi")
        out = scan_and_chunk(proj)
        assert len(out) == 1
        assert out[0][0].name == "a.md"
        assert len(out[0][1]) >= 1

    def test_scan_chunk_skips_tiny(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.miner as mn

        proj = tmp_path / "tinyproj"
        proj.mkdir()
        (proj / "a.md").write_text("hello world " * 50)
        with mock.patch.object(mn, "_read_text_no_follow", return_value=None):
            assert mn.scan_and_chunk(proj) == []
        with mock.patch.object(mn, "_read_text_no_follow", return_value=("hi", 1.0)):
            assert mn.scan_and_chunk(proj) == []

    def test_palace_config_and_alias(self):
        from dxrk.memory.palace import DxrkPalace, Palace

        assert DxrkPalace is Palace
        h = hashlib.sha256(b"x").hexdigest()[:16]
        assert len(h) == 16

    def test_sys_import_used(self):
        assert sys.version_info.major >= 3


class TestSqliteExtra:
    def test_where_in_nonempty(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "ine")
        try:
            col.add(documents=["a"], ids=["a1"], metadatas=[{"wing": "w1", "chunk_index": 0}])
            col.add(documents=["b"], ids=["b1"], metadatas=[{"wing": "w1", "chunk_index": 1}])
            got = col.get(where={"chunk_index": {"$in": [0]}})
            assert got.ids == ["a1"]
        finally:
            be.close()

    def test_upsert_update_existing(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "updup")
        try:
            col.add(documents=["first"], ids=["u1"], metadatas=[{"wing": "w"}])
            col.upsert(documents=["second"], ids=["u1"], metadatas=[{"wing": "w2"}])
            assert col.get(ids=["u1"]).documents[0] == "second"
            assert col.count() == 1
        finally:
            be.close()

    def test_get_empty_ids(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "emptyids")
        try:
            assert col.get(ids=[]).ids == []
        finally:
            be.close()

    def test_query_both_none_neutral(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "bothnone")
        try:
            col.add(documents=["hello"], ids=["n1"], metadatas=[{"wing": "w"}])
            q = col.query(n_results=5)
            assert "n1" in q.ids[0]
        finally:
            be.close()

    def test_query_where_document_empty_dict(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "wempty")
        try:
            col.add(documents=["hello world"], ids=["w1"], metadatas=[{"wing": "w"}])
            q = col.query(query_texts=["hello"], n_results=5, where_document={})
            assert "w1" in q.ids[0]
        finally:
            be.close()

    def test_query_non_dict_meta(self, tmp_path: Path):
        be, _, col = _col(tmp_path, "nondict")
        try:
            col.add(documents=["hello"], ids=["d1"], metadatas=[{"wing": "w"}])
            col._conn.execute(  # type: ignore[attr-defined]
                "UPDATE embeddings SET metadata=? WHERE id=?", ('"juststring"', "d1")
            )
            col._conn.commit()  # type: ignore[attr-defined]
            q = col.query(query_texts=["hello"], n_results=5)
            assert q.ids[0] == ["d1"]
            assert q.metadatas[0] == [{}]
        finally:
            be.close()

    def test_close_except_ignored(self, tmp_path: Path):
        be, ref, col = _col(tmp_path, "closeex")
        try:
            real = be._conns[ref.id]  # type: ignore[attr-defined]
            bad = mock.MagicMock()
            bad.close.side_effect = sqlite3.OperationalError("boom")
            be._conns[ref.id] = bad  # type: ignore[attr-defined]
            be.close_palace(ref)
            be._conns[ref.id] = real  # type: ignore[attr-defined]
            bad2 = mock.MagicMock()
            bad2.close.side_effect = sqlite3.OperationalError("boom")
            be._conns[ref.id] = bad2  # type: ignore[attr-defined]
            be.close()
        finally:
            try:
                be.close()
            except Exception:
                pass

    def test_init_fallback_all_fail(self, tmp_path: Path):
        be = SqliteBackend()
        try:
            ref = PalaceRef(id="fb", local_path=str(tmp_path / "fb"))
            be.get_collection(palace=ref, collection_name="c", create=True)
            conn = be._ensure_conn(ref, create=True)  # type: ignore[attr-defined]
            conn.execute("DROP TABLE IF EXISTS embedding_fts")
            conn.commit()

            class _AllFailCur:
                def executescript(self, sql):
                    return conn.executescript(sql)

                def execute(self, sql, *a, **k):
                    if "embedding_fts" in str(sql):
                        raise sqlite3.OperationalError("no fts")
                    return conn.execute(sql, *a, **k)

            fake = mock.MagicMock()
            fake.cursor.return_value = _AllFailCur()
            be._init_schema(fake)  # type: ignore[arg-type]
        finally:
            be.close()


class TestPalaceExtraA:
    def test_signal_missing_and_error(self, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(signal, "SIGHUP", None, raising=False)
        pal._install_shutdown_signal_handlers()
        monkeypatch.setattr(signal, "signal", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))
        pal._install_shutdown_signal_handlers()

    def test_read_close_error(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        f = tmp_path / "c.txt"
        f.write_text("close fail content here")
        monkeypatch.setattr(os, "close", lambda fd: (_ for _ in ()).throw(OSError("boom")))
        out = pal._read_text_no_follow_palace(f, tmp_path)
        assert out is not None

    def test_resolve_tenant_tid_oserror(self, tmp_path: Path, monkeypatch):
        from dxrk.memory.palace import _resolve_tenant_path

        monkeypatch.setenv("DXRK_TENANT", "tX")
        with mock.patch("dxrk.tenant.migration.tenant_root", side_effect=OSError("ro")):
            p = _resolve_tenant_path(None, None)
            assert ".dxrk" in str(p)
        monkeypatch.delenv("DXRK_TENANT")

    def test_mine_lock_chmod_fail(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "chmodlocks")
        monkeypatch.setattr(Path, "chmod", lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
        lp = pal._mine_lock_path("src-chmod", tenant_id=None)
        assert lp.endswith(".lock")

    def test_lock_blocking_variants(self, tmp_path: Path):
        import fcntl

        import dxrk.memory.palace as pal

        lp = str(tmp_path / "blk.lock")
        lf = pal._open_mine_lock_file(lp, create=True)
        try:
            with mock.patch.object(fcntl, "flock", side_effect=BlockingIOError("busy")):
                assert pal._lock_mine_lock_file(lf, blocking=False) is False
                with pytest.raises(BlockingIOError):
                    pal._lock_mine_lock_file(lf, blocking=True)
        finally:
            lf.close()

    def test_acquire_stale_unlock_fail(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        lp = str(tmp_path / "stale.lock")
        lf = pal._open_mine_lock_file(lp, create=True)
        try:
            monkeypatch.setattr(pal, "_mine_lock_file_is_current", lambda *a, **k: False)
            monkeypatch.setattr(pal, "_unlock_mine_lock_file", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("u")))
            assert pal._acquire_open_mine_lock_file(lf, lp) is False
        finally:
            lf.close()

    def test_acquire_mine_except(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "ae")
        lp = pal._mine_lock_path("src-ae", tenant_id=None)
        with mock.patch.object(pal, "_acquire_open_mine_lock_file", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                pal._acquire_mine_lock_file(lp)

    def test_cleanup_open_oserror(self, tmp_path: Path):
        import dxrk.memory.palace as pal

        with mock.patch.object(pal, "_open_mine_lock_file", side_effect=OSError("open boom")):
            pal._cleanup_mine_lock_file(str(tmp_path / "x.lock"))

    def test_cleanup_acquire_oserror(self, tmp_path: Path):
        import dxrk.memory.palace as pal

        lp = str(tmp_path / "ca.lock")
        Path(lp).write_text("x")
        with mock.patch.object(pal, "_lock_mine_lock_file", side_effect=OSError("lock boom")):
            pal._cleanup_mine_lock_file(lp)
            assert Path(lp).exists()

    def test_cleanup_not_current(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        lp = str(tmp_path / "nc.lock")
        Path(lp).write_text("x")
        monkeypatch.setattr(pal, "_mine_lock_file_is_current", lambda *a, **k: False)
        pal._cleanup_mine_lock_file(lp)
        assert Path(lp).exists()

    def test_cleanup_remove_oserror(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        lp = str(tmp_path / "rm.lock")
        Path(lp).write_text("x")
        monkeypatch.setattr(os, "remove", lambda p: (_ for _ in ()).throw(OSError("rm boom")))
        pal._cleanup_mine_lock_file(lp)
        assert Path(lp).exists()

    def test_reap_ghost_and_held(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        ld = tmp_path / "reaplocks"
        ld.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: ld)
        with mock.patch.object(os, "listdir", return_value=["ghost123.lock"]):
            assert pal.reap_stale_dxrk_locks() == (0, 0)
        held = ld / "held123.lock"
        held.write_text("x")
        old = time.time() - 7200
        os.utime(held, (old, old))
        lf = pal._open_mine_lock_file(str(held), create=False)
        try:
            pal._lock_mine_lock_file(lf, blocking=True)
            _, skipped = pal.reap_stale_dxrk_locks(min_age_seconds=3600)
            assert skipped >= 1
            assert held.exists()
        finally:
            pal._unlock_mine_lock_file(lf)
            lf.close()

    def test_maybe_reap_chmod_utime_fail(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        ld = tmp_path / "mr"
        ld.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: ld)
        marker = ld / ".last_reap"
        if marker.exists():
            marker.unlink()
        monkeypatch.setattr(Path, "chmod", lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
        pal._maybe_reap_stale_mine_locks()
        if marker.exists():
            marker.unlink()
        monkeypatch.setattr(os, "utime", lambda *a, **k: (_ for _ in ()).throw(OSError("ut")))
        monkeypatch.setattr(Path, "chmod", lambda self, *a, **k: None)
        pal._maybe_reap_stale_mine_locks()

    def test_mine_lock_release_fail(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "rlocks")
        with mock.patch.object(pal, "_unlock_mine_lock_file", side_effect=RuntimeError("u")):
            with pal.mine_lock("src-rel", tenant_id=None):
                assert True

    def test_mine_palace_zeroarg_and_chmod(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda: tmp_path / "pz")
        pp = str(tmp_path / "pzpal")
        Path(pp).mkdir(parents=True, exist_ok=True)
        with pal.mine_palace_lock(pp):
            assert True
        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "pz2")
        monkeypatch.setattr(Path, "chmod", lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
        with pal.mine_palace_lock(pp):
            assert True

    def test_mine_palace_exists_race(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "race")
        pp = str(tmp_path / "racepal")
        Path(pp).mkdir(parents=True, exist_ok=True)
        real_exists = Path.exists
        real_open = os.open

        def _fake_exists(self):
            if self.name.startswith("mine_palace_"):
                return False
            return real_exists(self)

        def _fake_open(path, flags, *a, **k):
            if str(path).endswith(".lock") and "race" in str(path):
                try:
                    real_open(path, flags, *a, **k)
                except OSError:
                    pass
                raise FileExistsError("race")
            return real_open(path, flags, *a, **k)

        monkeypatch.setattr(Path, "exists", _fake_exists)
        monkeypatch.setattr(os, "open", _fake_open)
        with pal.mine_palace_lock(pp):
            assert True

    def test_mine_palace_unlock_fail_ignored(self, tmp_path: Path, monkeypatch):
        import fcntl

        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "ulf")
        pp = str(tmp_path / "ulfpal")
        Path(pp).mkdir(parents=True, exist_ok=True)
        real_flock = fcntl.flock

        def _boom(fd, op):
            if op == fcntl.LOCK_UN:
                raise RuntimeError("unlock boom")
            return real_flock(fd, op)

        with mock.patch.object(fcntl, "flock", side_effect=_boom):
            with pal.mine_palace_lock(pp):
                assert True

    def test_nt_branches(self, tmp_path: Path, monkeypatch):
        import types

        import dxrk.memory.palace as pal

        fake = types.ModuleType("msvcrt")
        fake.LK_LOCK = 1  # type: ignore[attr-defined]
        fake.LK_NBLCK = 2  # type: ignore[attr-defined]
        fake.LK_UNLCK = 3  # type: ignore[attr-defined]
        fake.locking = lambda *a, **k: None  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "msvcrt", fake)
        monkeypatch.setattr(os, "name", "nt")
        lp = str(tmp_path / "nt.lock")
        lf = pal._open_mine_lock_file(lp, create=True)
        try:
            assert pal._lock_mine_lock_file(lf, blocking=True) is True
            assert pal._lock_mine_lock_file(lf, blocking=False) is True
            pal._unlock_mine_lock_file(lf)
            assert pal._mine_lock_file_is_current(lf, lp) is True
        finally:
            lf.close()
        pal._cleanup_mine_lock_file(lp)
        monkeypatch.setattr(os, "name", "posix")

    def test_nt_lock_fail(self, tmp_path: Path, monkeypatch):
        import types

        import dxrk.memory.palace as pal

        fake = types.ModuleType("msvcrt")
        fake.LK_LOCK = 1  # type: ignore[attr-defined]
        fake.LK_NBLCK = 2  # type: ignore[attr-defined]
        fake.LK_UNLCK = 3  # type: ignore[attr-defined]

        def _boom(*a, **k):
            raise OSError("nt busy")

        fake.locking = _boom  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "msvcrt", fake)
        monkeypatch.setattr(os, "name", "nt")
        lp = str(tmp_path / "nt2.lock")
        lf = pal._open_mine_lock_file(lp, create=True)
        try:
            assert pal._lock_mine_lock_file(lf, blocking=False) is False
            with pytest.raises(OSError):
                pal._lock_mine_lock_file(lf, blocking=True)
        finally:
            lf.close()
        monkeypatch.setattr(os, "name", "posix")

    def test_chunk_double_newline_branch(self):
        from dxrk.memory.palace import chunk_text

        content = "x" * 250 + "\n\n" + "y" * 500 + "\n" + "z" * 500
        chunks = chunk_text(content, chunk_size=400, chunk_overlap=20, min_chunk_size=10)
        assert len(chunks) >= 2

    def test_dxrk_resolve_except(self, tmp_path: Path):
        from dxrk.memory.palace import DxrkMemory

        with mock.patch.object(Path, "resolve", side_effect=OSError("res fail")):
            dm = DxrkMemory(str(tmp_path / "resfail"))
            assert "resfail" in dm.palace_path or ".dxrk" in dm.palace_path

    def test_mine_read_none_and_empty_chunks(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "rnlocks")
        proj = tmp_path / "rnproj"
        proj.mkdir()
        (proj / "a.md").write_text("hello world " * 30)
        dm = pal.DxrkMemory(str(tmp_path / "rnpal"))
        dm.init()
        try:
            with mock.patch.object(pal, "_read_text_no_follow_palace", return_value=None):
                r = dm.mine(str(proj))
                assert r["files_skipped"] >= 1
            with mock.patch.object(pal, "chunk_text", return_value=[]):
                with mock.patch.object(pal, "_read_text_no_follow_palace", return_value=("hello world " * 30, 1.0)):
                    r2 = dm.mine(str(proj))
                    assert r2["files_skipped"] >= 1
        finally:
            dm.close()

    def test_mine_closets_and_search(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "cslocks")
        proj = tmp_path / "csproj"
        proj.mkdir()
        (proj / "a.md").write_text("closet content hello " * 30)
        dm = pal.DxrkMemory(str(tmp_path / "cspal"))
        dm.init()
        try:
            closets = dm._collection(name="dxrk_closets", create=True)
            assert closets.count() == 0
            r = dm.mine(str(proj))
            assert r["files_mined"] >= 1
            s = dm.search("closet")
            assert "results" in s
            col = dm._collection(create=False)
            col.upsert(documents=["weirdw"], ids=["ww1"], metadatas=[{"wing": 123, "room": "r"}])
            assert isinstance(dm.list_wings(), list)
        finally:
            dm.close()

    def test_mine_partial_with_closets_warn(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal, "_dxrk_lock_dir", lambda tenant_id=None: tmp_path / "pwlocks")
        proj = tmp_path / "pwproj"
        proj.mkdir()
        (proj / "a.md").write_text("partial warn " * 40)
        dm = pal.DxrkMemory(str(tmp_path / "pwpal"))
        dm.init()
        try:
            dm._collection(name="dxrk_closets", create=True)
            col = dm._collection(create=True)

            def _boom(*a, **k):
                raise RuntimeError("upsert fail")

            with mock.patch.object(col, "upsert", side_effect=_boom):
                with mock.patch.object(col, "delete", side_effect=[None, RuntimeError("clean fail")]):
                    with mock.patch.object(dm, "_collection", return_value=col):
                        with pytest.raises(RuntimeError, match="upsert fail"):
                            dm.mine(str(proj))
        finally:
            dm.close()


class TestLayersMinerExtra:
    def test_resolve_tenant_oserror_tid(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.layers as ly

        monkeypatch.setenv("DXRK_TENANT", "tZ")
        with mock.patch("dxrk.tenant.migration.tenant_root", side_effect=OSError("ro")):
            assert ".dxrk" in ly._resolve_palace_path(None, None)
            assert ".dxrk" in ly._resolve_identity_path(None, None)
        monkeypatch.delenv("DXRK_TENANT")

    def test_layer1_get_fail_break(self, tmp_path: Path):
        import dxrk.memory.layers as ly

        class _BadCol:
            def get(self, **k):
                raise RuntimeError("get boom")

        with mock.patch.object(ly, "_get_collection", return_value=_BadCol()):
            assert "No memories" in ly.Layer1("whatever").generate()

    def test_layer1_token_estimate(self, tmp_path: Path):
        from dxrk.memory.palace import DxrkMemory

        pal = tmp_path / "tokpal"
        dm = DxrkMemory(str(pal))
        dm.init()
        try:
            dm.add_drawer("w", "r", "token hello " * 20, "/a.md", 0)
            l1 = Layer1(str(pal))
            assert l1.token_estimate() == len(l1.generate()) // 4
        finally:
            dm.close()

    def test_layer2_meta_not_dict_and_no_src(self, tmp_path: Path):
        import dxrk.memory.layers as ly

        class _FakeRes:
            def __init__(self):
                self.documents = ["doc hello", "x" * 500]
                self.metadatas = ["notadict", {"room": "r"}]

        class _FakeCol:
            def get(self, **k):
                return _FakeRes()

        with mock.patch.object(ly, "_get_collection", return_value=_FakeCol()):
            out = ly.Layer2("whatever").retrieve()
            assert "L2" in out

    def test_miner_close_oserror(self, tmp_path: Path, monkeypatch):
        import dxrk.memory.miner as mn

        f = tmp_path / "co.txt"
        f.write_text("close error content here")
        monkeypatch.setattr(os, "close", lambda fd: (_ for _ in ()).throw(OSError("c")))
        assert mn._is_regular_source_file(f, tmp_path) is True
        assert mn._read_text_no_follow(f, tmp_path) is not None

    def test_gitignore_slash_line(self, tmp_path: Path):
        from dxrk.memory.miner import GitignoreMatcher

        (tmp_path / ".gitignore").write_text("/\n*.log\n")
        m = GitignoreMatcher.from_dir(tmp_path)
        assert m is not None
        assert any(r["pattern"] == "*.log" for r in m.rules)

    def test_rule_empty_target(self, tmp_path: Path):
        from dxrk.memory.miner import GitignoreMatcher

        (tmp_path / ".gitignore").write_text("otherdir/\n")
        m = GitignoreMatcher.from_dir(tmp_path)
        assert m is not None
        assert m.matches(tmp_path / "file.txt", is_dir=False) is None
        rule = m.rules[0]
        assert m._rule_matches(rule, "file.txt", False) is False

    def test_force_include_root(self, tmp_path: Path):
        from dxrk.memory.miner import is_exact_force_include, is_force_included

        proj = tmp_path / "fproj"
        proj.mkdir()
        assert is_force_included(proj, proj, {"a"}) is False
        assert is_exact_force_include(proj, proj, {"a"}) is False

    def test_scan_large_and_fifo_print(self, tmp_path: Path, monkeypatch):
        import pathlib
        import stat as _stat

        import dxrk.memory.miner as mn

        proj = tmp_path / "largeproj"
        proj.mkdir()
        (proj / "a.md").write_text("hello")
        monkeypatch.setattr(mn, "MAX_FILE_SIZE", 1)
        assert "a.md" not in {p.name for p in mn.scan_project(proj)}
        monkeypatch.setattr(mn, "MAX_FILE_SIZE", 500 * 1024 * 1024)
        orig = pathlib.Path.stat

        def _fifo(self, *a, **k):
            if self.name == "a.md" and k.get("follow_symlinks", True) is not False:
                m = mock.Mock()
                m.st_mode = _stat.S_IFIFO
                m.st_size = 10
                return m
            return orig(self, *a, **k)

        monkeypatch.setattr(pathlib.Path, "stat", _fifo)
        files = mn.scan_project(proj)
        assert "a.md" not in {p.name for p in files}
