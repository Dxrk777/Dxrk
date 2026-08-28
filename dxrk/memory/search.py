# SPDX-License-Identifier: MIT
"""Hybrid search — BM25 + closet boost, stdlib only."""

from __future__ import annotations

import math
import re
from pathlib import Path

from .backend.base import BaseCollection
from .date_window import filed_at_in_window, parse_window

_TOKEN_RE = re.compile(r"\w{2,}", re.UNICODE)

CLOSET_RANK_BOOSTS: list[float] = [0.40, 0.25, 0.15, 0.08, 0.04]
CLOSET_DISTANCE_CAP = 1.5


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


def sanitize_query(query: str) -> str:
    """Strip prompt-injection / FTS5 special chars, limit length."""
    if not query:
        return ""
    # remove control chars, limit to 500 chars, collapse whitespace
    cleaned = re.sub(r"[^\w\s\-\.\,\!\?]", " ", query)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # drop prompt injection prefixes
    lower = cleaned.lower()
    for prefix in ("ignore previous", "system:", "assistant:", "user:"):
        if lower.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            lower = cleaned.lower()
    return cleaned[:500]


def _bm25_scores(query: str, documents: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(documents)
    q_terms = set(_tokenize(query))
    if not q_terms or n == 0:
        return [0.0] * n
    tokenized = [_tokenize(d) for d in documents]
    doc_lens = [len(t) for t in tokenized]
    if not any(doc_lens):
        return [0.0] * n
    avgdl = sum(doc_lens) / n or 1.0
    df: dict[str, int] = {t: 0 for t in q_terms}
    for toks in tokenized:
        for t in set(toks) & q_terms:
            df[t] += 1
    idf = {t: math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1) for t in q_terms}
    scores: list[float] = []
    for toks, dl in zip(tokenized, doc_lens):
        if dl == 0:
            scores.append(0.0)
            continue
        tf: dict[str, int] = {}
        for t in toks:
            if t in q_terms:
                tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for term, freq in tf.items():
            num = freq * (k1 + 1)
            den = freq + k1 * (1 - b + b * dl / avgdl)
            s += idf[term] * num / den
        scores.append(s)
    return scores


def _hybrid_rank(
    results: list[dict[str, object]],
    query: str,
    vector_weight: float = 0.6,
    bm25_weight: float = 0.4,
) -> list[dict[str, object]]:
    if not results:
        return results
    docs = [str(r.get("text", "")) for r in results]
    bm25_raw = _bm25_scores(query, docs)
    max_b = max(bm25_raw) if bm25_raw else 0.0
    bm25_norm = [s / max_b if max_b > 0 else 0.0 for s in bm25_raw]
    scored: list[tuple[float, dict[str, object]]] = []
    for r, raw, norm in zip(results, bm25_raw, bm25_norm):
        dist = r.get("distance")
        if dist is None:
            vec_sim = 0.0
        else:
            try:
                vec_sim = max(0.0, 1.0 - float(dist))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                vec_sim = 0.0
        r["bm25_score"] = round(raw, 3)
        scored.append((vector_weight * vec_sim + bm25_weight * norm, r))
    scored.sort(key=lambda p: p[0], reverse=True)
    results[:] = [r for _, r in scored]
    return results


def build_where_filter(wing: str | None = None, room: str | None = None) -> dict[str, object]:
    if wing and room:
        return {"$and": [{"wing": wing}, {"room": room}]}
    if wing:
        return {"wing": wing}
    if room:
        return {"room": room}
    return {}


def _candidate_pool_size(n_results: int, date_window_active: bool) -> int:
    if not date_window_active:
        return n_results * 3
    return max(min(n_results * 15, 500), n_results)


def hybrid_search(
    collection: BaseCollection,
    query: str,
    where: dict[str, object] | None = None,
    n_results: int = 5,
    closet_collection: BaseCollection | None = None,
    since: str | None = None,
    before: str | None = None,
) -> dict[str, object]:
    """Hybrid BM25 + optional closet boost search.

    Returns dict with keys: query, filters, total_before_filter, results.
    Each result: text, wing, room, source_file, distance, similarity, etc.
    since/before are inclusive/exclusive ISO date bounds on filed_at
    (stdlib-only date windowing, inclusive since / exclusive before).
    """
    # Parse date window first — invalid bounds are caller errors identical
    # whether or not the index is healthy (mirrors upstream pre-probe parse).
    try:
        since_dt, before_dt = parse_window(since, before)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    date_window_active = since_dt is not None or before_dt is not None
    q = sanitize_query(query)
    if not q:
        filt: dict[str, object] = dict(where or {})
        if since is not None:
            filt["since"] = since
        if before is not None:
            filt["before"] = before
        return {"query": query, "filters": filt, "total_before_filter": 0, "results": []}
    # drawer search: over-fetch for rerank; widen when date window active
    pool_size = _candidate_pool_size(n_results, date_window_active)
    dkwargs: dict[str, object] = {
        "query_texts": [q],
        "n_results": pool_size,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        dkwargs["where"] = where
    drawer_results = collection.query(**dkwargs)  # type: ignore[arg-type]

    # extract first query outer list
    try:
        docs = drawer_results.documents[0] if drawer_results.documents else []
        metas = drawer_results.metadatas[0] if drawer_results.metadatas else []
        dists = drawer_results.distances[0] if drawer_results.distances else []
    except (IndexError, AttributeError):
        docs, metas, dists = [], [], []

    # closet boost lookup
    boost_by_source: dict[str, tuple[int, float, str]] = {}
    if closet_collection is not None:
        try:
            ckwargs: dict[str, object] = {
                "query_texts": [q],
                "n_results": n_results * 2,
                "include": ["documents", "metadatas", "distances"],
            }
            if where:
                ckwargs["where"] = where
            closet_results = closet_collection.query(**ckwargs)  # type: ignore[arg-type]
            cdocs = closet_results.documents[0] if closet_results.documents else []
            cmetas = closet_results.metadatas[0] if closet_results.metadatas else []
            cdists = closet_results.distances[0] if closet_results.distances else []
            for rank, (cdoc, cmeta, cdist) in enumerate(zip(cdocs, cmetas, cdists)):
                cmeta = cmeta or {}
                src = str(cmeta.get("source_file", "")) if isinstance(cmeta, dict) else ""
                if src and src not in boost_by_source:
                    try:
                        dval = float(cdist) if cdist is not None else 2.0
                    except (TypeError, ValueError):
                        dval = 2.0
                    boost_by_source[src] = (rank, dval, str(cdoc)[:200] if isinstance(cdoc, str) else "")
        except Exception:
            pass

    scored: list[dict[str, object]] = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        if not isinstance(meta, dict):
            meta = {}
        # Date window is a post-filter: Chroma string metadata can't be range-filtered
        # server-side, and excluding here keeps the design requirement of recall
        # (widened pool) + precise Python wall-clock check.
        if date_window_active and not filed_at_in_window(meta.get("filed_at"), since_dt, before_dt):
            continue
        doc_str = str(doc) if doc is not None else ""
        try:
            dist_f = float(dist) if dist is not None else 1.0
        except (TypeError, ValueError):
            dist_f = 1.0
        source = str(meta.get("source_file", "")) if isinstance(meta.get("source_file"), str) else ""
        boost = 0.0
        matched_via = "drawer"
        if source in boost_by_source:
            rank, cdist, _preview = boost_by_source[source]
            if cdist <= CLOSET_DISTANCE_CAP and rank < len(CLOSET_RANK_BOOSTS):
                boost = CLOSET_RANK_BOOSTS[rank]
                matched_via = "drawer+closet"
        eff = max(0.0, min(2.0, dist_f - boost))
        scored.append(
            {
                "text": doc_str,
                "wing": str(meta.get("wing", "unknown")),
                "room": str(meta.get("room", "unknown")),
                "source_file": Path(source).name if source else "?",
                "created_at": str(meta.get("filed_at", "unknown")),
                "similarity": round(max(0.0, 1 - eff), 3),
                "distance": round(dist_f, 4),
                "effective_distance": round(eff, 4),
                "closet_boost": round(boost, 3),
                "matched_via": matched_via,
                "_sort_key": eff,
                "_source_file_full": source,
                "_filed_at": str(meta.get("filed_at", "")),
            }
        )

    scored.sort(key=lambda h: float(h.get("_sort_key", 0)))  # type: ignore[arg-type]
    hits = scored[:n_results]
    # finalize bm25 hybrid rerank
    hits = _hybrid_rank(hits, q)[:n_results]
    for h in hits:
        h.pop("_sort_key", None)
        h.pop("_source_file_full", None)
        h.pop("_filed_at", None)

    # Build filters envelope including date bounds for observability
    filt_out: dict[str, object] = dict(where or {})
    if since is not None:
        filt_out["since"] = since
    if before is not None:
        filt_out["before"] = before
    result: dict[str, object] = {
        "query": query,
        "filters": filt_out,
        "total_before_filter": len(docs),
        "results": hits,
    }
    # Flag truncation when widened pool came back full — rows beyond pool
    # never got a chance to match the window (mirrors upstream honesty flag).
    if date_window_active and len(docs) >= pool_size:
        result["date_filter_pool_truncated"] = True
    return result


# Keep alias for compat
query_sanitizer = sanitize_query
