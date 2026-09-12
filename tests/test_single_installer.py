# SPDX-License-Identifier: MIT
"""Tests del instalador único (estilo opencode): chat directo + rankings."""

from __future__ import annotations

import os


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


class TestLaunchSingleInstaller:
    """_launch_single_installer usa el run_install REAL y abre el chat."""

    def test_runs_real_install_then_opens_chat(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        import dxrk.__main__ as main_mod
        from dxrk.system import DetectionResult

        calls: dict = {}

        def fake_detect():
            calls["detect"] = True
            return DetectionResult()

        def fake_run_install(args, detection):
            calls["run_install"] = (args, detection)
            return SimpleNamespace(error="")

        def fake_launch_tui(version, initial_screen="welcome"):
            calls["tui"] = (version, initial_screen)

        monkeypatch.setattr("dxrk.system.detect", fake_detect)
        monkeypatch.setattr("dxrk.cli.install.run_install", fake_run_install)
        monkeypatch.setattr(main_mod, "_launch_tui", fake_launch_tui)
        monkeypatch.setenv("HOME", str(tmp_path))

        main_mod._launch_single_installer("9.9.9")

        assert calls.get("detect") is True
        assert calls["run_install"][0] == []
        assert isinstance(calls["run_install"][1], DetectionResult)
        assert calls["tui"] == ("9.9.9", "chat")

    def test_skips_install_when_already_installed(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        import dxrk.__main__ as main_mod
        from dxrk.state import InstallState
        from dxrk.state import write as state_write
        from dxrk.system import DetectionResult

        state_write(str(tmp_path), InstallState(installed_agents=["opencode"]))
        calls: dict = {}

        def fake_run_install(args, detection):
            calls["run_install"] = True
            return SimpleNamespace(error="")

        def fake_launch_tui(version, initial_screen="welcome"):
            calls["tui"] = (version, initial_screen)

        monkeypatch.setattr("dxrk.system.detect", lambda: DetectionResult())
        monkeypatch.setattr("dxrk.cli.install.run_install", fake_run_install)
        monkeypatch.setattr(main_mod, "_launch_tui", fake_launch_tui)
        monkeypatch.setenv("HOME", str(tmp_path))

        main_mod._launch_single_installer("9.9.9")

        assert "run_install" not in calls
        assert calls["tui"] == ("9.9.9", "chat")


class TestBackgroundAgentsPlugin:
    """sdd inject despliega plugins/background-agents.ts para opencode."""

    def test_writes_background_agents_ts(self, tmp_path):
        from dxrk.agents.opencode.adapter import OpenCodeAdapter
        from dxrk.components import sdd
        from dxrk.models import SDDModeID

        home = str(tmp_path)
        result = sdd.inject(
            home,
            OpenCodeAdapter(),
            sdd_mode=SDDModeID.SINGLE,
            options=None,
        )
        dest = os.path.join(home, ".config", "opencode", "plugins", "background-agents.ts")
        assert os.path.isfile(dest)
        with open(os.path.join("dxrk", "assets", "opencode", "plugins", "background-agents.ts"), encoding="utf-8") as f:
            asset = f.read()
        with open(dest, encoding="utf-8") as f:
            assert f.read() == asset
        assert result.Changed is True
        assert dest in result.Files


class TestVerifyContractMatchesInjects:
    def test_memory_lists_dxrk_memory_json_for_separate(self, tmp_path):
        from dxrk.agents.claude.adapter import ClaudeAdapter
        from dxrk.cli.install import _component_paths
        from dxrk.models import ComponentID, Selection

        paths = _component_paths(str(tmp_path), Selection(), [ClaudeAdapter()], ComponentID.DXRK_MEMORY)
        assert any(p.endswith("DXRK_MEMORY.json") for p in paths)
        assert not any(p.endswith("mcp/memory.json") for p in paths)

    def test_permissions_skips_unmapped_agents(self, tmp_path):
        from dxrk.agents.cursor.adapter import CursorAdapter
        from dxrk.cli.install import _component_paths
        from dxrk.models import ComponentID, Selection

        paths = _component_paths(str(tmp_path), Selection(), [CursorAdapter()], ComponentID.PERMISSIONS)
        assert paths == []

    def test_permissions_lists_mapped_agents(self, tmp_path):
        from dxrk.agents.claude.adapter import ClaudeAdapter
        from dxrk.cli.install import _component_paths
        from dxrk.models import ComponentID, Selection

        paths = _component_paths(str(tmp_path), Selection(), [ClaudeAdapter()], ComponentID.PERMISSIONS)
        assert any(p.endswith("settings.json") for p in paths)

    def test_context7_merge_lists_settings_only(self, tmp_path):
        from dxrk.agents.opencode.adapter import OpenCodeAdapter
        from dxrk.cli.install import _component_paths
        from dxrk.models import ComponentID, Selection

        paths = _component_paths(str(tmp_path), Selection(), [OpenCodeAdapter()], ComponentID.CONTEXT7)
        assert any(p.endswith("settings.json") for p in paths)
        assert not any(p.endswith("mcp.json") for p in paths)

    def test_verify_file_exists_passes_for_dirs(self, tmp_path):
        from dxrk.cli.run import _verify_file_exists

        d = tmp_path / "commands"
        d.mkdir()
        assert _verify_file_exists(str(d))() is None
        assert _verify_file_exists(str(tmp_path / "missing"))() is not None
