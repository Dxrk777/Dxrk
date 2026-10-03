# SPDX-License-Identifier: MIT
"""Policy engine espejo (Fase 0 tanda 2, tarea 9).

PolicyEngine(palace).maybe_run("write" | "periodic") con 4 triggers
RBAC-gateados por memory.maintain y throttling en sidecar.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


def _dm(tmp_path: Path, **kwargs):  # type: ignore[no-untyped-def]
    from dxrk.memory.palace import DxrkMemory

    dm = DxrkMemory(str(tmp_path / "palace"), **kwargs)
    dm.init()
    return dm


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Aisla HOME y limpia DXRK_TENANT (la CLI --tenant muta environ sin revertir)."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_USER", raising=False)


def _iso_days_ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


class TestPolicyWrite:
    def test_write_runs_over_budget_inline(self, tmp_path: Path) -> None:
        from dxrk.memory.policy import PolicyEngine

        dm = _dm(tmp_path, max_entries_per_wing=100)
        seeds = (
            "quantum garden lunar harvest festival " * 12,
            "rust borrow checker trait object lifetime elision " * 12,
            "sourdough fermentation hydration baker percentage " * 12,
        )
        for i, content in enumerate(seeds):
            dm.add_drawer("w", "r", content, f"f{i}.py", i)
        assert dm.wing_usage("w")["count"] == 3
        dm._max_entries_per_wing = 1  # force over-budget without touching the store
        out = PolicyEngine(dm).maybe_run("write")
        assert out["ok"] is True
        assert out["results"]["over_budget"]["evicted"] >= 1
        assert dm.wing_usage("w")["count"] <= 1

    def test_invalid_trigger_rejected(self, tmp_path: Path) -> None:
        from dxrk.memory.policy import PolicyEngine

        with pytest.raises(ValueError, match="trigger"):
            PolicyEngine(_dm(tmp_path)).maybe_run("nope")


class TestPolicyPeriodic:
    def test_rescore_stale_appends_ledger(self, tmp_path: Path) -> None:
        from dxrk.memory.policy import PolicyEngine

        dm = _dm(tmp_path)
        did = dm.add_drawer("w", "r", "stale drawer content here " * 10, "old.py", 0)
        col = dm._collection(create=False)
        got = col.get(ids=[did], include=["metadatas"])
        meta = dict(got.metadatas[0])
        meta["filed_at"] = _iso_days_ago(40)
        meta["score_ledger"] = []
        meta["score_ledger_dropped"] = 0
        col.update(ids=[did], metadatas=[meta])
        out = PolicyEngine(dm).maybe_run("periodic")
        assert out["ok"] is True
        got2 = dm.get_drawer(did)
        assert got2 is not None
        ledger = got2["metadata"].get("score_ledger") or []  # type: ignore[union-attr]
        assert any(e.get("reason") == "rescore_stale" for e in ledger)

    def test_checksum_sweep_reports_and_rehashes(self, tmp_path: Path) -> None:
        from dxrk.memory.policy import PolicyEngine

        dm = _dm(tmp_path)
        good = dm.add_drawer("w", "r", "good content for sweep " * 10, "good.py", 0)
        bad = dm.add_drawer("w", "r", "tampered content for sweep " * 10, "bad.py", 0)
        col = dm._collection(create=False)
        got = col.get(ids=[bad], include=["metadatas"])
        meta = dict(got.metadatas[0])
        meta["content_sha256"] = "0" * 64  # corrupt without touching the doc
        col.update(ids=[bad], metadatas=[meta])
        out = PolicyEngine(dm).maybe_run("periodic")
        sweep = out["results"]["checksum_sweep"]
        assert good not in sweep["mismatches"]
        assert bad in sweep["mismatches"]

    def test_quarantine_sweep_isolates_empty_doc(self, tmp_path: Path) -> None:
        from dxrk.memory.policy import PolicyEngine

        dm = _dm(tmp_path)
        col = dm._collection(create=True)
        col.upsert(
            documents=[""],
            ids=["empty-doc-drawer"],
            metadatas=[{"wing": "w", "room": "r", "source_file": "e.py", "chunk_index": 0}],
        )
        out = PolicyEngine(dm).maybe_run("periodic")
        swept = out["results"]["quarantine_sweep"]
        assert "empty-doc-drawer" in swept["quarantined"]
        stub = dm.get_drawer("empty-doc-drawer")
        assert stub is not None and stub.get("quarantined") is True

    def test_periodic_throttled_15min(self, tmp_path: Path) -> None:
        from dxrk.memory.policy import PolicyEngine

        dm = _dm(tmp_path)
        engine = PolicyEngine(dm, min_interval_seconds=900)
        first = engine.maybe_run("periodic")
        assert all(v.get("skipped") is not True for v in first["results"].values())
        second = engine.maybe_run("periodic")
        assert all(v.get("skipped") is True for v in second["results"].values())
        state_file = Path(dm.palace_path) / ".policy_state.json"
        assert state_file.is_file()


class TestPolicyRbac:
    def test_denied_without_cap(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.policy import PolicyEngine
        from dxrk.security.rbac import TenantRoleResolver

        home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        TenantRoleResolver("acme").save({}, "readonly")
        monkeypatch.setenv("DXRK_TENANT", "acme")
        dm = _dm(tmp_path)
        with pytest.raises(PermissionError, match="RBAC_DENIED"):
            PolicyEngine(dm).maybe_run("write")
        with pytest.raises(PermissionError, match="RBAC_DENIED"):
            PolicyEngine(dm).maybe_run("periodic")

    def test_allowed_with_explicit_grant(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.policy import PolicyEngine
        from dxrk.security.rbac import TenantRoleResolver, grant_memory_maintain

        home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        TenantRoleResolver("acme").save({}, "readonly")
        monkeypatch.setenv("DXRK_TENANT", "acme")
        grant_memory_maintain("acme", "system:policy")
        dm = _dm(tmp_path)
        out = PolicyEngine(dm).maybe_run("periodic")
        assert out["ok"] is True
