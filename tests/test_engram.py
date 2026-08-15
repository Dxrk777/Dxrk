# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os

from dxrk.components import engram
from dxrk.models import AgentID

import pytest


class TestSetupMode:
    def test_parse_setup_mode(self):
        assert engram.parse_setup_mode("") == "supported"
        assert engram.parse_setup_mode("off") == "off"
        assert engram.parse_setup_mode("opencode") == "opencode"
        assert engram.parse_setup_mode("supported") == "supported"
        assert engram.parse_setup_mode("anything") == "supported"

    def test_parse_setup_strict(self):
        assert engram.parse_setup_strict("true") is True
        assert engram.parse_setup_strict("false") is False
        assert engram.parse_setup_strict("") is False

    def test_parse_setup_strict_numeric(self):
        assert engram.parse_setup_strict("1") is True
        assert engram.parse_setup_strict("0") is False

    def test_setup_agent_slug(self):
        slug, ok = engram.setup_agent_slug(AgentID.CLAUDE_CODE)
        assert slug == "claude-code"
        assert ok is True

    def test_setup_agent_slug_kiro(self):
        slug, ok = engram.setup_agent_slug(AgentID.KIRO_IDE)
        assert ok is False

    def test_setup_agent_slug_antigravity(self):
        slug, ok = engram.setup_agent_slug(AgentID.ANTIGRAVITY)
        assert slug == "gemini-cli"
        assert ok is True

    def test_should_attempt_setup_enabled(self):
        assert engram.should_attempt_setup("supported", AgentID.CLAUDE_CODE) is True

    def test_should_attempt_setup_off(self):
        assert engram.should_attempt_setup("off", AgentID.CLAUDE_CODE) is False

    def test_should_attempt_setup_opencode_only(self):
        assert engram.should_attempt_setup("opencode", AgentID.CLAUDE_CODE) is False
        assert engram.should_attempt_setup("opencode", AgentID.OPENCODE) is True

    def test_should_attempt_setup_unsupported_agent(self):
        from dxrk.models import AgentID as A

        assert engram.should_attempt_setup("supported", A.KIRO_IDE) is False


class TestCommandResolution:
    def test_is_engram_command(self):
        from dxrk.components.engram import _is_DXRK_MEMORY_command

        assert _is_DXRK_MEMORY_command("DXRK_MEMORY") is True
        assert _is_DXRK_MEMORY_command("/usr/local/bin/DXRK_MEMORY") is True
        assert _is_DXRK_MEMORY_command("node") is False

    def test_is_absolute_engram_path(self):
        from dxrk.components.engram import _is_absolute_DXRK_MEMORY_path

        assert _is_absolute_DXRK_MEMORY_path("/usr/local/bin/DXRK_MEMORY") is True
        assert _is_absolute_DXRK_MEMORY_path("DXRK_MEMORY") is False

    def test_is_versioned_homebrew_cellar_path(self):
        from dxrk.components.engram import _is_versioned_homebrew_cellar_path

        assert (
            _is_versioned_homebrew_cellar_path(
                "/opt/homebrew/Cellar/DXRK_MEMORY/1.2.3/bin/DXRK_MEMORY"
            )
            is True
        )
        assert (
            _is_versioned_homebrew_cellar_path("/opt/homebrew/bin/DXRK_MEMORY") is False
        )

    def test_is_stable_homebrew_engram_path(self):
        from dxrk.components.engram import _is_stable_homebrew_DXRK_MEMORY_path

        assert (
            _is_stable_homebrew_DXRK_MEMORY_path("/opt/homebrew/bin/DXRK_MEMORY")
            is True
        )
        # Both Apple Silicon and Intel Homebrew prefixes are stable
        assert (
            _is_stable_homebrew_DXRK_MEMORY_path("/usr/local/bin/DXRK_MEMORY") is True
        )

    def test_executable_from_command_value(self):
        from dxrk.components.engram import _executable_from_command_value

        cmd, ok = _executable_from_command_value("engram")
        assert ok is True
        assert cmd == "engram"

        cmd2, ok2 = _executable_from_command_value(["npx", "-y", "engram"])
        assert ok2 is True
        assert cmd2 == "npx"

        cmd3, ok3 = _executable_from_command_value("")
        assert ok3 is False

    def test_is_standard_agent(self):
        from dxrk.components.engram import _is_standard_agent

        assert _is_standard_agent(AgentID.CLAUDE_CODE) is True
        assert _is_standard_agent(AgentID.OPENCODE) is True
        assert _is_standard_agent(AgentID.PI) is False


class TestEngramServerJson:
    def test_engram_server_json(self):
        data = json.loads(engram._DXRK_MEMORY_server_json_with_cmd("DXRK_MEMORY"))
        assert data["command"] == "DXRK_MEMORY"
        assert data["args"] == ["mcp", "--tools=agent"]

    def test_engram_server_json_with_cmd(self):
        data = json.loads(
            engram._DXRK_MEMORY_server_json_with_cmd("/custom/path/DXRK_MEMORY")
        )
        assert data["command"] == "/custom/path/DXRK_MEMORY"


class TestInject:
    def test_inject_separate_mcp_claude(self, tmp_path):
        from dxrk.agents.claude.adapter import ClaudeAdapter

        adapter = ClaudeAdapter()
        result = engram.inject(str(tmp_path), adapter)
        assert result.Changed is True
        mcp_dir = tmp_path / ".claude" / "mcp"
        assert mcp_dir.exists()
        mcp_file = mcp_dir / "DXRK_MEMORY.json"
        assert mcp_file.exists()
        data = json.loads(mcp_file.read_text())
        assert data["command"] == "DXRK_MEMORY"

    def test_inject_opencode(self, tmp_path):
        from dxrk.agents.opencode.adapter import OpenCodeAdapter

        adapter = OpenCodeAdapter()
        result = engram.inject(str(tmp_path), adapter)
        assert result.Changed is True
        settings = tmp_path / ".config" / "opencode" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "mcp" in data
        assert "DXRK_MEMORY" in data["mcp"]


class TestLookPath:
    def test_set_look_path_for_test(self, tmp_path):
        mock = lambda x: (
            str(tmp_path / "bin" / "DXRK_MEMORY") if x == "DXRK_MEMORY" else None
        )
        orig = engram.set_look_path_for_test(mock)
        assert callable(orig)
        engram.set_look_path_for_test(orig)
