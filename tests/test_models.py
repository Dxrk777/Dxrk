# SPDX-License-Identifier: MIT
from __future__ import annotations

from dxrk.models import (
    AGENTS,
    COMPONENTS,
    AgentID,
    ClaudeModelAlias,
    ComponentID,
    MCPStrategy,
    ModelAssignment,
    OpenCodeCommunityPluginID,
    PersonaID,
    Plan,
    PlanStatus,
    PlanStep,
    PresetID,
    Profile,
    RunResult,
    SDDModeID,
    SDDProfileStrategyID,
    Selection,
    SkillID,
    SupportTier,
    SyncOverrides,
    SystemPromptStrategy,
    UninstallMode,
    claude_model_preset_balanced,
    claude_model_preset_economy,
    claude_model_preset_performance,
)


def test_agent_ids_all_unique():
    values = [a.value for a in AgentID]
    assert len(values) == len(set(values))


def test_agent_ids_count():
    assert len(AgentID) == 14


def test_component_ids_all_unique():
    values = [c.value for c in ComponentID]
    assert len(values) == len(set(values))


def test_component_ids_count():
    assert len(ComponentID) == 11


def test_skill_ids_all_unique():
    values = [s.value for s in SkillID]
    assert len(values) == len(set(values))


def test_skill_ids_count():
    assert len(SkillID) == 351


def test_shorthand_aliases():
    assert AgentID.CLAUDE_CODE.value == "claude-code"
    assert AgentID.OPENCODE.value == "opencode"
    assert AgentID.KILOCODE.value == "kilocode"
    assert AgentID.GEMINI_CLI.value == "gemini-cli"
    assert AgentID.CURSOR.value == "cursor"
    assert AgentID.VSCODE_COPILOT.value == "vscode-copilot"
    assert AgentID.CODEX.value == "codex"
    assert AgentID.ANTIGRAVITY.value == "antigravity"
    assert AgentID.WINDSURF.value == "windsurf"
    assert AgentID.KIMI.value == "kimi"
    assert AgentID.QWEN_CODE.value == "qwen-code"
    assert AgentID.KIRO_IDE.value == "kiro-ide"
    assert AgentID.OPENCLAW.value == "openclaw"
    assert AgentID.PI.value == "pi"


def test_component_shorthand_aliases():
    assert ComponentID.DXRK_MEMORY.value == "DXRK_MEMORY"
    assert ComponentID.SDD.value == "sdd"
    assert ComponentID.SKILLS.value == "skills"
    assert ComponentID.CONTEXT7.value == "context7"
    assert ComponentID.PERSONA.value == "persona"
    assert ComponentID.PERMISSIONS.value == "permissions"
    assert ComponentID.DXRK_GUARDIAN.value == "DXRK_GUARDIAN"
    assert ComponentID.THEME.value == "theme"


def test_agents_list_contains_all():
    assert len(AGENTS) == 14
    assert AgentID.CLAUDE_CODE in AGENTS
    assert AgentID.PI in AGENTS
    assert AgentID.OPENCLAW in AGENTS


def test_components_list_contains_all():
    assert len(COMPONENTS) == 10
    assert ComponentID.DXRK_MEMORY in COMPONENTS
    assert ComponentID.OPENCODE_DXRK_LOGO in COMPONENTS


def test_claude_model_alias_valid():
    assert ClaudeModelAlias.OPUS.valid()
    assert ClaudeModelAlias.SONNET.valid()
    assert ClaudeModelAlias.HAIKU.valid()


def test_preset_balanced():
    presets = claude_model_preset_balanced()
    assert presets["orchestrator"] == ClaudeModelAlias.OPUS
    assert presets["default"] == ClaudeModelAlias.SONNET


def test_preset_performance():
    presets = claude_model_preset_performance()
    assert presets["sdd-verify"] == ClaudeModelAlias.OPUS
    assert presets["default"] == ClaudeModelAlias.SONNET


def test_preset_economy():
    presets = claude_model_preset_economy()
    assert presets["orchestrator"] == ClaudeModelAlias.SONNET
    for phase in ["sdd-apply", "sdd-spec", "sdd-explore"]:
        assert presets[phase] == ClaudeModelAlias.SONNET


def test_persona_ids():
    assert PersonaID.DXRK.value == "dxrk"
    assert PersonaID.NEUTRAL.value == "neutral"
    assert PersonaID.CUSTOM.value == "custom"


def test_system_prompt_strategies():
    assert SystemPromptStrategy.MARKDOWN_SECTIONS == 0
    assert SystemPromptStrategy.FILE_REPLACE == 1
    assert SystemPromptStrategy.APPEND_TO_FILE == 2
    assert SystemPromptStrategy.INSTRUCTIONS_FILE == 3
    assert SystemPromptStrategy.JINJA_MODULES == 4
    assert SystemPromptStrategy.STEERING_FILE == 5


def test_mcp_strategies():
    assert MCPStrategy.SEPARATE_MCP_FILES == 0
    assert MCPStrategy.MERGE_INTO_SETTINGS == 1
    assert MCPStrategy.MCP_CONFIG_FILE == 2
    assert MCPStrategy.TOML_FILE == 3


def test_preset_ids():
    assert PresetID.FULL_DXRK.value == "full-dxrk"
    assert PresetID.ECOSYSTEM_ONLY.value == "ecosystem-only"
    assert PresetID.MINIMAL.value == "minimal"
    assert PresetID.CUSTOM.value == "custom"


def test_sdd_mode_ids():
    assert SDDModeID.SINGLE.value == "single"
    assert SDDModeID.MULTI.value == "multi"


def test_uninstall_modes():
    assert UninstallMode.PARTIAL.value == "partial"
    assert UninstallMode.FULL.value == "full"
    assert UninstallMode.FULL_REMOVE.value == "full-remove"
    assert UninstallMode.CLEAN_INSTALL.value == "clean-install"


def test_support_tier():
    assert SupportTier.FULL.value == "full"


def test_open_code_plugins():
    assert (
        OpenCodeCommunityPluginID.SUB_AGENT_STATUSLINE.value == "sub-agent-statusline"
    )
    assert OpenCodeCommunityPluginID.SDD_ENGRAM_PLUGIN.value == "sdd-DXRK_MEMORY-plugin"


def test_plan_status():
    assert PlanStatus.PENDING.value == "pending"
    assert PlanStatus.RUNNING.value == "running"
    assert PlanStatus.SUCCEEDED.value == "succeeded"
    assert PlanStatus.FAILED.value == "failed"


def test_run_result():
    assert RunResult.SKIPPED.value == "skipped"
    assert RunResult.SUCCESS.value == "success"
    assert RunResult.FAILED.value == "failed"


def test_sdd_profile_strategies():
    assert SDDProfileStrategyID.GENERATED_MULTI.value == "generated-multi"
    assert SDDProfileStrategyID.EXTERNAL_SINGLE_ACTIVE.value == "external-single-active"


def test_model_assignment_full_id():
    m = ModelAssignment(provider_id="opencode", model_id="sonnet")
    assert m.full_id() == "opencode/sonnet"


def test_model_assignment_empty():
    m = ModelAssignment()
    assert m.full_id() == "/"


def test_profile_defaults():
    p = Profile(name="test")
    assert p.name == "test"
    assert p.orchestrator_model.provider_id == ""
    assert p.phase_assignments == {}


class TestSelection:
    def test_default_creation(self):
        s = Selection()
        assert s.agents == []
        assert s.persona == PersonaID.DXRK
        assert s.preset == PresetID.FULL_DXRK
        assert s.sdd_mode == SDDModeID.SINGLE
        assert s.strict_tdd is False

    def test_has_agent_true(self):
        s = Selection(agents=[AgentID.CLAUDE_CODE])
        assert s.has_agent(AgentID.CLAUDE_CODE)

    def test_has_agent_false(self):
        s = Selection(agents=[AgentID.CLAUDE_CODE])
        assert not s.has_agent(AgentID.OPENCODE)

    def test_has_component_true(self):
        s = Selection(components=[ComponentID.DXRK_MEMORY])
        assert s.has_component(ComponentID.DXRK_MEMORY)

    def test_has_component_false(self):
        s = Selection(components=[ComponentID.DXRK_MEMORY])
        assert not s.has_component(ComponentID.SDD)


def test_sync_overrides_defaults():
    s = SyncOverrides()
    assert s.model_assignments is None
    assert s.profiles == []


def test_sync_overrides_with_values():
    s = SyncOverrides(
        sdd_mode=SDDModeID.MULTI,
        strict_tdd=True,
        profiles=[Profile(name="p1")],
    )
    assert s.sdd_mode == SDDModeID.MULTI
    assert s.strict_tdd is True
    assert len(s.profiles) == 1


def test_plan_step_defaults():
    ps = PlanStep()
    assert ps.id == ""
    assert ps.status == PlanStatus.PENDING
    assert ps.result == RunResult.SKIPPED


def test_plan_creation():
    ps = PlanStep(id="step1", name="test step", status=PlanStatus.RUNNING)
    plan = Plan(
        id="plan1",
        selection=Selection(agents=[AgentID.CLAUDE_CODE]),
        status=PlanStatus.RUNNING,
        steps=[ps],
    )
    assert plan.id == "plan1"
    assert plan.selection.has_agent(AgentID.CLAUDE_CODE)
    assert plan.steps[0].name == "test step"
