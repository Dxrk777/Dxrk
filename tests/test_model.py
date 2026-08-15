# SPDX-License-Identifier: MIT

"""Tests for dxrk.model (mirrors internal/model tests)."""

import pytest

from dxrk.model import (
    AgentClaudeCode,
    AgentCodex,
    AgentID,
    AgentZCode,
    ClaudeModelAlias,
    ClaudeModelHaiku,
    ClaudeModelOpus,
    ClaudeModelSonnet,
    ComponentDxrkMemory,
    ComponentID,
    ComponentInternalMCPServer,
    DxrkMemoryUninstallScopeGlobal,
    DxrkMemoryUninstallScopeProject,
    MCPStrategy,
    ModelAssignment,
    OpenCodePluginDxrkLogo,
    OpenCodePluginSDDDxrkMemoryManage,
    OpenCodePluginSubAgentStatusline,
    PersonaCustom,
    PersonaDxrk,
    PersonaNeutral,
    Plan,
    PlanStatusFailed,
    PlanStatusPending,
    PlanStatusRunning,
    PlanStatusSucceeded,
    PlanStep,
    PresetCustom,
    PresetEcosystemOnly,
    PresetFullDxrk,
    PresetMinimal,
    Profile,
    RunResultFailed,
    RunResultSkipped,
    RunResultSuccess,
    SDDModeMulti,
    SDDModeSingle,
    SDDProfileStrategyExternalSingleActive,
    SDDProfileStrategyGeneratedMulti,
    SDDProfileStrategyID,
    Selection,
    SkillID,
    SkillPythonPro,
    SkillSDDApply,
    SkillSDDArchive,
    SkillSDDDesign,
    SkillSDDExplore,
    SkillSDDInit,
    SkillSDDPropose,
    SkillSDDSpec,
    SkillSDDTasks,
    SkillSDDVerify,
    SupportTier,
    SyncOverrides,
    SystemPromptStrategy,
    StrategyAppendToFile,
    StrategyFileReplace,
    StrategyInstructionsFile,
    StrategyJinjaModules,
    StrategyMarkdownSections,
    StrategyMCPConfigFile,
    StrategyMergeIntoSettings,
    StrategySeparateMCPFiles,
    StrategySteeringFile,
    StrategyTOMLFile,
    TierFull,
    UninstallModeCleanInstall,
    UninstallModeFull,
    UninstallModeFullRemove,
    UninstallModePartial,
    claude_model_default_key,
    claude_model_preset_balanced,
    claude_model_preset_economy,
    claude_model_preset_performance,
    kiro_model_id,
)


def test_agent_catalog_sample():
    assert AgentClaudeCode == "claude-code"
    assert AgentZCode == "zcode"
    assert AgentID == str


def test_support_tier():
    assert TierFull == "full"
    assert SupportTier == str


def test_component_catalog_sample():
    assert ComponentDxrkMemory == "dxrk-memory"
    assert ComponentInternalMCPServer == "internal-mcp-server"
    assert ComponentID == str


def test_uninstall_modes():
    assert UninstallModePartial == "partial"
    assert UninstallModeFull == "full"
    assert UninstallModeFullRemove == "full-remove"
    assert UninstallModeCleanInstall == "clean-install"


def test_dxrk_memory_uninstall_scopes():
    assert DxrkMemoryUninstallScopeGlobal == "global"
    assert DxrkMemoryUninstallScopeProject == "project"


def test_skill_catalog_sample():
    assert SkillSDDInit == "sdd-init"
    assert SkillSDDApply == "sdd-apply"
    assert SkillSDDVerify == "sdd-verify"
    assert SkillSDDExplore == "sdd-explore"
    assert SkillSDDPropose == "sdd-propose"
    assert SkillSDDSpec == "sdd-spec"
    assert SkillSDDDesign == "sdd-design"
    assert SkillSDDTasks == "sdd-tasks"
    assert SkillSDDArchive == "sdd-archive"
    assert SkillPythonPro == "python-pro"
    assert SkillID == str


def test_persona_catalog():
    assert PersonaDxrk == "dxrk"
    assert PersonaNeutral == "neutral"
    assert PersonaCustom == "custom"


def test_system_prompt_strategy_aliases():
    assert SystemPromptStrategy.MARKDOWN_SECTIONS == 0
    assert SystemPromptStrategy.FILE_REPLACE == 1
    assert SystemPromptStrategy.APPEND_TO_FILE == 2
    assert SystemPromptStrategy.INSTRUCTIONS_FILE == 3
    assert SystemPromptStrategy.JINJA_MODULES == 4
    assert SystemPromptStrategy.STEERING_FILE == 5
    assert StrategyMarkdownSections is SystemPromptStrategy.MARKDOWN_SECTIONS
    assert StrategySteeringFile is SystemPromptStrategy.STEERING_FILE


def test_mcp_strategy_aliases():
    assert MCPStrategy.SEPARATE_MCP_FILES == 0
    assert MCPStrategy.MERGE_INTO_SETTINGS == 1
    assert MCPStrategy.MCP_CONFIG_FILE == 2
    assert MCPStrategy.TOML_FILE == 3
    assert StrategyTOMLFile is MCPStrategy.TOML_FILE


def test_preset_catalog():
    assert PresetFullDxrk == "full-dxrk"
    assert PresetEcosystemOnly == "ecosystem-only"
    assert PresetMinimal == "minimal"
    assert PresetCustom == "custom"


def test_sdd_mode_catalog():
    assert SDDModeSingle == "single"
    assert SDDModeMulti == "multi"


def test_sdd_profile_strategy_catalog():
    assert SDDProfileStrategyGeneratedMulti == "generated-multi"
    assert SDDProfileStrategyExternalSingleActive == "external-single-active"
    assert SDDProfileStrategyID == str


def test_opencode_plugin_catalog():
    assert OpenCodePluginSubAgentStatusline == "sub-agent-statusline"
    assert OpenCodePluginSDDDxrkMemoryManage == "sdd-dxrk-memory-plugin"
    assert OpenCodePluginDxrkLogo == "dxrk-logo"


def test_claude_model_alias_values():
    assert ClaudeModelOpus == "opus"
    assert ClaudeModelSonnet == "sonnet"
    assert ClaudeModelHaiku == "haiku"
    assert ClaudeModelAlias.OPUS.value == "opus"
    assert ClaudeModelAlias.SONNET.value == "sonnet"
    assert ClaudeModelAlias.HAIKU.value == "haiku"


def test_claude_model_alias_valid():
    assert ClaudeModelOpus.valid() is True
    assert ClaudeModelSonnet.valid() is True
    assert ClaudeModelHaiku.valid() is True


def test_claude_model_alias_invalid_raises():
    with pytest.raises(ValueError):
        ClaudeModelAlias("invalid")


def test_claude_model_alias_str_coercion():
    assert str(ClaudeModelOpus) == "ClaudeModelAlias.OPUS"
    assert f"{ClaudeModelSonnet}" == "ClaudeModelAlias.SONNET"


def test_claude_model_default_key():
    assert claude_model_default_key == "default"


def test_preset_balanced():
    preset = claude_model_preset_balanced()
    assert set(preset) == {
        SkillSDDExplore,
        SkillSDDPropose,
        SkillSDDSpec,
        SkillSDDDesign,
        SkillSDDTasks,
        SkillSDDApply,
        SkillSDDVerify,
        SkillSDDArchive,
        claude_model_default_key,
    }
    assert preset[SkillSDDExplore] == ClaudeModelSonnet
    assert preset[SkillSDDPropose] == ClaudeModelOpus
    assert preset[SkillSDDSpec] == ClaudeModelSonnet
    assert preset[SkillSDDDesign] == ClaudeModelOpus
    assert preset[SkillSDDTasks] == ClaudeModelSonnet
    assert preset[SkillSDDApply] == ClaudeModelSonnet
    assert preset[SkillSDDVerify] == ClaudeModelSonnet
    assert preset[SkillSDDArchive] == ClaudeModelHaiku
    assert preset[claude_model_default_key] == ClaudeModelSonnet


def test_preset_performance():
    preset = claude_model_preset_performance()
    assert set(preset) == set(claude_model_preset_balanced())
    assert preset[SkillSDDVerify] == ClaudeModelOpus
    assert preset[SkillSDDPropose] == ClaudeModelOpus
    assert preset[SkillSDDArchive] == ClaudeModelHaiku
    assert preset[claude_model_default_key] == ClaudeModelSonnet


def test_preset_economy():
    preset = claude_model_preset_economy()
    assert set(preset) == set(claude_model_preset_balanced())
    for key in (
        SkillSDDExplore,
        SkillSDDPropose,
        SkillSDDSpec,
        SkillSDDDesign,
        SkillSDDTasks,
        SkillSDDApply,
        SkillSDDVerify,
        claude_model_default_key,
    ):
        assert preset[key] == ClaudeModelSonnet
    assert preset[SkillSDDArchive] == ClaudeModelHaiku


def test_preset_values_are_valid_aliases():
    for preset in (
        claude_model_preset_balanced(),
        claude_model_preset_performance(),
        claude_model_preset_economy(),
    ):
        for alias in preset.values():
            assert alias.valid() is True


def test_kiro_model_id():
    assert kiro_model_id(ClaudeModelOpus) == "claude-opus-4.6"
    assert kiro_model_id(ClaudeModelHaiku) == "claude-haiku-4.5"
    assert kiro_model_id(ClaudeModelSonnet) == "claude-sonnet-4.6"


def test_model_assignment_full_id():
    assignment = ModelAssignment(
        ProviderID="anthropic",
        ModelID="claude-sonnet-4-20250514",
    )
    assert assignment.full_id() == "anthropic/claude-sonnet-4-20250514"
    assert assignment.Effort == ""


def test_model_assignment_effort():
    assignment = ModelAssignment(
        ProviderID="anthropic",
        ModelID="claude-sonnet-4-20250514",
        Effort="high",
    )
    assert assignment.Effort == "high"


def test_selection_has_agent():
    selection = Selection(
        Agents=[AgentClaudeCode, AgentZCode],
        Components=[ComponentDxrkMemory],
        Skills=[SkillSDDInit],
        Persona=PersonaDxrk,
        Preset=PresetFullDxrk,
        SDDMode=SDDModeSingle,
        SDDProfileStrategy=SDDProfileStrategyGeneratedMulti,
    )
    assert selection.has_agent(AgentClaudeCode) is True
    assert selection.has_agent(AgentCodex) is False


def test_selection_has_component():
    selection = Selection(
        Agents=[AgentClaudeCode],
        Components=[ComponentDxrkMemory, ComponentInternalMCPServer],
        Skills=[SkillSDDInit],
        Persona=PersonaDxrk,
        Preset=PresetFullDxrk,
        SDDMode=SDDModeSingle,
        SDDProfileStrategy=SDDProfileStrategyGeneratedMulti,
    )
    assert selection.has_component(ComponentDxrkMemory) is True
    assert selection.has_component(ComponentInternalMCPServer) is True


def test_selection_strict_tdd_default():
    selection = Selection(
        Agents=[],
        Components=[],
        Skills=[],
        Persona=PersonaDxrk,
        Preset=PresetFullDxrk,
        SDDMode=SDDModeSingle,
        SDDProfileStrategy=SDDProfileStrategyGeneratedMulti,
    )
    assert selection.StrictTDD is False
    assert selection.ModelAssignments == {}
    assert selection.ClaudeModelAssignments == {}
    assert selection.KiroModelAssignments == {}
    assert selection.Profiles == []
    assert selection.OpenCodePlugins == []


def test_sync_overrides_defaults():
    overrides = SyncOverrides()
    assert overrides.TargetAgents == []
    assert overrides.ModelAssignments is None
    assert overrides.ClaudeModelAssignments is None
    assert overrides.KiroModelAssignments is None
    assert overrides.SDDMode == ""
    assert overrides.SDDProfileStrategy == ""
    assert overrides.StrictTDD is None
    assert overrides.Profiles == []


def test_sync_overrides_empty_dict_resets():
    overrides = SyncOverrides(ModelAssignments={})
    assert overrides.ModelAssignments == {}


def test_profile():
    assignment = ModelAssignment(
        ProviderID="anthropic", ModelID="claude-opus-4-20250514"
    )
    profile = Profile(
        Name="codex",
        OrchestratorModel=assignment,
        PhaseAssignments={"sdd-apply": assignment},
    )
    assert profile.Name == "codex"
    assert profile.OrchestratorModel is assignment
    assert profile.PhaseAssignments["sdd-apply"] is assignment


def test_plan_status_constants():
    assert PlanStatusPending == "pending"
    assert PlanStatusRunning == "running"
    assert PlanStatusSucceeded == "succeeded"
    assert PlanStatusFailed == "failed"


def test_run_result_constants():
    assert RunResultSkipped == "skipped"
    assert RunResultSuccess == "success"
    assert RunResultFailed == "failed"


def test_plan_and_steps():
    selection = Selection(
        Agents=[AgentClaudeCode],
        Components=[],
        Skills=[],
        Persona=PersonaDxrk,
        Preset=PresetMinimal,
        SDDMode=SDDModeMulti,
        SDDProfileStrategy=SDDProfileStrategyExternalSingleActive,
    )
    step = PlanStep(
        ID="step-1",
        Name="install claude-code",
        Status=PlanStatusSucceeded,
        Result=RunResultSuccess,
    )
    plan = Plan(
        ID="plan-1",
        Selection=selection,
        Status=PlanStatusPending,
        Steps=[step],
    )
    assert plan.ID == "plan-1"
    assert plan.Selection is selection
    assert plan.Status == "pending"
    assert plan.Steps == [step]
    assert step.Error == ""


def test_plan_step_error():
    step = PlanStep(
        ID="step-2",
        Name="install codex",
        Status=PlanStatusFailed,
        Result=RunResultFailed,
        Error="boom",
    )
    assert step.Error == "boom"
