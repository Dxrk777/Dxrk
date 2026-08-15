# SPDX-License-Identifier: MIT
from __future__ import annotations

import json

from dxrk.components import filemerge

import pytest


class TestWriteFileAtomic:
    def test_creates_new_file(self, tmp_path):
        path = str(tmp_path / "test.txt")
        result = filemerge.write_file_atomic(path, b"hello")
        assert result.Changed is True
        assert result.Created is True
        assert tmp_path.joinpath("test.txt").read_text() == "hello"

    def test_no_change_when_same_content(self, tmp_path):
        path = tmp_path / "test.txt"
        path.write_text("hello")
        result = filemerge.write_file_atomic(str(path), b"hello")
        assert result.Changed is False
        assert result.Created is False

    def test_changed_when_different_content(self, tmp_path):
        path = tmp_path / "test.txt"
        path.write_text("hello")
        result = filemerge.write_file_atomic(str(path), b"world")
        assert result.Changed is True
        assert path.read_text() == "world"


class TestMergeJsonObjects:
    def test_merge_empty_base(self):
        result = filemerge.merge_json_objects(b"", b'{"a": 1}')
        decoded = json.loads(result)
        assert decoded == {"a": 1}

    def test_merge_simple(self):
        result = filemerge.merge_json_objects(b'{"a": 1}', b'{"b": 2}')
        decoded = json.loads(result)
        assert decoded == {"a": 1, "b": 2}

    def test_overlay_overwrites(self):
        result = filemerge.merge_json_objects(b'{"a": 1}', b'{"a": 2}')
        decoded = json.loads(result)
        assert decoded == {"a": 2}

    def test_nested_merge(self):
        base = b'{"outer": {"inner": 1, "keep": "me"}}'
        overlay = b'{"outer": {"inner": 2}}'
        result = filemerge.merge_json_objects(base, overlay)
        decoded = json.loads(result)
        assert decoded == {"outer": {"inner": 2, "keep": "me"}}

    def test_sentinel_replace(self):
        base = b'{"key": {"nested": "value"}}'
        overlay = b'{"key": {"__replace__": "scalar"}}'
        result = filemerge.merge_json_objects(base, overlay)
        decoded = json.loads(result)
        assert decoded == {"key": "scalar"}

    def test_jsonc_comments(self):
        overlay = b'{"a": 1 /* comment */}'
        result = filemerge.merge_json_objects(b"", overlay)
        decoded = json.loads(result)
        assert decoded == {"a": 1}

    def test_trailing_comma(self):
        overlay = b'{"a": 1,}'
        result = filemerge.merge_json_objects(b"", overlay)
        decoded = json.loads(result)
        assert decoded == {"a": 1}

    def test_raises_on_invalid_overlay(self):
        with pytest.raises(ValueError, match="cannot unmarshal"):
            filemerge.merge_json_objects(b"", b"not json")


class TestInjectMarkdownSection:
    def test_injects_new_section(self):
        result = filemerge.inject_markdown_section("", "my-section", "hello")
        assert "<!-- dxrk:my-section -->" in result
        assert "hello" in result
        assert "<!-- /dxrk:my-section -->" in result

    def test_replaces_existing_section(self):
        existing = (
            "before\n"
            "<!-- dxrk:my-section -->\n"
            "old content\n"
            "<!-- /dxrk:my-section -->\n"
            "after"
        )
        result = filemerge.inject_markdown_section(
            existing, "my-section", "new content"
        )
        assert "old content" not in result
        assert "new content" in result
        assert "before" in result
        assert "after" in result

    def test_removes_section_when_content_empty(self):
        existing = (
            "before\n"
            "<!-- dxrk:my-section -->\n"
            "content\n"
            "<!-- /dxrk:my-section -->\n"
            "after"
        )
        result = filemerge.inject_markdown_section(existing, "my-section", "")
        assert "<!-- dxrk:my-section" not in result
        assert "before" in result
        assert "after" in result

    def test_appends_to_existing_content(self):
        existing = "existing text"
        result = filemerge.inject_markdown_section(existing, "section-id", "new")
        assert result.startswith("existing text")
        assert "section-id" in result
        assert "new" in result


class TestStripLegacyPersonaBlock:
    def test_strips_when_all_fingerprints_present(self):
        content = (
            "## Personality\n"
            "Senior Architect\n"
            "## Rules\n"
            "some rule\n"
            "<!-- dxrk:content -->\n"
            "preserved"
        )
        result = filemerge.strip_legacy_persona_block(content)
        assert "## Personality" not in result
        assert "Senior Architect" not in result
        assert "<!-- dxrk:content -->" in result
        assert "preserved" in result

    def test_returns_empty_when_legacy_without_marker(self):
        content = "## Personality\nSenior Architect\n## Rules\n"
        result = filemerge.strip_legacy_persona_block(content)
        assert result == ""

    def test_unchanged_when_not_all_fingerprints(self):
        content = "## Personality\nsome content\n<!-- dxrk:content -->"
        result = filemerge.strip_legacy_persona_block(content)
        assert "## Personality" in result


class TestStripLegacyATLBlock:
    def test_strips_atl_block(self):
        content = (
            "before\n"
            "<!-- BEGIN:agent-teams-lite -->\n"
            "atl content\n"
            "<!-- END:agent-teams-lite -->\n"
            "after"
        )
        result = filemerge.strip_legacy_atl_block(content)
        assert "BEGIN:agent-teams-lite" not in result
        assert "END:agent-teams-lite" not in result
        assert "atl content" not in result
        assert "before" in result
        assert "after" in result


class TestCodexUpserts:
    def test_adds_block_to_empty(self):
        result = filemerge.upsert_codex_DXRK_MEMORY_block("", "")
        assert "[mcp_servers.DXRK_MEMORY]" in result

    def test_replaces_existing_block(self):
        content = (
            "[mcp_servers.DXRK_MEMORY]\n"
            'command = "old"\n'
            'args = ["old"]\n'
            "\n"
            "[other]\n"
            'key = "val"\n'
        )
        result = filemerge.upsert_codex_DXRK_MEMORY_block(content, "new-cmd")
        assert "old" not in result
        assert "new-cmd" in result
        assert "other" in result

    def test_upsert_toml_string(self):
        result = filemerge.upsert_top_level_toml_string("", "key", "value")
        assert 'key = "value"' in result
