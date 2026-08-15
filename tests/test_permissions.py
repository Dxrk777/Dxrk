# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os

from dxrk.components import permissions
from dxrk.models import AgentID

import pytest


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
