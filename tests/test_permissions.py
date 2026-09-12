# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os

from dxrk.components import permissions
from dxrk.models import AgentID


def make_fake_adapter(agent_id: AgentID, settings_path: str | None = ".config/app/settings.json"):
    class FakeAdapter:
        agent = agent_id

        def settings_path(self, home_dir: str) -> str:
            if settings_path is None:
                return ""
            return os.path.join(home_dir, settings_path)

    return FakeAdapter()


class TestInject:
    def test_returns_empty_when_no_settings_path(self, tmp_path):
        adapter = make_fake_adapter(AgentID.CLAUDE_CODE, settings_path=None)
        result = permissions.inject(str(tmp_path), adapter)
        assert result.Changed is False
        assert result.Files == []

    def test_returns_empty_for_unsupported_agent(self, tmp_path):
        adapter = make_fake_adapter(AgentID.KIRO_IDE)
        result = permissions.inject(str(tmp_path), adapter)
        assert result.Changed is False

    def test_injects_claude_permissions(self, tmp_path):
        adapter = make_fake_adapter(AgentID.CLAUDE_CODE)
        result = permissions.inject(str(tmp_path), adapter)
        assert result.Changed is True
        assert len(result.Files) == 1
        settings = tmp_path / ".config" / "app" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "permissions" in data
        assert data["permissions"]["defaultMode"] == "bypassPermissions"

    def test_injects_opencode_permissions(self, tmp_path):
        adapter = make_fake_adapter(AgentID.OPENCODE)
        result = permissions.inject(str(tmp_path), adapter)
        assert result.Changed is True
        settings = tmp_path / ".config" / "app" / "settings.json"
        data = json.loads(settings.read_text())
        assert "permission" in data
        assert data["permission"]["bash"]["*"] == "allow"

    def test_idempotent(self, tmp_path):
        adapter = make_fake_adapter(AgentID.CLAUDE_CODE)
        permissions.inject(str(tmp_path), adapter)
        result = permissions.inject(str(tmp_path), adapter)
        assert result.Changed is False


class TestAgentOverlay:
    def test_claude_overlay(self):
        from dxrk.components.permissions import _agent_overlay

        overlay = _agent_overlay(AgentID.CLAUDE_CODE)
        assert overlay is not None
        data = json.loads(overlay)
        assert data["permissions"]["defaultMode"] == "bypassPermissions"

    def test_opencode_overlay(self):
        from dxrk.components.permissions import _agent_overlay

        overlay = _agent_overlay(AgentID.OPENCODE)
        assert overlay is not None
        data = json.loads(overlay)
        assert data["permission"]["bash"]["*"] == "allow"

    def test_gemini_overlay(self):
        from dxrk.components.permissions import _agent_overlay

        overlay = _agent_overlay(AgentID.GEMINI_CLI)
        assert overlay is not None
        data = json.loads(overlay)
        assert data["general"]["defaultApprovalMode"] == "auto_edit"

    def test_unsupported_returns_none(self):
        from dxrk.components.permissions import _agent_overlay

        assert _agent_overlay(AgentID.KIRO_IDE) is None


class TestPermissionsFile:
    def test_cursor_writes_permissions_json(self, tmp_path):
        from dxrk.agents.cursor.adapter import CursorAdapter

        home = str(tmp_path)
        result = permissions.inject(home, CursorAdapter())
        dest = os.path.join(home, ".cursor", "permissions.json")
        assert dest in result.Files
        with open(dest, encoding="utf-8") as f:
            data = json.load(f)
        assert "git" in data["terminalAllowlist"]
        assert data["mcpAllowlist"] == ["DXRK_MEMORY", "context7"]

    def test_cursor_inject_is_idempotent(self, tmp_path):
        from dxrk.agents.cursor.adapter import CursorAdapter

        home = str(tmp_path)
        permissions.inject(home, CursorAdapter())
        second = permissions.inject(home, CursorAdapter())
        assert second.Changed is False

    def test_kiro_writes_yaml_once(self, tmp_path):
        from dxrk.agents.kiro.adapter import KiroAdapter

        home = str(tmp_path)
        result = permissions.inject(home, KiroAdapter())
        dest = os.path.join(home, ".kiro", "settings", "permissions.yaml")
        assert dest in result.Files
        with open(dest, encoding="utf-8") as f:
            content = f.read()
        assert "DXRK_MEMORY" in content

    def test_kiro_keeps_existing_yaml(self, tmp_path):
        from dxrk.agents.kiro.adapter import KiroAdapter

        home = str(tmp_path)
        dest = os.path.join(home, ".kiro", "settings", "permissions.yaml")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write("# user rules\n")
        result = permissions.inject(home, KiroAdapter())
        assert result.Changed is False
        with open(dest, encoding="utf-8") as f:
            assert f.read() == "# user rules\n"

    def test_managed_paths(self, tmp_path):
        from dxrk.agents.claude.adapter import ClaudeAdapter
        from dxrk.agents.cursor.adapter import CursorAdapter
        from dxrk.agents.kiro.adapter import KiroAdapter

        home = str(tmp_path)
        assert permissions.managed_paths(CursorAdapter(), home) == [os.path.join(home, ".cursor", "permissions.json")]
        assert permissions.managed_paths(KiroAdapter(), home) == [
            os.path.join(home, ".kiro", "settings", "permissions.yaml")
        ]
        assert permissions.managed_paths(ClaudeAdapter(), home) == [os.path.join(home, ".claude", "settings.json")]
