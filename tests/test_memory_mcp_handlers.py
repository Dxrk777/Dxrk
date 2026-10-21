# SPDX-License-Identifier: MIT
"""Contract tests for the MCP tool-handler registry split."""

from __future__ import annotations

from pathlib import Path

from dxrk.memory.mcp_handlers import TOOL_HANDLERS
from dxrk.memory.mcp_server import TOOLS, _handle_tool


def test_every_exposed_tool_has_a_handler() -> None:
    assert set(TOOL_HANDLERS) == set(TOOLS)
    assert len(TOOL_HANDLERS) == len(TOOLS) == 35


def test_handle_tool_dispatches_through_registry(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[dict[str, object], str]] = []

    def stub(args: dict[str, object], malla_path: str) -> dict[str, object]:
        calls.append((args, malla_path))
        return {"stubbed": True}

    monkeypatch.setitem(TOOL_HANDLERS, "dxrk_memory_status", stub)
    malla = tmp_path / "malla"
    res = _handle_tool("dxrk_memory_status", {"malla": str(malla)})

    assert res == {"stubbed": True}
    assert calls == [({"malla": str(malla)}, str(malla.resolve()))]
