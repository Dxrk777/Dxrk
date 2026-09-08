# SPDX-License-Identifier: MIT
"""Verificación enterprise: CLI tenant + migración + TUI switcher.

Determinista: sin red ni sleeps. HOME aislado por test con ``tmp_path`` +
``monkeypatch`` y ``DXRK_TENANT`` siempre controlado.

Cómo se invoca la CLI en los tests de este repo (no hay CliRunner: la CLI
es argparse + Registry propio): ``register_all().execute(argv, out=...,
err=..., cwd=...)`` con ``io.StringIO`` como captura (patrón de
``tests/test_tenant_e2e.py`` y ``tests/test_commands.py``). El flag
``--tenant``/``-t`` se ejercita vía ``dxrk.__main__.main`` con ``sys.argv``
parcheado, que es el único camino que lo resuelve (valida con
``validate_id`` y exporta ``DXRK_TENANT``).

El piloto TUI reutiliza el patrón de ``tests/test_tui.py``:
``async with DxrkApp(ctx).run_test() as pilot`` + ``push_screen`` +
``pilot.pause()`` (sin sleeps).
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest

from dxrk.__main__ import main as dxrk_main
from dxrk.commands import register_all
from dxrk.security.jwt import validate_id
from dxrk.tenant.migration import ensure_tenant, is_migrated, list_tenants, migrate_legacy_to_default
from dxrk.tui.app import DxrkApp


def _iso_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Aísla HOME y limpia env de tenant/vault (espejo de test_tenant_e2e)."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_VAULT_KEY", raising=False)
    for key in [k for k in os.environ if k.startswith("DXRK_VAULT_KEY_")]:
        monkeypatch.delenv(key, raising=False)
    return home


def _run_cli(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    """Ejecuta la CLI vía Registry con capturas en memoria."""
    reg = register_all()
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(argv, out=out, err=err, cwd=str(cwd))
    return code, out.getvalue(), err.getvalue()


def _repoint_legacy_paths(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """Reconstruye LEGACY_PATHS contra el HOME aislado.

    LEGACY_PATHS se materializa a import time con el HOME real (documentado
    en la cabecera de migration.py); sin este repoint la migración miraría
    ``~/.dxrk`` del usuario real en vez del tmp. Monkeypatch lo revierte solo.
    """
    import dxrk.tenant.migration as migration

    dxrk_dir = home / ".dxrk"
    monkeypatch.setattr(
        migration,
        "LEGACY_PATHS",
        [
            (dxrk_dir / "palace" / "sqlite_palace.db", Path("palace") / "sqlite_palace.db"),
            (dxrk_dir / "locks", Path("locks")),
            (dxrk_dir / "knowledge_graph.sqlite3", Path("knowledge_graph.sqlite3")),
            (dxrk_dir / "identity.txt", Path("identity.txt")),
            (dxrk_dir / "config.yaml", Path("config.yaml")),
            (dxrk_dir / "settings.json", Path("settings.json")),
            (dxrk_dir / "vault.enc", Path("vault.enc")),
            (dxrk_dir / "memories.json", Path("memories.json")),
            (dxrk_dir / "iq.json", Path("iq.json")),
        ],
    )


class TestTenantCliRoundtrip:
    def test_create_list_current_delete_roundtrip(self, tmp_path, monkeypatch) -> None:
        home = _iso_home(tmp_path, monkeypatch)
        code, out, _ = _run_cli(["tenant", "create", "acme"], tmp_path)
        assert code == 0
        assert "Created tenant acme" in out
        code, out, _ = _run_cli(["tenant", "create", "bob"], tmp_path)
        assert code == 0
        assert "Created tenant bob" in out

        code, out, _ = _run_cli(["tenant", "list"], tmp_path)
        assert code == 0
        assert "acme" in out and "bob" in out

        code, out, _ = _run_cli(["tenant", "switch", "acme"], tmp_path)
        assert code == 0
        assert "Switched to tenant acme" in out
        assert (home / ".dxrk" / "tenants" / "_active").read_text(encoding="utf-8") == "acme"

        code, out, _ = _run_cli(["tenant", "current"], tmp_path)
        assert code == 0
        assert out.strip() == "acme"

        code, out, _ = _run_cli(["tenant", "delete", "acme", "--force"], tmp_path)
        assert code == 0
        assert "Deleted tenant acme" in out
        assert not (home / ".dxrk" / "tenants" / "acme").exists()

        code, out, _ = _run_cli(["tenant", "list"], tmp_path)
        assert code == 0
        assert "acme" not in out
        assert "bob" in out

    def test_switch_unknown_tenant_fails(self, tmp_path, monkeypatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, _, err = _run_cli(["tenant", "switch", "ghost"], tmp_path)
        assert code == 1
        assert "not found" in err

    def test_delete_requires_force(self, tmp_path, monkeypatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _run_cli(["tenant", "create", "acme"], tmp_path)
        code, _, err = _run_cli(["tenant", "delete", "acme"], tmp_path)
        assert code == 1
        assert "--force" in err
        code, out, _ = _run_cli(["tenant", "list"], tmp_path)
        assert code == 0
        assert "acme" in out

    def test_create_duplicate_is_idempotent(self, tmp_path, monkeypatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        assert _run_cli(["tenant", "create", "acme"], tmp_path)[0] == 0
        code, out, _ = _run_cli(["tenant", "create", "acme"], tmp_path)
        assert code == 0
        assert "Created tenant acme" in out

    @pytest.mark.parametrize("tid", ["../evil", "a/b", "bad id", "x" * 257, "a:b"])
    def test_cli_create_rejects_invalid(self, tmp_path, monkeypatch, tid: str) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, _, err = _run_cli(["tenant", "create", tid], tmp_path)
        assert code == 1
        assert "invalid tenant id" in err


class TestTenantWhoami:
    def test_whoami_reflects_env_tenant(self, tmp_path, monkeypatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        _run_cli(["tenant", "create", "acme"], tmp_path)
        monkeypatch.setenv("DXRK_TENANT", "acme")
        code, out, _ = _run_cli(["tenant", "whoami"], tmp_path)
        assert code == 0
        assert out.strip() == "acme"

    def test_whoami_reflects_flag_tenant(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture) -> None:
        _iso_home(tmp_path, monkeypatch)
        monkeypatch.setattr(sys, "argv", ["dxrk", "--tenant", "acme", "tenant", "whoami"])
        dxrk_main()
        assert capsys.readouterr().out.strip() == "acme"
        assert os.environ.get("DXRK_TENANT") == "acme"

    def test_flag_short_t_overrides_env(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture) -> None:
        _iso_home(tmp_path, monkeypatch)
        monkeypatch.setenv("DXRK_TENANT", "bob")
        monkeypatch.setattr(sys, "argv", ["dxrk", "-t", "acme", "tenant", "whoami"])
        dxrk_main()
        assert capsys.readouterr().out.strip() == "acme"

    def test_flag_invalid_tenant_rejected(self, tmp_path, monkeypatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        monkeypatch.setattr(sys, "argv", ["dxrk", "--tenant", "../evil", "tenant", "whoami"])
        with pytest.raises(SystemExit):
            dxrk_main()

    def test_current_and_whoami_without_tenant(self, tmp_path, monkeypatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, out, _ = _run_cli(["tenant", "current"], tmp_path)
        assert code == 0
        assert out.strip() == "No current tenant"
        code, out, _ = _run_cli(["tenant", "whoami"], tmp_path)
        assert code == 0
        assert out.strip() == "No tenant"


class TestValidateId:
    @pytest.mark.parametrize("tid", ["acme", "a", "A-1_2", "default", "0", "TENANT_01", "x" * 256])
    def test_accepts_valid(self, tid: str) -> None:
        assert validate_id(tid) is True

    @pytest.mark.parametrize(
        "tid",
        ["", "../evil", "..", "a/b", "a\\b", "a b", "acme!", "a:b", "t@x", ".", ".hidden", "/", "áé", "x" * 257],
    )
    def test_rejects_invalid(self, tid: str) -> None:
        assert validate_id(tid) is False


class TestMigration:
    @staticmethod
    def _seed_legacy(home: Path) -> dict[str, str]:
        dxrk_dir = home / ".dxrk"
        (dxrk_dir / "palace").mkdir(parents=True, exist_ok=True)
        (dxrk_dir / "locks").mkdir(parents=True, exist_ok=True)
        seeds = {
            str(dxrk_dir / "palace" / "sqlite_palace.db"): "fake-db-bytes",
            str(dxrk_dir / "locks" / "a.lock"): "locked",
            str(dxrk_dir / "identity.txt"): "legacy identity",
            str(dxrk_dir / "config.yaml"): "key: value\n",
        }
        for path, content in seeds.items():
            Path(path).write_text(content, encoding="utf-8")
        return seeds

    def test_migrate_copies_legacy_and_is_idempotent(self, tmp_path, monkeypatch) -> None:
        home = _iso_home(tmp_path, monkeypatch)
        _repoint_legacy_paths(monkeypatch, home)
        seeds = self._seed_legacy(home)

        first = migrate_legacy_to_default(dry_run=False)
        assert first["moved"] == []
        assert len(first["copied"]) == len(seeds)
        assert is_migrated() is True

        default_root = home / ".dxrk" / "tenants" / "default"
        assert (default_root / "palace" / "sqlite_palace.db").read_text(encoding="utf-8") == "fake-db-bytes"
        assert (default_root / "locks" / "a.lock").read_text(encoding="utf-8") == "locked"
        assert (default_root / "identity.txt").read_text(encoding="utf-8") == "legacy identity"
        assert (default_root / "config.yaml").read_text(encoding="utf-8") == "key: value\n"
        # la migración copia, no mueve: el legado queda intacto
        for legacy, content in seeds.items():
            assert Path(legacy).read_text(encoding="utf-8") == content

        registry = json.loads((home / ".dxrk" / "tenants" / "_registry.json").read_text(encoding="utf-8"))
        assert registry["tenants"][0]["id"] == "default"
        assert (home / ".dxrk" / "tenants" / "_active").read_text(encoding="utf-8") == "default"

        # segunda corrida: idempotente — nada nuevo que copiar, mismo layout final
        snapshot = {p: p.read_bytes() for p in default_root.rglob("*") if p.is_file()}
        second = migrate_legacy_to_default(dry_run=False)
        assert second["moved"] == []
        assert second["copied"] == []
        assert {p: p.read_bytes() for p in default_root.rglob("*") if p.is_file()} == snapshot
        assert is_migrated() is True

    def test_migrate_dry_run_reports_without_mutating(self, tmp_path, monkeypatch) -> None:
        home = _iso_home(tmp_path, monkeypatch)
        _repoint_legacy_paths(monkeypatch, home)
        self._seed_legacy(home)
        plan = migrate_legacy_to_default(dry_run=True)
        assert len(plan["copied"]) == 4
        assert not (home / ".dxrk" / "tenants" / "default").exists()
        assert not (home / ".dxrk" / "tenants" / "_registry.json").exists()
        assert is_migrated() is False

    def test_cli_migrate_reports(self, tmp_path, monkeypatch) -> None:
        home = _iso_home(tmp_path, monkeypatch)
        _repoint_legacy_paths(monkeypatch, home)
        self._seed_legacy(home)
        code, out, _ = _run_cli(["tenant", "migrate"], tmp_path)
        assert code == 0
        assert "Migrated" in out
        assert is_migrated() is True
        assert (home / ".dxrk" / "tenants" / "default" / "identity.txt").exists()


class TestSwitcherPureLogic:
    def test_get_tenants_sorted_and_skips_invalid(self, tmp_path, monkeypatch) -> None:
        from dxrk.tui.screens.tenant_switcher import _get_tenants

        home = _iso_home(tmp_path, monkeypatch)
        ensure_tenant("bob")
        ensure_tenant("acme")
        (home / ".dxrk" / "tenants" / "bad!id").mkdir()
        (home / ".dxrk" / "tenants" / "_registry.json").write_text("{}", encoding="utf-8")
        assert _get_tenants() == ["acme", "bob"]
        assert list_tenants() == ["acme", "bob"]

    def test_badge_text_reflects_ctx(self, tmp_path, monkeypatch) -> None:
        from dxrk.tui.context import TUIContext, get_ctx, set_ctx
        from dxrk.tui.screens.tenant_switcher import _tenant_badge_text

        _iso_home(tmp_path, monkeypatch)
        previous = get_ctx()
        set_ctx(TUIContext(version="test", tenant_id="acme", role="admin"))
        try:
            assert _tenant_badge_text() == "tenant: acme · role: admin"
        finally:
            set_ctx(previous)

    def test_effective_tenant_priority(self, tmp_path, monkeypatch) -> None:
        from dxrk.commands.registry import CommandContext
        from dxrk.commands.tenant import _effective_tenant

        home = _iso_home(tmp_path, monkeypatch)
        (home / ".dxrk" / "tenants").mkdir(parents=True, exist_ok=True)
        (home / ".dxrk" / "tenants" / "_active").write_text("file-tenant", encoding="utf-8")
        assert _effective_tenant(None) == "file-tenant"
        monkeypatch.setenv("DXRK_TENANT", "env-tenant")
        assert _effective_tenant(None) == "env-tenant"
        assert _effective_tenant(CommandContext(args=[], tenant_id="ctx-tenant")) == "ctx-tenant"


class TestSwitcherPilot:
    """Pantalla real con pilot (patrón de tests/test_tui.py)."""

    @pytest.mark.asyncio
    async def test_switcher_lists_and_switches_active(self, tmp_path, monkeypatch) -> None:
        from dxrk.tui.context import TUIContext, get_ctx
        from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

        home = _iso_home(tmp_path, monkeypatch)
        ensure_tenant("acme")
        ensure_tenant("bob")

        app = DxrkApp(TUIContext(version="test", tenant_id="acme", role="readonly"))
        async with app.run_test() as pilot:
            await pilot.app.push_screen("tenant_switcher")
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, TenantSwitcherScreen)
            assert screen._tenants == ["acme", "bob"]
            assert screen.query_one("#tenant-create-input") is not None
            assert screen.cursor == 0
            await pilot.press("down")
            await pilot.pause()
            assert screen.cursor == 1
            await pilot.press("enter")
            await pilot.pause()
            assert get_ctx().tenant_id == "bob"
            assert os.environ.get("DXRK_TENANT") == "bob"
            assert (home / ".dxrk" / "tenants" / "_active").read_text(encoding="utf-8") == "bob"
