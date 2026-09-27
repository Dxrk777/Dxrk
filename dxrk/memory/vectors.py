# SPDX-License-Identifier: MIT
"""Stdlib-only local vectors for hybrid recall — hashed char-ngram space.

Design (deliberately dependency-free, no torch/sentence-transformers):
- Features: whole word tokens (len>=2) + char 3-grams with boundary
  padding per token. Trigrams give morphological robustness
  (``auth`` ~ ``authentication`` share ``aut``/``uth``) without a stemmer.
- Hashing trick into ``DIM`` buckets via md5 (deterministic across runs).
- Stored form: raw TF counts (float32 BLOB). At query time an IDF vector
  is estimated over the candidate pool (BM25-style) and both sides are
  IDF-weighted before the cosine — common ngrams (``the``/``ing``) get
  downweighted, distinctive ones (``jwt``/``auth``) dominate.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct

DIM = 512

_TOKEN_RE = re.compile(r"\w{2,}", re.UNICODE)

# Minimal English stopwords — dropped from the QUERY side only (docs keep
# full features so exact-stopword queries still match). Standard IR practice:
# content-bearing terms must dominate the cosine.
STOPWORDS: frozenset[str] = frozenset(
    "a an and are as at be but by can could did do does for from had has have "
    "how i in is it its me my of on or our so that the this to was we what "
    "when where which who will with you your".split()
)


def features(text: str) -> list[str]:
    """Feature multiset for ``text`` (tokens + padded char trigrams)."""
    feats: list[str] = []
    for tok in _TOKEN_RE.findall((text or "").lower()):
        feats.append("w:" + tok)
        padded = "^" + tok + "$"
        for i in range(len(padded) - 2):
            feats.append("g:" + padded[i : i + 3])
    return feats


def query_features(text: str) -> list[str]:
    """Query-side features: content tokens only (stopwords dropped)."""
    feats: list[str] = []
    for tok in _TOKEN_RE.findall((text or "").lower()):
        if tok in STOPWORDS:
            continue
        feats.append("w:" + tok)
        padded = "^" + tok + "$"
        for i in range(len(padded) - 2):
            feats.append("g:" + padded[i : i + 3])
    return feats


def _bucket(feat: str) -> int:
    digest = hashlib.md5(feat.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "little") % DIM


def embed_counts(text: str) -> list[float]:
    """Raw TF count vector (len DIM) — the stored form."""
    vec = [0.0] * DIM
    for feat in features(text):
        vec[_bucket(feat)] += 1.0
    return vec


def embed_query_counts(text: str) -> list[float]:
    """Raw TF count vector for query text (stopwords dropped)."""
    vec = [0.0] * DIM
    for feat in query_features(text):
        vec[_bucket(feat)] += 1.0
    return vec


def embed_text(text: str) -> list[float]:
    """L2-normalized dense vector (convenience for callers/tests)."""
    vec = embed_counts(text)
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return vec
    return [v / norm for v in vec]


def encode(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def decode(blob: bytes, dim: int = DIM) -> list[float] | None:
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        return None
    try:
        raw = bytes(blob)
        if len(raw) != dim * 4:
            return None
        return list(struct.unpack(f"<{dim}f", raw))
    except struct.error:
        return None


def idf_weights(pool_counts: list[list[float]]) -> list[float]:
    """BM25-style IDF per dim over the candidate pool."""
    n = len(pool_counts)
    if n == 0:
        return [0.0] * DIM
    df = [0] * DIM
    for vec in pool_counts:
        for i, v in enumerate(vec):
            if v > 0:
                df[i] += 1
    return [math.log((n - d + 0.5) / (d + 0.5) + 1.0) for d in df]


def weighted_cosine(a: list[float], b: list[float], idf: list[float]) -> float:
    """Cosine of IDF-weighted vectors; 0.0 when either side is empty."""
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y, w in zip(a, b, idf):
        wx = x * w
        wy = y * w
        dot += wx * wy
        na += wx * wx
        nb += wy * wy
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def cosine(a: list[float], b: list[float]) -> float:
    """Plain cosine (explicit query_embeddings vs stored counts)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)
