# SPDX-License-Identifier: MIT
from __future__ import annotations

from dxrk.components import gga
from dxrk.models import AgentID


class TestProviderForAgents:
    def test_claude_first(self):
        assert (
            gga.provider_for_agents([AgentID.CLAUDE_CODE, AgentID.OPENCODE]) == "claude"
        )

    def test_opcode_fallback(self):
        assert (
            gga.provider_for_agents([AgentID.OPENCODE, AgentID.GEMINI_CLI])
            == "opencode"
        )

    def test_gemini_fallback(self):
        assert gga.provider_for_agents([AgentID.GEMINI_CLI]) == "gemini"

    def test_antigravity_returns_gemini(self):
        assert gga.provider_for_agents([AgentID.ANTIGRAVITY]) == "gemini"

    def test_codex_fallback(self):
        assert gga.provider_for_agents([AgentID.CODEX]) == "codex"

    def test_default_to_claude(self):
        assert gga.provider_for_agents([AgentID.KIRO_IDE]) == "claude"

    def test_empty_returns_claude(self):
        assert gga.provider_for_agents([]) == "claude"


class TestBuildConfig:
    def test_contains_provider(self):
        config = gga.build_config("claude")
        assert (
            b"PROVIDER='claude'" in config
            or b'PROVIDER="claude"' in config
            or b"PROVIDER='claude'" in config
        )
        assert b"claude" in config

    def test_contains_section_headers(self):
        config = gga.build_config("opencode").decode("utf-8")
        assert "Dxrk Guardian Angel" in config
        assert "PROVIDER=" in config
        assert "FILE_PATTERNS=" in config
        assert "EXCLUDE_PATTERNS=" in config
        assert "RULES_FILE=" in config
        assert "STRICT_MODE=" in config
        assert "TIMEOUT=" in config

    def test_interpolation(self):
        config = gga.build_config("codex").decode("utf-8")
        assert "PROVIDER='codex'" in config or 'PROVIDER="codex"' in config


class TestPaths:
    def test_config_path(self):
        path = gga.config_path("/home/user")
        assert path == "/home/user/.config/DXRK_GUARDIAN/config"

    def test_agents_template_path(self):
        path = gga.agents_template_path("/home/user")
        assert path == "/home/user/.config/DXRK_GUARDIAN/AGENTS.md"

    def test_runtime_lib_dir(self):
        path = gga.runtime_lib_dir("/home/user")
        assert path == "/home/user/.local/share/DXRK_GUARDIAN/lib"

    def test_runtime_bin_dir(self):
        path = gga.runtime_bin_dir("/home/user")
        assert path == "/home/user/.local/share/DXRK_GUARDIAN/bin"

    def test_runtime_pr_mode_path(self):
        path = gga.runtime_pr_mode_path("/home/user")
        assert path.endswith("pr_mode.sh")

    def test_runtime_ps1_path(self):
        path = gga.runtime_ps1_path("/home/user")
        assert path.endswith("DXRK_GUARDIAN.ps1")


class TestPostInstallMessages:
    def test_returns_messages(self):
        msgs = gga.post_install_messages()
        assert len(msgs) == 2
        assert all(isinstance(m, str) for m in msgs)
        assert any("DXRK_GUARDIAN install" in m for m in msgs)


class TestInject:
    def test_creates_config_and_agents_files(self, tmp_path):
        result = gga.inject(str(tmp_path), [AgentID.CLAUDE_CODE])
        assert result.ConfigFile
        assert result.AgentsFile
        assert result.ConfigChanged is True
        assert result.AgentsChanged is True

        config = tmp_path / ".config" / "DXRK_GUARDIAN" / "config"
        assert config.exists()
        assert b"PROVIDER=" in config.read_bytes()

        agents = tmp_path / ".config" / "DXRK_GUARDIAN" / "AGENTS.md"
        assert agents.exists()

    def test_returns_files_written(self, tmp_path):
        result = gga.inject(str(tmp_path), [AgentID.OPENCODE])
        files = result.files_written()
        assert len(files) == 2
        assert all(f for f in files)

    def test_idempotent(self, tmp_path):
        gga.inject(str(tmp_path), [AgentID.CLAUDE_CODE])
        result = gga.inject(str(tmp_path), [AgentID.CLAUDE_CODE])
        assert result.ConfigChanged is False
        assert result.AgentsChanged is False


class TestShouldInstall:
    def test_installs_when_enabled(self):
        assert gga.should_install(True) is True

    def test_skips_when_disabled(self):
        assert gga.should_install(False) is False
