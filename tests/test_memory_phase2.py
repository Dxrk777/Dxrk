# SPDX-License-Identifier: MIT
"""DxrkMemory Phase 2 (memory lifecycle) — distill/dedupe, decay scoring, KG episodes, contradiction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

BASE = "The authentication service issues short-lived JWT bearer tokens at login and rotates them on refresh. " * 3
BASE_EXTENDED = BASE + " Logout revokes every outstanding token immediately."

AUTH = (
    "Our authentication service issues short-lived JWT bearer tokens at login. "
    "The refresh flow rotates them automatically and revokes them on logout."
)
DEPLOY = (
    "Releases ship through the blue-green pipeline every Thursday morning. "
    "Rollback flips the router alias back to the previous healthy target."
)

DISTINCT_DOCS = [
    "Aurora borealis shimmered over the fjord while reindeer crossed the frozen lake at dawn.",
    "The harbour master logged seventeen container ships before the tide turned at noon.",
    "Sourdough starter needs daily feeding with rye flour and lukewarm spring water.",
    "Quantum error correction encodes logical qubits across entangled physical lattices.",
    "Medieval cartographers drew sea serpents where the Atlantic charts ran out of coast.",
    "The lighthouse keeper polished the fresnel lens before the autumn storm arrived.",
]


def _dm(tmp_path: Path, name: str = "palace", **kwargs):  # type: ignore[no-untyped-def]
    from dxrk.memory.palace import DxrkMemory

    pal = tmp_path / name
    dm = DxrkMemory(str(pal), **kwargs)
    dm.init()
    return dm


# ---------------------------------------------------------------------------
# A) write-time distill/dedupe
# ---------------------------------------------------------------------------


class TestClassifyContentPair:
    def test_identical_is_duplicate(self):
        from dxrk.memory.palace import classify_content_pair

        assert classify_content_pair(BASE, BASE) == "duplicate"

    def test_extension_is_duplicate(self):
        from dxrk.memory.palace import classify_content_pair

        assert classify_content_pair(BASE_EXTENDED, BASE) == "duplicate"

    def test_unrelated_is_distinct(self):
        from dxrk.memory.palace import classify_content_pair

        assert classify_content_pair(AUTH, DEPLOY) == "distinct"

    def test_empty_is_distinct(self):
        from dxrk.memory.palace import classify_content_pair

        assert classify_content_pair("", AUTH) == "distinct"
        assert classify_content_pair(AUTH, "") == "distinct"

    def test_contradiction_branch(self, monkeypatch):
        import dxrk.memory.palace as pal

        # Same-topic pair (sim 0.36, overlap ~0.05): unreachable at the real
        # 0.85 bar by construction, so lower the bar to exercise the branch.
        monkeypatch.setattr(pal, "DEDUPE_SIM_THRESHOLD", 0.3)
        assert pal.classify_content_pair(AUTH, DEPLOY) == "contradiction"


class TestAddDrawerDedupe:
    def test_near_duplicate_updates_existing(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            first = dm.add_drawer("w", "r", BASE, "/a.txt", 0)
            second = dm.add_drawer("w", "r", BASE_EXTENDED, "/b.txt", 0)
            assert second == first
            assert dm.count() == 1
            got = dm.get_drawer(first)
            assert got is not None
            assert got["document"] == BASE  # original content kept, no fork
            assert int(got["metadata"].get("seen_count", 0)) >= 1
        finally:
            dm.close()

    def test_same_content_distinct_wings_coexist(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            id_a = dm.add_drawer("wingA", "r", BASE, "/a.txt", 0)
            id_b = dm.add_drawer("wingB", "r", BASE, "/a.txt", 0)
            assert id_a != id_b
            assert dm.count() == 2
        finally:
            dm.close()

    def test_distinct_content_inserts(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            id_a = dm.add_drawer("w", "r", AUTH, "/a.txt", 0)
            id_b = dm.add_drawer("w", "r", DEPLOY, "/b.txt", 0)
            assert id_a != id_b
            assert dm.count() == 2
        finally:
            dm.close()

    def test_mine_skips_divergent_copies(self, tmp_path: Path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "one.md").write_text(BASE * 5)
        (proj / "two.md").write_text((BASE + " ") * 5)
        dm = _dm(tmp_path)
        try:
            res = dm.mine(str(proj), wing="w", room="r")
            assert res["files_mined"] == 2
            assert int(res["drawers_deduped"]) >= 1
            # Whichever file mined second collapsed onto the first file's
            # drawers — exactly one file keeps rows, no divergent copies.
            col = dm._collection(create=False)
            got_one = col.get(where={"source_file": str(proj / "one.md")})
            got_two = col.get(where={"source_file": str(proj / "two.md")})
            assert (got_one.ids == []) != (got_two.ids == [])
            assert dm.count() == 3
        finally:
            dm.close()


# ---------------------------------------------------------------------------
# B) decay-aware scoring + bounded wings
# ---------------------------------------------------------------------------


class TestRankScore:
    def test_missing_signals_neutral(self):
        from dxrk.memory.scoring import rank_score

        assert rank_score(0.9) == 0.9
        assert rank_score(0.9, 0, None, None) == 0.9

    def test_access_boosts(self):
        from dxrk.memory.scoring import rank_score

        now = datetime.now(UTC).isoformat()
        assert rank_score(1.0, 10, now, now) > rank_score(1.0, 0, now, None)

    def test_filed_decay_sinks_stale(self):
        from dxrk.memory.scoring import decay_factor, rank_score

        fresh = datetime.now(UTC).isoformat()
        stale = (datetime.now(UTC) - timedelta(days=400)).isoformat()
        assert rank_score(2.0, 0, stale, None) < rank_score(2.0, 0, fresh, None)
        assert 0.0 < decay_factor(stale) < decay_factor(fresh) <= 1.0
        assert decay_factor(None) == 1.0
        assert decay_factor("not-a-date") == 1.0

    def test_top_by_importance_uses_access_on_ties(self):
        from dxrk.memory import top_by_importance
        from dxrk.memory.types import MemoryEntry
        from dxrk.memory.types import top_by_importance as types_top

        now = datetime.now(UTC).isoformat()
        quiet = MemoryEntry(id="q", content="q", importance=1.0, created_at=now)
        busy = MemoryEntry(id="b", content="b", importance=1.0, created_at=now, accessed_at=now, access_count=12)
        assert types_top([quiet, busy], 1)[0].id == "b"
        assert top_by_importance([quiet, busy], 1)[0].id == "b"

    def test_get_drawer_bumps_access(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DISTINCT_DOCS[0], "/a.txt", 0)
            dm.get_drawer(did)
            got = dm.get_drawer(did)
            assert got is not None
            assert int(got["metadata"].get("access_count", 0)) == 2
            assert got["metadata"].get("accessed_at")
        finally:
            dm.close()

    def test_layer1_prefers_important_then_fresh(self, tmp_path: Path):
        from dxrk.memory.layers import Layer1

        dm = _dm(tmp_path)
        try:
            col = dm._collection(create=True)
            now = datetime.now(UTC).isoformat()
            old = (datetime.now(UTC) - timedelta(days=500)).isoformat()
            col.upsert(
                documents=["low importance filler " * 10, "HIGH importance filler " * 10, "stale filler " * 10],
                ids=["d-low", "d-high", "d-stale"],
                metadatas=[
                    {"wing": "w", "room": "r", "source_file": "/l.txt", "filed_at": now, "importance": 0.5},
                    {"wing": "w", "room": "r", "source_file": "/h.txt", "filed_at": now, "importance": 4.5},
                    {"wing": "w", "room": "r", "source_file": "/s.txt", "filed_at": old, "importance": 0.5},
                ],
            )
            out = Layer1(str(tmp_path / "palace")).generate(wing="w")
            assert out.index("HIGH importance") < out.index("low importance")
        finally:
            dm.close()


class TestWingCap:
    def test_cap_bounds_growth(self, tmp_path: Path):
        dm = _dm(tmp_path, max_entries_per_wing=3)
        try:
            for i, doc in enumerate(DISTINCT_DOCS):
                dm.add_drawer("w", "r", doc, f"/f{i}.txt", 0)
            assert dm.count() <= 3
        finally:
            dm.close()

    def test_cap_evicts_lowest_rank_first(self, tmp_path: Path):
        dm = _dm(tmp_path, max_entries_per_wing=3)
        try:
            ids = []
            for i, doc in enumerate(DISTINCT_DOCS[:5]):
                ids.append(dm.add_drawer("w", "r", doc, f"/f{i}.txt", 0, importance=float(i + 1)))
            assert dm.count() <= 3
            # Highest importance (5.0) must survive; lowest (1.0) must be gone.
            assert dm.get_drawer(ids[4]) is not None
            assert dm.get_drawer(ids[0]) is None
        finally:
            dm.close()

    def test_cap_zero_disables(self, tmp_path: Path):
        dm = _dm(tmp_path, max_entries_per_wing=0)
        try:
            for i, doc in enumerate(DISTINCT_DOCS):
                dm.add_drawer("w", "r", doc, f"/f{i}.txt", 0)
            assert dm.count() == len(DISTINCT_DOCS)
        finally:
            dm.close()


# ---------------------------------------------------------------------------
# C) KG auto-extraction on mine (one episode per file version)
# ---------------------------------------------------------------------------


def _kg_for(dm, tmp_path: Path):  # type: ignore[no-untyped-def]
    from dxrk.memory.graph import KnowledgeGraph

    return KnowledgeGraph(str(tmp_path / "palace" / "knowledge_graph.sqlite3"))


V1 = "Alice led the redesign. Alice reviewed every pull request. Alice shipped the release. Bob wrote the docs. Bob fixed the tests. Bob closed the tickets."
V2 = "Alice led the redesign. Alice reviewed every pull request. Alice shipped the release. Carol ran the migration. Carol tuned the database. Carol owned the rollout."


class TestKgEpisodes:
    def test_mine_creates_episode_with_provenance(self, tmp_path: Path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "notes.md").write_text(V1 + " " + "filler text to reach chunk size " * 20)
        dm = _dm(tmp_path)
        try:
            res = dm.mine(str(proj), wing="w", room="r")
            assert int(res["kg_triples"]) >= 2
            kg = _kg_for(dm, tmp_path)
            try:
                current = kg.triples_for_source(str(proj / "notes.md"), current_only=True)
                assert len(current) >= 2
                assert all(t["source_drawer_id"] for t in current)
                subjects = {t["subject"] for t in current}
                assert "Alice" in subjects and "Bob" in subjects
            finally:
                kg.close()
        finally:
            dm.close()

    def test_remine_changed_file_supersedes_episode(self, tmp_path: Path):
        proj = tmp_path / "proj"
        proj.mkdir()
        target = proj / "notes.md"
        target.write_text(V1 + " " + "filler text to reach chunk size " * 20)
        dm = _dm(tmp_path)
        try:
            dm.mine(str(proj), wing="w", room="r")
            target.write_text(V2 + " " + "filler text to reach chunk size " * 20)
            dm.mine(str(proj), wing="w", room="r")
            kg = _kg_for(dm, tmp_path)
            try:
                current = kg.triples_for_source(str(target), current_only=True)
                subjects = {t["subject"] for t in current}
                assert "Carol" in subjects and "Alice" in subjects
                assert "Bob" not in subjects  # old episode superseded, not deleted
                history = kg.triples_for_source(str(target), current_only=False)
                expired = [t for t in history if not t["current"]]
                assert len(expired) >= 1
                assert all(t["valid_to"] for t in expired)
            finally:
                kg.close()
        finally:
            dm.close()

    def test_remine_unchanged_is_noop(self, tmp_path: Path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "notes.md").write_text(V1 + " " + "filler text to reach chunk size " * 20)
        dm = _dm(tmp_path)
        try:
            dm.mine(str(proj), wing="w", room="r")
            res2 = dm.mine(str(proj), wing="w", room="r")
            assert int(res2["kg_triples"]) == 0
            kg = _kg_for(dm, tmp_path)
            try:
                history = kg.triples_for_source(str(proj / "notes.md"), current_only=False)
                assert history and all(t["current"] for t in history)
            finally:
                kg.close()
        finally:
            dm.close()

    def test_supersede_source_unit(self, tmp_path: Path):
        from dxrk.memory.graph import KnowledgeGraph

        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.db"))
        try:
            kg.add_triple("Alice", "knows", "Bob", source_file="/n.md")
            assert kg.supersede_source("/n.md") == 1
            assert kg.triples_for_source("/n.md", current_only=True) == []
            assert len(kg.triples_for_source("/n.md", current_only=False)) == 1
            assert kg.supersede_source("/missing.md") == 0
        finally:
            kg.close()


# ---------------------------------------------------------------------------
# D) contradiction handling via invalidation
# ---------------------------------------------------------------------------


class TestContradiction:
    def test_explicit_supersedes_invalidates_old(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            old = dm.add_drawer("w", "r", AUTH, "/old.md", 0)
            new = dm.add_drawer("w", "r", DEPLOY, "/new.md", 0, supersedes=old)
            assert new != old
            old_got = dm.get_drawer(old)
            assert old_got is not None
            assert old_got["metadata"].get("valid_to")
            assert old_got["metadata"].get("superseded_by") == new
            new_got = dm.get_drawer(new)
            assert new_got is not None
            assert new_got["metadata"].get("supersedes") == old
            # Superseded rows never rank: searching the old text finds nothing.
            res = dm.search("authentication JWT bearer", wing="w")
            texts = [str(h.get("text", "")) for h in res.get("results", [])]
            assert all("authentication service issues" not in t for t in texts)
        finally:
            dm.close()

    def test_explicit_supersedes_missing_target_still_inserts(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            new = dm.add_drawer("w", "r", DEPLOY, "/new.md", 0, supersedes="drawer_missing")
            got = dm.get_drawer(new)
            assert got is not None
            assert got["metadata"].get("supersedes") == "drawer_missing"
        finally:
            dm.close()

    def test_same_id_remine_still_overwrites(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            id1 = dm.add_drawer("w", "r", "content version one here", "/same.txt", 0)
            id2 = dm.add_drawer("w", "r", "content version two here", "/same.txt", 0)
            assert id1 == id2
            assert dm.count() == 1
            got = dm.get_drawer(id1)
            assert got is not None
            assert got["document"] == "content version two here"
        finally:
            dm.close()

    def test_mcp_add_drawer_supersedes_passthrough(self, tmp_path: Path, monkeypatch):
        from dxrk.memory.mcp_server import _handle_tool

        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "mcp_palace"))
        first = _handle_tool(
            "dxrk_memory_add_drawer",
            {"wing": "w", "room": "r", "content": AUTH, "source_file": "/o.md"},
        )
        second = _handle_tool(
            "dxrk_memory_add_drawer",
            {"wing": "w", "room": "r", "content": DEPLOY, "source_file": "/n.md", "supersedes": first["drawer_id"]},
        )
        assert second["drawer_id"] != first["drawer_id"]
        got = _handle_tool("dxrk_memory_get_drawer", {"drawer_id": first["drawer_id"]})
        assert got["drawer"]["metadata"].get("valid_to")
        assert got["drawer"]["metadata"].get("superseded_by") == second["drawer_id"]


@pytest.mark.skip(reason="documented non-goal: session summaries stay naive concatenation in Phase 2")
def test_session_summaries_distill():
    """Placeholder proving the Phase 2 scope boundary (summaries untouched)."""
