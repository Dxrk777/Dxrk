# SPDX-License-Identifier: MIT
"""R12 RBAC enforcement — mine/search dispatch (dxrk.memory CLI) + MCP tools.

Cubre el wiring que faltaba tras ``test_rbac_enforcement.py``: gate
``mine``/``read`` en ``dxrk/memory/__main__.py`` y ``_check_mcp_op`` en
``dxrk/memory/mcp_server.py`` (denegado -> error con ``RBAC_DENIED`` e
``isError=true`` en JSON-RPC).

Determinista: sin red ni sleeps. HOME aislado por test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dxrk.memory import __main__ as mem_cli
from dxrk.memory.mcp_server import _check_mcp_op, _dispatch, _handle_tool
from dxrk.security.rbac import TenantRoleResolver

WRITE_TOOLS = [
    "dxrk_memory_add_drawer",
    "dxrk_memory_update_drawer",
    "dxrk_memory_delete_drawer",
    "dxrk_memory_mine",
    "dxrk_memory_kg_add",
    "dxrk_memory_kg_invalidate",
]

READ_TOOLS = [
    "dxrk_memory_status",
    "dxrk_memory_search",
    "dxrk_memory_get_drawer",
    "dxrk_memory_list_drawers",
    "dxrk_memory_list_wings",
]


def _iso_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_USER", raising=False)
    return home


def _seed_tenant(tenant: str, users: dict[str, str], default_role: str = "readonly") -> None:
    TenantRoleResolver(tenant).save(users, default_role)


def _as_user(monkeypatch: pytest.MonkeyPatch, tenant: str, user: str) -> None:
    monkeypatch.setenv("DXRK_TENANT", tenant)
    monkeypatch.setenv("DXRK_USER", user)


class TestCheckMcpOp:
    @pytest.mark.parametrize("tool", WRITE_TOOLS)
    def test_write_denied_readonly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"ro": "readonly"})
        _as_user(monkeypatch, "acme", "ro")
        with pytest.raises(PermissionError, match="RBAC_DENIED"):
            _check_mcp_op(tool, {})

    @pytest.mark.parametrize("tool", WRITE_TOOLS)
    def test_write_allowed_dev(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"dev": "dev"})
        _as_user(monkeypatch, "acme", "dev")
        _check_mcp_op(tool, {})  # no raise

    @pytest.mark.parametrize("tool", READ_TOOLS)
    def test_read_bypasses_gate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"ro": "readonly"})
        _as_user(monkeypatch, "acme", "ro")
        _check_mcp_op(tool, {})  # no raise: todos los roles tienen fs.read

    def test_local_mode_bypasses(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _check_mcp_op("dxrk_memory_mine", {})  # sin tenant/user: trusted mode
        monkeypatch.setenv("DXRK_USER", "alice")
        _check_mcp_op("dxrk_memory_add_drawer", {})  # sin tenant: bypass igual

    def test_tenant_from_args(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"ro": "readonly"})
        monkeypatch.setenv("DXRK_USER", "ro")  # sin DXRK_TENANT en env
        with pytest.raises(PermissionError, match="RBAC_DENIED"):
            _check_mcp_op("dxrk_memory_mine", {"tenant": "acme"})

    def test_unknown_tool_bypasses(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"ro": "readonly"})
        _as_user(monkeypatch, "acme", "ro")
        _check_mcp_op("dxrk_memory_nope", {})  # no raise: _handle_tool responde unknown tool


class TestHandleTool:
    def test_add_drawer_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"ro": "readonly"})
        _as_user(monkeypatch, "acme", "ro")
        res = _handle_tool("dxrk_memory_add_drawer", {"wing": "w", "room": "r", "content": "c", "source_file": "f"})
        assert "RBAC_DENIED" in res.get("error", "")

    def test_mine_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"ro": "readonly"})
        _as_user(monkeypatch, "acme", "ro")
        res = _handle_tool("dxrk_memory_mine", {"project_dir": str(tmp_path)})
        assert "RBAC_DENIED" in res.get("error", "")

    def test_kg_add_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"ro": "readonly"})
        _as_user(monkeypatch, "acme", "ro")
        res = _handle_tool("dxrk_memory_kg_add", {"subject": "a", "predicate": "b", "object": "c"})
        assert "RBAC_DENIED" in res.get("error", "")


class TestDispatch:
    def test_tools_call_denied_is_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"ro": "readonly"})
        _as_user(monkeypatch, "acme", "ro")
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "dxrk_memory_mine", "arguments": {"project_dir": str(tmp_path)}},
        }
        out = _dispatch(req)
        assert out is not None
        result = out["result"]
        assert result["isError"] is True
        assert "RBAC_DENIED" in result["content"][0]["text"]


class TestMemoryCli:
    def test_mine_denied_readonly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"ro": "readonly"})
        _as_user(monkeypatch, "acme", "ro")
        code = mem_cli._cmd_mine(["--dry-run", str(tmp_path)])
        assert code == 1
        assert "RBAC_DENIED" in capsys.readouterr().err

    def test_mine_local_mode_runs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = _iso_home(tmp_path, monkeypatch)
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "a.py").write_text("x = 1\n", encoding="utf-8")
        code = mem_cli._cmd_mine(["--dry-run", "--wing", "t", str(proj)])
        assert code == 0
        assert (home / ".dxrk").exists()  # palace aislado en HOME temporal

    def test_search_local_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _iso_home(tmp_path, monkeypatch)
        code = mem_cli._cmd_search(["hola"])
        assert code == 0
        capsys.readouterr()  # sin resultados en palace vacio, sin error

    def test_search_readonly_allowed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"ro": "readonly"})
        _as_user(monkeypatch, "acme", "ro")
        assert mem_cli._cmd_search(["hola"]) == 0  # read lo tienen los 3 roles

    def test_search_invalid_tenant(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _iso_home(tmp_path, monkeypatch)
        monkeypatch.setenv("DXRK_TENANT", "bad!id")
        monkeypatch.setenv("DXRK_USER", "alice")
        assert mem_cli._cmd_search(["hola"]) == 1
        assert capsys.readouterr().err.strip() != ""

    def test_main_dispatch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        assert mem_cli.main(["bogus"]) == 2
        assert mem_cli.main([]) == 0
