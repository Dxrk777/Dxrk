# SPDX-License-Identifier: MIT
"""Tests for TUI Express Install (one-shot installer, opencode style)."""

from __future__ import annotations

import asyncio
import threading

from dxrk.cli.install import InstallFlags, normalize_install_flags
from dxrk.models import PersonaID, PresetID
from dxrk.system import DetectionResult


def _fake_detection() -> DetectionResult:
    return DetectionResult()


async def _never_finish_run(selection, on_progress=None):
    """Fake pipeline that never returns: keeps InstallingScreen mounted."""
    await asyncio.sleep(3600)
    return True


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
    async def test_enter_pushes_installing(self, monkeypatch):
        from dxrk.tui.app import DxrkApp, WelcomeScreen
        from dxrk.tui.context import TUIContext, ctx_var
        from dxrk.tui.screens.installing import InstallingScreen

        monkeypatch.setattr("dxrk.pipeline.run_install_pipeline", _never_finish_run)
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

    async def test_ctx_matches_cli_selection(self, monkeypatch):
        from dxrk.tui.app import DxrkApp
        from dxrk.tui.context import TUIContext, ctx_var

        monkeypatch.setattr("dxrk.pipeline.run_install_pipeline", _never_finish_run)
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


class TestInstallingAutoStart:
    async def test_install_starts_on_mount(self, monkeypatch):
        """Pushing 'installing' must start the pipeline (no stuck spinner)."""
        from dxrk.tui.app import DxrkApp
        from dxrk.tui.context import TUIContext, ctx_var

        started = threading.Event()
        calls = []

        async def fake_run(selection, on_progress=None):
            calls.append(selection)
            started.set()
            return True

        monkeypatch.setattr("dxrk.pipeline.run_install_pipeline", fake_run)
        ctx = TUIContext(version="1.1.0")
        ctx.detection = _fake_detection()
        ctx_var.set(ctx)
        app = DxrkApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            pushed = []
            orig_push = app.push_screen
            await orig_push("installing")
            # Patch AFTER installing is mounted: the worker sleeps 1s before
            # pushing "complete", so this lands in time and keeps it hermetic.
            app.push_screen = lambda name: pushed.append(name)  # type: ignore[method-assign]
            assert await asyncio.to_thread(started.wait, 10)
            assert len(calls) == 1
            assert list(calls[0].agents) == list(ctx.selected_agents)
            for _ in range(100):
                if pushed:
                    break
                await pilot.pause()
            assert pushed == ["complete"]
