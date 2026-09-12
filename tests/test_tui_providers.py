# SPDX-License-Identifier: MIT
"""Tests de la pantalla de proveedores de IA (gratis + pago con token)."""

from __future__ import annotations

import json
import os

import pytest

from dxrk.tui import providers_backend as backend
from dxrk.tui.context import TUIContext, ctx_var
from dxrk.tui.screens.providers import ProvidersScreen


class TestCatalog:
    def test_one_free_provider(self):
        assert len(backend.FREE_PROVIDERS) == 1
        assert backend.FREE_PROVIDERS[0].id == "opencode"
        assert backend.FREE_PROVIDERS[0].kind == "free"

    def test_free_models_verified(self):
        models = backend.FREE_PROVIDERS[0].models
        assert len(models) == 7
        assert "opencode/big-pickle" in models

    def test_paid_providers_have_counts(self):
        ids = {p.id for p in backend.PAID_PROVIDERS}
        assert {"openrouter", "google", "groq", "cerebras", "deepseek", "mistral", "xai", "cohere"} <= ids
        for p in backend.PAID_PROVIDERS:
            assert p.kind == "api"

    def test_all_combined(self):
        assert len(backend.ALL_PROVIDERS) == 1 + len(backend.PAID_PROVIDERS)


class TestAuthFile:
    def test_connected_empty_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert backend.connected_providers() == set()

    def test_connected_reads_keys_not_values(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        target = backend.auth_file_path()
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump({"openrouter": {"type": "api", "key": "SECRET-X"}, "empty": {}}, f)
        assert backend.connected_providers() == {"openrouter"}

    def test_connected_invalid_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        target = backend.auth_file_path()
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write("not json{{{")
        assert backend.connected_providers() == set()

    def test_save_token_roundtrip_and_backup(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        target = backend.auth_file_path()
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump({"google": {"type": "oauth", "key": "G"}}, f)
        written = backend.save_api_token("openrouter", "tok-123")
        assert written == target
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
        assert data["openrouter"] == {"type": "api", "key": "tok-123"}
        assert data["google"] == {"type": "oauth", "key": "G"}
        with open(target + ".bak", encoding="utf-8") as f:
            assert "google" in f.read()

    def test_save_token_files_are_owner_only(self, tmp_path, monkeypatch):
        import stat

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        target = backend.auth_file_path()
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump({"google": {"type": "oauth", "key": "G"}}, f)
        backend.save_api_token("openrouter", "tok-123")
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(target + ".bak").st_mode) == 0o600

    def test_save_token_rejects_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        with pytest.raises(ValueError):
            backend.save_api_token("", "tok")
        with pytest.raises(ValueError):
            backend.save_api_token("openrouter", "  ")

    def test_validate_rejects_blank_and_missing_binary(self, monkeypatch):
        assert backend.validate_provider_id("") is False
        assert backend.validate_provider_id("a b") is False
        monkeypatch.setattr(backend.subprocess, "run", broken_run)
        assert backend.validate_provider_id("openrouter", binary="nope") is False


def broken_run(*args, **kwargs):
    raise OSError("no binary")


class TestProvidersScreen:
    def test_registered(self):
        from dxrk.tui.app import DxrkApp

        assert DxrkApp.SCREENS["providers"] is ProvidersScreen

    async def test_rows_render_and_escape(self):
        from dxrk.tui.app import DxrkApp

        ctx = TUIContext(version="9.9.9-test")
        token = ctx_var.set(ctx)
        try:
            app = DxrkApp(ctx)
            async with app.run_test() as pilot:
                await app.push_screen("providers")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, ProvidersScreen)
                rows = screen.query("#providers-list > Container")
                assert len(rows) == len(backend.ALL_PROVIDERS)
                screen.action_cursor_down()
                assert screen.cursor == 1
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, ProvidersScreen)
        finally:
            ctx_var.reset(token)

    async def test_token_submit_saves(self, monkeypatch):
        from textual.widgets import Input

        from dxrk.tui.app import DxrkApp

        saved = {}
        monkeypatch.setattr(backend, "validate_provider_id", lambda *a, **k: True)
        monkeypatch.setattr(
            backend,
            "save_api_token",
            lambda p, t, path="": saved.setdefault("args", (p, t)) or "wrote",
        )
        ctx = TUIContext(version="9.9.9-test")
        token = ctx_var.set(ctx)
        try:
            app = DxrkApp(ctx)
            async with app.run_test() as pilot:
                await app.push_screen("providers")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, ProvidersScreen)
                screen.cursor = 1  # first paid provider
                widget = screen.query_one("#provider-token", Input)
                widget.value = "tok-abc"
                widget.focus()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.pause()
        finally:
            ctx_var.reset(token)
        assert saved.get("args", (None,))[0] == backend.ALL_PROVIDERS[1].id
        assert saved["args"][1] == "tok-abc"
