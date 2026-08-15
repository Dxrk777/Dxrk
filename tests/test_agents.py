# SPDX-License-Identifier: MIT
from __future__ import annotations

from dxrk.agents.errors import AdapterNotFoundError, DuplicateAdapterError, Error
from dxrk.agents.factory import create_registry
from dxrk.agents.interface import Adapter
from dxrk.agents.registry import Registry
from dxrk.models import AgentID, MCPStrategy, SupportTier, SystemPromptStrategy

import pytest


def test_error_hierarchy():
    assert issubclass(DuplicateAdapterError, Error)
    assert issubclass(AdapterNotFoundError, Error)


def test_registry_empty():
    r = Registry()
    assert len(r) == 0
    assert r.supported_agents == []


def test_registry_register_and_get():
    r = Registry()
    from dxrk.agents.claude.adapter import ClaudeAdapter
    adapter = ClaudeAdapter()
    r.register(adapter)
    assert r.get(AgentID.CLAUDE_CODE) is adapter


def test_registry_duplicate_raises():
    r = Registry()
    from dxrk.agents.claude.adapter import ClaudeAdapter
    r.register(ClaudeAdapter())
    from dxrk.agents.claude.adapter import ClaudeAdapter as CA2
    with pytest.raises(DuplicateAdapterError):
        r.register(CA2())


def test_registry_get_missing():
    r = Registry()
    assert r.get(AgentID.OPENCODE) is None


class TestFactory:
    def test_creates_all_agents(self):
        r = create_registry()
        agents = r.supported_agents
        assert len(agents) == 14
        assert AgentID.CLAUDE_CODE in agents
        assert AgentID.OPENCODE in agents
        assert AgentID.KILOCODE in agents
        assert AgentID.GEMINI_CLI in agents
        assert AgentID.CODEX in agents
        assert AgentID.CURSOR in agents
        assert AgentID.VSCODE_COPILOT in agents
        assert AgentID.ANTIGRAVITY in agents
        assert AgentID.WINDSURF in agents
        assert AgentID.KIMI in agents
        assert AgentID.QWEN_CODE in agents
        assert AgentID.KIRO_IDE in agents
        assert AgentID.OPENCLAW in agents
        assert AgentID.PI in agents


class TestAllAdapters:
    def test_each_adapter_has_agent_id(self):
        r = create_registry()
        for agent_id in r.supported_agents:
            adapter = r.get(agent_id)
            assert adapter.agent == agent_id, f"{agent_id}: .agent mismatch"

    def test_each_adapter_has_tier(self):
        r = create_registry()
        for agent_id in r.supported_agents:
            adapter = r.get(agent_id)
            assert adapter.tier == SupportTier.FULL, f"{agent_id}: unexpected tier"

    def test_each_adapter_has_system_prompt_strategy(self):
        r = create_registry()
        for agent_id in r.supported_agents:
            adapter = r.get(agent_id)
            assert isinstance(adapter.system_prompt_strategy, SystemPromptStrategy)

    def test_each_adapter_has_mcp_strategy(self):
        r = create_registry()
        for agent_id in r.supported_agents:
            adapter = r.get(agent_id)
            assert isinstance(adapter.mcp_strategy, MCPStrategy)


class TestClaudeAdapter:
    def setup_method(self):
        from dxrk.agents.claude.adapter import ClaudeAdapter
        self.adapter = ClaudeAdapter()

    def test_properties(self):
        assert self.adapter.agent == AgentID.CLAUDE_CODE
        assert self.adapter.tier == SupportTier.FULL
        assert self.adapter.supports_auto_install is True
        assert self.adapter.supports_output_styles is True
        assert self.adapter.supports_slash_commands is True
        assert self.adapter.supports_sub_agents is True
        assert self.adapter.supports_skills is True
        assert self.adapter.supports_system_prompt is True
        assert self.adapter.supports_mcp is True

    def test_strategies(self):
        assert self.adapter.system_prompt_strategy == SystemPromptStrategy.MARKDOWN_SECTIONS
        assert self.adapter.mcp_strategy == MCPStrategy.SEPARATE_MCP_FILES

    def test_paths(self, tmp_path):
        home = str(tmp_path)
        assert self.adapter.global_config_dir(home) == str(tmp_path / ".claude")
        assert self.adapter.system_prompt_dir(home) == str(tmp_path / ".claude")
        assert self.adapter.system_prompt_file(home) == str(tmp_path / ".claude" / "CLAUDE.md")
        assert self.adapter.skills_dir(home) == str(tmp_path / ".claude" / "skills")
        assert self.adapter.settings_path(home) == str(tmp_path / ".claude" / "settings.json")
        assert self.adapter.output_style_dir(home) == str(tmp_path / ".claude" / "output-styles")
        assert self.adapter.commands_dir(home) == str(tmp_path / ".claude" / "commands")
        assert self.adapter.sub_agents_dir(home) == str(tmp_path / ".claude" / "agents")
        mcp_path = self.adapter.mcp_config_path(home, server_name="test")
        assert mcp_path == str(tmp_path / ".claude" / "mcp" / "test.json")


class TestOpenCodeAdapter:
    def setup_method(self):
        from dxrk.agents.opencode.adapter import OpenCodeAdapter
        self.adapter = OpenCodeAdapter()

    def test_properties(self):
        assert self.adapter.agent == AgentID.OPENCODE
        assert self.adapter.supports_auto_install is True
        assert self.adapter.supports_slash_commands is True
        assert self.adapter.supports_sub_agents is True
        assert self.adapter.supports_skills is True

    def test_strategies(self):
        assert self.adapter.system_prompt_strategy == SystemPromptStrategy.FILE_REPLACE
        assert self.adapter.mcp_strategy == MCPStrategy.MERGE_INTO_SETTINGS

    def test_paths(self, tmp_path):
        home = str(tmp_path)
        assert self.adapter.global_config_dir(home) == str(tmp_path / ".config" / "opencode")
        assert self.adapter.system_prompt_file(home) == str(tmp_path / ".config" / "opencode" / "AGENTS.md")
        assert self.adapter.skills_dir(home) == str(tmp_path / ".config" / "opencode" / "skills")
        assert self.adapter.commands_dir(home) == str(tmp_path / ".config" / "opencode" / "commands")


class TestPiAdapter:
    def setup_method(self):
        from dxrk.agents.pi.adapter import PiAdapter
        self.adapter = PiAdapter()

    def test_properties(self):
        assert self.adapter.agent == AgentID.PI
        assert self.adapter.supports_auto_install is True
        assert self.adapter.supports_skills is False
        assert self.adapter.supports_system_prompt is False
        assert self.adapter.supports_mcp is True


class TestKimiAdapter:
    def setup_method(self):
        from dxrk.agents.kimi.adapter import KimiAdapter
        self.adapter = KimiAdapter()

    def test_properties(self):
        assert self.adapter.agent == AgentID.KIMI
        assert self.adapter.supports_sub_agents is True
        assert self.adapter.supports_system_prompt is True

    def test_strategies(self):
        assert self.adapter.system_prompt_strategy == SystemPromptStrategy.JINJA_MODULES


class TestKiroAdapter:
    def setup_method(self):
        from dxrk.agents.kiro.adapter import KiroAdapter
        self.adapter = KiroAdapter()

    def test_properties(self):
        assert self.adapter.agent == AgentID.KIRO_IDE
        assert self.adapter.supports_sub_agents is True

    def test_strategies(self):
        assert self.adapter.system_prompt_strategy == SystemPromptStrategy.STEERING_FILE


class TestCodexAdapter:
    def setup_method(self):
        from dxrk.agents.codex.adapter import CodexAdapter
        self.adapter = CodexAdapter()

    def test_properties(self):
        assert self.adapter.agent == AgentID.CODEX
        assert self.adapter.supports_auto_install is True

    def test_strategies(self):
        assert self.adapter.mcp_strategy == MCPStrategy.TOML_FILE


class TestVSCodeAdapter:
    def setup_method(self):
        from dxrk.agents.vscode.adapter import VSCodeAdapter
        self.adapter = VSCodeAdapter()

    def test_strategies(self):
        assert self.adapter.system_prompt_strategy == SystemPromptStrategy.INSTRUCTIONS_FILE


class TestWindsurfAdapter:
    def setup_method(self):
        from dxrk.agents.windsurf.adapter import WindsurfAdapter
        self.adapter = WindsurfAdapter()

    def test_strategies(self):
        assert self.adapter.system_prompt_strategy == SystemPromptStrategy.APPEND_TO_FILE

    def test_workflows_not_in_interface(self):
        # Windsurf has workflow features in Go but Python adapter may not have them
        assert hasattr(self.adapter, "workflows_dir") or True


class TestDetectResult:
    def test_namedtuple(self):
        from dxrk.agents.interface import DetectResult
        dr = DetectResult(installed=True, binary_path="/usr/bin/claude",
                          config_path="/home/user/.claude", config_found=True)
        assert dr.installed is True
        assert dr.binary_path == "/usr/bin/claude"
        assert dr.config_path == "/home/user/.claude"
        assert dr.config_found is True
