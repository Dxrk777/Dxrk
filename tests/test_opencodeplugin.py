# SPDX-License-Identifier: MIT
from __future__ import annotations

import json

from dxrk.components import opencodeplugin
from dxrk.models import OpenCodeCommunityPluginID

import pytest


class TestDefinitions:
    def test_returns_all_definitions(self):
        defs = opencodeplugin.definitions()
        assert len(defs) >= 2
        ids = [d.id for d in defs]
        assert OpenCodeCommunityPluginID.SUB_AGENT_STATUSLINE in ids
        assert OpenCodeCommunityPluginID.SDD_ENGRAM_PLUGIN in ids

    def test_each_definition_has_fields(self):
        for d in opencodeplugin.definitions():
            assert d.id
            assert d.name
            assert d.package_name
            assert d.repo_url
            assert d.owner
            assert d.repo
            assert d.description


class TestDefinitionFor:
    def test_finds_existing(self):
        defn = opencodeplugin.definition_for(OpenCodeCommunityPluginID.SUB_AGENT_STATUSLINE)
        assert defn is not None
        assert defn.name == "Sub-agent Statusline"

    def test_returns_none_for_unknown(self):
        class Unknown:
            value = "unknown"
        assert opencodeplugin.definition_for(Unknown()) is None


class TestInstall:
    def test_creates_tui_json(self, tmp_path):
        result = opencodeplugin.install(str(tmp_path), OpenCodeCommunityPluginID.SUB_AGENT_STATUSLINE)
        assert result.Changed is True
        assert len(result.Files) == 1
        tui_path = tmp_path / ".config" / "opencode" / "tui.json"
        assert tui_path.exists()
        data = json.loads(tui_path.read_text())
        assert data["$schema"] == "https://opencode.ai/tui.json"
        assert "opencode-subagent-statusline" in data["plugin"]

    def test_appends_to_existing(self, tmp_path):
        tui_path = tmp_path / ".config" / "opencode" / "tui.json"
        tui_path.parent.mkdir(parents=True)
        tui_path.write_text(json.dumps({"$schema": "https://opencode.ai/tui.json", "plugin": ["existing"]}) + "\n")

        opencodeplugin.install(str(tmp_path), OpenCodeCommunityPluginID.SUB_AGENT_STATUSLINE)
        data = json.loads(tui_path.read_text())
        assert "existing" in data["plugin"]
        assert "opencode-subagent-statusline" in data["plugin"]

    def test_idempotent(self, tmp_path):
        opencodeplugin.install(str(tmp_path), OpenCodeCommunityPluginID.SUB_AGENT_STATUSLINE)
        result = opencodeplugin.install(str(tmp_path), OpenCodeCommunityPluginID.SUB_AGENT_STATUSLINE)
        assert result.Changed is False

    def test_raises_on_unknown_plugin(self):
        class Unknown:
            value = "unknown"
        with pytest.raises(ValueError, match="unknown"):
            opencodeplugin.install("/tmp", Unknown())


class TestStringSlice:
    def test_extracts_strings(self):
        from dxrk.components.opencodeplugin import _string_slice
        assert _string_slice(["a", "b"]) == ["a", "b"]

    def test_skips_non_strings(self):
        from dxrk.components.opencodeplugin import _string_slice
        assert _string_slice(["a", 1, None, "b"]) == ["a", "b"]

    def test_returns_empty_for_non_list(self):
        from dxrk.components.opencodeplugin import _string_slice
        assert _string_slice("not a list") == []
        assert _string_slice(None) == []
