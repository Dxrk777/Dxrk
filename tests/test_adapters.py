# SPDX-License-Identifier: MIT
from __future__ import annotations

import os

import pytest

from dxrk.agents.interface import DetectResult
from dxrk.agents.antigravity.adapter import AntigravityAdapter
from dxrk.agents.claude.adapter import ClaudeAdapter
from dxrk.agents.codex.adapter import CodexAdapter
from dxrk.agents.cursor.adapter import CursorAdapter
from dxrk.agents.gemini.adapter import GeminiCLIAdapter
from dxrk.agents.kilocode.adapter import KiloCodeAdapter
from dxrk.agents.kimi.adapter import KimiAdapter
from dxrk.agents.kiro.adapter import KiroAdapter
from dxrk.agents.openclaw.adapter import OpenClawAdapter
from dxrk.agents.opencode.adapter import OpenCodeAdapter
from dxrk.agents.pi.adapter import PiAdapter
from dxrk.agents.qwen.adapter import QwenCodeAdapter
from dxrk.agents.vscode.adapter import VSCodeAdapter
from dxrk.agents.windsurf.adapter import WindsurfAdapter
from dxrk.models import AgentID, MCPStrategy, SupportTier, SystemPromptStrategy

_ADAPTER_RECORDS = [
    (
        AntigravityAdapter,
        "antigravity",
        AgentID.ANTIGRAVITY,
        None,
        pytest.mark.antigravity,
    ),
    (ClaudeAdapter, "claude", AgentID.CLAUDE_CODE, "claude", pytest.mark.claude),
    (CodexAdapter, "codex", AgentID.CODEX, "codex", pytest.mark.codex),
    (CursorAdapter, "cursor", AgentID.CURSOR, None, pytest.mark.cursor),
    (GeminiCLIAdapter, "gemini", AgentID.GEMINI_CLI, "gemini", pytest.mark.gemini),
    (KiloCodeAdapter, "kilocode", AgentID.KILOCODE, "kilo", pytest.mark.kilocode),
    (KimiAdapter, "kimi", AgentID.KIMI, "kimi", pytest.mark.kimi),
    (KiroAdapter, "kiro", AgentID.KIRO_IDE, "kiro", pytest.mark.kiro),
    (OpenClawAdapter, "openclaw", AgentID.OPENCLAW, None, pytest.mark.openclaw),
    (OpenCodeAdapter, "opencode", AgentID.OPENCODE, "opencode", pytest.mark.opencode),
    (PiAdapter, "pi", AgentID.PI, "pi", pytest.mark.pi),
    (QwenCodeAdapter, "qwen", AgentID.QWEN_CODE, "qwen", pytest.mark.qwen),
    (VSCodeAdapter, "vscode", AgentID.VSCODE_COPILOT, "code", pytest.mark.vscode),
    (WindsurfAdapter, "windsurf", AgentID.WINDSURF, None, pytest.mark.windsurf),
]

ALL_ADAPTERS = [
    pytest.param(cls, name, agent, binary, marks=mark, id=name)
    for cls, name, agent, binary, mark in _ADAPTER_RECORDS
]

INSTALL_ADAPTERS = [
    pytest.param(ClaudeAdapter, "claude", marks=pytest.mark.claude, id="claude"),
    pytest.param(CodexAdapter, "codex", marks=pytest.mark.codex, id="codex"),
    pytest.param(GeminiCLIAdapter, "gemini", marks=pytest.mark.gemini, id="gemini"),
    pytest.param(
        KiloCodeAdapter, "kilocode", marks=pytest.mark.kilocode, id="kilocode"
    ),
    pytest.param(KimiAdapter, "kimi", marks=pytest.mark.kimi, id="kimi"),
    pytest.param(PiAdapter, "pi", marks=pytest.mark.pi, id="pi"),
    pytest.param(QwenCodeAdapter, "qwen", marks=pytest.mark.qwen, id="qwen"),
]


class TestAdapterProperties:
    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_agent(self, adapter_class, name, agent_id, binary_name):
        adapter = adapter_class()
        assert adapter.agent == agent_id

    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_tier(self, adapter_class, name, agent_id, binary_name):
        adapter = adapter_class()
        assert adapter.tier == SupportTier.FULL

    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_global_config_dir(
        self, adapter_class, name, agent_id, binary_name, tmp_path
    ):
        adapter = adapter_class()
        result = adapter.global_config_dir(str(tmp_path))
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_system_prompt_dir(
        self, adapter_class, name, agent_id, binary_name, tmp_path
    ):
        adapter = adapter_class()
        result = adapter.system_prompt_dir(str(tmp_path))
        assert isinstance(result, str)

    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_system_prompt_file(
        self, adapter_class, name, agent_id, binary_name, tmp_path
    ):
        adapter = adapter_class()
        result = adapter.system_prompt_file(str(tmp_path))
        assert isinstance(result, str)

    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_skills_dir(self, adapter_class, name, agent_id, binary_name, tmp_path):
        adapter = adapter_class()
        result = adapter.skills_dir(str(tmp_path))
        assert isinstance(result, str)

    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_settings_path(self, adapter_class, name, agent_id, binary_name, tmp_path):
        adapter = adapter_class()
        result = adapter.settings_path(str(tmp_path))
        assert isinstance(result, str)

    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_mcp_config_path(
        self, adapter_class, name, agent_id, binary_name, tmp_path
    ):
        adapter = adapter_class()
        result = adapter.mcp_config_path(str(tmp_path), server_name="test-server")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_system_prompt_strategy(self, adapter_class, name, agent_id, binary_name):
        adapter = adapter_class()
        assert isinstance(adapter.system_prompt_strategy, SystemPromptStrategy)

    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_mcp_strategy(self, adapter_class, name, agent_id, binary_name):
        adapter = adapter_class()
        assert isinstance(adapter.mcp_strategy, MCPStrategy)

    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_supports_properties(self, adapter_class, name, agent_id, binary_name):
        adapter = adapter_class()
        assert isinstance(adapter.supports_auto_install, bool)
        assert isinstance(adapter.supports_output_styles, bool)
        assert isinstance(adapter.supports_slash_commands, bool)
        assert isinstance(adapter.supports_sub_agents, bool)
        assert isinstance(adapter.supports_skills, bool)
        assert isinstance(adapter.supports_system_prompt, bool)
        assert isinstance(adapter.supports_mcp, bool)


class TestAdapterDetect:
    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_detect(
        self, adapter_class, name, agent_id, binary_name, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/" + x)
        adapter = adapter_class()
        home = str(tmp_path)
        config_dir = adapter.global_config_dir(home)
        os.makedirs(config_dir, exist_ok=True)
        result = adapter.detect(home)
        assert isinstance(result, DetectResult)
        assert result.config_found is True
        assert result.config_path == config_dir
        if binary_name is not None:
            assert result.installed is True
            assert result.binary_path == "/usr/bin/" + binary_name
        else:
            assert result.binary_path == ""


class TestAdapterDetectConfigNotFound:
    @pytest.mark.parametrize("adapter_class,name,agent_id,binary_name", ALL_ADAPTERS)
    def test_detect_config_not_found(
        self, adapter_class, name, agent_id, binary_name, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/" + x)
        adapter = adapter_class()
        home = str(tmp_path)
        result = adapter.detect(home)
        assert isinstance(result, DetectResult)
        assert result.config_found is False


class TestInstallCommand:
    @pytest.mark.parametrize("adapter_class,name", INSTALL_ADAPTERS)
    def test_returns_list_of_lists(self, adapter_class, name):
        adapter = adapter_class()
        cmds = adapter.install_command("default")
        assert isinstance(cmds, list)
        assert len(cmds) > 0
        for cmd in cmds:
            assert isinstance(cmd, list)
            assert len(cmd) > 0
            assert isinstance(cmd[0], str)
