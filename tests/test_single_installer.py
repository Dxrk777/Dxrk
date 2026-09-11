# SPDX-License-Identifier: MIT
"""Tests del instalador único (estilo opencode): chat directo + rankings."""

from __future__ import annotations


async def test_initial_screen_chat_opens_chat():
    from dxrk.tui.app import DxrkApp
    from dxrk.tui.context import TUIContext, ctx_var
    from dxrk.tui.screens.chat import ChatScreen

    ctx = TUIContext(version="test")
    ctx_var.set(ctx)
    app = DxrkApp(ctx, initial_screen="chat")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ChatScreen)


async def test_initial_screen_defaults_to_welcome():
    from dxrk.tui.app import DxrkApp, WelcomeScreen
    from dxrk.tui.context import TUIContext, ctx_var

    ctx = TUIContext(version="test")
    ctx_var.set(ctx)
    app = DxrkApp(ctx)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, WelcomeScreen)


def test_is_installed_false_when_missing(tmp_path):
    from dxrk.__main__ import _is_installed

    assert _is_installed(str(tmp_path)) is False


def test_is_installed_true_with_state(tmp_path):
    from dxrk.__main__ import _is_installed
    from dxrk.state import InstallState
    from dxrk.state import write as state_write

    state_write(str(tmp_path), InstallState(installed_agents=["claude"]))
    assert _is_installed(str(tmp_path)) is True


def test_paid_ranking_best_first():
    from dxrk.tui import providers_backend as backend

    ids = [p.id for p in backend.PAID_PROVIDERS]
    assert ids == [
        "openrouter",
        "google",
        "deepseek",
        "mistral",
        "groq",
        "xai",
        "cohere",
        "cerebras",
        "github-copilot",
    ]
    assert "big-pickle" in backend.FREE_PROVIDERS[0].detail


class TestAgentInstallStepSkip:
    def _step(self, monkeypatch, tmp_path, commands):
        from types import SimpleNamespace

        from dxrk.cli.install import AgentInstallStep
        from dxrk.models import AgentID
        from dxrk.system import PlatformProfile

        class FakeAdapter:
            agent = AgentID.PI
            supports_auto_install = True

            def detect(self, home_dir):
                return SimpleNamespace(installed=False)

            def install_command(self, profile):
                return commands

        class FakeReg:
            def get(self, aid):
                return FakeAdapter()

        monkeypatch.setattr("dxrk.agents.factory.create_registry", lambda: FakeReg())
        profile = PlatformProfile(os="linux", linux_distro="ubuntu", package_manager="apt")
        return AgentInstallStep("s", AgentID.PI, str(tmp_path), profile)

    def test_skips_when_lead_binary_missing(self, monkeypatch, tmp_path, caplog):
        import logging

        step = self._step(monkeypatch, tmp_path, [["dxrk-noexiste-bin-xyz", "install", "x"]])
        with caplog.at_level(logging.WARNING, logger="dxrk.cli.install"):
            assert step.run() is None
        assert "se omite la instalación" in caplog.text

    def test_runs_when_lead_binary_present(self, monkeypatch, tmp_path):
        import sys

        step = self._step(monkeypatch, tmp_path, [[sys.executable, "-c", "pass"]])
        assert step.run() is None
