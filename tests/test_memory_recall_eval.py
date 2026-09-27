# SPDX-License-Identifier: MIT
"""Phase 1 recall eval — graded conceptual queries over a fixture corpus.

Regression net for hybrid retrieval: every graded query uses vocabulary
that does NOT literally overlap the target document, so BM25-only +
AND-token filtering fails them. Precision@k / recall@k are asserted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dxrk.memory import AgentMemory
from dxrk.memory.palace import DxrkMemory

WING = "proj"

# (drawer_id, room, content)
CORPUS: list[tuple[str, str, str]] = [
    (
        "auth",
        "backend",
        "Our authentication service issues short-lived JWT bearer tokens at login. "
        "The refresh flow rotates them automatically and revokes them on logout.",
    ),
    (
        "deploy",
        "ops",
        "Releases ship through the blue-green pipeline every Thursday morning. "
        "Rollback flips the router alias back to the previous healthy target.",
    ),
    (
        "backup",
        "ops",
        "Nightly snapshots of the postgres cluster go to cold storage and are "
        "retained for thirty days for disaster recovery.",
    ),
    (
        "verify",
        "workflow",
        "Run the full verification gate with pytest plus coverage to verify every change before opening a pull request against main.",
    ),
    (
        "cook",
        "offtopic",
        "Pasta recipe: boil water, salt generously, cook spaghetti nine minutes, toss with olive oil and parmesan.",
    ),
    (
        "sport",
        "offtopic",
        "The final match ended two to one after extra time, with the winning goal scored in the last minute.",
    ),
    (
        "garden",
        "offtopic",
        "Tomatoes need full sun and consistent watering; mulch keeps the soil moist through the summer.",
    ),
    (
        "music",
        "offtopic",
        "The band rehearses on Tuesdays; the setlist mixes old favorites with two brand new songs.",
    ),
]

# (query, expected target marker, k)
GRADED: list[tuple[str, str, int]] = [
    ("how do we handle auth?", "auth", 3),
    ("ship to production procedure?", "deploy", 3),
    ("database backup recovery plan?", "backup", 3),
    ("how do I verify my changes?", "verify", 3),
]


def _marker(meta: object, doc: str) -> str:
    if isinstance(meta, dict):
        src = str(meta.get("source_file") or "")
        for mid in ("auth", "deploy", "backup", "verify", "cook", "sport", "garden", "music"):
            if mid in src:
                return mid
    for mid in ("JWT bearer", "blue-green", "cold storage", "pytest plus coverage"):
        if mid in doc:
            return {"JWT bearer": "auth", "blue-green": "deploy", "cold storage": "backup"}.get(mid, "verify")
    return "?"


@pytest.fixture(autouse=True)
def _reset_hook_state_flag():
    """Mirror tests/test_cov_f_hooks.py: the hook module caches STATE_DIR init."""
    import dxrk.memory.hooks_cli as hc

    hc._state_dir_initialized = False
    yield
    hc._state_dir_initialized = False


@pytest.fixture()
def palace(tmp_path: Path) -> Path:
    pal = tmp_path / "eval_palace"
    dm = DxrkMemory(str(pal))
    dm.init()
    for marker, room, content in CORPUS:
        dm.add_drawer(WING, room, content, source_file=f"/eval/{marker}.md", chunk_index=0)
    dm.close()
    return pal


def _palace_hits(pal: Path, query: str, k: int) -> list[str]:
    dm = DxrkMemory(str(pal))
    try:
        res = dm.search(query, wing=WING, n_results=k)
    finally:
        dm.close()
    hits = res.get("results", [])
    assert isinstance(hits, list)
    out: list[str] = []
    for h in hits:
        assert isinstance(h, dict)
        out.append(_marker(h.get("source_file"), str(h.get("text", ""))))
    return out


def _agent_hits(pal: Path, query: str, k: int) -> list[str]:
    mem = AgentMemory(path=str(pal))
    entries = mem.search(WING, query, 0, k)
    out: list[str] = []
    for e in entries:
        out.append(_marker({"source_file": e.palace_path}, e.content))
    return out


def _precision_at_k(ranked: list[str], target: str, k: int) -> float:
    topk = ranked[:k]
    return sum(1 for m in topk if m == target) / k


def test_eval_palace_hybrid_recall(palace: Path):
    """Each conceptual query must rank its target in the top-k (palace path)."""
    recalls: list[float] = []
    for query, target, k in GRADED:
        ranked = _palace_hits(palace, query, k)
        assert target in ranked[:k], f"query {query!r} missed {target}: {ranked}"
        assert _precision_at_k(ranked, target, k) >= 1 / k
        recalls.append(1.0 if target in ranked[:k] else 0.0)
    assert sum(recalls) / len(recalls) == 1.0


def test_eval_agent_search_recall(palace: Path):
    """Same bar through AgentMemory.search (AND-filter removal, Phase 1B)."""
    recalls: list[float] = []
    for query, target, k in GRADED:
        ranked = _agent_hits(palace, query, k)
        assert target in ranked[:k], f"query {query!r} missed {target}: {ranked}"
        assert _precision_at_k(ranked, target, k) >= 1 / k
        recalls.append(1.0 if target in ranked[:k] else 0.0)
    assert sum(recalls) / len(recalls) == 1.0


def test_eval_pure_vector_win(palace: Path):
    """The auth query has ZERO lexical overlap — only the vector can rank it.

    Pins Phase 1A: BM25-only retrieval scores this 0.0 and can never
    separate it from decoys on meaning.
    """
    dm = DxrkMemory(str(palace))
    try:
        res = dm.search("how do we handle auth?", wing=WING, n_results=3)
    finally:
        dm.close()
    hits = res.get("results", [])
    assert isinstance(hits, list) and len(hits) >= 1
    top = hits[0]
    assert isinstance(top, dict)
    assert str(top.get("source_file", "")).endswith("auth.md")
    assert float(top.get("bm25_score", -1)) == 0.0
    assert float(top.get("similarity", 0.0)) >= 0.15


def test_eval_gibberish_recall_floor(palace: Path):
    """A nonsense query must not surface corpus drawers (relevance floor)."""
    mem = AgentMemory(path=str(palace))
    assert mem.search(WING, "xqzt blorpt fnord quantum", 0, 5) == []


def test_hook_session_start_round_trip(palace: Path, tmp_path: Path, monkeypatch):
    """hook_session_start returns L0+L1 context; a conceptual query then recalls it."""
    import dxrk.memory.hooks_cli as hc

    state = tmp_path / "hstate"
    monkeypatch.setattr(hc, "PALACE_ROOT", palace)
    monkeypatch.setattr(hc, "STATE_DIR", state)
    monkeypatch.setattr(hc, "_MINE_PID_DIR", state / "mine_pids")
    hc._state_dir_initialized = False

    outs: list[dict] = []
    monkeypatch.setattr(hc, "_output", outs.append)
    hc.hook_session_start({"session_id": "eval-sess", "transcript_path": ""}, "dxrk")
    assert len(outs) == 1
    msg = outs[0].get("systemMessage", "")
    assert "JWT bearer" in msg  # L1 top drawer surfaced at session start
    assert len(msg) <= 2000  # compact output bound

    # round-trip: the hooked context is searchable via a conceptual query
    assert "auth" in _agent_hits(palace, "how do we handle auth?", 3)[:3]


# ---------------------------------------------------------------------------
# Local-vector unit tests (Phase 1A mechanics)
# ---------------------------------------------------------------------------


class TestLocalVectors:
    def test_embed_deterministic_and_sized(self):
        from dxrk.memory.vectors import DIM, embed_counts, embed_text

        a = embed_counts("hello world")
        assert len(a) == DIM
        assert a == embed_counts("hello world")
        assert embed_counts("totally different") != a
        normed = embed_text("hello world")
        assert abs(sum(v * v for v in normed) - 1.0) < 1e-6

    def test_query_drops_stopwords(self):
        from dxrk.memory.vectors import embed_counts, embed_query_counts

        assert embed_query_counts("how do we handle auth?") == embed_counts("handle auth")

    def test_query_embeddings_dim_matched_ranks(self, tmp_path: Path):
        """Explicit DIM-wide embeddings are honored (true hybrid, not neutral)."""
        from dxrk.memory.backend import PalaceRef, SqliteBackend
        from dxrk.memory.vectors import embed_text

        be = SqliteBackend()
        try:
            ref = PalaceRef(id=str(tmp_path), local_path=str(tmp_path))
            col = be.get_collection(palace=ref, collection_name="qemb2", create=True)
            col.add(documents=["alpha beta gamma"], ids=["a"], metadatas=[{"wing": "w"}])
            col.add(documents=["unrelated zebra quantum"], ids=["b"], metadatas=[{"wing": "w"}])
            q = col.query(query_embeddings=[embed_text("alpha beta gamma")], n_results=2)
            assert q.ids[0][0] == "a"
            assert q.distances[0][0] < q.distances[0][1]
        finally:
            be.close()

    def test_query_embeddings_dim_mismatch_stays_neutral(self, tmp_path: Path):
        from dxrk.memory.backend import PalaceRef, SqliteBackend

        be = SqliteBackend()
        try:
            ref = PalaceRef(id=str(tmp_path), local_path=str(tmp_path))
            col = be.get_collection(palace=ref, collection_name="qemb3", create=True)
            col.add(documents=["alpha beta"], ids=["q1"], metadatas=[{"wing": "w"}])
            q = col.query(query_embeddings=[[0.1, 0.2]], n_results=5)
            assert "q1" in q.ids[0]
            assert q.distances[0][0] == 0.5
        finally:
            be.close()

    def test_legacy_rows_backfilled_on_query(self, tmp_path: Path):
        """Rows written before doc_vectors existed get vectors lazily."""
        from dxrk.memory.backend import PalaceRef, SqliteBackend

        be = SqliteBackend()
        try:
            ref = PalaceRef(id=str(tmp_path), local_path=str(tmp_path))
            col = be.get_collection(palace=ref, collection_name="backfill", create=True)
            col.add(documents=["authentication tokens login"], ids=["l1"], metadatas=[{"wing": "w"}])
            col._conn.execute("DELETE FROM doc_vectors")  # type: ignore[attr-defined]
            col._conn.commit()  # type: ignore[attr-defined]
            q = col.query(query_texts=["how do we handle auth?"], n_results=5)
            assert q.ids[0] == ["l1"]
            cur = col._conn.execute("SELECT COUNT(*) FROM doc_vectors")  # type: ignore[attr-defined]
            assert cur.fetchone()[0] == 1
        finally:
            be.close()

    def test_delete_purges_vectors(self, tmp_path: Path):
        from dxrk.memory.backend import PalaceRef, SqliteBackend

        be = SqliteBackend()
        try:
            ref = PalaceRef(id=str(tmp_path), local_path=str(tmp_path))
            col = be.get_collection(palace=ref, collection_name="delvec", create=True)
            col.add(documents=["to be deleted"], ids=["d1"], metadatas=[{"wing": "w"}])
            col.delete(ids=["d1"])
            cur = col._conn.execute("SELECT COUNT(*) FROM doc_vectors")  # type: ignore[attr-defined]
            assert cur.fetchone()[0] == 0
        finally:
            be.close()
