# SPDX-License-Identifier: MIT
"""Codebase indexer for RAG."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .chunker import ChunkConfig, ChunkFile, DefaultIgnoreDirs, IsCodeFile
from .embedder import Embedder
from .store import VectorRecord, VectorStore

_logger = logging.getLogger("dxrk.rag")


@dataclass
class IndexStats:
    """Statistics from an indexing run."""

    files_scanned: int
    files_indexed: int
    chunks_created: int
    duration_ms: int
    total_vectors: int
    last_run: str


class Indexer:
    """Walks a root directory and indexes supported code files."""

    def __init__(
        self, store: VectorStore, embedder: Embedder, root_dir: str, cfg: ChunkConfig
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._cfg = cfg
        self._root_dir = root_dir
        self._ignore_dirs = DefaultIgnoreDirs()
        self._mu = threading.Lock()
        self._last_run: Optional[str] = None
        self._file_hashes: Dict[str, str] = {}

    def AddIgnoreDir(self, dir: str) -> None:
        with self._mu:
            self._ignore_dirs[dir] = True

    def Index(self) -> IndexStats:
        start = time.monotonic()
        files: List[str] = []
        for dirpath, dirnames, filenames in os.walk(self._root_dir):
            dirnames[:] = [d for d in dirnames if not self._should_ignore_dir(d)]
            for name in filenames:
                full = os.path.join(dirpath, name)
                if IsCodeFile(full):
                    files.append(full)

        scanned = len(files)
        indexed = 0
        total_chunks = 0

        for file in files:
            h = self._file_hash(file)
            if h is None:
                continue
            with self._mu:
                if self._file_hashes.get(file) == h:
                    continue
            chunks = ChunkFile(file, self._cfg)
            if not chunks:
                continue
            texts = [c.text for c in chunks]
            embeddings = self._embedder.embed(texts)
            if embeddings is None:
                continue
            records = [
                VectorRecord(
                    id=hashlib.sha256(
                        f"{file}:{c.start_line}".encode("utf-8")
                    ).hexdigest(),
                    chunk=c,
                    embedding=embeddings[i],
                )
                for i, c in enumerate(chunks)
                if i < len(embeddings)
            ]
            self._store.Insert(records)
            with self._mu:
                self._file_hashes[file] = h
            indexed += 1
            total_chunks += len(records)

        with self._mu:
            self._last_run = datetime.now(timezone.utc).isoformat()
        duration_ms = int((time.monotonic() - start) * 1000)
        count, _ = self._store.Stats()
        return IndexStats(
            files_scanned=scanned,
            files_indexed=indexed,
            chunks_created=total_chunks,
            duration_ms=duration_ms,
            total_vectors=count,
            last_run=self._last_run or "",
        )

    def Query(self, text: str, max_results: int) -> Optional[List]:
        embeddings = self._embedder.embed([text])
        if embeddings is None:
            return None
        if not embeddings:
            return None
        return self._store.Search(embeddings[0], max_results)

    def LastRun(self) -> Optional[str]:
        with self._mu:
            return self._last_run

    def TotalVectors(self) -> int:
        count, _ = self._store.Stats()
        return count

    def _should_ignore_dir(self, name: str) -> bool:
        if name.startswith(".") and name != ".":
            return True
        return name in self._ignore_dirs

    @staticmethod
    def _file_hash(path: str) -> Optional[str]:
        try:
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except OSError as err:
            _logger.warning("file hash failed for %s: %s", path, err)
            return None
