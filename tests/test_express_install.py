# SPDX-License-Identifier: MIT
"""Tests for TUI Express Install (one-shot installer, opencode style)."""

from __future__ import annotations

from dxrk.cli.install import InstallFlags, normalize_install_flags
from dxrk.models import PersonaID, PresetID
from dxrk.system import DetectionResult


def _fake_detection() -> DetectionResult:
    return DetectionResult()


def test_express_is_first_option():
    from dxrk.tui.app import WELCOME_OPTIONS

    assert WELCOME_OPTIONS[0][0] == "Express Install"


def test_parity_with_cli_oneshot():
    sel = normalize_install_flags(InstallFlags(), _fake_detection()).selection
    assert sel.persona == PersonaID.DXRK
    assert sel.preset == PresetID.FULL_DXRK
    assert len(sel.components) == 7
    assert sel.skills == []
    assert len(sel.agents) > 0


class TestExpressInstall:
    async def test_enter_pushes_installing(self):
        from dxrk.tui.app import DxrkApp, WelcomeScreen
        from dxrk.tui.context import TUIContext, ctx_var
        from dxrk.tui.screens.installing import InstallingScreen

        ctx = TUIContext(version="1.1.0")
        ctx.detection = _fake_detection()
        ctx_var.set(ctx)
        app = DxrkApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, WelcomeScreen)
            assert app.screen.cursor == 0
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, InstallingScreen)

    async def test_ctx_matches_cli_selection(self):
        from dxrk.tui.app import DxrkApp
        from dxrk.tui.context import TUIContext, ctx_var

        detection = _fake_detection()
        ctx = TUIContext(version="1.1.0")
        ctx.detection = detection
        ctx_var.set(ctx)
        app = DxrkApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            sel = normalize_install_flags(InstallFlags(), detection).selection
            assert list(ctx.selected_agents) == list(sel.agents)
            assert list(ctx.selected_components) == list(sel.components)
            assert list(ctx.selected_skills) == list(sel.skills)
            assert ctx.persona == sel.persona
            assert ctx.preset == sel.preset
            assert ctx.sdd_mode == sel.sdd_mode
            assert ctx.strict_tdd is False
            assert ctx.model_assignments == {}
