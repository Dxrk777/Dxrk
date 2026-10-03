# SPDX-License-Identifier: MIT
"""Proyeccion de reads MCP (Fase 0 tanda 2, tarea 10).

Los reads MCP (get_drawer, list_drawers) exponen metadata proyectada:
score_ledger truncado a los ultimos 5 (con score_ledger_dropped ajustado
para que la cadena siga verificando) y access_history crudo reemplazado
por access_history_len. La busqueda ya filtra via _public_meta (pin).
"""

from __future__ import annotations

from pathlib import Path


def _dm(tmp_path: Path):  # type: ignore[no-untyped-def]
    from dxrk.memory.palace import DxrkMemory

    dm = DxrkMemory(str(tmp_path / "palace"))
    dm.init()
    return dm


def _handle(name, args):  # type: ignore[no-untyped-def]
    from dxrk.memory.mcp_server import _handle_tool

    return _handle_tool(name, args)


class TestMcpLedgerProjection:
    def test_get_drawer_truncates_ledger_to_last_five(self, tmp_path: Path) -> None:
        from dxrk.memory.migrate import verify_chain

        dm = _dm(tmp_path)
        did = dm.add_drawer("w", "r", "ledger projection content here " * 10, "f.py", 0)
        for _ in range(8):
            dm.get_drawer(did)
        res = _handle("dxrk_memory_get_drawer", {"drawer_id": did, "palace": str(tmp_path / "palace")})
        meta = res["drawer"]["metadata"]
        assert len(meta["score_ledger"]) == 5
        assert all(e.get("reason") == "access" for e in meta["score_ledger"])
        assert meta["score_ledger_dropped"] >= 3
        assert "access_history" not in meta
        assert meta["access_history_len"] >= 8
        ok, _ = verify_chain(meta)
        assert ok is True

    def test_list_drawers_projects_each_row(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        did = dm.add_drawer("w", "r", "list projection content here " * 10, "f.py", 0)
        for _ in range(7):
            dm.get_drawer(did)
        res = _handle("dxrk_memory_list_drawers", {"palace": str(tmp_path / "palace"), "limit": 10})
        assert res["count"] >= 1
        row = next(d for d in res["drawers"] if d["id"] == did)
        assert len(row["metadata"]["score_ledger"]) == 5
        assert "access_history" not in row["metadata"]
        assert row["metadata"]["access_history_len"] >= 7

    def test_quarantined_stub_has_no_raw_history(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        did = dm.add_drawer("w", "r", "quarantine stub projection " * 10, "f.py", 0)
        dm.quarantine_drawer(did, reason="t10")
        res = _handle("dxrk_memory_get_drawer", {"drawer_id": did, "palace": str(tmp_path / "palace")})
        assert res["drawer"].get("quarantined") is True
        assert "document" not in res["drawer"]
        assert "access_history" not in res["drawer"]["metadata"]


class TestPublicMetaPins:
    def test_search_hides_raw_access_history(self, tmp_path: Path) -> None:
        from dxrk.memory.backend.sqlite import _public_meta

        m = _public_meta('{"wing": "w", "_embedding": [1.0], "access_history": ["a", "b"]}')
        assert "_embedding" not in m
        assert "access_history" not in m
        assert m["access_history_len"] == 2

    def test_search_results_carry_no_full_meta(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        dm.add_drawer("w", "r", "searchable projection probe content " * 10, "f.py", 0)
        res = _handle(
            "dxrk_memory_search",
            {"query": "searchable projection probe", "palace": str(tmp_path / "palace")},
        )
        for hit in res["result"]["results"]:
            assert "_meta" not in hit
            assert "score_ledger" not in hit
