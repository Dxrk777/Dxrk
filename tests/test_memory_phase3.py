# SPDX-License-Identifier: MIT
"""DxrkMemory Phase 3 (agent-managed memory) — consolidate, forget, pin, budgets, timeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from dxrk.memory.palace import MAX_CONSOLIDATED_CHARS


def _dm(tmp_path: Path, name: str = "palace", **kwargs):  # type: ignore[no-untyped-def]
    from dxrk.memory.palace import DxrkMemory

    pal = tmp_path / name
    dm = DxrkMemory(str(pal), **kwargs)
    dm.init()
    return dm


DOC_A = (
    "The authentication service issues short-lived JWT bearer tokens at login. "
    "We decided to rotate every token on refresh because long-lived secrets caused an incident. "
    "Logout revokes every outstanding token immediately."
)
DOC_B = (
    "Releases ship through the blue-green pipeline every Thursday morning. "
    "Rollback flips the router alias back to the previous healthy target within minutes. "
    "The team must announce every deploy in the release channel."
)
DOC_C = (
    "The database migration runs online with a backfill job and a verification pass. "
    "We deprecated the legacy user table after the dual-write window closed. "
    "Every migration requires a tested rollback plan before it ships."
)


def _unique_doc(marker: str) -> str:
    return (
        f"The {marker} ledger records every midnight reconciliation exactly once. "
        f"Operators decided the {marker} pipeline must never skip the audit window. "
        f"Because the {marker} flow broke last quarter, rollback now takes seconds."
    )


# ---------------------------------------------------------------------------
# A) consolidate
# ---------------------------------------------------------------------------


class TestConsolidate:
    def test_merge_distills_and_supersedes(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            a = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            b = dm.add_drawer("w", "r", DOC_B, "/b.md", 0)
            c = dm.add_drawer("w", "r", DOC_C, "/c.md", 0)
            res = dm.consolidate_drawers([a, b, c])
            new_id = str(res["drawer_id"])
            assert res["sources"] == 3
            got = dm.get_drawer(new_id)
            assert got is not None
            assert len(str(got["document"])) <= MAX_CONSOLIDATED_CHARS
            assert got["metadata"].get("consolidated_from") == [a, b, c]
            assert got["metadata"].get("supersedes") == a
            # Every source superseded, never overwritten.
            for src in (a, b, c):
                old = dm.get_drawer(src)
                assert old is not None
                assert old["metadata"].get("valid_to")
                assert old["metadata"].get("superseded_by") == new_id
            # Distillate keeps signal from each source.
            text = str(got["document"]).lower()
            assert "jwt" in text or "token" in text
            assert "rollback" in text
        finally:
            dm.close()

    def test_consolidate_is_deterministic(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            a = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            b = dm.add_drawer("w", "r", DOC_B, "/b.md", 0)
            first = dm.consolidate_drawers([a, b])
            second = dm.consolidate_drawers([b, a])
            assert first["drawer_id"] == second["drawer_id"]
        finally:
            dm.close()

    def test_consolidate_rejects(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            with pytest.raises(ValueError, match="at least 2"):
                dm.consolidate_drawers(["only-one"])
            with pytest.raises(ValueError, match="found none"):
                dm.consolidate_drawers(["drawer_missing_1", "drawer_missing_2"])
        finally:
            dm.close()

    def test_consolidate_missing_reported(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            a = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            b = dm.add_drawer("w", "r", DOC_B, "/b.md", 0)
            res = dm.consolidate_drawers([a, b, "drawer_missing"])
            assert res["sources"] == 2
            assert res["missing"] == ["drawer_missing"]
        finally:
            dm.close()

    def test_mcp_consolidate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from dxrk.memory.mcp_server import _handle_tool

        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "mcp_palace"))
        first = _handle_tool(
            "dxrk_memory_add_drawer", {"wing": "w", "room": "r", "content": DOC_A, "source_file": "/a.md"}
        )
        second = _handle_tool(
            "dxrk_memory_add_drawer", {"wing": "w", "room": "r", "content": DOC_B, "source_file": "/b.md"}
        )
        res = _handle_tool("dxrk_memory_consolidate", {"drawer_ids": [first["drawer_id"], second["drawer_id"]]})
        assert "drawer_id" in res
        assert res["sources"] == 2


# ---------------------------------------------------------------------------
# A) forget
# ---------------------------------------------------------------------------


class TestForget:
    def test_soft_forget_keeps_history_but_hides(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            marker = "QuixoticZebra"
            did = dm.add_drawer("w", "r", _unique_doc(marker), "/a.md", 0)
            before = dm.search(marker, wing="w")
            assert any(marker.lower() in str(h.get("text", "")).lower() for h in before.get("results", []))
            res = dm.forget(drawer_ids=[did])
            assert res["soft_forgotten"] == 1
            assert res["deleted"] == 0
            got = dm.get_drawer(did)
            assert got is not None  # still readable history
            assert got["metadata"].get("forgotten") is True
            assert got["metadata"].get("valid_to")
            after = dm.search(marker, wing="w")
            assert all(marker.lower() not in str(h.get("text", "")).lower() for h in after.get("results", []))
            from dxrk.memory.layers import Layer1

            assert marker.lower() not in Layer1(str(tmp_path / "palace")).generate(wing="w").lower()
        finally:
            dm.close()

    def test_hard_forget_deletes(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            res = dm.forget(drawer_ids=[did], hard=True)
            assert res["deleted"] == 1
            assert dm.get_drawer(did) is None
        finally:
            dm.close()

    def test_forget_wing_room_scope(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            dm.add_drawer("w1", "r", DOC_A, "/a.md", 0)
            keep = dm.add_drawer("w2", "r", DOC_B, "/b.md", 0)
            res = dm.forget(wing="w1")
            assert res["matched"] == 1
            assert dm.get_drawer(keep) is not None
            assert dm.get_drawer(keep)["metadata"].get("forgotten") is None
        finally:
            dm.close()

    def test_forget_before_scope(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            assert dm.forget(before="2000-01-01")["matched"] == 0
            assert dm.forget(before="2999-01-01")["matched"] >= 1
            got = dm.get_drawer(did)
            assert got is not None and got["metadata"].get("forgotten") is True
        finally:
            dm.close()

    def test_forget_needs_scope(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            with pytest.raises(ValueError, match="needs a scope"):
                dm.forget()
        finally:
            dm.close()

    def test_forget_missing_reported(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            res = dm.forget(drawer_ids=["drawer_nope"])
            assert res["matched"] == 0
            assert res["missing"] == ["drawer_nope"]
        finally:
            dm.close()

    def test_forget_kg_untouched_by_default(self, tmp_path: Path):
        from dxrk.memory.graph import KnowledgeGraph

        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC_A, "/n.md", 0)
            kg = KnowledgeGraph(str(tmp_path / "palace" / "knowledge_graph.sqlite3"))
            try:
                kg.add_triple("Alice", "knows", "Bob", source_file="/n.md")
                dm.forget(drawer_ids=[did])
                assert kg.triples_for_source("/n.md", current_only=True) != []
                dm.forget(drawer_ids=[did], include_kg=True)
                assert kg.triples_for_source("/n.md", current_only=True) == []
                history = kg.triples_for_source("/n.md", current_only=False)
                assert len(history) == 1 and history[0]["valid_to"]  # superseded, never deleted
            finally:
                kg.close()
        finally:
            dm.close()

    def test_mcp_forget(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from dxrk.memory.mcp_server import _handle_tool

        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "mcp_palace"))
        added = _handle_tool(
            "dxrk_memory_add_drawer", {"wing": "w", "room": "r", "content": DOC_A, "source_file": "/a.md"}
        )
        res = _handle_tool("dxrk_memory_forget", {"drawer_ids": [added["drawer_id"]]})
        assert res["soft_forgotten"] == 1
        bad = _handle_tool("dxrk_memory_forget", {})
        assert "needs a scope" in bad.get("error", "")


# ---------------------------------------------------------------------------
# A) pin
# ---------------------------------------------------------------------------


class TestPin:
    def test_pin_unpin_roundtrip(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            assert dm.pin_drawer(did) is True
            got = dm.get_drawer(did)
            assert got is not None and got["metadata"].get("pinned") is True
            assert dm.unpin_drawer(did) is True
            got2 = dm.get_drawer(did)
            assert got2 is not None and got2["metadata"].get("pinned") is None
            assert dm.pin_drawer("drawer_missing") is False
            assert dm.unpin_drawer("drawer_missing") is False
        finally:
            dm.close()

    def test_pinned_leads_wake_up(self, tmp_path: Path):
        from dxrk.memory.layers import MemoryStack

        dm = _dm(tmp_path)
        try:
            for i in range(20):
                dm.add_drawer("w", "r", _unique_doc(f"loudtopic{i}") * 2, f"/f{i}.md", 0, importance=9.0)
            pinned = dm.add_drawer("w", "r", "ZephyrQuinox low signal note nobody ranks.", "/p.md", 0, importance=0.1)
            assert dm.pin_drawer(pinned) is True
            text = MemoryStack(palace_path=str(tmp_path / "palace")).wake_up(wing="w")
            assert "ZephyrQuinox" in text
        finally:
            dm.close()

    def test_pin_identity_roundtrip(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            rec = dm.pin_identity()
            assert rec["scope"] == "identity" and rec.get("pinned_at")
            assert (tmp_path / "palace" / "pins.json").is_file()
            assert dm.unpin_identity() is True
            assert dm.unpin_identity() is False
        finally:
            dm.close()

    def test_mcp_pin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from dxrk.memory.mcp_server import _handle_tool

        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "mcp_palace"))
        added = _handle_tool(
            "dxrk_memory_add_drawer", {"wing": "w", "room": "r", "content": DOC_A, "source_file": "/a.md"}
        )
        res = _handle_tool("dxrk_memory_pin", {"drawer_id": added["drawer_id"]})
        assert res["pinned"] is True
        un = _handle_tool("dxrk_memory_pin", {"drawer_id": added["drawer_id"], "pinned": False})
        assert un["pinned"] is False
        ident = _handle_tool("dxrk_memory_pin", {"scope": "identity"})
        assert ident["scope"] == "identity"
        missing = _handle_tool("dxrk_memory_pin", {"drawer_id": "drawer_nope"})
        assert "not found" in missing.get("error", "")


# ---------------------------------------------------------------------------
# B) budgets + eviction order
# ---------------------------------------------------------------------------


class TestBudgets:
    def test_eviction_order_superseded_lowest_pinned_never(self, tmp_path: Path):
        dm = _dm(tmp_path, max_entries_per_wing=3)
        try:
            v1 = dm.add_drawer("w", "r", DOC_A, "/v1.md", 0, importance=5.0)
            dm.add_drawer("w", "r", DOC_B, "/v2.md", 0, supersedes=v1, importance=1.0)
            low1 = dm.add_drawer("w", "r", _unique_doc("PinnedKeeper"), "/low1.md", 0, importance=0.1)
            dm.add_drawer("w", "r", _unique_doc("DullFiller"), "/low2.md", 0, importance=0.5)
            # Over cap (4 rows): superseded v1 evicted first despite top score.
            assert dm.get_drawer(v1) is None
            assert dm.pin_drawer(low1) is True
            dm.add_drawer("w", "r", _unique_doc("ShinyNew"), "/high.md", 0, importance=9.0)
            # Pinned lowest-score row survives; lowest unpinned goes instead.
            assert dm.get_drawer(low1) is not None
            assert dm.count() <= 3
        finally:
            dm.close()

    def test_wing_usage_and_budgets(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            dm.add_drawer("w", "r", DOC_A, "/a.md", 0)
            dm.add_drawer("w", "r", DOC_B, "/b.md", 0)
            usage = dm.wing_usage("w")
            assert usage["count"] == 2
            assert usage["budget"] == 1000
            assert usage["remaining"] == 998
            assert usage["over"] is False
            assert usage["unbounded"] is False
            assert usage["truncated"] is False
            all_budgets = dm.budgets()
            assert all_budgets["w"]["count"] == 2
        finally:
            dm.close()

    def test_unbounded_flag(self, tmp_path: Path):
        dm = _dm(tmp_path, max_entries_per_wing=0)
        try:
            assert dm.wing_usage("w")["unbounded"] is True
        finally:
            dm.close()

    def test_status_exposes_budgets(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from dxrk.memory.mcp_server import _handle_tool

        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "mcp_palace"))
        _handle_tool("dxrk_memory_add_drawer", {"wing": "w", "room": "r", "content": DOC_A, "source_file": "/a.md"})
        st = _handle_tool("dxrk_memory_status", {})
        assert st["budgets"]["w"]["count"] == 1
        assert st["budgets"]["w"]["budget"] == 1000

    def test_update_path_enforces_cap(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from dxrk.memory import palace as pal
        from dxrk.memory.mcp_server import _handle_tool

        # The MCP update path builds its own DxrkMemory (default budget 1000,
        # too large to fill here) — spy that it invokes wing-cap enforcement
        # on the destination wing after the upsert.
        calls: list[str] = []
        orig = pal.DxrkMemory.enforce_wing_cap

        def _spy(self, wing: str) -> int:  # type: ignore[no-untyped-def]
            calls.append(wing)
            return orig(self, wing)

        monkeypatch.setattr(pal.DxrkMemory, "enforce_wing_cap", _spy)
        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "mcp_palace"))
        added = _handle_tool(
            "dxrk_memory_add_drawer", {"wing": "other", "room": "r", "content": DOC_C, "source_file": "/c.md"}
        )
        _handle_tool("dxrk_memory_update_drawer", {"drawer_id": added["drawer_id"], "wing": "w", "content": DOC_C})
        assert calls == ["w"]


# ---------------------------------------------------------------------------
# C) timeline
# ---------------------------------------------------------------------------


class TestTimeline:
    def _seed(self, dm, tmp_path: Path):  # type: ignore[no-untyped-def]
        from dxrk.memory.graph import KnowledgeGraph

        sess = dm.add_drawer("w", "2026-09-27", "Session notes: decided to ship Friday.", "session:abc", 0)
        linked = dm.add_drawer("w", "r", DOC_A, "/proj/n.md", 0)
        pinned = dm.add_drawer("w", "r", "Keep this pinned note.", "/p.md", 0)
        assert dm.pin_drawer(pinned) is True
        kg = KnowledgeGraph(str(tmp_path / "palace" / "knowledge_graph.sqlite3"))
        try:
            kg.add_triple(
                "Alice", "knows", "Bob", valid_from="2026-03-01", source_file="/proj/n.md", source_drawer_id=linked
            )
        finally:
            kg.close()
        return sess, pinned

    def test_kinds_and_order(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            self._seed(dm, tmp_path)
            entries = dm.timeline()
            kinds = {e["kind"] for e in entries}
            assert {"session", "file", "pin"} <= kinds
            times = [str(e["time"]) for e in entries]
            assert times == sorted(times)
            for e in entries:
                assert set(e) >= {"time", "kind", "summary", "ref", "wing"}
                assert len(str(e["summary"])) <= 160
            file_entry = next(e for e in entries if e["kind"] == "file")
            assert file_entry["ref"] == "/proj/n.md"
            assert file_entry["wing"] == "w"
        finally:
            dm.close()

    def test_window_and_wing_filter(self, tmp_path: Path):
        dm = _dm(tmp_path)
        try:
            self._seed(dm, tmp_path)
            assert dm.timeline(before="2000-01-01") == []
            assert dm.timeline(since="2999-01-01") == []
            assert dm.timeline(wing="nope") == []
            assert dm.timeline(since="2026-01-01", before="2026-12-31") != []
            with pytest.raises(ValueError):
                dm.timeline(since="not-a-date")
        finally:
            dm.close()

    def test_limit_bounded(self, tmp_path: Path):
        from dxrk.memory import palace as pal

        dm = _dm(tmp_path)
        try:
            self._seed(dm, tmp_path)
            assert len(dm.timeline(limit=1)) == 1
            assert len(dm.timeline(limit=10**9)) <= pal.TIMELINE_MAX_LIMIT
        finally:
            dm.close()

    def test_mcp_timeline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from dxrk.memory.mcp_server import _handle_tool

        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "mcp_palace"))
        _handle_tool(
            "dxrk_memory_add_drawer",
            {"wing": "w", "room": "r", "content": "Session notes here.", "source_file": "session:xyz"},
        )
        res = _handle_tool("dxrk_memory_timeline", {"wing": "w", "limit": 10})
        assert res["count"] >= 1
        assert res["entries"][0]["kind"] == "session"
        bad = _handle_tool("dxrk_memory_timeline", {"since": "bogus"})
        assert "error" in bad


# ---------------------------------------------------------------------------
# RBAC for the new write tools
# ---------------------------------------------------------------------------


class TestPhase3Rbac:
    def _locked(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        from dxrk.security.rbac import TenantRoleResolver

        TenantRoleResolver("acme").save({"ro": "readonly"}, "readonly")
        monkeypatch.setenv("DXRK_TENANT", "acme")
        monkeypatch.setenv("DXRK_USER", "ro")

    @pytest.mark.parametrize("tool", ["dxrk_memory_consolidate", "dxrk_memory_forget", "dxrk_memory_pin"])
    def test_new_writes_denied_readonly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
        from dxrk.memory.mcp_server import _check_mcp_op

        self._locked(tmp_path, monkeypatch)
        with pytest.raises(PermissionError, match="RBAC_DENIED"):
            _check_mcp_op(tool, {})

    def test_timeline_reads_bypass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _check_mcp_op

        self._locked(tmp_path, monkeypatch)
        _check_mcp_op("dxrk_memory_timeline", {})  # no raise
