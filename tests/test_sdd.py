# SPDX-License-Identifier: MIT
from __future__ import annotations

import json

from dxrk.components import sdd
from dxrk.models import (
    AgentID, ModelAssignment, PersonaID, Profile, SDDModeID, SDDProfileStrategyID,
    ClaudeModelAlias,
)

import pytest


class TestValidateProfileName:
    def test_valid_names(self):
        assert sdd.validate_profile_name("cheap") is None
        assert sdd.validate_profile_name("premium") is None
        assert sdd.validate_profile_name("my-profile") is None

    def test_invalid_names(self):
        assert sdd.validate_profile_name("") is not None
        assert sdd.validate_profile_name("-leading") is not None
        assert sdd.validate_profile_name("UPPERCASE") is not None


class TestProfilePhaseOrder:
    def test_returns_ordered_phases(self):
        phases = sdd.profile_phase_order()
        assert len(phases) >= 9
        assert phases[0] == "sdd-init"
        assert phases[-1] == "sdd-onboard"
        assert "sdd-apply" in phases


class TestResolveProfileStrategy:
    def test_resolves_to_generated_multi_by_default(self, tmp_path):
        result = sdd.resolve_profile_strategy(str(tmp_path), SDDProfileStrategyID.GENERATED_MULTI)
        assert result == SDDProfileStrategyID.GENERATED_MULTI

    def test_resolves_to_explicit_value(self, tmp_path):
        result = sdd.resolve_profile_strategy(
            str(tmp_path), SDDProfileStrategyID.EXTERNAL_SINGLE_ACTIVE
        )
        assert result == SDDProfileStrategyID.EXTERNAL_SINGLE_ACTIVE


class TestProfileAgentKeys:
    def test_generates_keys(self):
        keys = sdd.profile_agent_keys("test")
        assert "sdd-orchestrator-test" in keys
        assert "sdd-init-test" in keys
        assert "sdd-apply-test" in keys


class TestProfileOverlay:
    def test_generate_overlay(self, tmp_path):
        profile = Profile(
            name="test",
            orchestrator_model=ModelAssignment(provider_id="opencode", model_id="qwen3.6-plus-free"),
        )
        overlay = sdd.generate_profile_overlay(profile, str(tmp_path))
        decoded = json.loads(overlay)
        assert "agent" in decoded
        agent_keys = list(decoded["agent"].keys())
        assert any("test" in k for k in agent_keys)

    def test_raises_for_default_name(self):
        profile = Profile(name="default")
        with pytest.raises(ValueError):
            sdd.generate_profile_overlay(profile, "/tmp")


class TestDetectProfiles:
    def test_returns_empty_when_no_settings(self, tmp_path):
        profiles = sdd.detect_profiles(str(tmp_path / "nonexistent.json"))
        assert profiles == []


class TestReadCurrentProfiles:
    def test_returns_empty_when_no_settings(self, tmp_path):
        profiles = sdd.read_current_profiles(str(tmp_path / "nonexistent.json"))
        assert profiles == []


class TestReadCurrentModelAssignments:
    def test_returns_empty_when_no_settings(self, tmp_path):
        assignments = sdd.read_current_model_assignments(str(tmp_path / "nonexistent.json"))
        assert assignments == {}


class TestInject:
    def test_inject_minimal_opencode(self, tmp_path):
        from dxrk.agents.opencode.adapter import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        result = sdd.inject(
            home_dir=str(tmp_path),
            adapter=adapter,
            selected_agents=[AgentID.OPENCODE],
            selected_components=None,
            sdd_mode=SDDModeID.SINGLE,
            persona=PersonaID.DXRK,
            profile=None,
            claude_model_assignments=None,
            kiro_model_assignments=None,
            model_assignments=None,
            strict_tdd=False,
        )
        assert result.Changed is True
        settings = tmp_path / ".config" / "opencode" / "settings.json"
        assert settings.exists()

    def test_inject_minimal_claude(self, tmp_path):
        from dxrk.agents.claude.adapter import ClaudeAdapter
        adapter = ClaudeAdapter()
        result = sdd.inject(
            home_dir=str(tmp_path),
            adapter=adapter,
            selected_agents=[AgentID.CLAUDE_CODE],
            selected_components=None,
            sdd_mode=SDDModeID.SINGLE,
            persona=PersonaID.DXRK,
            profile=None,
            claude_model_assignments=None,
            kiro_model_assignments=None,
            model_assignments=None,
            strict_tdd=False,
        )
        assert result.Changed is True
        claude_md = tmp_path / ".claude" / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "sdd-orchestrator" in content


class TestClaudeModelAlias:
    def test_resolve_claude_model_alias(self):
        from dxrk.components.sdd import _resolve_claude_model_alias
        alias = _resolve_claude_model_alias(
            {"sdd-init": "claude-sonnet-4-20250514"},
            "sdd-init",
        )
        assert alias == ClaudeModelAlias.SONNET

    def test_resolve_defaults_to_sonnet(self):
        from dxrk.components.sdd import _resolve_claude_model_alias
        alias = _resolve_claude_model_alias({}, "unknown-phase")
        assert alias == ClaudeModelAlias.SONNET
