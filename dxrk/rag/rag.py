# SPDX-License-Identifier: MIT
"""RAG core: configuration, construction and query entry point."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

from .chunker import ChunkConfig
from .embedder import Embedder, NewOpenAIEmbedder
from .indexer import Indexer
from .store import VectorStore

_logger = logging.getLogger("dxrk.rag")

DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 64
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_MAX_RESULTS = 5


@dataclass
class Config:
    """Configuration for the RAG engine."""

    enabled: bool = False
    embedding_model: str = ""
    chunk_size: int = 0
    chunk_overlap: int = 0
    max_results: int = 0
    api_key: str = ""
    base_url: str = ""
    root_dir: str = ""
    persist_path: str = ""


class RAG:
    """Retrieval-augmented generation over the local codebase."""

    def __init__(
        self, indexer: Indexer, store: VectorStore, embedder: Embedder, enabled: bool
    ) -> None:
        self._indexer = indexer
        self._store = store
        self._embedder = embedder
        self._mu = threading.Lock()
        self._enabled = enabled

    def IsEnabled(self) -> bool:
        with self._mu:
            return self._enabled

    def Query(self, query: str, max_results: int = 0) -> Optional[list]:
        if not self.IsEnabled():
            return None
        if max_results <= 0:
            max_results = DEFAULT_MAX_RESULTS
        return self._indexer.Query(query, max_results)


def New(cfg: Config) -> RAG:
    """Constructs a RAG engine from configuration."""
    chunk_size = cfg.chunk_size if cfg.chunk_size > 0 else DEFAULT_CHUNK_SIZE
    chunk_overlap = (
        cfg.chunk_overlap if cfg.chunk_overlap > 0 else DEFAULT_CHUNK_OVERLAP
    )
    chunk_cfg = ChunkConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    model = cfg.embedding_model or DEFAULT_EMBEDDING_MODEL
    embedder = NewOpenAIEmbedder(cfg.api_key, model, cfg.base_url)
    store = VectorStore(embedder.dimensions(), cfg.persist_path)
    indexer = Indexer(store, embedder, cfg.root_dir, chunk_cfg)
    return RAG(indexer=indexer, store=store, embedder=embedder, enabled=cfg.enabled)
