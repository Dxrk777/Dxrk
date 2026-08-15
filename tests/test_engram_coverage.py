# SPDX-License-Identifier: MIT
"""Coverage gap tests for engram.py — targets uncovered lines.

Sections: Config/Setup, Injection, Download, Verify, Install command.
"""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dxrk.components import engram
from dxrk.models import AgentID, MCPStrategy, SystemPromptStrategy

# Source bug fixed: line 434 now calls _DXRK_MEMORY_install_dir directly.
# Create the alias so monkeypatch can still target _DXRK_MEMORY_install_dir_fn.
if not hasattr(engram, "_DXRK_MEMORY_install_dir_fn"):
    engram._DXRK_MEMORY_install_dir_fn = engram._DXRK_MEMORY_install_dir


# ─── Fake adapter for inject tests ──────────────────────────────────────────


class FakeAdapter:
    def __init__(
        self,
        agent=AgentID.OPENCODE,
        supports_mcp=True,
        mcp_strategy=MCPStrategy.MERGE_INTO_SETTINGS,
        supports_system_prompt=False,
        system_prompt_strategy=SystemPromptStrategy.MARKDOWN_SECTIONS,
        mcp_config_path=None,
        settings_path=None,
        global_config_dir=None,
    ):

        self._agent = agent
        self._supports_mcp = supports_mcp
        self._mcp_strategy = mcp_strategy
        self._supports_system_prompt = supports_system_prompt
        self._system_prompt_strategy = system_prompt_strategy
        self._mcp_config_path = mcp_config_path
        self._settings_path = settings_path
        self._global_config_dir = global_config_dir

    @property
    def agent(self):
        return self._agent

    @property
    def supports_mcp(self):
        return self._supports_mcp

    @property
    def mcp_strategy(self):
        return self._mcp_strategy

    @property
    def supports_system_prompt(self):
        return self._supports_system_prompt

    @property
    def system_prompt_strategy(self):
        return self._system_prompt_strategy

    def mcp_config_path(self, home_dir, server_name=""):
        if self._mcp_config_path:
            return self._mcp_config_path
        return ""

    def settings_path(self, home_dir):
        if self._settings_path is not None:
            return self._settings_path
        return ""

    def global_config_dir(self, home_dir):
        if self._global_config_dir:
            return self._global_config_dir
        return os.path.join(home_dir, ".config", "opencode")

    def system_prompt_file(self, home_dir):
        return os.path.join(home_dir, "SYSTEM.md")


# ═══════════════════════════════════════════════════════════════════════════
# 1. Config / Setup
# ═══════════════════════════════════════════════════════════════════════════


class TestParseSetupMode:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("off", "off"),
            ("OPENCODE", "opencode"),
            ("", "supported"),
            ("supported", "supported"),
            ("random", "supported"),
        ],
    )
    def test_parse_setup_mode(self, value, expected):
        assert engram.parse_setup_mode(value) == expected


class TestParseSetupStrict:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("true", True),
            ("1", True),
            ("false", False),
            ("", False),
            ("0", False),
        ],
    )
    def test_parse_setup_strict(self, value, expected):
        assert engram.parse_setup_strict(value) is expected


class TestSetupAgentSlug:
    @pytest.mark.parametrize(
        ("agent", "expected_slug", "expected_ok"),
        [
            (AgentID.WINDSURF, "windsurf", True),
            (AgentID.CODEX, "codex", True),
            (AgentID.GEMINI_CLI, "gemini-cli", True),
            (AgentID.ANTIGRAVITY, "gemini-cli", True),
            (AgentID.OPENCODE, "opencode", True),
            (AgentID.KILOCODE, "kilocode", True),
            (AgentID.CLAUDE_CODE, "claude-code", True),
        ],
    )
    def test_known(self, agent, expected_slug, expected_ok):
        slug, ok = engram.setup_agent_slug(agent)
        assert slug == expected_slug
        assert ok is expected_ok

    def test_unknown(self):
        slug, ok = engram.setup_agent_slug(AgentID.KIRO_IDE)
        assert slug == ""
        assert ok is False


class TestShouldAttemptSetup:
    @pytest.mark.parametrize(
        ("mode", "agent", "expected"),
        [
            ("off", AgentID.OPENCODE, False),
            ("opencode", AgentID.OPENCODE, True),
            ("opencode", AgentID.KILOCODE, False),
            ("supported", AgentID.OPENCODE, True),
            ("supported", AgentID.KILOCODE, True),
            ("supported", AgentID.KIRO_IDE, False),
            ("off", AgentID.KIRO_IDE, False),
        ],
    )
    def test_should_attempt_setup(self, mode, agent, expected):
        assert engram.should_attempt_setup(mode, agent) is expected


# ═══════════════════════════════════════════════════════════════════════════
# 2. Injection — uncovered code paths
# ═══════════════════════════════════════════════════════════════════════════


class TestEngramServerJson:
    def test_DXRK_MEMORY_server_json_with_mock_look_path(self):
        mock = lambda x: "/mock/bin/DXRK_MEMORY" if x == "DXRK_MEMORY" else None
        orig = engram.set_look_path_for_test(mock)
        try:
            result = engram._DXRK_MEMORY_server_json()
            data = json.loads(result)
            assert data["command"] == "/mock/bin/DXRK_MEMORY"
            assert data["args"] == ["mcp", "--tools=agent"]
        finally:
            engram.set_look_path_for_test(orig)

    def test_DXRK_MEMORY_server_json_fallback(self):
        mock = lambda x: None
        orig = engram.set_look_path_for_test(mock)
        try:
            result = engram._DXRK_MEMORY_server_json()
            data = json.loads(result)
            assert data["command"] == "DXRK_MEMORY"
        finally:
            engram.set_look_path_for_test(orig)


class TestVSCodeEngramOverlayJson:
    def test_vs_code_DXRK_MEMORY_overlay_json(self):
        result = engram._vs_code_DXRK_MEMORY_overlay_json("/usr/bin/DXRK_MEMORY")
        data = json.loads(result)
        assert "servers" in data
        assert "DXRK_MEMORY" in data["servers"]
        assert data["servers"]["DXRK_MEMORY"]["command"] == "/usr/bin/DXRK_MEMORY"
        assert data["servers"]["DXRK_MEMORY"]["args"] == ["mcp", "--tools=agent"]


class TestInjectMCPConfigFile:
    def test_vscode_copilot(self, tmp_path):
        mcp_file = tmp_path / "mcp.json"
        mcp_file.write_text("{}")
        adapter = FakeAdapter(
            agent=AgentID.VSCODE_COPILOT,
            mcp_strategy=MCPStrategy.MCP_CONFIG_FILE,
            mcp_config_path=str(mcp_file),
        )
        result = engram.inject(str(tmp_path), adapter)
        assert result.Changed is True
        data = json.loads(mcp_file.read_text())
        assert "servers" in data
        assert "DXRK_MEMORY" in data["servers"]

    def test_antigravity_bootstrap(self, tmp_path):
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir(parents=True)
        ag_settings = gemini_dir / "antigravity" / "settings.json"
        mcp_file = tmp_path / "mcp_config.json"
        mcp_file.write_text("{}")
        adapter = FakeAdapter(
            agent=AgentID.ANTIGRAVITY,
            mcp_strategy=MCPStrategy.MCP_CONFIG_FILE,
            mcp_config_path=str(mcp_file),
            settings_path=str(ag_settings),
        )
        result = engram.inject(str(tmp_path), adapter)
        assert result.Changed is True
        assert ag_settings.exists()

    def test_antigravity_existing_settings(self, tmp_path):
        ag_settings = tmp_path / ".gemini" / "antigravity" / "settings.json"
        ag_settings.parent.mkdir(parents=True)
        ag_settings.write_text('{"key": "value"}')
        mcp_file = tmp_path / "mcp_config.json"
        mcp_file.write_text("{}")
        adapter = FakeAdapter(
            agent=AgentID.ANTIGRAVITY,
            mcp_strategy=MCPStrategy.MCP_CONFIG_FILE,
            mcp_config_path=str(mcp_file),
            settings_path=str(ag_settings),
        )
        result = engram.inject(str(tmp_path), adapter)
        assert result.Changed is True
        assert json.loads(ag_settings.read_text()) == {"key": "value"}


class TestInjectTOMLFile:
    def test_codex_toml(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "dxrk.components.assets.must_read",
            lambda path: f"# {path} content\n" if "codex" in path else "",
        )
        monkeypatch.setattr(
            "dxrk.components.assets.read",
            lambda path, root=None: f"# {path}" if "codex" in path else None,
        )
        config_path = tmp_path / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("")
        adapter = FakeAdapter(
            agent=AgentID.CODEX,
            mcp_strategy=MCPStrategy.TOML_FILE,
            mcp_config_path=str(config_path),
        )
        result = engram.inject(str(tmp_path), adapter)
        assert result.Changed is True
        text = config_path.read_text()
        assert "DXRK_MEMORY" in text


class TestInjectSystemPrompt:
    def test_jinja_modules(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "dxrk.components.assets.must_read",
            lambda path: "# protocol content",
        )
        adapter = FakeAdapter(
            agent=AgentID.OPENCODE,
            supports_system_prompt=True,
            system_prompt_strategy=SystemPromptStrategy.JINJA_MODULES,
            global_config_dir=str(tmp_path / ".config" / "opencode"),
        )
        result = engram.inject(str(tmp_path), adapter)
        assert result.Changed is True
        module_path = tmp_path / ".config" / "opencode" / "DXRK_MEMORY-protocol.md"
        assert module_path.exists()

    def test_jinja_modules_with_bootstrap(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "dxrk.components.assets.must_read",
            lambda path: "# protocol content",
        )
        bootstrapped = False

        def fake_bootstrap(home_dir):
            nonlocal bootstrapped
            bootstrapped = True

        adapter = FakeAdapter(
            agent=AgentID.OPENCODE,
            supports_system_prompt=True,
            system_prompt_strategy=SystemPromptStrategy.JINJA_MODULES,
            global_config_dir=str(tmp_path / ".config" / "opencode"),
        )
        adapter.bootstrap_template = fake_bootstrap
        result = engram.inject(str(tmp_path), adapter)
        assert result.Changed is True
        assert bootstrapped is True

    def test_fallback_branch(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "dxrk.components.assets.must_read",
            lambda path: "# protocol content",
        )
        prompt_file = tmp_path / "SYSTEM.md"
        adapter = FakeAdapter(
            agent=AgentID.OPENCODE,
            supports_system_prompt=True,
            system_prompt_strategy=SystemPromptStrategy.FILE_REPLACE,
        )
        result = engram.inject(str(tmp_path), adapter)
        assert result.Changed is True
        assert prompt_file.exists()

    def test_no_change_when_no_mcp(self, tmp_path):
        adapter = FakeAdapter(agent=AgentID.OPENCODE, supports_mcp=False)
        result = engram.inject(str(tmp_path), adapter)
        assert result.Changed is False
        assert result.Files == []


class TestEnsureAntigravitySettings:
    def test_settings_path_none(self, tmp_path):
        adapter = FakeAdapter(agent=AgentID.ANTIGRAVITY, settings_path=None)
        result = engram._ensure_antigravity_settings(str(tmp_path), adapter)
        assert result.Changed is False
        assert result.Path == ""

    def test_settings_path_exists(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text('{"a": 1}')
        adapter = FakeAdapter(agent=AgentID.ANTIGRAVITY, settings_path=str(settings))
        result = engram._ensure_antigravity_settings(str(tmp_path), adapter)
        assert result.Changed is False
        assert result.Path == str(settings)

    def test_settings_path_not_exists_creates_from_source(self, tmp_path):
        settings = tmp_path / "settings.json"
        source_dir = tmp_path / ".gemini"
        source_dir.mkdir()
        source = source_dir / "settings.json"
        source.write_text('{"b": 2}')
        adapter = FakeAdapter(agent=AgentID.ANTIGRAVITY, settings_path=str(settings))
        result = engram._ensure_antigravity_settings(str(tmp_path), adapter)
        assert result.Changed is True
        assert json.loads(settings.read_text()) == {"b": 2}

    def test_settings_path_not_exists_source_missing(self, tmp_path):
        settings = tmp_path / "settings.json"
        adapter = FakeAdapter(agent=AgentID.ANTIGRAVITY, settings_path=str(settings))
        result = engram._ensure_antigravity_settings(str(tmp_path), adapter)
        assert result.Changed is True
        assert json.loads(settings.read_text()) == {}


class TestWriteCodexInstructionFiles:
    def test_writes_files(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "dxrk.components.engram.must_read",
            lambda path: f"# content of {path}",
        )
        instr, compact, err = engram._write_codex_instruction_files(str(tmp_path))
        assert err is None
        assert "DXRK_MEMORY-instructions.md" in instr
        assert "DXRK_MEMORY-compact-prompt.md" in compact
        assert Path(instr).exists()
        assert Path(compact).exists()


class TestMergeJsonFile:
    def test_path_exists(self, tmp_path):
        target = tmp_path / "settings.json"
        target.write_text('{"existing": true}')
        overlay = json.dumps({"mcp": {"engram": {"command": "engram"}}}).encode()
        wr, merged = engram._merge_json_file(str(target), overlay)
        assert wr.Changed is True
        assert merged is not None
        data = json.loads(merged)
        assert data["existing"] is True
        assert "mcp" in data

    def test_path_not_exists(self, tmp_path):
        target = tmp_path / "new.json"
        overlay = json.dumps({"key": "val"}).encode()
        wr, merged = engram._merge_json_file(str(target), overlay)
        assert wr.Changed is True
        data = json.loads(merged)
        assert data["key"] == "val"


class TestOsReadFile:
    def test_exists(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello")
        assert engram._os_read_file(str(f)) == b"hello"

    def test_not_exists(self, tmp_path):
        assert engram._os_read_file(str(tmp_path / "nonexistent")) == b""

    def test_os_error(self, monkeypatch, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"data")

        def failing_open(*args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr("builtins.open", failing_open)
        assert engram._os_read_file(str(f)) == b""


class TestReadFileOrEmpty:
    def test_exists(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content")
        assert engram._read_file_or_empty(str(f)) == "content"

    def test_not_found(self, tmp_path):
        assert engram._read_file_or_empty(str(tmp_path / "nope")) == ""


class TestStableEngramCommandForMergedConfig:
    def test_file_exists_with_cmd(self, tmp_path):
        f = tmp_path / "config.json"
        f.write_text(json.dumps({"mcp": {"DXRK_MEMORY": {"command": "DXRK_MEMORY"}}}))
        result = engram._stable_DXRK_MEMORY_command_for_merged_config(
            str(f), AgentID.OPENCODE
        )
        assert result == "DXRK_MEMORY"

    def test_file_exists_no_cmd(self, tmp_path):
        f = tmp_path / "config.json"
        f.write_text(json.dumps({"mcp": {}}))
        result = engram._stable_DXRK_MEMORY_command_for_merged_config(
            str(f), AgentID.OPENCODE
        )
        assert result in ("DXRK_MEMORY",)

    def test_file_not_exists_standard_agent(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            engram, "_preferred_stable_DXRK_MEMORY_command", lambda: "/custom/engram"
        )
        result = engram._stable_DXRK_MEMORY_command_for_merged_config(
            str(tmp_path / "nonexistent"), AgentID.OPENCODE
        )
        assert result == "/custom/engram"

    def test_file_not_exists_nonstandard_agent(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            engram, "_resolve_DXRK_MEMORY_command", lambda: ("/some/engram", True)
        )
        result = engram._stable_DXRK_MEMORY_command_for_merged_config(
            str(tmp_path / "nonexistent"), AgentID.PI
        )
        assert result == "/some/engram"


class TestStableEngramCommandForExisting:
    def test_cellar_path_returns_preferred(self, monkeypatch):
        monkeypatch.setattr(
            engram,
            "_preferred_stable_DXRK_MEMORY_command",
            lambda: "/opt/homebrew/bin/DXRK_MEMORY",
        )
        result = engram._stable_DXRK_MEMORY_command_for_existing(
            "/opt/homebrew/Cellar/DXRK_MEMORY/1.2.3/bin/DXRK_MEMORY", AgentID.OPENCODE
        )
        assert result == "/opt/homebrew/bin/DXRK_MEMORY"

    def test_non_cellar_path_returns_as_is(self):
        result = engram._stable_DXRK_MEMORY_command_for_existing(
            "/usr/local/bin/DXRK_MEMORY", AgentID.OPENCODE
        )
        assert result == "/usr/local/bin/DXRK_MEMORY"


class TestPreferredStableEngramCommand:
    def test_stable_path(self):
        mock = lambda x: "/opt/homebrew/bin/DXRK_MEMORY" if x == "DXRK_MEMORY" else None
        orig = engram.set_look_path_for_test(mock)
        try:
            result = engram._preferred_stable_DXRK_MEMORY_command()
            assert result == "/opt/homebrew/bin/DXRK_MEMORY"
        finally:
            engram.set_look_path_for_test(orig)

    def test_non_stable_path(self):
        mock = lambda x: "/tmp/bin/DXRK_MEMORY" if x == "DXRK_MEMORY" else None
        orig = engram.set_look_path_for_test(mock)
        try:
            result = engram._preferred_stable_DXRK_MEMORY_command()
            assert result == "DXRK_MEMORY"
        finally:
            engram.set_look_path_for_test(orig)


class TestExistingMergedEngramCommand:
    def test_empty_bytes(self):
        cmd, ok = engram._existing_merged_DXRK_MEMORY_command(b"", AgentID.OPENCODE)
        assert cmd == ""
        assert ok is False

    def test_invalid_json(self):
        cmd, ok = engram._existing_merged_DXRK_MEMORY_command(
            b"not json", AgentID.OPENCODE
        )
        assert cmd == ""
        assert ok is False

    def test_no_server_entries(self):
        raw = json.dumps({"some": "thing"}).encode()
        cmd, ok = engram._existing_merged_DXRK_MEMORY_command(raw, AgentID.OPENCODE)
        assert cmd == ""
        assert ok is False

    def test_opencode_with_mcp_engram(self):
        raw = json.dumps({"mcp": {"DXRK_MEMORY": {"command": "DXRK_MEMORY"}}}).encode()
        cmd, ok = engram._existing_merged_DXRK_MEMORY_command(raw, AgentID.OPENCODE)
        assert cmd == "DXRK_MEMORY"
        assert ok is True

    def test_opencode_with_command_list(self):
        raw = json.dumps(
            {"mcp": {"DXRK_MEMORY": {"command": ["npx", "-y", "DXRK_MEMORY"]}}}
        ).encode()
        cmd, ok = engram._existing_merged_DXRK_MEMORY_command(raw, AgentID.OPENCODE)
        assert cmd == "npx"
        assert ok is True

    def test_vscode_copilot(self):
        raw = json.dumps(
            {"servers": {"DXRK_MEMORY": {"command": "DXRK_MEMORY"}}}
        ).encode()
        cmd, ok = engram._existing_merged_DXRK_MEMORY_command(
            raw, AgentID.VSCODE_COPILOT
        )
        assert cmd == "DXRK_MEMORY"
        assert ok is True

    def test_other_agent(self):
        raw = json.dumps(
            {"mcpServers": {"DXRK_MEMORY": {"command": "DXRK_MEMORY"}}}
        ).encode()
        cmd, ok = engram._existing_merged_DXRK_MEMORY_command(raw, AgentID.CLAUDE_CODE)
        assert cmd == "DXRK_MEMORY"
        assert ok is True


class TestBuildSeparateMCPContent:
    def test_file_not_exists(self, tmp_path):
        f = tmp_path / "nonexistent.json"
        default = json.dumps({"command": "engram", "args": []}).encode()
        result = engram._build_separate_mcp_content(str(f), default)
        assert json.loads(result) == {"command": "engram", "args": []}

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        default = json.dumps({"command": "engram", "args": []}).encode()
        result = engram._build_separate_mcp_content(str(f), default)
        assert json.loads(result) == {"command": "engram", "args": []}

    def test_valid_engram_command(self, tmp_path):
        f = tmp_path / "mcp.json"
        f.write_text(json.dumps({"command": "DXRK_MEMORY", "args": ["mcp"]}))
        default = json.dumps({"command": "DXRK_MEMORY", "args": []}).encode()
        result = engram._build_separate_mcp_content(str(f), default)
        data = json.loads(result)
        assert data["command"] == "DXRK_MEMORY"
        assert data["args"] == ["mcp", "--tools=agent"]

    def test_non_engram_command_returns_default(self, tmp_path):
        f = tmp_path / "mcp.json"
        f.write_text(json.dumps({"command": "node"}))
        default = json.dumps({"command": "engram", "args": []}).encode()
        result = engram._build_separate_mcp_content(str(f), default)
        assert json.loads(result) == {"command": "engram", "args": []}


# ═══════════════════════════════════════════════════════════════════════════
# 3. Download
# ═══════════════════════════════════════════════════════════════════════════


class TestIsWritableDir:
    def test_writable_dir(self, tmp_path):
        assert engram._is_writable_dir(str(tmp_path)) is True

    def test_non_existing_dir(self):
        assert engram._is_writable_dir("/nonexistent/path") is False

    def test_permission_error(self, monkeypatch):
        def failing_mkstemp(*args, **kwargs):
            raise PermissionError("no write")

        monkeypatch.setattr("tempfile.mkstemp", failing_mkstemp)
        assert engram._is_writable_dir("/tmp") is False


class TestGitHubToken:
    def test_github_token_set(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh_token_123")
        assert engram._github_token() == "gh_token_123"

    def test_gh_token_fallback(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "gh_token_fallback")
        assert engram._github_token() == "gh_token_fallback"

    def test_no_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        assert engram._github_token() == ""


class TestNormalizeArch:
    @pytest.mark.parametrize(
        ("machine", "expected"),
        [
            ("i386", "amd64"),
            ("i686", "amd64"),
            ("x86", "amd64"),
            ("x86_64", "amd64"),
            ("armv7l", "arm64"),
            ("armv8l", "arm64"),
            ("aarch64", "arm64"),
            ("arm64", "arm64"),
            ("amd64", "amd64"),
            ("riscv64", "riscv64"),
        ],
    )
    def test_arch_mapping(self, monkeypatch, machine, expected):
        monkeypatch.setattr("platform.machine", lambda: machine)
        assert engram._normalize_arch() == expected


class TestEngramApiBaseUrl:
    def test_normal_base(self):
        result = engram._DXRK_MEMORY_api_base_url()
        assert result == "https://api.github.com"

    def test_localhost_base(self, monkeypatch):
        monkeypatch.setattr(
            engram, "_DXRK_MEMORY_github_base_url", "http://localhost:8080"
        )
        result = engram._DXRK_MEMORY_api_base_url()
        assert result == "http://localhost:8080"

    def test_127_localhost_base(self, monkeypatch):
        monkeypatch.setattr(
            engram, "_DXRK_MEMORY_github_base_url", "http://127.0.0.1:8080"
        )
        result = engram._DXRK_MEMORY_api_base_url()
        assert result == "http://127.0.0.1:8080"


class TestEngramAssetUrl:
    def test_linux(self):
        url = engram._DXRK_MEMORY_asset_url(
            "https://github.com", "1.0.0", "linux", "amd64"
        )
        assert url.endswith(".tar.gz")
        assert "v1.0.0" in url

    def test_windows(self):
        url = engram._DXRK_MEMORY_asset_url(
            "https://github.com", "2.0.0", "windows", "amd64"
        )
        assert url.endswith(".zip")
        assert "v2.0.0" in url


class TestEngramInstallDir:
    def test_windows(self, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\test\\AppData\\Local")
        result = engram._DXRK_MEMORY_install_dir("windows")
        assert "AppData" in result
        assert "DXRK_MEMORY" in result
        assert "bin" in result

    def test_windows_no_localappdata(self, monkeypatch):
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        result = engram._DXRK_MEMORY_install_dir("windows")
        assert "AppData" in result

    def test_linux_writable_usr_local(self, monkeypatch):
        monkeypatch.setattr(engram, "_is_writable_dir", lambda d: d == "/usr/local/bin")
        result = engram._DXRK_MEMORY_install_dir("linux")
        assert result == "/usr/local/bin"

    def test_linux_not_writable_usr_local(self, monkeypatch):
        monkeypatch.setattr(engram, "_is_writable_dir", lambda d: False)
        result = engram._DXRK_MEMORY_install_dir("linux")
        assert ".local" in result
        assert "bin" in result


class TestWriteExecutable:
    def test_writes_binary(self, monkeypatch, tmp_path):
        out = tmp_path / "bin" / "engram"

        class FakeFile:
            fd = 9999

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def write(self, data):
                pass

            def flush(self):
                pass

        called_fsync = False

        def fake_fsync(fd):
            nonlocal called_fsync
            called_fsync = True

        monkeypatch.setattr("os.fdopen", lambda fd, mode: FakeFile())
        monkeypatch.setattr("os.fsync", fake_fsync)
        monkeypatch.setattr("os.replace", lambda src, dst: None)
        monkeypatch.setattr("os.chmod", lambda p, m: None)
        engram._write_executable(b"binary content", str(out))
        assert called_fsync is True

    def test_cleanup_on_failure(self, monkeypatch, tmp_path):
        class FakeFile:
            fd = 9999

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def write(self, data):
                pass

            def flush(self):
                pass

        monkeypatch.setattr("os.fdopen", lambda fd, mode: FakeFile())
        monkeypatch.setattr("os.fsync", lambda fd: None)

        def failing_replace(*args, **kwargs):
            raise RuntimeError("replace failed")

        monkeypatch.setattr("os.replace", failing_replace)
        out = tmp_path / "bin" / "engram"
        with pytest.raises(RuntimeError):
            engram._write_executable(b"data", str(out))
        tmp_files = list(tmp_path.glob(".DXRK_MEMORY-upgrade-*"))
        assert len(tmp_files) == 0


class TestDownloadAndExtractTarGz:
    def test_extracts_binary(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            engram,
            "_write_executable",
            lambda data, out_path: Path(out_path).write_bytes(data),
        )
        binary_name = "DXRK_MEMORY"
        out_path = str(tmp_path / "DXRK_MEMORY")

        tar_buffer = BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            info = tarfile.TarInfo(name=binary_name)
            info.type = tarfile.REGTYPE
            content = b"extracted binary"
            info.size = len(content)
            tar.addfile(info, BytesIO(content))
        tar_data = tar_buffer.getvalue()

        class FakeResp:
            def read(self):
                return tar_data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr(engram, "urlopen", lambda req, timeout=None: FakeResp())
        engram._download_and_extract_tar_gz(
            "https://example.com/engram.tar.gz", binary_name, out_path
        )
        assert Path(out_path).read_bytes() == b"extracted binary"

    def test_not_found(self, monkeypatch):
        monkeypatch.setattr(engram, "_write_executable", lambda data, out_path: None)
        tar_buffer = BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="other_file")
            info.type = tarfile.REGTYPE
            tar.addfile(info, BytesIO(b"data"))
        tar_data = tar_buffer.getvalue()

        class FakeResp:
            def read(self):
                return tar_data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr(engram, "urlopen", lambda req, timeout=None: FakeResp())
        with pytest.raises(FileNotFoundError, match="binary.*not found"):
            engram._download_and_extract_tar_gz(
                "https://example.com/DXRK_MEMORY.tar.gz", "DXRK_MEMORY", "/tmp/out"
            )


class TestDownloadAndExtractZip:
    def test_extracts_binary(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            engram,
            "_write_executable",
            lambda data, out_path: Path(out_path).write_bytes(data),
        )
        binary_name = "DXRK_MEMORY.exe"
        out_path = str(tmp_path / "DXRK_MEMORY.exe")

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr(binary_name, b"extracted zip binary")
        zip_data = zip_buffer.getvalue()

        class FakeResp:
            def read(self):
                return zip_data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr(engram, "urlopen", lambda req, timeout=None: FakeResp())
        engram._download_and_extract_zip(
            "https://example.com/engram.zip", binary_name, out_path
        )
        assert Path(out_path).read_bytes() == b"extracted zip binary"

    def test_not_found(self, monkeypatch):
        monkeypatch.setattr(engram, "_write_executable", lambda data, out_path: None)
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("other.exe", b"data")
        zip_data = zip_buffer.getvalue()

        class FakeResp:
            def read(self):
                return zip_data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr(engram, "urlopen", lambda req, timeout=None: FakeResp())
        with pytest.raises(FileNotFoundError, match="binary.*not found"):
            engram._download_and_extract_zip(
                "https://example.com/DXRK_MEMORY.zip", "DXRK_MEMORY.exe", "/tmp/out"
            )


class TestFetchLatestEngramVersion:
    def test_success(self, monkeypatch):
        monkeypatch.setattr(
            engram,
            "_fetch_latest_DXRK_MEMORY_version_request",
            lambda token: ("3.2.1", 200),
        )
        monkeypatch.setattr(engram, "_github_token", lambda: "token123")
        version = engram._fetch_latest_DXRK_MEMORY_version()
        assert version == "3.2.1"

    def test_fallback_with_token(self, monkeypatch):
        calls = []

        def request(token):
            calls.append(token)
            if token:
                raise RuntimeError("api error")
            return ("1.0.0", 200)

        monkeypatch.setattr(
            engram, "_fetch_latest_DXRK_MEMORY_version_request", request
        )
        monkeypatch.setattr(engram, "_github_token", lambda: "mytoken")
        version = engram._fetch_latest_DXRK_MEMORY_version()
        assert version == "1.0.0"
        assert calls == ["mytoken", ""]

    def test_error_no_token_raises(self, monkeypatch):
        monkeypatch.setattr(
            engram,
            "_fetch_latest_DXRK_MEMORY_version_request",
            lambda token: (_ for _ in ()).throw(RuntimeError("fail")),
        )
        monkeypatch.setattr(engram, "_github_token", lambda: "")
        with pytest.raises(RuntimeError, match="fail"):
            engram._fetch_latest_DXRK_MEMORY_version()


class TestFetchLatestEngramVersionRequest:
    def test_success(self, monkeypatch):
        class FakeResp:
            def read(self):
                return json.dumps({"tag_name": "v1.2.3"}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr(engram, "urlopen", lambda req, timeout=None: FakeResp())
        version, status = engram._fetch_latest_DXRK_MEMORY_version_request("")
        assert version == "1.2.3"
        assert status == 200

    def test_empty_tag_raises(self, monkeypatch):
        class FakeResp:
            def read(self):
                return json.dumps({"tag_name": ""}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr(engram, "urlopen", lambda req, timeout=None: FakeResp())
        with pytest.raises(RuntimeError, match="empty tag_name"):
            engram._fetch_latest_DXRK_MEMORY_version_request("")


class TestDownloadLatestBinary:
    def test_end_to_end_tar(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            engram,
            "_write_executable",
            lambda data, out_path: Path(out_path).write_bytes(data),
        )
        monkeypatch.setattr(
            engram, "_fetch_latest_DXRK_MEMORY_version", lambda: "4.0.0"
        )
        monkeypatch.setattr("platform.machine", lambda: "x86_64")

        install_dir = tmp_path / "install"
        monkeypatch.setattr(
            engram,
            "_DXRK_MEMORY_install_dir_fn",
            lambda goos: str(install_dir),
            raising=False,
        )

        tar_buffer = BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="DXRK_MEMORY")
            info.type = tarfile.REGTYPE
            content = b"binary!"
            info.size = len(content)
            tar.addfile(info, BytesIO(content))
        tar_data = tar_buffer.getvalue()

        class FakeResp:
            def read(self):
                return tar_data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr(engram, "urlopen", lambda req, timeout=None: FakeResp())

        profile = MagicMock()
        profile.os = "linux"
        out = engram.download_latest_binary(profile)
        assert Path(out).read_bytes() == b"binary!"

    def test_end_to_end_zip(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            engram,
            "_write_executable",
            lambda data, out_path: Path(out_path).write_bytes(data),
        )
        monkeypatch.setattr(
            engram, "_fetch_latest_DXRK_MEMORY_version", lambda: "5.0.0"
        )
        monkeypatch.setattr("platform.machine", lambda: "amd64")

        install_dir = tmp_path / "install"
        monkeypatch.setattr(
            engram,
            "_DXRK_MEMORY_install_dir_fn",
            lambda goos: str(install_dir),
            raising=False,
        )

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("DXRK_MEMORY.exe", b"windows binary!")
        zip_data = zip_buffer.getvalue()

        class FakeResp:
            def read(self):
                return zip_data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr(engram, "urlopen", lambda req, timeout=None: FakeResp())

        profile = MagicMock()
        profile.os = "windows"
        out = engram.download_latest_binary(profile)
        assert Path(out).read_bytes() == b"windows binary!"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Verify
# ═══════════════════════════════════════════════════════════════════════════


class TestCommand:
    def test_output_with_echo(self):
        cmd = engram._Command("echo", "hello world")
        assert cmd.output() == "hello world"


class TestVerifyInstalled:
    def test_installed(self, monkeypatch):
        monkeypatch.setattr(
            "shutil.which",
            lambda x: "/usr/bin/DXRK_MEMORY" if x == "DXRK_MEMORY" else None,
        )
        assert engram.verify_installed() is None

    def test_not_installed(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda x: None)
        err = engram.verify_installed()
        assert err is not None
        assert "not found" in err


class TestVerifyVersion:
    def test_success(self, monkeypatch):
        monkeypatch.setattr(
            "subprocess.check_output",
            lambda args, text=True: "1.2.3\n",
        )
        result = engram.verify_version()
        assert result == "1.2.3"

    def test_called_process_error(self, monkeypatch):
        monkeypatch.setattr(
            "subprocess.check_output",
            lambda args, text=True: (_ for _ in ()).throw(
                subprocess.CalledProcessError(1, ["engram", "version"], output="")
            ),
        )
        result = engram.verify_version()
        assert "returned non-zero exit status 1" in result

    def test_file_not_found(self, monkeypatch):
        monkeypatch.setattr(
            "subprocess.check_output",
            lambda args, text=True: (_ for _ in ()).throw(
                FileNotFoundError("no such file")
            ),
        )
        result = engram.verify_version()
        assert "no such file" in result


class TestVerifyHealth:
    def test_healthy(self, monkeypatch):
        class FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=2: FakeResp())
        assert engram.verify_health("http://127.0.0.1:7437") is None

    def test_non_200(self, monkeypatch):
        class FakeResp:
            status = 500

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=2: FakeResp())
        err = engram.verify_health()
        assert err is not None
        assert "500" in err

    def test_url_error(self, monkeypatch):
        def fake_urlopen(url, timeout=2):
            import urllib.error

            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        err = engram.verify_health()
        assert err is not None
        assert "connection refused" in err


# ═══════════════════════════════════════════════════════════════════════════
# 5. Install command
# ═══════════════════════════════════════════════════════════════════════════


class TestInstallCommand:
    def test_returns_list(self):
        profile = MagicMock()
        profile.package_manager = "brew"
        result = engram.install_command(profile)
        assert isinstance(result, list)
        assert len(result) > 0
        assert isinstance(result[0], list)

    def test_non_brew(self):
        profile = MagicMock()
        profile.package_manager = "apt"
        result = engram.install_command(profile)
        assert isinstance(result, list)
        assert len(result) > 0


# ═══════════════════════════════════════════════════════════════════════════
# 6. Edge case coverage for uncovered lines
# ═══════════════════════════════════════════════════════════════════════════


class TestResolveEngramCommandEdge:
    def test_versioned_homebrew_cellar_path(self, monkeypatch):
        monkeypatch.setattr(
            engram,
            "_DXRK_MEMORY_look_path",
            lambda x: "/opt/homebrew/Cellar/DXRK_MEMORY/1.2.3/bin/DXRK_MEMORY",
        )
        cmd, ok = engram._resolve_DXRK_MEMORY_command()
        assert cmd == "DXRK_MEMORY"
        assert ok is False


class TestInjectTOMLFileError:
    def test_write_codex_instruction_files_returns_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            engram,
            "_write_codex_instruction_files",
            lambda home_dir: ("", "", "mock error"),
        )
        config_path = tmp_path / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("")
        from dxrk.models import AgentID, MCPStrategy

        adapter = FakeAdapter(
            agent=AgentID.CODEX,
            mcp_strategy=MCPStrategy.TOML_FILE,
            mcp_config_path=str(config_path),
        )
        result = engram.inject(str(tmp_path), adapter)
        assert result.Changed is False
        assert result.Files == []


class TestJinjaModulesFallthrough:
    def test_dead_code_comment(self):
        """Line 230 `elif sps in (JINJA_MODULES,): pass` is dead code."""


class TestExistingMergedEngramCommandEdge:
    def test_merge_json_objects_raises(self, monkeypatch):
        monkeypatch.setattr(
            "dxrk.components.filemerge.merge_json_objects",
            lambda raw, default: (_ for _ in ()).throw(ValueError("corrupt")),
        )
        cmd, ok = engram._existing_merged_DXRK_MEMORY_command(b"{}", AgentID.OPENCODE)
        assert cmd == ""
        assert ok is False

    def test_normalized_json_loads_raises(self, monkeypatch):
        monkeypatch.setattr(
            "dxrk.components.filemerge.merge_json_objects",
            lambda raw, default: b"corrupted{json",
        )
        cmd, ok = engram._existing_merged_DXRK_MEMORY_command(b"{}", AgentID.OPENCODE)
        assert cmd == ""
        assert ok is False


class TestExecutableFromCommandValueEdge:
    def test_non_string_first_element_in_list(self):
        cmd, ok = engram._executable_from_command_value([123, "engram"])
        assert cmd == ""
        assert ok is False


class TestIsEngramCommandEdge:
    def test_empty_string(self):
        assert engram._is_DXRK_MEMORY_command("") is False

    def test_non_engram_command(self):
        assert engram._is_DXRK_MEMORY_command("not-engram") is False

    def test_valid_engram(self):
        assert engram._is_DXRK_MEMORY_command("/usr/local/bin/DXRK_MEMORY") is True


class TestFetchLatestEngramVersionEdge:
    def test_fallback_with_falsy_status(self, monkeypatch):
        calls = []

        def request(token):
            calls.append(token)
            if token:
                return ("1.0.0", 0)
            return ("2.0.0", 200)

        monkeypatch.setattr(
            engram, "_fetch_latest_DXRK_MEMORY_version_request", request
        )
        monkeypatch.setattr(engram, "_github_token", lambda: "mytoken")
        version = engram._fetch_latest_DXRK_MEMORY_version()
        assert version == "2.0.0"
        assert calls == ["mytoken", ""]


class TestFetchLatestEngramVersionRequestEdge:
    def test_with_authorization_header(self, monkeypatch):
        headers = {}

        class FakeRequest:
            def __init__(self, url):
                self.url = url

            def add_header(self, key, value):
                headers[key] = value

        monkeypatch.setattr("urllib.request.Request", FakeRequest)
        monkeypatch.setattr(engram, "Request", FakeRequest)

        class FakeResp:
            def read(self):
                return json.dumps({"tag_name": "v1.2.3"}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr(engram, "urlopen", lambda req, timeout=None: FakeResp())

        version, status = engram._fetch_latest_DXRK_MEMORY_version_request(
            "gh_token_abc"
        )
        assert version == "1.2.3"
        assert status == 200
        assert headers.get("Authorization") == "Bearer gh_token_abc"


class TestWriteExecutableEdge:
    def test_os_replace_raises_unlink_also_fails(self, monkeypatch, tmp_path):
        out = tmp_path / "bin" / "engram"

        class FakeFile:
            fd = 9999

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def write(self, data):
                pass

            def flush(self):
                pass

        monkeypatch.setattr("os.fdopen", lambda fd, mode: FakeFile())
        monkeypatch.setattr("os.fsync", lambda fd: None)
        monkeypatch.setattr("os.chmod", lambda p, m: None)
        monkeypatch.setattr(
            "os.replace",
            lambda src, dst: (_ for _ in ()).throw(OSError("replace failed")),
        )
        monkeypatch.setattr(
            "os.unlink",
            lambda path: (_ for _ in ()).throw(OSError("unlink also failed")),
        )
        with pytest.raises(OSError, match="replace failed"):
            engram._write_executable(b"data", str(out))
