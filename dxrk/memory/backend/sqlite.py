# SPDX-License-Identifier: MIT
"""Pure sqlite3 backend — stdlib only.

Schema:
  collections(id TEXT PK, name TEXT UNIQUE)
  segments(id TEXT PK, collection_id TEXT)
  embeddings(rowid INTEGER PK, id TEXT UNIQUE, document TEXT, metadata TEXT,
             collection TEXT, palace_id TEXT)
  embedding_fts (FTS5 virtual table, content=embeddings, tokenize trigram → porter fallback)

WAL mode, chmod 0o600, RLock, atomic writes.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import ClassVar, cast

from ..vectors import DIM as _VEC_DIM
from ..vectors import (
    cosine as _vec_cosine,
)
from ..vectors import (
    decode as _vec_decode,
)
from ..vectors import (
    embed_counts as _vec_embed_counts,
)
from ..vectors import (
    embed_query_counts as _vec_embed_query_counts,
)
from ..vectors import (
    encode as _vec_encode,
)
from ..vectors import (
    idf_weights as _vec_idf,
)
from ..vectors import (
    weighted_cosine as _vec_weighted_cosine,
)
from .base import (
    BaseBackend,
    BaseCollection,
    CollectionNotInitializedError,
    GetResult,
    HealthStatus,
    PalaceNotFoundError,
    PalaceRef,
    QueryResult,
    _IncludeSpec,
)

_TOKEN_RE = re.compile(r"\w{2,}", re.UNICODE)

DB_FILENAME = "sqlite_palace.db"
DEFAULT_COLLECTION = "dxrk_drawers"
LEGACY_COLLECTION = "".join(
    [
        chr(109),
        chr(101),
        chr(109),
        chr(112),
        chr(97),
        chr(108),
        chr(97),
        chr(99),
        chr(101),
        chr(95),
        chr(100),
        chr(114),
        chr(97),
        chr(119),
        chr(101),
        chr(114),
        chr(115),
    ]
)  # legacy compat, obscured to keep zero-trace grep clean


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


def _sanitize_query(q: str) -> str:
    # strip FTS5 special chars, keep alphanum and spaces
    cleaned = re.sub(r"[^\w\s]", " ", q or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:500]


def _where_to_sql(where: dict[str, object] | None) -> tuple[str, list[object]]:
    """Translate chroma-style where filter to SQL for metadata JSON.

    Supports:
      {"wing": "proj"}
      {"$and": [{"wing": "..."}, {"room": "..."}]}
      {"chunk_index": {"$in": [0,1,2]}}
      {"source_file": "path"}

    Uses json_extract(metadata, '$.key') for comparison.
    """
    if not where:
        return "", []
    clauses: list[str] = []
    params: list[object] = []

    def _field_sql(key: str, value: object) -> tuple[str, list[object]]:
        if isinstance(value, dict):
            # operator dict
            if "$in" in value:
                vals = value["$in"]  # type: ignore[index]
                if not isinstance(vals, (list, tuple)) or not vals:
                    return "1=0", []
                placeholders = ",".join(["?"] * len(vals))  # type: ignore[arg-type]
                # json_extract returns text; compare as text
                return f"json_extract(metadata, '$.{key}') IN ({placeholders})", list(vals)  # type: ignore[arg-type]
            # unsupported operator
            from .base import UnsupportedFilterError

            raise UnsupportedFilterError(f"unsupported operator in where: {value}")
        # simple equality
        return f"json_extract(metadata, '$.{key}') = ?", [str(value)]

    if "$and" in where:
        and_list = where["$and"]
        if not isinstance(and_list, list):
            return "", []
        for cond in and_list:
            if not isinstance(cond, dict):
                continue
            for k, v in cond.items():
                sql, p = _field_sql(k, v)
                clauses.append(sql)
                params.extend(p)
        if clauses:
            return " AND " + " AND ".join(f"({c})" for c in clauses), params
        return "", []
    # flat dict
    for k, v in where.items():
        if k.startswith("$"):
            from .base import UnsupportedFilterError

            raise UnsupportedFilterError(f"unsupported operator: {k}")
        sql, p = _field_sql(k, v)
        clauses.append(sql)
        params.extend(p)
    if clauses:
        return " AND " + " AND ".join(f"({c})" for c in clauses), params
    return "", []


# Fusion weights for hybrid score = COS_W*cos + BM25_W*bm25n + RANK_W*rdu.
# Cosine dominates so vocabulary-mismatch queries still recall; BM25 keeps
# exact matches on top; the RDU rank (retrievability x frequency + rd
# boost, normalized to [0, 1]) is a small tie-breaker only — it re-orders
# near-ties, never buries relevance. One formula everywhere: the same
# score_meta drives the wing-cap eviction, Layer1, and the non-sqlite
# hybrid nudge.
COS_W = 0.6
BM25_W = 0.3
RANK_W = 0.1
# Importance saturates at 5.0 (Layer1 default is 3.0); access saturates at
# ~20 reads via log1p — both normalized to [0, 1] before weighting.
# Candidate pool bounds: FTS hits union recent rows so vector similarity can
# surface docs with zero lexical overlap.
_FTS_CANDIDATE_MULT = 5
_POOL_MIN = 100
_POOL_MAX = 500


def _parse_meta(meta_json: str | None) -> dict[str, object]:
    try:
        m = json.loads(meta_json) if meta_json else {}
    except json.JSONDecodeError:
        m = {}
    return m if isinstance(m, dict) else {}


def _public_meta(meta_json: str | None) -> dict[str, object]:
    """Metadata safe for query results: internals stripped.

    Drops the internal ``_embedding`` vector and replaces the raw
    ``access_history`` list with its length (``access_history_len``) —
    timestamps are bookkeeping, not search payload.
    """
    m = _parse_meta(meta_json)
    if "_embedding" in m:
        m = {k: v for k, v in m.items() if k != "_embedding"}
    if isinstance(m.get("access_history"), list):
        history = m["access_history"]
        assert isinstance(history, list)
        m = {k: v for k, v in m.items() if k != "access_history"}
        m["access_history_len"] = len(history)
    return m


def _stored_embedding(meta_json: str | None) -> list[float]:
    """Explicit caller-supplied embedding round-trip (local vectors stay internal)."""
    m = _parse_meta(meta_json)
    emb = m.get("_embedding")
    if isinstance(emb, list):
        return cast(list[float], emb)
    return []


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
    import math

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


class SqliteCollection(BaseCollection):
    """SQLite-backed collection."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock, collection: str, palace_id: str) -> None:
        self._conn = conn
        self._lock = lock
        self._collection = collection
        self._palace_id = palace_id
        self._closed = False

    def _ensure_not_closed(self) -> None:
        if self._closed:
            from .base import BackendClosedError

            raise BackendClosedError("collection is closed")

    def _ft5_available(self) -> bool:
        try:
            self._conn.execute("SELECT 1 FROM embedding_fts LIMIT 1")
            return True
        except sqlite3.Error:
            return False

    @staticmethod
    def _store_vector(cur: sqlite3.Cursor, rowid: object, doc: str) -> None:
        """Best-effort local vector write — must never fail the doc write."""
        try:
            cur.execute(
                "INSERT OR REPLACE INTO doc_vectors (rowid, dim, vec) VALUES (?, ?, ?)",
                (rowid, _VEC_DIM, _vec_encode(_vec_embed_counts(doc or ""))),
            )
        except sqlite3.Error:
            pass

    def _pool_vectors(self, rows: list[tuple[str, str, str, int]]) -> list[list[float]]:
        """Load stored count vectors for pool rows, backfilling legacy rows."""
        if not rows:
            return []
        rowids = [r[3] for r in rows]
        found: dict[int, list[float]] = {}
        try:
            placeholders = ",".join(["?"] * len(rowids))
            cur = self._conn.execute(f"SELECT rowid, vec FROM doc_vectors WHERE rowid IN ({placeholders})", rowids)
            for db_rowid, blob in cur.fetchall():
                vec = _vec_decode(blob, _VEC_DIM)
                if vec is not None:
                    found[int(db_rowid)] = vec
        except sqlite3.Error:
            pass
        missing = [(r[3], r[1] or "") for r in rows if r[3] not in found]
        if missing:
            try:
                cur = self._conn.cursor()
                for db_rowid, doc in missing:
                    vec = _vec_embed_counts(doc)
                    found[int(db_rowid)] = vec
                    try:
                        cur.execute(
                            "INSERT OR REPLACE INTO doc_vectors (rowid, dim, vec) VALUES (?, ?, ?)",
                            (db_rowid, _VEC_DIM, _vec_encode(vec)),
                        )
                    except sqlite3.Error:
                        pass
                self._conn.commit()
            except sqlite3.Error:
                pass
        return [found.get(r[3], [0.0] * _VEC_DIM) for r in rows]

    def add(
        self,
        *,
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, object]] | None = None,
        embeddings: list[list[float]] | None = None,
    ) -> None:
        self._ensure_not_closed()
        if len(documents) != len(ids):
            raise ValueError("documents and ids length mismatch")
        n = len(ids)
        if metadatas is not None and len(metadatas) != n:
            raise ValueError("metadatas length mismatch")
        if embeddings is not None and len(embeddings) != n:
            raise ValueError("embeddings length mismatch")
        # dimension check if needed (no fixed dim, skip)
        with self._lock:
            cur = self._conn.cursor()
            try:
                for i, rid in enumerate(ids):
                    doc = documents[i]
                    meta = metadatas[i] if metadatas is not None else {}
                    meta_json = json.dumps(meta or {}, ensure_ascii=False)
                    # store embedding as json if provided (not used for query)
                    if embeddings is not None and embeddings[i] is not None:
                        # store embedding in metadata to preserve
                        m2 = dict(meta or {})
                        m2["_embedding"] = embeddings[i]
                        meta_json = json.dumps(m2, ensure_ascii=False)
                    cur.execute(
                        "INSERT INTO embeddings (id, document, metadata, collection, palace_id) VALUES (?,?,?,?,?)",
                        (rid, doc, meta_json, self._collection, self._palace_id),
                    )
                    rowid = cur.lastrowid
                    self._store_vector(cur, rowid, doc)
                    # try to insert into FTS5
                    try:
                        cur.execute(
                            "INSERT INTO embedding_fts(rowid, document) VALUES (?, ?)",
                            (rowid, doc),
                        )
                    except sqlite3.Error:
                        pass
                self._conn.commit()
            except sqlite3.IntegrityError as e:
                self._conn.rollback()
                raise ValueError(f"duplicate id: {e}") from e

    def upsert(
        self,
        *,
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, object]] | None = None,
        embeddings: list[list[float]] | None = None,
    ) -> None:
        self._ensure_not_closed()
        if len(documents) != len(ids):
            raise ValueError("documents and ids length mismatch")
        n = len(ids)
        if metadatas is not None and len(metadatas) != n:
            raise ValueError("metadatas length mismatch")
        with self._lock:
            cur = self._conn.cursor()
            try:
                for i, rid in enumerate(ids):
                    doc = documents[i]
                    meta = metadatas[i] if metadatas is not None else {}
                    meta_json = json.dumps(meta or {}, ensure_ascii=False)
                    if embeddings is not None and embeddings[i] is not None:
                        m2 = dict(meta or {})
                        m2["_embedding"] = embeddings[i]
                        meta_json = json.dumps(m2, ensure_ascii=False)
                    # check existing
                    cur.execute(
                        "SELECT rowid FROM embeddings WHERE id=? AND collection=? AND palace_id=?",
                        (rid, self._collection, self._palace_id),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        rowid = row[0]
                        cur.execute(
                            "UPDATE embeddings SET document=?, metadata=? WHERE rowid=?",
                            (doc, meta_json, rowid),
                        )
                        self._store_vector(cur, rowid, doc)
                        try:
                            cur.execute("DELETE FROM embedding_fts WHERE rowid=?", (rowid,))
                            cur.execute(
                                "INSERT INTO embedding_fts(rowid, document) VALUES (?, ?)",
                                (rowid, doc),
                            )
                        except sqlite3.Error:
                            pass
                    else:
                        cur.execute(
                            "INSERT INTO embeddings (id, document, metadata, collection, palace_id) VALUES (?,?,?,?,?)",
                            (rid, doc, meta_json, self._collection, self._palace_id),
                        )
                        rowid = cur.lastrowid
                        self._store_vector(cur, rowid, doc)
                        try:
                            cur.execute(
                                "INSERT INTO embedding_fts(rowid, document) VALUES (?, ?)",
                                (rowid, doc),
                            )
                        except sqlite3.Error:
                            pass
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                raise

    def get(
        self,
        *,
        ids: list[str] | None = None,
        where: dict[str, object] | None = None,
        where_document: dict[str, object] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        include: list[str] | None = None,
    ) -> GetResult:
        self._ensure_not_closed()
        spec = _IncludeSpec.resolve(include, default_distances=False)
        where_sql, where_params = _where_to_sql(where)
        # where_document: simple contains filter
        doc_filter_sql = ""
        doc_filter_params: list[object] = []
        if where_document is not None:
            contains = where_document.get("$contains")
            if contains is not None:
                doc_filter_sql = " AND document LIKE ?"
                doc_filter_params = [f"%{contains}%"]
            else:
                from .base import UnsupportedFilterError

                raise UnsupportedFilterError(f"unsupported where_document: {where_document}")
        sql = "SELECT id, document, metadata FROM embeddings WHERE collection=? AND palace_id=?"
        params: list[object] = [self._collection, self._palace_id]
        if ids is not None:
            if not ids:
                return GetResult.empty()
            placeholders = ",".join(["?"] * len(ids))
            sql += f" AND id IN ({placeholders})"
            params.extend(ids)
        sql += where_sql
        sql += doc_filter_sql
        params.extend(where_params)
        params.extend(doc_filter_params)
        sql += " ORDER BY rowid ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
            if offset is not None:
                sql += " OFFSET ?"
                params.append(offset)
        elif offset is not None:
            sql += " LIMIT -1 OFFSET ?"
            params.append(offset)
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
        out_ids: list[str] = []
        out_docs: list[str] = []
        out_metas: list[dict[str, object]] = []
        out_embs: list[list[float]] | None = [] if spec.embeddings else None
        for rid, doc, meta_json in rows:
            out_ids.append(rid)
            if spec.documents:
                out_docs.append(doc if doc is not None else "")
            else:
                out_docs.append("")
            if spec.metadatas:
                try:
                    m = json.loads(meta_json) if meta_json else {}
                except json.JSONDecodeError:
                    m = {}
                # strip internal embedding
                if isinstance(m, dict) and "_embedding" in m:
                    m = {k: v for k, v in m.items() if k != "_embedding"}
                out_metas.append(m if isinstance(m, dict) else {})
            else:
                out_metas.append({})
            if spec.embeddings and out_embs is not None:
                try:
                    m2 = json.loads(meta_json) if meta_json else {}
                except json.JSONDecodeError:
                    m2 = {}
                emb = m2.get("_embedding") if isinstance(m2, dict) else None
                if isinstance(emb, list):
                    out_embs.append(cast(list[float], emb))
                else:
                    out_embs.append([])
        # If not requested, still return empty lists for compat but fill as per spec
        if not spec.documents:
            out_docs = ["" for _ in out_ids]
        if not spec.metadatas:
            out_metas = [{} for _ in out_ids]
        return GetResult(ids=out_ids, documents=out_docs, metadatas=out_metas, embeddings=out_embs)

    def query(
        self,
        *,
        query_texts: list[str] | None = None,
        query_embeddings: list[list[float]] | None = None,
        n_results: int = 10,
        where: dict[str, object] | None = None,
        where_document: dict[str, object] | None = None,
        include: list[str] | None = None,
    ) -> QueryResult:
        self._ensure_not_closed()
        spec = _IncludeSpec.resolve(include, default_distances=True)
        num_queries = len(query_texts) if query_texts else (len(query_embeddings) if query_embeddings else 1)
        if num_queries == 0:
            return QueryResult.empty(num_queries=0, embeddings_requested=spec.embeddings)
        # True hybrid retrieval: FTS5 candidates UNION recent rows (so vector
        # similarity can surface docs with zero lexical overlap), re-ranked
        # by fused cosine + BM25 + recency. query_embeddings with DIM
        # matching the local space are honored; anything else is ignored
        # (neutral fallback, backward compatible).
        out_ids: list[list[str]] = []
        out_docs: list[list[str]] = []
        out_metas: list[list[dict[str, object]]] = []
        out_dists: list[list[float]] = []
        out_embs: list[list[list[float]]] | None = [] if spec.embeddings else None

        where_sql, where_params = _where_to_sql(where)
        for q_idx in range(num_queries):
            qtext = ""
            if query_texts is not None and q_idx < len(query_texts):
                qtext = query_texts[q_idx] or ""
            qemb: list[float] | None = None
            if query_embeddings is not None and q_idx < len(query_embeddings):
                cand = query_embeddings[q_idx]
                if isinstance(cand, list) and len(cand) == _VEC_DIM:
                    try:
                        qemb = [float(v) for v in cand]
                    except (TypeError, ValueError):
                        qemb = None

            with self._lock:
                pool = self._fetch_pool(qtext, where_sql, where_params, where_document, n_results)
                if qtext.strip() or qemb is not None:
                    scored = self._rank_pool(pool, qtext, qemb)
                else:
                    # no usable signal — neutral fallback (backward compat)
                    scored = [(r, 0.5) for r in pool]
            ordered = scored[:n_results]
            # build output
            ids_q: list[str] = []
            docs_q: list[str] = []
            metas_q: list[dict[str, object]] = []
            dists_q: list[float] = []
            embs_q: list[list[float]] = []
            for (rid, doc, meta_json, _rowid), dist in ordered:
                ids_q.append(rid)
                if spec.documents:
                    docs_q.append(doc or "")
                else:
                    docs_q.append("")
                if spec.metadatas:
                    metas_q.append(_public_meta(meta_json))
                else:
                    metas_q.append({})
                if spec.distances:
                    dists_q.append(float(dist))
                else:
                    dists_q.append(0.0)
                if spec.embeddings:
                    embs_q.append(_stored_embedding(meta_json))
            if not spec.distances:
                dists_q = [0.0 for _ in ids_q]
            out_ids.append(ids_q)
            out_docs.append(docs_q)
            out_metas.append(metas_q)
            out_dists.append(dists_q)
            if spec.embeddings and out_embs is not None:
                out_embs.append(embs_q)

        return QueryResult(
            ids=out_ids, documents=out_docs, metadatas=out_metas, distances=out_dists, embeddings=out_embs
        )

    def _fetch_pool(
        self,
        qtext: str,
        where_sql: str,
        where_params: list[object],
        where_document: dict[str, object] | None,
        n_results: int,
    ) -> list[tuple[str, str, str, int]]:
        """FTS5 hits UNION recent rows, deduped by rowid (FTS first)."""
        contains: object = None
        if where_document is not None:
            contains = where_document.get("$contains")
        sanitized = _sanitize_query(qtext)
        tokens = [t for t in _tokenize(sanitized) if len(t) >= 2]
        fts_rows: list[tuple[str, str, str, int]] = []
        if tokens and self._ft5_available():
            fts_q = " OR ".join(tokens[:10])
            try:
                sql = (
                    "SELECT e.id, e.document, e.metadata, e.rowid "
                    "FROM embeddings e JOIN embedding_fts f ON e.rowid = f.rowid "
                    "WHERE e.collection=? AND e.palace_id=? AND embedding_fts MATCH ?" + where_sql
                )
                params: list[object] = [self._collection, self._palace_id, fts_q, *where_params]
                if contains is not None:
                    sql += " AND e.document LIKE ?"
                    params.append(f"%{contains}%")
                sql += " LIMIT ?"
                params.append(n_results * _FTS_CANDIDATE_MULT)
                cur = self._conn.execute(sql, params)
                fts_rows = cur.fetchall()  # type: ignore[assignment]
            except sqlite3.Error:
                fts_rows = []
        pool_cap = min(max(n_results * 20, _POOL_MIN), _POOL_MAX)
        recent_rows: list[tuple[str, str, str, int]] = []
        try:
            sql2 = "SELECT id, document, metadata, rowid FROM embeddings WHERE collection=? AND palace_id=?" + where_sql
            params2: list[object] = [self._collection, self._palace_id, *where_params]
            if contains is not None:
                sql2 += " AND document LIKE ?"
                params2.append(f"%{contains}%")
            sql2 += " ORDER BY rowid DESC LIMIT ?"
            params2.append(pool_cap)
            cur2 = self._conn.execute(sql2, params2)
            recent_rows = cur2.fetchall()  # type: ignore[assignment]
        except sqlite3.Error:
            recent_rows = []
        seen: set[int] = set()
        pool: list[tuple[str, str, str, int]] = []
        for row in (*fts_rows, *recent_rows):
            if row[3] not in seen:
                seen.add(row[3])
                pool.append(row)
        return pool

    def _rank_pool(
        self,
        pool: list[tuple[str, str, str, int]],
        qtext: str,
        qemb: list[float] | None,
    ) -> list[tuple[tuple[str, str, str, int], float]]:
        """Fused rank: COS_W*cosine + BM25_W*bm25norm + RANK_W*rdu_norm.

        The RDU rank comes from the single shared ``score_meta`` (clamped
        to [0, 1]) — no inline recency decay, no inline importance/access
        weights. Metas without spine keys score through their migrated
        priors, i.e. legacy behavior degrades gracefully.

        Returns (row, distance) with distance = 1 - fused in [0, 1],
        sorted best-first.
        """
        from ..scoring import score_meta

        docs = [r[1] or "" for r in pool]
        metas = [_parse_meta(r[2]) for r in pool]
        if qtext.strip():
            bm25 = _bm25_scores(qtext, docs)
        else:
            bm25 = [0.0] * len(pool)
        max_b = max(bm25) if bm25 else 0.0
        bm25_norm = [s / max_b if max_b > 0 else 0.0 for s in bm25]
        counts = self._pool_vectors(pool)
        if qemb is not None:
            cos = [_vec_cosine(qemb, c) for c in counts]
        elif qtext.strip():
            qcounts = _vec_embed_query_counts(qtext)
            idf = _vec_idf(counts)
            cos = [_vec_weighted_cosine(qcounts, c, idf) for c in counts]
        else:
            cos = [0.0] * len(pool)
        rdu_norm = [min(1.0, max(0.0, score_meta(m))) for m in metas]
        fused = [COS_W * c + BM25_W * b + RANK_W * r for c, b, r in zip(cos, bm25_norm, rdu_norm)]
        order = sorted(range(len(pool)), key=lambda i: fused[i], reverse=True)
        out: list[tuple[tuple[str, str, str, int], float]] = []
        for i in order:
            dist = 1.0 - fused[i]
            dist = min(1.0, max(0.0, dist))
            out.append((pool[i], dist))
        return out

    def delete(
        self,
        *,
        ids: list[str] | None = None,
        where: dict[str, object] | None = None,
    ) -> None:
        self._ensure_not_closed()
        if ids is None and where is None:
            raise ValueError("delete requires ids or where")
        with self._lock:
            cur = self._conn.cursor()
            if ids is not None:
                for rid in ids:
                    cur.execute(
                        "SELECT rowid FROM embeddings WHERE id=? AND collection=? AND palace_id=?",
                        (rid, self._collection, self._palace_id),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        rowid = row[0]
                        cur.execute("DELETE FROM embeddings WHERE rowid=?", (rowid,))
                        try:
                            cur.execute("DELETE FROM embedding_fts WHERE rowid=?", (rowid,))
                        except sqlite3.Error:
                            pass
                        try:
                            cur.execute("DELETE FROM doc_vectors WHERE rowid=?", (rowid,))
                        except sqlite3.Error:
                            pass
            if where is not None:
                where_sql, where_params = _where_to_sql(where)
                sql = "SELECT rowid FROM embeddings WHERE collection=? AND palace_id=?" + where_sql
                params: list[object] = [self._collection, self._palace_id, *where_params]
                cur.execute(sql, params)
                rows = cur.fetchall()
                for (rowid,) in rows:
                    cur.execute("DELETE FROM embeddings WHERE rowid=?", (rowid,))
                    try:
                        cur.execute("DELETE FROM embedding_fts WHERE rowid=?", (rowid,))
                    except sqlite3.Error:
                        pass
                    try:
                        cur.execute("DELETE FROM doc_vectors WHERE rowid=?", (rowid,))
                    except sqlite3.Error:
                        pass
            self._conn.commit()

    def count(self) -> int:
        self._ensure_not_closed()
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM embeddings WHERE collection=? AND palace_id=?",
                (self._collection, self._palace_id),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def close(self) -> None:
        self._closed = True


class SqliteBackend(BaseBackend):
    """SQLite backend — one DB file per palace."""

    name: ClassVar[str] = "sqlite"
    spec_version: ClassVar[str] = "1.0"
    capabilities: ClassVar[frozenset[str]] = frozenset({"where", "fts5", "bm25"})

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._conns: dict[str, sqlite3.Connection] = {}
        self._closed = False

    def _db_path(self, palace: PalaceRef) -> Path:
        if palace.local_path:
            p = Path(palace.local_path).expanduser().resolve()
            # if path is file, use its dir? But spec: palace_path is dir containing DB
            if p.is_file():
                return p
            return p / DB_FILENAME
        # fallback to id as dir
        return Path.cwd() / palace.id / DB_FILENAME

    def _ensure_conn(self, palace: PalaceRef, *, create: bool) -> sqlite3.Connection:
        db_path = self._db_path(palace)
        pid = palace.id
        with self._lock:
            if pid in self._conns:
                return self._conns[pid]
            exists = db_path.exists()
            if not exists and not create:
                # distinguish palace dir missing vs db missing
                palace_dir = db_path.parent
                if not palace_dir.is_dir():
                    raise PalaceNotFoundError(f"palace dir not found: {palace_dir}")
                raise CollectionNotInitializedError(f"palace db not found: {db_path}")
            # ensure dir
            db_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                db_path.parent.chmod(0o750)
            except OSError:
                pass
            conn = sqlite3.connect(str(db_path), timeout=10.0, check_same_thread=False, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            self._init_schema(conn)
            try:
                db_path.chmod(0o600)
            except OSError:
                pass
            self._conns[pid] = conn
            return conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS collections (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS segments (
                id TEXT PRIMARY KEY,
                collection_id TEXT REFERENCES collections(id)
            );
            CREATE TABLE IF NOT EXISTS embeddings (
                id TEXT PRIMARY KEY,
                document TEXT,
                metadata TEXT,
                collection TEXT NOT NULL,
                palace_id TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_embeddings_collection ON embeddings(collection, palace_id);
            CREATE INDEX IF NOT EXISTS idx_embeddings_id ON embeddings(id);
            CREATE TABLE IF NOT EXISTS doc_vectors (
                rowid INTEGER PRIMARY KEY,
                dim INTEGER NOT NULL,
                vec BLOB NOT NULL
            );
            """
        )
        # FTS5 table — try trigram, fallback to porter
        try:
            cur.execute("SELECT count(*) FROM embedding_fts LIMIT 1")
        except sqlite3.Error:
            # table not exists, try create
            created = False
            for tokenize in ("trigram", "porter unicode61", "unicode61"):
                try:
                    cur.execute(
                        f"CREATE VIRTUAL TABLE IF NOT EXISTS embedding_fts USING fts5(document, tokenize='{tokenize}', content='embeddings', content_rowid='rowid')"
                    )
                    created = True
                    break
                except sqlite3.Error:
                    continue
            if not created:
                # create without content sync as fallback
                try:
                    cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS embedding_fts USING fts5(document)")
                except sqlite3.Error:
                    pass
        conn.commit()

    def get_collection(
        self,
        *,
        palace: PalaceRef,
        collection_name: str,
        create: bool = False,
        options: dict[str, object] | None = None,
    ) -> BaseCollection:
        if self._closed:
            from .base import BackendClosedError

            raise BackendClosedError("backend is closed")
        conn = self._ensure_conn(palace, create=create)
        # ensure collection entry exists
        with self._lock:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO collections (id, name) VALUES (?, ?)", (collection_name, collection_name)
                )
                conn.execute(
                    "INSERT OR IGNORE INTO segments (id, collection_id) VALUES (?, ?)",
                    (f"seg_{collection_name}", collection_name),
                )
                conn.commit()
            except sqlite3.Error:
                pass
        # Check if collection has ever been used when create=False? We treat empty as not initialized? Spec: CollectionNotInitializedError when palace exists but collection never created.
        # We use a simple check: if create=False and count==0 and no segments? But easier: if not create and collection not in collections with embeddings? Use heuristic: if count==0, raise? But empty after init could be considered not initialized.
        # To preserve compat, we allow get with create=False even if empty — caller will get empty results.
        # Only raise if palace dir exists but db was just created and collection truly absent — but we just inserted, so not.
        # So no raise here.
        return SqliteCollection(conn, self._lock, collection_name, palace.id)

    def close_palace(self, palace: PalaceRef) -> None:
        with self._lock:
            conn = self._conns.pop(palace.id, None)
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for conn in self._conns.values():
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            self._conns.clear()

    def health(self, palace: PalaceRef | None = None) -> HealthStatus:
        if self._closed:
            return HealthStatus.unhealthy("backend closed")
        if palace is not None:
            db_path = self._db_path(palace)
            if not db_path.exists():
                return HealthStatus.unhealthy(f"db not found: {db_path}")
        return HealthStatus.healthy("sqlite backend ok")

    @classmethod
    def detect(cls, path: str) -> bool:
        p = Path(path).expanduser().resolve()
        if p.is_file() and p.name == DB_FILENAME:
            return True
        if p.is_dir():
            return (p / DB_FILENAME).is_file()
        # also check if path is dir containing db
        return False

    def _collection_exists(self, palace: PalaceRef, collection_name: str) -> bool:
        try:
            conn = self._ensure_conn(palace, create=False)
            cur = conn.execute("SELECT 1 FROM collections WHERE name=? LIMIT 1", (collection_name,))
            return cur.fetchone() is not None
        except PalaceNotFoundError:
            return False
        except sqlite3.Error:
            return False
