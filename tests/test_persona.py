# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os

import pytest

from dxrk.components import persona
from dxrk.models import AgentID, PersonaID, SystemPromptStrategy


# ─── Fake adapter ──────────────────────────────────────────────────────────


class FakeAdapter:
    def __init__(
        self,
        agent_id=AgentID.CLAUDE_CODE,
        prompt_strategy=None,
        supports_system_prompt=True,
        supports_output_styles=False,
        settings_path=None,
    ):
        self._agent = agent_id
        self._prompt_strategy = prompt_strategy or SystemPromptStrategy.MARKDOWN_SECTIONS
        self._supports_system_prompt = supports_system_prompt
        self._supports_output_styles = supports_output_styles
        self._settings_path = settings_path

    @property
    def agent(self):
        return self._agent

    @property
    def supports_system_prompt(self):
        return self._supports_system_prompt

    @property
    def supports_output_styles(self):
        return self._supports_output_styles

    @property
    def system_prompt_strategy(self):
        return self._prompt_strategy

    def system_prompt_file(self, home_dir: str) -> str:
        return os.path.join(home_dir, ".claude", "CLAUDE.md")

    def system_prompt_dir(self, home_dir: str) -> str:
        return os.path.join(home_dir, ".claude")

    def settings_path(self, home_dir: str) -> str:
        if self._settings_path is not None:
            return self._settings_path
        return os.path.join(home_dir, ".claude", "settings.json")

    def output_style_dir(self, home_dir: str) -> str:
        return os.path.join(home_dir, ".claude", "output-styles")

    def global_config_dir(self, home_dir: str) -> str:
        return os.path.join(home_dir, ".claude")

    def bootstrap_template(self, home_dir: str) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# _persona_content
# ═══════════════════════════════════════════════════════════════════════════


class TestPersonaContent:
    def test_neutral(self, monkeypatch):
        paths = []

        def mock_must_read(path):
            paths.append(path)
            return "neutral content"

        monkeypatch.setattr("dxrk.components.persona._must_read", mock_must_read)
        result = persona._persona_content(AgentID.CLAUDE_CODE, PersonaID.NEUTRAL)
        assert result == "neutral content"
        assert paths == ["generic/persona-neutral.md"]

    def test_custom(self):
        result = persona._persona_content(AgentID.CLAUDE_CODE, PersonaID.CUSTOM)
        assert result == ""

    def test_claude_code(self, monkeypatch):
        paths = []

        def mock_must_read(path):
            paths.append(path)
            return "dxrk content"

        monkeypatch.setattr("dxrk.components.persona._must_read", mock_must_read)
        result = persona._persona_content(AgentID.CLAUDE_CODE, PersonaID.DXRK)
        assert result == "dxrk content"
        assert paths == ["claude/persona-dxrk.md"]

    def test_opencode(self, monkeypatch):
        paths = []

        def mock_must_read(path):
            paths.append(path)
            return "opencode content"

        monkeypatch.setattr("dxrk.components.persona._must_read", mock_must_read)
        result = persona._persona_content(AgentID.OPENCODE, PersonaID.DXRK)
        assert result == "opencode content"
        assert paths == ["opencode/persona-dxrk.md"]

    def test_kilocode(self, monkeypatch):
        paths = []

        def mock_must_read(path):
            paths.append(path)
            return "kilocode content"

        monkeypatch.setattr("dxrk.components.persona._must_read", mock_must_read)
        result = persona._persona_content(AgentID.KILOCODE, PersonaID.DXRK)
        assert result == "kilocode content"
        assert paths == ["opencode/persona-dxrk.md"]

    def test_kimi(self, monkeypatch):
        paths = []

        def mock_must_read(path):
            paths.append(path)
            return "kimi content"

        monkeypatch.setattr("dxrk.components.persona._must_read", mock_must_read)
        result = persona._persona_content(AgentID.KIMI, PersonaID.DXRK)
        assert result == "kimi content"
        assert paths == ["kimi/persona-dxrk.md"]

    def test_kiro_ide(self, monkeypatch):
        paths = []

        def mock_must_read(path):
            paths.append(path)
            return "kiro content"

        monkeypatch.setattr("dxrk.components.persona._must_read", mock_must_read)
        result = persona._persona_content(AgentID.KIRO_IDE, PersonaID.DXRK)
        assert result == "kiro content"
        assert paths == ["kiro/persona-dxrk.md"]

    def test_fallback_unknown_agent(self, monkeypatch):
        paths = []

        def mock_must_read(path):
            paths.append(path)
            return "generic content"

        monkeypatch.setattr("dxrk.components.persona._must_read", mock_must_read)
        result = persona._persona_content(AgentID.CURSOR, PersonaID.DXRK)
        assert result == "generic content"
        assert paths == ["generic/persona-dxrk.md"]


# ═══════════════════════════════════════════════════════════════════════════
# _is_exact_legacy_persona_asset
# ═══════════════════════════════════════════════════════════════════════════


class TestIsExactLegacyPersonaAsset:
    def test_matches_asset(self, monkeypatch):
        def mock_must_read(path):
            return "  matching content  "

        monkeypatch.setattr("dxrk.components.persona._must_read", mock_must_read)
        assert persona._is_exact_legacy_persona_asset("matching content") is True

    def test_does_not_match(self, monkeypatch):
        def mock_must_read(path):
            return "different content"

        monkeypatch.setattr("dxrk.components.persona._must_read", mock_must_read)
        assert persona._is_exact_legacy_persona_asset("something else") is False

    def test_empty_trimmed(self, monkeypatch):
        def mock_must_read(path):
            return "content"

        monkeypatch.setattr("dxrk.components.persona._must_read", mock_must_read)
        assert persona._is_exact_legacy_persona_asset("   ") is False

    def test_empty_string(self, monkeypatch):
        def mock_must_read(path):
            return "content"

        monkeypatch.setattr("dxrk.components.persona._must_read", mock_must_read)
        assert persona._is_exact_legacy_persona_asset("") is False


# ═══════════════════════════════════════════════════════════════════════════
# _should_strip_managed_legacy_persona
# ═══════════════════════════════════════════════════════════════════════════


class TestShouldStripManagedLegacyPersona:
    def test_has_marker(self):
        content = "some text\n<!-- dxrk:persona -->\nmore text"
        assert persona._should_strip_managed_legacy_persona(content) is True

    def test_no_marker(self):
        content = "some text without the marker"
        assert persona._should_strip_managed_legacy_persona(content) is False

    def test_empty_content(self):
        assert persona._should_strip_managed_legacy_persona("") is False


# ═══════════════════════════════════════════════════════════════════════════
# _is_legacy_unwrapped_persona
# ═══════════════════════════════════════════════════════════════════════════


class TestIsLegacyUnwrappedPersona:
    def test_legacy_content(self):
        content = "## Personality\nSenior Architect\n## Rules\n"
        assert persona._is_legacy_unwrapped_persona(content) is True

    def test_with_frontmatter(self):
        content = "---\nkey: val\n---\n## Personality\nSenior Architect\n## Rules\n"
        assert persona._is_legacy_unwrapped_persona(content) is False

    def test_missing_fingerprint(self):
        content = "## Personality\n## Rules\n"
        assert persona._is_legacy_unwrapped_persona(content) is False

    def test_empty_content(self):
        assert persona._is_legacy_unwrapped_persona("") is False

    def test_frontmatter_only_no_fingerprints(self):
        content = "---\nkey: val\n---\n"
        assert persona._is_legacy_unwrapped_persona(content) is False


# ═══════════════════════════════════════════════════════════════════════════
# _legacy_vscode_persona_paths
# ═══════════════════════════════════════════════════════════════════════════


class TestLegacyVSCodePersonaPaths:
    def test_returns_expected_paths(self):
        paths = persona._legacy_vscode_persona_paths("/home/user")
        assert paths == ["/home/user/.github/copilot-instructions.md"]

    def test_with_tmp_path(self, tmp_path):
        paths = persona._legacy_vscode_persona_paths(str(tmp_path))
        assert paths == [os.path.join(str(tmp_path), ".github", "copilot-instructions.md")]


# ═══════════════════════════════════════════════════════════════════════════
# _clean_legacy_vscode_persona
# ═══════════════════════════════════════════════════════════════════════════


class TestCleanLegacyVSCodePersona:
    def test_removes_legacy_file(self, tmp_path):
        target = tmp_path / ".github" / "copilot-instructions.md"
        target.parent.mkdir(parents=True)
        target.write_text("## Personality\nSenior Architect\n## Rules\n")
        assert target.exists()
        result = persona._clean_legacy_vscode_persona(str(tmp_path))
        assert result is True
        assert not target.exists()

    def test_skips_non_legacy(self, tmp_path):
        target = tmp_path / ".github" / "copilot-instructions.md"
        target.parent.mkdir(parents=True)
        target.write_text("some ordinary content")
        result = persona._clean_legacy_vscode_persona(str(tmp_path))
        assert result is False
        assert target.exists()

    def test_missing_file(self, tmp_path):
        result = persona._clean_legacy_vscode_persona(str(tmp_path))
        assert result is False

    def test_oserror_on_read(self, monkeypatch, tmp_path):
        target = tmp_path / ".github" / "copilot-instructions.md"
        target.parent.mkdir(parents=True)
        target.write_text("## Personality\nSenior Architect\n## Rules\n")

        original_open = builtins_open = open

        def failing_open(*args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr("builtins.open", failing_open)
        with pytest.raises(OSError, match="read legacy vscode persona"):
            persona._clean_legacy_vscode_persona(str(tmp_path))

    def test_oserror_on_remove_ignored(self, monkeypatch, tmp_path):
        target = tmp_path / ".github" / "copilot-instructions.md"
        target.parent.mkdir(parents=True)
        target.write_text("## Personality\nSenior Architect\n## Rules\n")

        original_remove = os.remove

        def fail_first_remove(path):
            raise FileNotFoundError("already gone")

        monkeypatch.setattr(os, "remove", fail_first_remove)
        result = persona._clean_legacy_vscode_persona(str(tmp_path))
        assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# _preserve_managed_sections
# ═══════════════════════════════════════════════════════════════════════════


class TestPreserveManagedSections:
    def test_preserves_managed_sections(self):
        existing = "some content\n<!-- dxrk:persona -->\nmanaged stuff\n<!-- /dxrk:persona -->\n"
        updated, ok = persona._preserve_managed_sections(existing, "new persona", PersonaID.NEUTRAL)
        assert ok is True
        assert "new persona" in updated
        assert "managed stuff" in updated
        assert "<!-- dxrk:persona -->" in updated
        assert "<!-- /dxrk:persona -->" in updated

    def test_empty_existing(self):
        updated, ok = persona._preserve_managed_sections("", "new persona", PersonaID.NEUTRAL)
        assert updated == ""
        assert ok is False

    def test_persona_dxrk(self):
        existing = "some content\n<!-- dxrk:persona -->\nmanaged\n"
        updated, ok = persona._preserve_managed_sections(existing, "new persona", PersonaID.DXRK)
        assert updated == ""
        assert ok is False

    def test_no_managed_marker(self):
        existing = "some content without managed marker"
        updated, ok = persona._preserve_managed_sections(existing, "new persona", PersonaID.NEUTRAL)
        assert updated == ""
        assert ok is False

    def test_ensures_newline_on_new_persona(self):
        existing = "prefix\n<!-- dxrk:persona -->\nsuffix\n"
        updated, ok = persona._preserve_managed_sections(existing, "no-newline-end", PersonaID.NEUTRAL)
        assert ok is True
        assert "no-newline-end\n\n" in updated or "no-newline-end\n<!--" in updated

    def test_idx_at_zero(self):
        existing = "<!-- dxrk:persona -->\nsuffix\n"
        updated, ok = persona._preserve_managed_sections(existing, "new", PersonaID.NEUTRAL)
        assert ok is True
        assert updated.startswith("new")

    def test_idx_gt_zero_with_extra_newline(self):
        existing = "prefix\n<!-- dxrk:persona -->\nsuffix\n"
        updated, ok = persona._preserve_managed_sections(existing, "new", PersonaID.NEUTRAL)
        assert ok is True
        assert "prefix" not in updated
        assert "new" in updated
        assert "suffix" in updated


# ═══════════════════════════════════════════════════════════════════════════
# _wrap_instructions_file
# ═══════════════════════════════════════════════════════════════════════════


class TestWrapInstructionsFile:
    def test_wraps_content(self):
        wrapped = persona._wrap_instructions_file("hello world")
        assert wrapped.startswith("---\n")
        assert "hello world" in wrapped
        assert "name: Dxrk AI Persona" in wrapped
        assert 'applyTo: "**"' in wrapped

    def test_empty_content(self):
        wrapped = persona._wrap_instructions_file("")
        assert wrapped.startswith("---\n")


# ═══════════════════════════════════════════════════════════════════════════
# _wrap_steering_file
# ═══════════════════════════════════════════════════════════════════════════


class TestWrapSteeringFile:
    def test_wraps_content(self):
        wrapped = persona._wrap_steering_file("hello world")
        assert wrapped.startswith("---\n")
        assert "hello world" in wrapped
        assert "inclusion: always" in wrapped

    def test_empty_content(self):
        wrapped = persona._wrap_steering_file("")
        assert wrapped.startswith("---\n")


# ═══════════════════════════════════════════════════════════════════════════
# inject
# ═══════════════════════════════════════════════════════════════════════════


class TestInjectNoSystemPrompt:
    def test_returns_early_when_no_system_prompt(self, tmp_path):
        adapter = FakeAdapter(supports_system_prompt=False)
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is False
        assert result.Files == []


class TestInjectCustomPersona:
    def test_returns_early_for_custom_persona(self, tmp_path):
        adapter = FakeAdapter()
        result = persona.inject(str(tmp_path), adapter, PersonaID.CUSTOM)
        assert result.Changed is False
        assert result.Files == []


class TestInjectEmptyContent:
    def test_returns_early_when_content_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda path: "")
        adapter = FakeAdapter(AgentID.OPENCODE)
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is False
        assert result.Files == []


class TestInjectMarkdownSections:
    def test_injects_persona(self, tmp_path):
        adapter = FakeAdapter(AgentID.CLAUDE_CODE)
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        prompt = tmp_path / ".claude" / "CLAUDE.md"
        assert prompt.exists()
        content = prompt.read_text()
        assert "<!-- dxrk:persona -->" in content

    def test_replaces_existing_section(self, tmp_path):
        prompt = tmp_path / ".claude" / "CLAUDE.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("<!-- dxrk:persona -->\nold content\n<!-- /dxrk:persona -->\n")
        adapter = FakeAdapter(AgentID.CLAUDE_CODE)
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        content = prompt.read_text()
        assert "old content" not in content


class TestInjectFileReplace:
    def test_opencode_injects_persona(self, tmp_path):
        from dxrk.agents.opencode.adapter import OpenCodeAdapter

        adapter = OpenCodeAdapter()
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        prompt = tmp_path / ".config" / "opencode" / "AGENTS.md"
        assert prompt.exists()
        content = prompt.read_text()
        assert "<!-- dxrk:persona -->" in content

    def test_opencode_strips_managed_legacy(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "new content")
        prompt = tmp_path / ".config" / "opencode" / "AGENTS.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("## Personality\nSenior Architect\n<!-- dxrk:persona -->\nmanaged\n")
        from dxrk.agents.opencode.adapter import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        content = prompt.read_text()
        assert "<!-- dxrk:persona -->" in content

    def test_opencode_strips_exact_legacy_asset(self, monkeypatch, tmp_path):
        def mock_must_read(path):
            if path == "opencode/persona-dxrk.md":
                return "exact asset content"
            return ""

        monkeypatch.setattr("dxrk.components.persona._must_read", mock_must_read)
        prompt = tmp_path / ".config" / "opencode" / "AGENTS.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("exact asset content")
        from dxrk.agents.opencode.adapter import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        content = prompt.read_text()
        assert "persona" in content

    def test_opencode_no_legacy(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "new persona content")
        prompt = tmp_path / ".config" / "opencode" / "AGENTS.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("existing content\n")
        from dxrk.agents.opencode.adapter import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        content = prompt.read_text()
        assert "existing content" in content
        assert "persona" in content

    def test_non_opencode_preserve_managed(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "new persona")
        prompt = tmp_path / ".claude" / "CLAUDE.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("prefix\n<!-- dxrk:persona -->\nmanaged\n")
        adapter = FakeAdapter(
            AgentID.KILOCODE,
            prompt_strategy=SystemPromptStrategy.FILE_REPLACE,
        )
        result = persona.inject(str(tmp_path), adapter, PersonaID.NEUTRAL)
        assert result.Changed is True
        content = prompt.read_text()
        assert "managed" in content
        assert "new persona" in content

    def test_non_opencode_no_preserve(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "new persona")
        prompt = tmp_path / ".claude" / "CLAUDE.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("plain content")
        adapter = FakeAdapter(
            AgentID.KILOCODE,
            prompt_strategy=SystemPromptStrategy.FILE_REPLACE,
        )
        result = persona.inject(str(tmp_path), adapter, PersonaID.NEUTRAL)
        assert result.Changed is True
        content = prompt.read_text()
        assert "new persona" in content


class TestInjectInstructionsFile:
    def test_injects_instructions_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "persona content")
        prompt = tmp_path / ".claude" / "instructions.md"
        prompt.parent.mkdir(parents=True)
        adapter = FakeAdapter(
            AgentID.CLAUDE_CODE,
            prompt_strategy=SystemPromptStrategy.INSTRUCTIONS_FILE,
        )
        original_system_prompt_file = adapter.system_prompt_file

        def system_prompt_file(home_dir):
            return os.path.join(home_dir, ".claude", "instructions.md")

        adapter.system_prompt_file = system_prompt_file
        result = persona.inject(str(tmp_path), adapter, PersonaID.NEUTRAL)
        assert result.Changed is True
        content = prompt.read_text()
        assert content.startswith("---\n")
        assert "name: Dxrk AI Persona" in content

    def test_preserves_managed_in_instructions(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "new content")
        prompt = tmp_path / ".claude" / "instructions.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("<!-- dxrk:persona -->\nmanaged section\n")
        adapter = FakeAdapter(
            AgentID.CLAUDE_CODE,
            prompt_strategy=SystemPromptStrategy.INSTRUCTIONS_FILE,
        )

        def system_prompt_file(home_dir):
            return os.path.join(home_dir, ".claude", "instructions.md")

        adapter.system_prompt_file = system_prompt_file
        result = persona.inject(str(tmp_path), adapter, PersonaID.NEUTRAL)
        assert result.Changed is True
        content = prompt.read_text()
        assert "managed section" in content


class TestInjectSteeringFile:
    def test_injects_steering_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "steering content")
        prompt = tmp_path / ".claude" / "steering.md"
        prompt.parent.mkdir(parents=True)
        adapter = FakeAdapter(
            AgentID.CLAUDE_CODE,
            prompt_strategy=SystemPromptStrategy.STEERING_FILE,
        )

        def system_prompt_file(home_dir):
            return os.path.join(home_dir, ".claude", "steering.md")

        adapter.system_prompt_file = system_prompt_file
        result = persona.inject(str(tmp_path), adapter, PersonaID.NEUTRAL)
        assert result.Changed is True
        content = prompt.read_text()
        assert content.startswith("---\n")
        assert "inclusion: always" in content

    def test_preserves_managed_in_steering(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "new steering")
        prompt = tmp_path / ".claude" / "steering.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("<!-- dxrk:persona -->\nmanaged section\n")
        adapter = FakeAdapter(
            AgentID.CLAUDE_CODE,
            prompt_strategy=SystemPromptStrategy.STEERING_FILE,
        )

        def system_prompt_file(home_dir):
            return os.path.join(home_dir, ".claude", "steering.md")

        adapter.system_prompt_file = system_prompt_file
        result = persona.inject(str(tmp_path), adapter, PersonaID.NEUTRAL)
        assert result.Changed is True
        content = prompt.read_text()
        assert "managed section" in content


class TestInjectAppendToFile:
    def test_appends_when_not_present(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "content to append")
        prompt = tmp_path / ".claude" / "CLAUDE.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("existing text")
        adapter = FakeAdapter(
            AgentID.CLAUDE_CODE,
            prompt_strategy=SystemPromptStrategy.APPEND_TO_FILE,
        )
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        content = prompt.read_text()
        assert "existing text" in content
        assert "content to append" in content

    def test_no_change_when_already_present(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "content to append")
        prompt = tmp_path / ".claude" / "CLAUDE.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("content to append")
        adapter = FakeAdapter(
            AgentID.CLAUDE_CODE,
            prompt_strategy=SystemPromptStrategy.APPEND_TO_FILE,
        )
        original = prompt.read_text()
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is False
        assert prompt.read_text() == original

    def test_appends_with_spacing(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "extra content")
        prompt = tmp_path / ".claude" / "CLAUDE.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("some text\n")
        adapter = FakeAdapter(
            AgentID.CLAUDE_CODE,
            prompt_strategy=SystemPromptStrategy.APPEND_TO_FILE,
        )
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        content = prompt.read_text()
        assert "\n\n" in content


class TestInjectJinjaModules:
    def test_injects_jinja_modules(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "persona content")
        config_dir = tmp_path / ".config" / "opencode"
        adapter = FakeAdapter(
            AgentID.OPENCODE,
            prompt_strategy=SystemPromptStrategy.JINJA_MODULES,
        )

        def global_config_dir(home_dir):
            return str(config_dir)

        adapter.global_config_dir = global_config_dir
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        persona_file = config_dir / "persona.md"
        assert persona_file.exists()
        assert persona_file.read_text() == "persona content"
        output_style = config_dir / "output-style.md"
        assert output_style.exists()

    def test_injects_jinja_modules_bootstrap(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "content")
        bootstrapped = False

        def fake_bootstrap(home_dir):
            nonlocal bootstrapped
            bootstrapped = True

        config_dir = tmp_path / ".config" / "opencode"
        adapter = FakeAdapter(
            AgentID.OPENCODE,
            prompt_strategy=SystemPromptStrategy.JINJA_MODULES,
        )
        adapter.bootstrap_template = fake_bootstrap

        def global_config_dir(home_dir):
            return str(config_dir)

        adapter.global_config_dir = global_config_dir
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        assert bootstrapped is True

    def test_neutral_persona_no_output_style(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "neutral content")
        config_dir = tmp_path / ".config" / "opencode"
        adapter = FakeAdapter(
            AgentID.OPENCODE,
            prompt_strategy=SystemPromptStrategy.JINJA_MODULES,
        )

        def global_config_dir(home_dir):
            return str(config_dir)

        adapter.global_config_dir = global_config_dir
        result = persona.inject(str(tmp_path), adapter, PersonaID.NEUTRAL)
        assert result.Changed is True
        output_style = config_dir / "output-style.md"
        assert output_style.exists()
        assert output_style.read_text() == ""


class TestInjectOpenCodeSettings:
    def test_merges_settings_for_opencode(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "content")
        config_dir = tmp_path / ".config" / "opencode"
        config_dir.mkdir(parents=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text("{}")
        adapter = FakeAdapter(
            AgentID.OPENCODE,
            prompt_strategy=SystemPromptStrategy.MARKDOWN_SECTIONS,
            settings_path=str(settings_file),
        )
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        data = json.loads(settings_file.read_text())
        assert "agent" in data

    def test_merges_settings_for_kilocode(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "content")
        config_dir = tmp_path / ".config" / "opencode"
        config_dir.mkdir(parents=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text("{}")
        adapter = FakeAdapter(
            AgentID.KILOCODE,
            prompt_strategy=SystemPromptStrategy.MARKDOWN_SECTIONS,
            settings_path=str(settings_file),
        )
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        data = json.loads(settings_file.read_text())
        assert "agent" in data

    def test_skips_settings_for_non_opencode(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "content")
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}")
        adapter = FakeAdapter(
            AgentID.CLAUDE_CODE,
            prompt_strategy=SystemPromptStrategy.MARKDOWN_SECTIONS,
            settings_path=str(settings_file),
        )
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        data = json.loads(settings_file.read_text())
        assert "agent" not in data


class TestInjectDxrkOutputStyle:
    def test_injects_output_style(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "content")
        output_dir = tmp_path / ".claude" / "output-styles"
        output_dir.mkdir(parents=True)
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}")
        adapter = FakeAdapter(
            AgentID.CLAUDE_CODE,
            prompt_strategy=SystemPromptStrategy.MARKDOWN_SECTIONS,
            supports_output_styles=True,
            settings_path=str(settings_file),
        )
        result = persona.inject(str(tmp_path), adapter, PersonaID.DXRK)
        assert result.Changed is True
        style_file = output_dir / "dxrk.md"
        assert style_file.exists()
        data = json.loads(settings_file.read_text())
        assert "outputStyle" in data

    def test_skips_output_style_for_non_dxrk(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "neutral content")
        output_dir = tmp_path / ".claude" / "output-styles"
        output_dir.mkdir(parents=True)
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}")
        adapter = FakeAdapter(
            AgentID.CLAUDE_CODE,
            prompt_strategy=SystemPromptStrategy.MARKDOWN_SECTIONS,
            supports_output_styles=True,
            settings_path=str(settings_file),
        )
        result = persona.inject(str(tmp_path), adapter, PersonaID.NEUTRAL)
        style_file = output_dir / "dxrk.md"
        assert not style_file.exists()


class TestInjectLegacyCleanOnInstructionsFile:
    def test_cleans_legacy_vscode_persona(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "content")
        vscode_path = tmp_path / ".github" / "copilot-instructions.md"
        vscode_path.parent.mkdir(parents=True)
        vscode_path.write_text("## Personality\nSenior Architect\n## Rules\n")
        prompt = tmp_path / ".claude" / "instructions.md"
        prompt.parent.mkdir(parents=True)
        adapter = FakeAdapter(
            AgentID.CLAUDE_CODE,
            prompt_strategy=SystemPromptStrategy.INSTRUCTIONS_FILE,
        )

        def system_prompt_file(home_dir):
            return os.path.join(home_dir, ".claude", "instructions.md")

        adapter.system_prompt_file = system_prompt_file
        result = persona.inject(str(tmp_path), adapter, PersonaID.NEUTRAL)
        assert result.Changed is True
        assert not vscode_path.exists()

    def test_handles_oserror_on_legacy_clean(self, monkeypatch, tmp_path):
        monkeypatch.setattr("dxrk.components.persona._must_read", lambda p: "content")
        vscode_path = tmp_path / ".github" / "copilot-instructions.md"
        vscode_path.parent.mkdir(parents=True)
        vscode_path.write_text("## Personality\nSenior Architect\n## Rules\n")
        prompt = tmp_path / ".claude" / "instructions.md"
        prompt.parent.mkdir(parents=True)

        original_open = open

        def failing_open(path, *args, **kwargs):
            if ".github" in str(path):
                raise OSError("access denied")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", failing_open)
        adapter = FakeAdapter(
            AgentID.CLAUDE_CODE,
            prompt_strategy=SystemPromptStrategy.INSTRUCTIONS_FILE,
        )

        def system_prompt_file(home_dir):
            return os.path.join(home_dir, ".claude", "instructions.md")

        adapter.system_prompt_file = system_prompt_file
        result = persona.inject(str(tmp_path), adapter, PersonaID.NEUTRAL)
        assert result.Changed is True


# ═══════════════════════════════════════════════════════════════════════════
# _merge_json_file
# ═══════════════════════════════════════════════════════════════════════════


class TestMergeJsonFile:
    def test_path_exists(self, tmp_path):
        target = tmp_path / "settings.json"
        target.write_text('{"existing": true}')
        overlay = json.dumps({"new": "value"}).encode()
        wr, merged = persona._merge_json_file(str(target), overlay)
        assert wr.Changed is True
        data = json.loads(merged)
        assert data["existing"] is True
        assert data["new"] == "value"

    def test_path_not_exists(self, tmp_path):
        target = tmp_path / "new.json"
        overlay = json.dumps({"key": "val"}).encode()
        wr, merged = persona._merge_json_file(str(target), overlay)
        assert wr.Changed is True
        data = json.loads(merged)
        assert data["key"] == "val"

    def test_empty_base(self, tmp_path):
        target = tmp_path / "empty.json"
        target.write_text("")
        overlay = json.dumps({"key": "val"}).encode()
        wr, merged = persona._merge_json_file(str(target), overlay)
        assert wr.Changed is True
        data = json.loads(merged)
        assert data["key"] == "val"


# ═══════════════════════════════════════════════════════════════════════════
# _os_read_file
# ═══════════════════════════════════════════════════════════════════════════


class TestOsReadFile:
    def test_exists(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello")
        assert persona._os_read_file(str(f)) == b"hello"

    def test_not_found(self, tmp_path):
        assert persona._os_read_file(str(tmp_path / "nonexistent")) == b""

    def test_os_error(self, monkeypatch, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"data")

        def failing_open(*args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr("builtins.open", failing_open)
        with pytest.raises(OSError):
            persona._os_read_file(str(f))


# ═══════════════════════════════════════════════════════════════════════════
# _read_file_or_empty
# ═══════════════════════════════════════════════════════════════════════════


class TestReadFileOrEmpty:
    def test_exists(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content")
        assert persona._read_file_or_empty(str(f)) == "content"

    def test_not_found(self, tmp_path):
        assert persona._read_file_or_empty(str(tmp_path / "nope")) == ""
