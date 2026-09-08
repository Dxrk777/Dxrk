# SPDX-License-Identifier: MIT
"""R12 RBAC enforcement — require_op matrix + CLI wiring (tenant manage, memory read).

Hallazgo API vs brief: ``dxrk/commands/memory.py`` solo expone ``memory``
(uso de RAM, op ``read``); NO existen subcomandos Registry
``mine``/``search``/``query``/``recall``. El ``mine``/``search`` real vive en
``dxrk/memory/__main__.py`` (``python -m dxrk.memory mine|search``, gate
``mine``/``read`` via ``require_op``) y en ``dxrk/memory/mcp_server.py``
(tools ``dxrk_memory_*`` de escritura exigen op ``mine`` via
``_check_mcp_op``; denegado responde error con ``RBAC_DENIED`` e
``isError=true``). Ver ``tests/test_memory_rbac.py``. Por eso aqui
``mine`` se verifica a nivel ``require_op`` (misma llamada que hace la
CLI) y ``read`` via Registry ``["memory"]``.

Determinista: sin red ni sleeps. HOME aislado por test.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from dxrk.commands import register_all
from dxrk.security.enforcement import VALID_OPS, require_op, resolve_user
from dxrk.security.rbac import TenantRoleResolver


def _iso_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_USER", raising=False)
    return home


def _run_cli(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    reg = register_all()
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(argv, out=out, err=err, cwd=str(cwd))
    return code, out.getvalue(), err.getvalue()


def _seed_tenant(tenant: str, users: dict[str, str], default_role: str = "readonly") -> None:
    TenantRoleResolver(tenant).save(users, default_role)


class TestResolveUser:
    def test_default_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        assert resolve_user() == ""

    def test_reads_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        monkeypatch.setenv("DXRK_USER", "alice")
        assert resolve_user() == "alice"

    def test_strips_whitespace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        monkeypatch.setenv("DXRK_USER", "  bob  ")
        assert resolve_user() == "bob"


MATRIX: list[tuple[str, str, bool]] = [
    # (role, op, allowed)
    ("admin", "read", True),
    ("admin", "mine", True),
    ("admin", "manage", True),
    ("dev", "read", True),
    ("dev", "mine", True),
    ("dev", "manage", False),
    ("readonly", "read", True),
    ("readonly", "mine", False),
    ("readonly", "manage", False),
]


@pytest.mark.parametrize(("role", "op", "allowed"), MATRIX)
def test_require_op_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str, op: str, allowed: bool) -> None:
    _iso_home(tmp_path, monkeypatch)
    tenant = "acme"
    user = f"user-{role}-{op}"
    _seed_tenant(tenant, {user: role}, "readonly")
    if allowed:
        assert require_op(tenant, user, op) == role
    else:
        with pytest.raises(PermissionError, match="RBAC_DENIED"):
            require_op(tenant, user, op)


class TestRequireOpLocalMode:
    def test_empty_tenant_bypasses(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        assert require_op("", "alice", "manage") == ""
        assert require_op("", "alice", "mine") == ""
        assert require_op("", "alice", "read") == ""

    def test_empty_user_bypasses(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"alice": "admin"}, "readonly")
        assert require_op("acme", "", "manage") == ""
        assert require_op("acme", "", "mine") == ""

    def test_whitespace_bypasses(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        assert require_op("   ", "alice", "manage") == ""
        assert require_op("acme", "   ", "manage") == ""

    def test_valid_ops_constant(self) -> None:
        assert VALID_OPS == frozenset({"read", "mine", "manage"})


class TestRequireOpUsers:
    def test_unknown_user_falls_to_default_readonly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"alice": "admin"}, "readonly")
        # desconocido -> readonly: read ok, mine/manage denegados
        assert require_op("acme", "ghost", "read") == "readonly"
        with pytest.raises(PermissionError, match="RBAC_DENIED: role=readonly op=mine tenant=acme"):
            require_op("acme", "ghost", "mine")
        with pytest.raises(PermissionError, match="RBAC_DENIED"):
            require_op("acme", "ghost", "manage")

    def test_unknown_user_falls_to_default_dev(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {}, "dev")
        assert require_op("acme", "stranger", "mine") == "dev"
        with pytest.raises(PermissionError, match="RBAC_DENIED"):
            require_op("acme", "stranger", "manage")

    def test_invalid_tenant_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            require_op("../evil", "alice", "read")
        with pytest.raises(ValueError):
            require_op("a/b", "alice", "mine")

    def test_invalid_op_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            require_op("acme", "alice", "write")
        with pytest.raises(ValueError):
            require_op("", "", "bogus")

    def test_denied_message_format(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"carol": "readonly"}, "readonly")
        with pytest.raises(PermissionError, match=r"RBAC_DENIED: role=readonly op=mine tenant=acme"):
            require_op("acme", "carol", "mine")


class TestCliTenantManage:
    def test_create_as_dev_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"bob": "dev"}, "readonly")
        monkeypatch.setenv("DXRK_TENANT", "acme")
        monkeypatch.setenv("DXRK_USER", "bob")
        code, _, err = _run_cli(["tenant", "create", "newbie"], tmp_path)
        assert code == 1
        assert "RBAC_DENIED" in err

    def test_create_as_readonly_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"carol": "readonly"}, "readonly")
        monkeypatch.setenv("DXRK_TENANT", "acme")
        monkeypatch.setenv("DXRK_USER", "carol")
        code, _, err = _run_cli(["tenant", "create", "newbie"], tmp_path)
        assert code == 1
        assert "RBAC_DENIED" in err

    def test_create_as_admin_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"alice": "admin"}, "readonly")
        monkeypatch.setenv("DXRK_TENANT", "acme")
        monkeypatch.setenv("DXRK_USER", "alice")
        code, out, _ = _run_cli(["tenant", "create", "newbie"], tmp_path)
        assert code == 0
        assert "Created tenant newbie" in out

    def test_delete_as_dev_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"bob": "dev"}, "readonly")
        _seed_tenant("victim", {}, "readonly")
        monkeypatch.setenv("DXRK_TENANT", "acme")
        monkeypatch.setenv("DXRK_USER", "bob")
        code, _, err = _run_cli(["tenant", "delete", "victim", "--force"], tmp_path)
        assert code == 1
        assert "RBAC_DENIED" in err

    def test_delete_as_admin_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"alice": "admin"}, "readonly")
        _seed_tenant("victim", {}, "readonly")
        monkeypatch.setenv("DXRK_TENANT", "acme")
        monkeypatch.setenv("DXRK_USER", "alice")
        code, out, _ = _run_cli(["tenant", "delete", "victim", "--force"], tmp_path)
        assert code == 0
        assert "Deleted tenant victim" in out

    def test_create_local_mode_no_user_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, out, _ = _run_cli(["tenant", "create", "local1"], tmp_path)
        assert code == 0
        assert "Created tenant local1" in out


class TestCliMemoryRead:
    def test_memory_as_readonly_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"carol": "readonly"}, "readonly")
        monkeypatch.setenv("DXRK_TENANT", "acme")
        monkeypatch.setenv("DXRK_USER", "carol")
        code, out, _ = _run_cli(["memory"], tmp_path)
        assert code == 0
        assert "Memory Usage" in out

    def test_memory_local_mode_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, out, _ = _run_cli(["memory"], tmp_path)
        assert code == 0
        assert "Memory Usage" in out


class TestCliMinePattern:
    """Registry no tiene `memory mine`: se ejerce el mismo patron de wiring
    (require_op mine + Error: RBAC_DENIED en err + return 1) que usa tenant."""

    @staticmethod
    def _mine_cli(tenant_id: str, user: str, err: io.StringIO) -> int:
        try:
            require_op(tenant_id, user, "mine")
        except PermissionError as exc:
            err.write(f"Error: {exc}\n")
            return 1
        return 0

    def test_mine_as_readonly_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"carol": "readonly"}, "readonly")
        err = io.StringIO()
        code = self._mine_cli("acme", "carol", err)
        assert code == 1
        assert "RBAC_DENIED" in err.getvalue()

    def test_mine_as_dev_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"bob": "dev"}, "readonly")
        err = io.StringIO()
        assert self._mine_cli("acme", "bob", err) == 0

    def test_search_as_readonly_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _seed_tenant("acme", {"carol": "readonly"}, "readonly")
        assert require_op("acme", "carol", "read") == "readonly"
        code, _, _ = _run_cli(["memory"], tmp_path)
        # local (sin DXRK_TENANT/DXRK_USER en este test) tambien pasa
        assert code == 0
