# SPDX-License-Identifier: MIT
"""Tests for the RAG package. Mirrors internal/rag/rag_test.go."""

from __future__ import annotations

import json

import pytest

from dxrk.rag import (
    ChunkConfig,
    ChunkFile,
    Config,
    IsCodeFile,
    LanguageFromExt,
    New,
    NewOpenAIEmbedder,
    VectorRecord,
    VectorStore,
    cosine_similarity,
    DefaultChunkConfig,
    DefaultIgnoreDirs,
)
from dxrk.rag.chunker import Chunk
from dxrk.rag.embedder import OpenAIEmbedder
from dxrk.rag.indexer import Indexer
from dxrk.rag.tools import RegisterTools
from dxrk.tools import Registry


class _FakeEmbedder:
    def __init__(self, dims: int = 3) -> None:
        self._dims = dims

    def embed(self, texts):
        if not texts:
            return None
        return [[1.0 / (i + 1)] * self._dims for i in range(len(texts))]

    def model(self) -> str:
        return "fake"

    def dimensions(self) -> int:
        return self._dims


class TestChunker:
    def test_default_chunk_config(self):
        cfg = DefaultChunkConfig()
        assert cfg.chunk_size == 512
        assert cfg.chunk_overlap == 64

    def test_is_code_file(self):
        for path in (
            "a.py",
            "b.go",
            "c.ts",
            "d.tsx",
            "e.js",
            "f.jsx",
            "g.rs",
            "h.yaml",
            "i.yml",
            "j.json",
            "k.toml",
            "l.md",
            "m.html",
            "n.svelte",
            "o.vue",
            "p.css",
            "q.sh",
            "r.sql",
        ):
            assert IsCodeFile(path), path
        assert not IsCodeFile("a.txt")
        assert not IsCodeFile("a.PNG")
        assert not IsCodeFile("noext")

    def test_language_from_ext(self):
        assert LanguageFromExt("x.go") == "go"
        assert LanguageFromExt("x.ts") == "typescript"
        assert LanguageFromExt("x.tsx") == "typescript"
        assert LanguageFromExt("x.py") == "python"
        assert LanguageFromExt("x.rs") == "rust"
        assert LanguageFromExt("x.java") == "java"
        assert LanguageFromExt("x.c") == "c"
        assert LanguageFromExt("x.cpp") == "cpp"
        assert LanguageFromExt("x.h") == "c"
        assert LanguageFromExt("x.rb") == "ruby"
        assert LanguageFromExt("x.php") == "php"
        assert LanguageFromExt("x.sh") == "shell"
        assert LanguageFromExt("x.zsh") == "shell"
        assert LanguageFromExt("x.yaml") == "yaml"
        assert LanguageFromExt("x.json") == "json"
        assert LanguageFromExt("x.toml") == "toml"
        assert LanguageFromExt("x.md") == "markdown"
        assert LanguageFromExt("x.html") == "html"
        assert LanguageFromExt("x.svelte") == "html"
        assert LanguageFromExt("x.css") == "css"
        assert LanguageFromExt("x.txt") == "text"

    def test_chunk_file_small_file(self, tmp_path):
        p = tmp_path / "small.py"
        p.write_text("a\nb\nc\n", encoding="utf-8")
        cfg = ChunkConfig(chunk_size=512, chunk_overlap=64)
        chunks = ChunkFile(str(p), cfg)
        assert len(chunks) == 1
        assert chunks[0].text == "a\nb\nc\n"
        assert chunks[0].file_path == str(p)
        assert chunks[0].start_line == 1
        assert chunks[0].end_line == 4
        assert chunks[0].language == "python"

    def test_chunk_file_large_file(self, tmp_path):
        p = tmp_path / "big.py"
        lines = [f"line {i}" for i in range(100)]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cfg = ChunkConfig(chunk_size=10, chunk_overlap=2)
        chunks = ChunkFile(str(p), cfg)
        assert len(chunks) == 13
        assert chunks[0].start_line == 1
        assert chunks[0].end_line == 10
        assert chunks[1].start_line == 9
        assert chunks[-1].end_line == 101

    def test_chunk_file_binary(self, tmp_path):
        p = tmp_path / "bin.py"
        p.write_bytes(b"\xff\xfe\x00\x01")
        chunks = ChunkFile(str(p), ChunkConfig(chunk_size=512, chunk_overlap=64))
        assert chunks == []

    def test_default_ignore_dirs(self):
        dirs = DefaultIgnoreDirs()
        assert dirs[".git"]
        assert dirs["node_modules"]
        assert dirs["__pycache__"]
        assert dirs[".dxrk"]


class TestStore:
    def test_insert_and_search(self):
        store = VectorStore(dimensions=3)
        store.Insert(
            [
                VectorRecord(
                    id="1",
                    chunk=Chunk("a", "a.py", 1, 1, "python"),
                    embedding=[1.0, 0.0, 0.0],
                ),
                VectorRecord(
                    id="2",
                    chunk=Chunk("b", "b.py", 1, 1, "python"),
                    embedding=[0.0, 1.0, 0.0],
                ),
            ]
        )
        assert store.Len() == 2
        results = store.Search([1.0, 0.0, 0.0], 1)
        assert len(results) == 1
        assert results[0].record.id == "1"
        assert results[0].score == pytest.approx(1.0)

    def test_search_empty(self):
        store = VectorStore(dimensions=3)
        assert store.Search([1.0, 0.0, 0.0], 5) == []
        store.Insert(
            [
                VectorRecord(
                    id="1",
                    chunk=Chunk("a", "a.py", 1, 1, "python"),
                    embedding=[1.0, 0.0, 0.0],
                )
            ]
        )
        assert store.Search([1.0, 0.0, 0.0], 0) == []

    def test_insert_empty_id_skipped(self):
        store = VectorStore(dimensions=3)
        store.Insert(
            [
                VectorRecord(
                    id="", chunk=Chunk("a", "a.py", 1, 1, "python"), embedding=[1.0]
                )
            ]
        )
        assert store.Len() == 0

    def test_delete_and_clear(self):
        store = VectorStore(dimensions=3)
        store.Insert(
            [
                VectorRecord(
                    id="1", chunk=Chunk("a", "a.py", 1, 1, "python"), embedding=[1.0]
                )
            ]
        )
        store.Delete("1")
        assert store.Len() == 0
        store.Insert(
            [
                VectorRecord(
                    id="1", chunk=Chunk("a", "a.py", 1, 1, "python"), embedding=[1.0]
                )
            ]
        )
        store.Clear()
        assert store.Len() == 0

    def test_stats(self):
        store = VectorStore(dimensions=7)
        count, dims = store.Stats()
        assert count == 0
        assert dims == 7

    def test_persist_roundtrip(self, tmp_path):
        path = str(tmp_path / "store.json")
        store = VectorStore(dimensions=3, persist_path=path)
        store.Insert(
            [
                VectorRecord(
                    id="1",
                    chunk=Chunk("a", "a.py", 1, 1, "python"),
                    embedding=[1.0, 0.0, 0.0],
                )
            ]
        )
        store2 = VectorStore(dimensions=3, persist_path=path)
        assert store2.Len() == 1
        assert store2._records["1"].chunk.text == "a"

    def test_cosine_similarity(self):
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
        assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0
        assert cosine_similarity([], []) == 0.0
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
        assert cosine_similarity([1.0, 0.0], [0.0, 0.0]) == 0.0


class TestEmbedder:
    def test_defaults(self):
        e = NewOpenAIEmbedder("key", "", "")
        assert e.model() == "text-embedding-3-small"
        assert e._base_url == "https://api.openai.com/v1"
        assert e.dimensions() == 1536

    def test_base_url_trailing_slash_trimmed(self):
        e = NewOpenAIEmbedder("key", "m", "https://x.example/v1/")
        assert e._base_url == "https://x.example/v1"

    def test_embed_empty(self):
        e = NewOpenAIEmbedder("key", "m", "")
        assert e.embed([]) is None

    def test_embed_batches(self, monkeypatch):
        e = NewOpenAIEmbedder("key", "m", "")
        seen = []
        import dxrk.rag.embedder as emb

        def fake_batch(self, texts):
            seen.append(texts)
            return [[1.0, 2.0] for _ in texts]

        monkeypatch.setattr(emb.OpenAIEmbedder, "_embed_batch", fake_batch)
        out = e.embed(["a"] * 300)
        assert len(out) == 300
        assert len(seen) == 2
        assert len(seen[0]) == 256
        assert len(seen[1]) == 44

    def test_embed_batch_http_error(self, monkeypatch):
        e = NewOpenAIEmbedder("key", "m", "")

        def fake_batch(self, texts):
            return None

        monkeypatch.setattr(OpenAIEmbedder, "_embed_batch", fake_batch)
        assert e.embed(["a"]) is None


class TestIndexer:
    def test_index_empty_dir(self, tmp_path):
        store = VectorStore(dimensions=3)
        idx = Indexer(store, _FakeEmbedder(), str(tmp_path), DefaultChunkConfig())
        stats = idx.Index()
        assert stats.files_scanned == 0
        assert stats.files_indexed == 0
        assert stats.chunks_created == 0
        assert idx.LastRun() is not None

    def test_index_ignores_non_code_and_ignored_dirs(self, tmp_path):
        (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "skip.txt").write_text("hi\n", encoding="utf-8")
        sub = tmp_path / "node_modules"
        sub.mkdir()
        (sub / "dep.js").write_text("var a;\n", encoding="utf-8")
        store = VectorStore(dimensions=3)
        idx = Indexer(store, _FakeEmbedder(), str(tmp_path), DefaultChunkConfig())
        stats = idx.Index()
        assert stats.files_scanned == 1
        assert stats.files_indexed == 1
        assert stats.chunks_created == 1
        assert store.Len() == 1

    def test_index_skips_unchanged_files(self, tmp_path):
        p = tmp_path / "keep.py"
        p.write_text("x = 1\n", encoding="utf-8")
        store = VectorStore(dimensions=3)
        idx = Indexer(store, _FakeEmbedder(), str(tmp_path), DefaultChunkConfig())
        stats = idx.Index()
        assert stats.files_indexed == 1
        stats = idx.Index()
        assert stats.files_indexed == 0

    def test_chunk_id_hash(self, tmp_path):
        p = tmp_path / "h.py"
        p.write_text("y = 2\n", encoding="utf-8")
        store = VectorStore(dimensions=3)
        idx = Indexer(store, _FakeEmbedder(), str(tmp_path), DefaultChunkConfig())
        idx.Index()
        rec = list(store._records.values())[0]
        import hashlib

        assert rec.id == hashlib.sha256(f"{p}:1".encode()).hexdigest()

    def test_query(self, tmp_path):
        p = tmp_path / "q.py"
        p.write_text("def foo():\n    pass\n", encoding="utf-8")
        store = VectorStore(dimensions=3)
        idx = Indexer(store, _FakeEmbedder(), str(tmp_path), DefaultChunkConfig())
        idx.Index()
        results = idx.Query("foo", 5)
        assert results is not None
        assert len(results) == 1

    def test_add_ignore_dir(self, tmp_path):
        (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")
        sub = tmp_path / "mydir"
        sub.mkdir()
        (sub / "also.py").write_text("y = 2\n", encoding="utf-8")
        store = VectorStore(dimensions=3)
        idx = Indexer(store, _FakeEmbedder(), str(tmp_path), DefaultChunkConfig())
        idx.AddIgnoreDir("mydir")
        stats = idx.Index()
        assert stats.files_scanned == 1


class TestRAG:
    def test_new_defaults(self, tmp_path):
        cfg = Config(api_key="k", root_dir=str(tmp_path))
        rag = New(cfg)
        assert rag.IsEnabled() is False
        assert rag._embedder.model() == "text-embedding-3-small"
        assert rag._indexer._cfg.chunk_size == 512
        assert rag._indexer._cfg.chunk_overlap == 64

    def test_new_custom_chunk_cfg(self, tmp_path):
        cfg = Config(
            api_key="k", root_dir=str(tmp_path), chunk_size=64, chunk_overlap=8
        )
        rag = New(cfg)
        assert rag._indexer._cfg.chunk_size == 64
        assert rag._indexer._cfg.chunk_overlap == 8

    def test_new_negative_chunk_uses_defaults(self, tmp_path):
        cfg = Config(
            api_key="k", root_dir=str(tmp_path), chunk_size=-10, chunk_overlap=-2
        )
        rag = New(cfg)
        assert rag._indexer._cfg.chunk_size == 512
        assert rag._indexer._cfg.chunk_overlap == 64

    def test_query_disabled(self, tmp_path):
        cfg = Config(api_key="k", root_dir=str(tmp_path))
        rag = New(cfg)
        assert rag.Query("foo") is None

    def test_query_default_max_results(self, tmp_path):
        p = tmp_path / "q.py"
        p.write_text("def foo():\n    pass\n", encoding="utf-8")
        store = VectorStore(dimensions=3)
        idx = Indexer(store, _FakeEmbedder(), str(tmp_path), DefaultChunkConfig())
        idx.Index()
        rag = New(Config(api_key="k", root_dir=str(tmp_path), enabled=True))
        rag._indexer = idx
        rag._store = store
        results = rag.Query("foo")
        assert results is not None
        assert len(results) == 1


class TestTools:
    def _rag_with_data(self, tmp_path) -> tuple:
        p = tmp_path / "q.py"
        p.write_text("def foo():\n    pass\n", encoding="utf-8")
        store = VectorStore(dimensions=3)
        idx = Indexer(store, _FakeEmbedder(), str(tmp_path), DefaultChunkConfig())
        idx.Index()
        from dxrk.rag.rag import RAG

        return RAG(
            indexer=idx, store=store, embedder=_FakeEmbedder(), enabled=True
        ), store

    def test_register_tools(self, tmp_path):
        rag, _ = self._rag_with_data(tmp_path)
        reg = Registry()
        RegisterTools(reg, rag)
        names = [t.name() for t in reg.list()]
        assert "codebase_query" in names
        assert "codebase_index" in names

    def test_codebase_query_disabled(self):
        from dxrk.rag.rag import RAG

        rag = RAG(indexer=None, store=None, embedder=None, enabled=False)  # type: ignore[arg-type]
        reg = Registry()
        RegisterTools(reg, rag)
        tool = reg.get("codebase_query")
        result, err = tool.execute(None, {"query": "foo"})
        assert err is None
        assert result["enabled"] is False
        assert "no está habilitado" in result["message"]

    def test_codebase_query_requires_query(self, tmp_path):
        rag, _ = self._rag_with_data(tmp_path)
        reg = Registry()
        RegisterTools(reg, rag)
        tool = reg.get("codebase_query")
        result, err = tool.execute(None, {})
        assert result is None
        assert err == "query is required"

    def test_codebase_query_success(self, tmp_path):
        rag, store = self._rag_with_data(tmp_path)
        reg = Registry()
        RegisterTools(reg, rag)
        tool = reg.get("codebase_query")
        result, err = tool.execute(None, {"query": "foo"})
        assert err is None
        assert result["enabled"] is True
        assert result["total"] == 1
        assert result["results"][0]["file_path"] == str(tmp_path / "q.py")
        assert result["results"][0]["language"] == "python"
        assert "score" in result["results"][0]

    def test_codebase_index_disabled(self):
        from dxrk.rag.rag import RAG

        rag = RAG(indexer=None, store=None, embedder=None, enabled=False)  # type: ignore[arg-type]
        reg = Registry()
        RegisterTools(reg, rag)
        tool = reg.get("codebase_index")
        result, err = tool.execute(None, {})
        assert err is None
        assert result["enabled"] is False

    def test_codebase_index_path_override_not_supported(self, tmp_path):
        rag, _ = self._rag_with_data(tmp_path)
        reg = Registry()
        RegisterTools(reg, rag)
        tool = reg.get("codebase_index")
        result, err = tool.execute(None, {"path": "/tmp"})
        assert result is None
        assert err == "path override not supported yet; index the project root"

    def test_codebase_index_success(self, tmp_path):
        rag, _ = self._rag_with_data(tmp_path)
        reg = Registry()
        RegisterTools(reg, rag)
        tool = reg.get("codebase_index")
        result, err = tool.execute(None, {})
        assert err is None
        assert result["files_scanned"] == 1
        assert result["files_indexed"] == 0
        assert "last_run" in result
