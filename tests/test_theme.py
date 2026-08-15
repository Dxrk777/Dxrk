# SPDX-License-Identifier: MIT
from __future__ import annotations

import json

from dxrk.components import theme
from dxrk.models import AgentID

import pytest


def make_fake_adapter(agent_id: AgentID, settings_path: str | None = ".config/app/settings.json"):
    class FakeAdapter:
        agent = agent_id
        def settings_path(self, home_dir: str) -> str:
            if settings_path is None:
                return ""
            import os
            return os.path.join(home_dir, settings_path)

    return FakeAdapter()


class TestInject:
    def test_returns_empty_when_no_settings_path(self, tmp_path):
        adapter = make_fake_adapter(AgentID.CLAUDE_CODE, settings_path=None)
        result = theme.inject(str(tmp_path), adapter)
        assert result.Changed is False
        assert result.Files == []

    def test_injects_theme(self, tmp_path):
        adapter = make_fake_adapter(AgentID.CLAUDE_CODE)
        result = theme.inject(str(tmp_path), adapter)
        assert result.Changed is True
        assert len(result.Files) == 1
        settings = tmp_path / ".config" / "app" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert data["theme"] == "dxrk-kanagawa"

    def test_merges_with_existing(self, tmp_path):
        import os
        settings = tmp_path / ".config" / "app" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"existing": "value"}) + "\n")

        adapter = make_fake_adapter(AgentID.CLAUDE_CODE)
        result = theme.inject(str(tmp_path), adapter)
        assert result.Changed is True
        data = json.loads(settings.read_text())
        assert data["existing"] == "value"
        assert data["theme"] == "dxrk-kanagawa"

    def test_idempotent(self, tmp_path):
        adapter = make_fake_adapter(AgentID.CLAUDE_CODE)
        theme.inject(str(tmp_path), adapter)
        result = theme.inject(str(tmp_path), adapter)
        assert result.Changed is False
