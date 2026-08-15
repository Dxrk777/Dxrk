# SPDX-License-Identifier: MIT
"""Embedding provider for RAG."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import List, Optional, Protocol

_logger = logging.getLogger("dxrk.rag")

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_DIMENSIONS = 1536
MAX_BATCH = 256
TIMEOUT_SECONDS = 30


class Embedder(Protocol):
    """Generates embeddings for text."""

    def embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        """Embeds the given texts; returns None on error."""
        ...

    def model(self) -> str:
        """Returns the model name."""
        ...

    def dimensions(self) -> int:
        """Returns the embedding dimensions."""
        ...


class OpenAIEmbedder:
    """OpenAI-compatible embedding provider."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        dimensions: int = DEFAULT_DIMENSIONS,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._dimensions = dimensions

    def model(self) -> str:
        return self._model

    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        if not texts:
            return None
        embeddings: List[List[float]] = []
        for i in range(0, len(texts), MAX_BATCH):
            batch = texts[i : i + MAX_BATCH]
            batch_embeddings = self._embed_batch(batch)
            if batch_embeddings is None:
                return None
            embeddings.extend(batch_embeddings)
        return embeddings

    def _embed_batch(self, texts: List[str]) -> Optional[List[List[float]]]:
        url = f"{self._base_url}/embeddings"
        body = json.dumps({"model": self._model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                status = resp.status
                raw = resp.read()
        except Exception as err:  # noqa: BLE001
            _logger.warning("embed batch request failed: %s", err)
            return None

        if status != 200:
            _logger.warning(
                "embed api error %d: %s", status, raw.decode("utf-8", errors="replace")
            )
            return None

        try:
            data = json.loads(raw)
        except ValueError:
            _logger.warning("embed invalid json response")
            return None

        ordered: List[List[float]] = []
        for item in data.get("data", []):
            index = item.get("index")
            if index is None or not isinstance(index, int):
                continue
            while len(ordered) <= index:
                ordered.append([])
            ordered[index] = item.get("embedding", [])
        return ordered


def NewOpenAIEmbedder(api_key: str, model: str, base_url: str) -> OpenAIEmbedder:
    """Creates an OpenAI embedder with defaults applied."""
    if not model:
        model = DEFAULT_EMBEDDING_MODEL
    if not base_url:
        base_url = DEFAULT_BASE_URL
    base_url = base_url.rstrip("/")
    return OpenAIEmbedder(api_key=api_key, model=model, base_url=base_url)
