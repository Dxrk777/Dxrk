# SPDX-License-Identifier: MIT
"""RAG package: semantic search over the local codebase."""

from .chunker import (
    Chunk,
    ChunkConfig,
    ChunkFile,
    DefaultChunkConfig,
    DefaultIgnoreDirs,
    IsCodeFile,
    LanguageFromExt,
)
from .embedder import Embedder, NewOpenAIEmbedder, OpenAIEmbedder
from .indexer import Indexer, IndexStats
from .rag import RAG, Config, New
from .store import SearchResult, VectorRecord, VectorStore, cosine_similarity
from .tools import RegisterTools

__all__ = [
    "Chunk",
    "ChunkConfig",
    "ChunkFile",
    "Config",
    "DefaultChunkConfig",
    "DefaultIgnoreDirs",
    "Embedder",
    "IndexStats",
    "Indexer",
    "IsCodeFile",
    "LanguageFromExt",
    "New",
    "NewOpenAIEmbedder",
    "OpenAIEmbedder",
    "RAG",
    "RegisterTools",
    "SearchResult",
    "VectorRecord",
    "VectorStore",
    "cosine_similarity",
]
