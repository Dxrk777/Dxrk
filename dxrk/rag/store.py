# SPDX-License-Identifier: MIT
"""In-memory vector store with optional JSON persistence."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .chunker import Chunk

_logger = logging.getLogger("dxrk.rag")


@dataclass
class VectorRecord:
    """A stored vector with its associated chunk."""

    id: str
    chunk: Chunk
    embedding: List[float]


@dataclass
class SearchResult:
    """A search hit with its similarity score."""

    record: VectorRecord
    score: float


class VectorStore:
    """In-memory vector store with optional JSON file persistence."""

    def __init__(self, dimensions: int, persist_path: str = "") -> None:
        self._mu = threading.Lock()
        self._records: Dict[str, VectorRecord] = {}
        self._dims = dimensions
        self._persist = persist_path
        if persist_path:
            self._load()

    def Insert(self, records: List[VectorRecord]) -> None:
        with self._mu:
            for r in records:
                if not r.id:
                    continue
                self._records[r.id] = r
            if self._persist:
                self._save()

    def Delete(self, id: str) -> None:
        with self._mu:
            self._records.pop(id, None)
            if self._persist:
                self._save()

    def Clear(self) -> None:
        with self._mu:
            self._records = {}
            if self._persist:
                self._save()

    def Search(self, query: List[float], max_results: int) -> List[SearchResult]:
        with self._mu:
            if not self._records or max_results <= 0:
                return []
            results = [
                SearchResult(record=rec, score=cosine_similarity(query, rec.embedding))
                for rec in self._records.values()
            ]
            results.sort(key=lambda r: r.score, reverse=True)
            return results[:max_results]

    def Len(self) -> int:
        with self._mu:
            return len(self._records)

    def Stats(self) -> Tuple[int, int]:
        with self._mu:
            return len(self._records), self._dims

    def _load(self) -> None:
        try:
            with open(self._persist, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._records = {}
            for r in data:
                self._records[r["id"]] = VectorRecord(
                    id=r["id"],
                    chunk=Chunk(
                        text=r["chunk"]["text"],
                        file_path=r["chunk"]["file_path"],
                        start_line=r["chunk"]["start_line"],
                        end_line=r["chunk"]["end_line"],
                        language=r["chunk"]["language"],
                    ),
                    embedding=r["embedding"],
                )
        except (OSError, ValueError, KeyError, TypeError):
            self._records = {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._persist), mode=0o750, exist_ok=True)
        except OSError as err:
            _logger.warning("vector store mkdir failed: %s", err)
            return
        try:
            payload = []
            for r in self._records.values():
                payload.append(
                    {
                        "id": r.id,
                        "chunk": {
                            "text": r.chunk.text,
                            "file_path": r.chunk.file_path,
                            "start_line": r.chunk.start_line,
                            "end_line": r.chunk.end_line,
                            "language": r.chunk.language,
                        },
                        "embedding": r.embedding,
                    }
                )
            with open(self._persist, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.chmod(self._persist, 0o600)
        except OSError as err:
            _logger.warning("vector store save failed: %s", err)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Computes cosine similarity between two vectors."""
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
