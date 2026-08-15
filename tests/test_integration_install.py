# SPDX-License-Identifier: MIT
from __future__ import annotations

from dxrk.cli import install as install_mod
from dxrk.models import (
    AgentID,
    ComponentID,
    PresetID,
    Selection,
    SkillID,
    SDDModeID,
    SDDProfileStrategyID,
    PersonaID,
    ModelAssignment,
)
from dxrk.system import DetectionResult, PlatformProfile, SystemInfo, DependencyReport
from dxrk.planner import ResolvedPlan, ReviewPayload, PlatformDecision

import pytest


def _make_detection() -> DetectionResult:
    return DetectionResult(
        system=SystemInfo(
            os="darwin",
            arch="arm64",
            shell="/bin/zsh",
            supported=True,
            profile=PlatformProfile(
                os="darwin", package_manager="brew", supported=True
            ),
        ),
    )


class TestRunInstallDryRun:
    def test_returns_result_with_dry_run_flag(self):
        result = install_mod.run_install(["--dry-run"], _make_detection())
        assert result.dry_run is True

    def test_includes_selection(self):
        result = install_mod.run_install(["--dry-run"], _make_detection())
        assert result.selection is not None
        assert result.selection.preset == PresetID.FULL_DXRK

    def test_includes_review(self):
        result = install_mod.run_install(["--dry-run"], _make_detection())
        assert result.review is not None

    def test_includes_resolved_plan(self):
        result = install_mod.run_install(["--dry-run"], _make_detection())
        assert result.resolved is not None

    def test_minimal_preset(self):
        result = install_mod.run_install(
            ["--dry-run", "--preset", "minimal"], _make_detection()
        )
        assert result.dry_run is True
        assert result.selection.preset == PresetID.MINIMAL

    def test_ecosystem_preset(self):
        result = install_mod.run_install(
            ["--dry-run", "--preset", "ecosystem-only"], _make_detection()
        )
        assert result.selection.preset == PresetID.ECOSYSTEM_ONLY

    def test_with_agent_flag(self):
        result = install_mod.run_install(
            ["--dry-run", "--agents", "claude-code"], _make_detection()
        )
        assert AgentID.CLAUDE_CODE in result.selection.agents

    def test_with_component_flag(self):
        result = install_mod.run_install(
            ["--dry-run", "--components", "DXRK_MEMORY"], _make_detection()
        )
        assert ComponentID.DXRK_MEMORY in result.selection.components

    def test_with_skills_flag(self):
        result = install_mod.run_install(
            ["--dry-run", "--skills", "go-testing"], _make_detection()
        )
        assert SkillID.GO_TESTING in result.selection.skills

    def test_multiple_agents(self):
        result = install_mod.run_install(
            ["--dry-run", "--agents", "claude-code,opencode"], _make_detection()
        )
        assert AgentID.CLAUDE_CODE in result.selection.agents
        assert AgentID.OPENCODE in result.selection.agents


class TestBuildStagePlan:
    def test_returns_stage_plan(self):
        selection = Selection(
            agents=[AgentID.CLAUDE_CODE], components=[ComponentID.DXRK_MEMORY]
        )
        resolved = ResolvedPlan(
            agents=[AgentID.CLAUDE_CODE],
            ordered_components=[ComponentID.DXRK_MEMORY],
        )
        plan = install_mod.build_stage_plan(selection, resolved)
        assert plan is not None
        assert len(plan.prepare) == 2
        assert len(plan.apply) >= 1

    def test_empty_selection(self):
        selection = Selection()
        resolved = ResolvedPlan()
        plan = install_mod.build_stage_plan(selection, resolved)
        assert len(plan.prepare) == 0
        assert len(plan.apply) == 0


class TestResolveInstallProfile:
    def test_uses_detection_profile(self):
        detection = _make_detection()
        profile = install_mod.resolve_install_profile(detection)
        assert profile.os == "darwin"
        assert profile.package_manager == "brew"

    def test_fallback_when_empty(self):
        detection = DetectionResult()
        profile = install_mod.resolve_install_profile(detection)
        assert profile.os == "darwin"


class TestRenderDryRun:
    def test_renders_dry_run_output(self):
        selection = Selection(
            agents=[AgentID.CLAUDE_CODE],
            components=[ComponentID.DXRK_MEMORY, ComponentID.SDD],
            preset=PresetID.FULL_DXRK,
        )
        resolved = ResolvedPlan(
            agents=[AgentID.CLAUDE_CODE],
            ordered_components=[ComponentID.DXRK_MEMORY, ComponentID.SDD],
        )
        result = install_mod.InstallResult(
            selection=selection,
            resolved=resolved,
            dry_run=True,
        )
        output = install_mod.render_dry_run(result)
        assert "claude-code" in output
        assert "DXRK_MEMORY" in output

    def test_dry_run_label_in_output(self):
        selection = Selection(
            preset=PresetID.MINIMAL,
            components=[ComponentID.DXRK_MEMORY],
        )
        resolved = ResolvedPlan(ordered_components=[ComponentID.DXRK_MEMORY])
        result = install_mod.InstallResult(
            selection=selection,
            resolved=resolved,
            dry_run=True,
        )
        output = install_mod.render_dry_run(result)
        assert "DRY RUN" in output or "dry-run" in output or "DRY" in output

    def test_renders_agent_and_component_count(self):
        selection = Selection(
            agents=[AgentID.CLAUDE_CODE, AgentID.OPENCODE],
            components=[
                ComponentID.DXRK_MEMORY,
                ComponentID.SDD,
                ComponentID.DXRK_GUARDIAN,
            ],
            preset=PresetID.FULL_DXRK,
        )
        resolved = ResolvedPlan(
            agents=[AgentID.CLAUDE_CODE, AgentID.OPENCODE],
            ordered_components=[
                ComponentID.DXRK_MEMORY,
                ComponentID.SDD,
                ComponentID.DXRK_GUARDIAN,
            ],
        )
        result = install_mod.InstallResult(
            selection=selection,
            resolved=resolved,
            dry_run=True,
        )
        output = install_mod.render_dry_run(result)
        assert len(output) > 0


class TestNormalizeInstallFlags:
    def test_dry_run_flag(self):
        from dxrk.cli.install import parse_install_flags, normalize_install_flags

        flags = parse_install_flags(["--dry-run"])
        detection = _make_detection()
        inp = normalize_install_flags(flags, detection)
        assert inp.dry_run is True

    def test_minimal_preset(self):
        from dxrk.cli.install import parse_install_flags, normalize_install_flags

        flags = parse_install_flags(["--preset", "minimal"])
        detection = _make_detection()
        inp = normalize_install_flags(flags, detection)
        assert inp.selection.preset == PresetID.MINIMAL

    def test_agents_flag(self):
        from dxrk.cli.install import parse_install_flags, normalize_install_flags

        flags = parse_install_flags(["--agents", "claude-code"])
        detection = _make_detection()
        inp = normalize_install_flags(flags, detection)
        assert AgentID.CLAUDE_CODE in inp.selection.agents
