# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os

import pytest

from dxrk.components import context7
from dxrk.models import AgentID, MCPStrategy


class FakeAdapter:
    def __init__(self, agent_id, supports_mcp=True, mcp_strategy=None, settings_path=None):
        self._agent = agent_id
        self._supports_mcp = supports_mcp
        self._mcp_strategy = mcp_strategy if mcp_strategy is not None else MCPStrategy.MCP_CONFIG_FILE
        self._settings_path = settings_path

    @property
    def agent(self):
        return self._agent

    @property
    def supports_mcp(self):
        return self._supports_mcp

    @property
    def mcp_strategy(self):
        return self._mcp_strategy

    def mcp_config_path(self, home_dir: str, server_name: str = "") -> str:
        return os.path.join(home_dir, "context7.json")

    def settings_path(self, home_dir: str) -> str:
        if self._settings_path is None:
            return ""
        return os.path.join(home_dir, self._settings_path)


class TestInject:
    def test_returns_empty_when_no_mcp_support(self, tmp_path):
        adapter = FakeAdapter(AgentID.CLAUDE_CODE, supports_mcp=False)
        result = context7.inject(str(tmp_path), adapter)
        assert result.Changed is False
        assert result.Files == []

    def test_inject_separate_mcp_file(self, tmp_path):
        # Ensure we use our FakeAdapter, not some other adapter
        adapter = FakeAdapter(AgentID.CLAUDE_CODE, mcp_strategy=MCPStrategy.SEPARATE_MCP_FILES)
        result = context7.inject(str(tmp_path), adapter)
        assert result.Changed is True
        mcp_file = tmp_path / "context7.json"
        assert mcp_file.exists()
        raw = mcp_file.read_text()
        print(f"\nDEBUG mcp_file content: {raw!r}")
        data = json.loads(raw)
        # With SEPARATE_MCP_FILES we write _DEFAULT_CONTEXT7_SERVER_JSON
        # which has top-level "command" key
        assert data.get("command") == "npx", f"Expected 'command' key in {list(data.keys())}"

    def test_inject_merge_into_settings_opencode(self, tmp_path):
        from dxrk.agents.opencode.adapter import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        result = context7.inject(str(tmp_path), adapter)
        assert result.Changed is True
        settings = tmp_path / ".config" / "opencode" / "settings.json"
        assert settings.exists()

    def test_inject_mcp_config_file_default(self, tmp_path):
        adapter = FakeAdapter(AgentID.CURSOR)
        result = context7.inject(str(tmp_path), adapter)
        assert result.Changed is True
        data = json.loads((tmp_path / "context7.json").read_text())
        assert data["mcpServers"]["context7"]["command"] == "npx"

    def test_toml_returns_empty(self, tmp_path):
        adapter = FakeAdapter(AgentID.CODEX, mcp_strategy=MCPStrategy.TOML_FILE)
        result = context7.inject(str(tmp_path), adapter)
        assert result.Changed is False

    def test_raises_on_unknown_strategy(self):
        adapter = FakeAdapter(AgentID.CLAUDE_CODE, mcp_strategy="UNKNOWN")
        with pytest.raises(ValueError):
            context7.inject("/tmp", adapter)

    def test_inject_vscode(self, tmp_path):
        adapter = FakeAdapter(AgentID.VSCODE_COPILOT)
        result = context7.inject(str(tmp_path), adapter)
        assert result.Changed is True
        data = json.loads((tmp_path / "context7.json").read_text())
        assert data["servers"]["context7"]["type"] == "http"

    def test_inject_antigravity(self, tmp_path):
        adapter = FakeAdapter(AgentID.ANTIGRAVITY)
        result = context7.inject(str(tmp_path), adapter)
        assert result.Changed is True
        data = json.loads((tmp_path / "context7.json").read_text())
        assert data["mcpServers"]["context7"]["serverUrl"]

    def test_inject_kimi(self, tmp_path):
        adapter = FakeAdapter(AgentID.KIMI)
        result = context7.inject(str(tmp_path), adapter)
        assert result.Changed is True
        data = json.loads((tmp_path / "context7.json").read_text())
        assert data["mcpServers"]["context7"]["transport"] == "http"


class TestOverlayAccessors:
    def test_default_server(self):
        data = json.loads(context7.default_context7_server_json())
        assert data["command"] == "npx"

    def test_default_overlay(self):
        data = json.loads(context7.default_context7_overlay_json())
        assert "context7" in data["mcpServers"]

    def test_opencode_overlay(self):
        data = json.loads(context7.opencode_context7_overlay_json())
        assert data["mcp"]["context7"]["type"] == "remote"

    def test_vscode_overlay(self):
        data = json.loads(context7.vscode_context7_overlay_json())
        assert data["servers"]["context7"]["type"] == "http"

    def test_antigravity_overlay(self):
        data = json.loads(context7.antigravity_context7_overlay_json())
        assert "serverUrl" in data["mcpServers"]["context7"]

    def test_kimi_overlay(self):
        data = json.loads(context7.kimi_context7_overlay_json())
        assert data["mcpServers"]["context7"]["transport"] == "http"
