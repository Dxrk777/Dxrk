# SPDX-License-Identifier: MIT
"""Install/sync/restore/uninstall runtimes, results and entry points."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dxrk.cli.install_flags import (
    SyncFlags,
    UninstallFlags,
    parse_install_flags,
    parse_sync_flags,
    parse_uninstall_flags,
)
from dxrk.cli.install_normalize import _unique, normalize_install_flags
from dxrk.cli.install_steps import (
    AgentInstallStep,
    CheckDependenciesStep,
    ComponentApplyStep,
    KimiSystemPromptHubStep,
    NoopStep,
    OpenCodePluginInstallStep,
    PrepareBackupStep,
    RollbackRestoreStep,
    _resolve_adapters,
    _selected_skill_ids,
)
from dxrk.cli.install_verify import (
    _build_report,
    _render_report,
    _run_checks,
    _VerifyCheck,
    _VerifyReport,
)
from dxrk.models import (
    AgentID,
    ComponentID,
    ModelAssignment,
    PersonaID,
    PresetID,
    SDDModeID,
    SDDProfileStrategyID,
    Selection,
    SkillID,
)
from dxrk.pipeline import Step
from dxrk.planner import (
    PlatformDecision,
    ResolvedPlan,
    ReviewPayload,
    platform_decision_from_profile,
)
from dxrk.state import ModelAssignmentState
from dxrk.system import DetectionResult, PlatformProfile

log = logging.getLogger("dxrk.cli.install")

@dataclass
class RuntimeState:
    manifest: dict[str, Any] = field(default_factory=dict)


class InstallRuntime:
    def __init__(
        self,
        home_dir: str,
        workspace_dir: str,
        selection: Selection,
        resolved: ResolvedPlan,
        profile: PlatformProfile,
        backup_root: str = "",
        app_version: str = "dev",
    ):
        self.home_dir = home_dir
        self.workspace_dir = workspace_dir
        self.selection = selection
        self.resolved = resolved
        self.profile = profile
        self.backup_root = backup_root or os.path.join(home_dir, ".gentle-ai", "backups")
        self.app_version = app_version
        self._state: dict[str, Any] = {}

    def stage_plan(self):
        from dxrk.pipeline import StagePlan

        targets = _backup_targets(self.home_dir, self.selection, self.resolved)

        prepare: list[Step] = [
            CheckDependenciesStep(
                "prepare:check-dependencies",
                self.profile,
                self.home_dir,
                self.selection,
            ),
            PrepareBackupStep(
                step_id="prepare:backup-snapshot",
                snapshot_dir=os.path.join(
                    self.backup_root,
                    datetime.now(UTC).strftime("%Y%m%d%H%M%S.%f"),
                ),
                targets=targets,
                state=self._state,
                backup_root=self.backup_root,
                source="install",
                description="instantánea previa a la instalación",
                app_version=self.app_version,
            ),
        ]

        apply: list[Step] = [
            RollbackRestoreStep("apply:rollback-restore", self._state),
        ]

        for agent in self.resolved.agents:
            if agent == AgentID.KIMI:
                apply.append(KimiSystemPromptHubStep("agent:kimi-prompt-hub", self.home_dir))

        for agent in self.resolved.agents:
            apply.append(AgentInstallStep(f"agent:{agent.value}", agent, self.home_dir, self.profile))

        if any(a == AgentID.OPENCODE for a in self.resolved.agents):
            for plugin in self.selection.opencode_plugins:
                apply.append(
                    OpenCodePluginInstallStep(
                        f"opencode-plugin:{plugin.value}",
                        plugin,
                        self.home_dir,
                    )
                )

        for component in self.resolved.ordered_components:
            apply.append(
                ComponentApplyStep(
                    step_id=f"component:{component.value}",
                    component=component,
                    home_dir=self.home_dir,
                    workspace_dir=self.workspace_dir,
                    agents=self.resolved.agents,
                    selection=self.selection,
                    profile=self.profile,
                )
            )

        if not self.selection.agents and not self.resolved.ordered_components:
            prepare = []

        return StagePlan(prepare=prepare, apply=apply)


def _backup_targets(home_dir: str, selection: Selection, resolved: ResolvedPlan) -> list[str]:
    paths: set[str] = set()
    adapters = _resolve_adapters(resolved.agents)

    for component in resolved.ordered_components:
        for p in _component_paths(home_dir, selection, adapters, component):
            paths.add(p)

    return sorted(paths)


def _component_paths(
    home_dir: str,
    selection: Selection,
    adapters: list[Any],
    component: ComponentID,
) -> list[str]:
    result: list[str] = []
    for adapter in adapters:
        if not adapter:
            continue

        if component == ComponentID.DXRK_MEMORY:
            from dxrk.models import MCPStrategy

            mcps = adapter.mcp_strategy
            if mcps in (MCPStrategy.SEPARATE_MCP_FILES, MCPStrategy.MCP_CONFIG_FILE):
                result.append(adapter.mcp_config_path(home_dir, "DXRK_MEMORY"))
            elif mcps == MCPStrategy.MERGE_INTO_SETTINGS:
                p = adapter.settings_path(home_dir)
                if p:
                    result.append(p)
            elif mcps == MCPStrategy.TOML_FILE:
                p = adapter.mcp_config_path(home_dir, "memory")
                if p:
                    result.append(p)
            from dxrk.models import SystemPromptStrategy

            if adapter.system_prompt_strategy == SystemPromptStrategy.MARKDOWN_SECTIONS:
                result.append(adapter.system_prompt_file(home_dir))

        elif component == ComponentID.CONTEXT7:
            from dxrk.models import MCPStrategy

            mcps = adapter.mcp_strategy
            if mcps in (MCPStrategy.SEPARATE_MCP_FILES,):
                result.append(adapter.mcp_config_path(home_dir, "context7"))
            elif mcps == MCPStrategy.MERGE_INTO_SETTINGS:
                p = adapter.settings_path(home_dir)
                if p:
                    result.append(p)
            elif mcps == MCPStrategy.MCP_CONFIG_FILE:
                p = adapter.mcp_config_path(home_dir, "context7")
                if p:
                    result.append(p)

        elif component == ComponentID.SDD:
            if adapter.supports_system_prompt:
                from dxrk.models import SystemPromptStrategy

                if adapter.system_prompt_strategy != SystemPromptStrategy.JINJA_MODULES:
                    result.append(adapter.system_prompt_file(home_dir))
            if adapter.supports_slash_commands:
                cmd_dir = adapter.commands_dir(home_dir)
                if cmd_dir:
                    result.append(cmd_dir)
            if adapter.agent == AgentID.OPENCODE:
                result.append(adapter.settings_path(home_dir))
                result.append(
                    os.path.join(
                        home_dir,
                        ".config",
                        "opencode",
                        "plugins",
                        "background-agents.ts",
                    )
                )
            if adapter.supports_skills:
                sk_dir = adapter.skills_dir(home_dir)
                if sk_dir:
                    result.append(os.path.join(sk_dir, "_shared"))

        elif component == ComponentID.PERSONA:
            if selection.persona == PersonaID.CUSTOM:
                break
            if adapter.supports_system_prompt:
                from dxrk.models import SystemPromptStrategy

                if adapter.system_prompt_strategy != SystemPromptStrategy.JINJA_MODULES:
                    result.append(adapter.system_prompt_file(home_dir))
            if selection.persona == PersonaID.DXRK:
                if adapter.supports_output_styles:
                    result.append(os.path.join(adapter.output_style_dir(home_dir), "dxrk.md"))
                    p = adapter.settings_path(home_dir)
                    if p:
                        result.append(p)

        elif component == ComponentID.SKILLS:
            skill_ids = _selected_skill_ids(selection)
            for sid in skill_ids:
                from dxrk.components.skills import skill_path_for_agent

                p = skill_path_for_agent(home_dir, adapter, sid)
                if p:
                    result.append(p)

        elif component == ComponentID.PERMISSIONS:
            from dxrk.components import permissions as _permissions

            for p in _permissions.managed_paths(adapter, home_dir):
                result.append(p)

        elif component == ComponentID.DXRK_GUARDIAN:
            from dxrk.components.gga import agents_template_path, config_path

            result.append(config_path(home_dir))
            result.append(agents_template_path(home_dir))

        elif component == ComponentID.THEME:
            p = adapter.settings_path(home_dir)
            if p:
                result.append(p)

    return result


# ─── Sync Runtime ───────────────────────────────────────────────────────────


@dataclass
class SyncResult:
    agents: list[AgentID] = field(default_factory=list)
    selection: Selection = field(default_factory=Selection)
    plan: Any = None
    execution: Any = None
    verify: _VerifyReport = field(default_factory=_VerifyReport)
    dry_run: bool = False
    no_op: bool = False
    files_changed: int = 0


class ComponentSyncStep(Step):
    def __init__(
        self,
        step_id: str,
        component: ComponentID,
        home_dir: str,
        workspace_dir: str,
        agents: list[AgentID],
        selection: Selection,
        files_changed: list[int],
    ):
        self._id = step_id
        self._component = component
        self._home_dir = home_dir
        self._workspace_dir = workspace_dir
        self._agents = agents
        self._selection = selection
        self._files_changed = files_changed

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        adapters = _resolve_adapters(self._agents)
        c = self._component

        if c == ComponentID.DXRK_MEMORY:
            from dxrk.components.memory import inject as memory_inject

            for adapter in adapters:
                res_memory = memory_inject(self._home_dir, adapter)
                self._count_changed(int(res_memory.Changed))
            return None

        if c == ComponentID.CONTEXT7:
            from dxrk.components.context7 import inject as mcp_inject

            for adapter in adapters:
                res_mcp = mcp_inject(self._home_dir, adapter)
                self._count_changed(int(res_mcp.Changed))
            return None

        if c == ComponentID.SDD:
            from dxrk.components.sdd import (
                InjectOptions,
                detect_profiles,
                resolve_profile_strategy,
            )
            from dxrk.components.sdd import (
                inject as sdd_inject,
            )

            profile_strategy = resolve_profile_strategy(self._home_dir, self._selection.sdd_profile_strategy)
            profiles = list(self._selection.profiles)

            if not profiles and profile_strategy != "external-single-active":
                for adapter in adapters:
                    if adapter.agent == AgentID.OPENCODE:
                        settings_path = adapter.settings_path(self._home_dir)
                        if settings_path:
                            try:
                                detected = detect_profiles(settings_path)
                                profiles = detected
                            except Exception:
                                pass
                        break

            sdd_mode = self._selection.sdd_mode
            if profile_strategy == "external-single-active":
                sdd_mode = SDDModeID.MULTI if sdd_mode is None else sdd_mode
            elif profiles and (sdd_mode is None or sdd_mode == ""):
                sdd_mode = SDDModeID.MULTI

            for adapter in adapters:
                opts = InjectOptions(
                    opencode_model_assignments=self._selection.model_assignments,
                    claude_model_assignments=self._selection.claude_model_assignments,
                    kiro_model_assignments=self._selection.kiro_model_assignments,
                    workspace_dir=self._workspace_dir,
                    strict_tdd=self._selection.strict_tdd,
                    preserve_opencode_orchestrator_prompt=(profile_strategy == "external-single-active"),
                    profiles=profiles,
                )
                res_sdd = sdd_inject(
                    self._home_dir,
                    adapter,
                    sdd_mode or SDDModeID.SINGLE,
                    opts,
                )
                self._count_changed(int(res_sdd.Changed))
            return None

        if c == ComponentID.SKILLS:
            skill_ids = _selected_skill_ids(self._selection)
            if not skill_ids:
                return None
            from dxrk.components.skills import inject as skills_inject

            for adapter in adapters:
                res_skills = skills_inject(self._home_dir, adapter, skill_ids)
                self._count_changed(int(res_skills.Changed))
            return None

        if c == ComponentID.DXRK_GUARDIAN:
            from dxrk.components.gga import ensure_runtime_assets
            from dxrk.components.gga import inject as gga_inject

            ensure_runtime_assets(self._home_dir)

            res_gga = gga_inject(self._home_dir, self._agents)
            self._count_changed(int(res_gga.ConfigChanged) + int(res_gga.AgentsChanged))
            return None

        if c == ComponentID.PERMISSIONS:
            from dxrk.components.permissions import inject as perm_inject

            for adapter in adapters:
                res_perms = perm_inject(self._home_dir, adapter)
                self._count_changed(int(res_perms.Changed))
            return None

        if c == ComponentID.THEME:
            from dxrk.components.theme import inject as theme_inject

            for adapter in adapters:
                res_theme = theme_inject(self._home_dir, adapter)
                self._count_changed(int(res_theme.Changed))
            return None

        return None

    def _count_changed(self, n: int) -> None:
        if n > 0 and self._files_changed:
            self._files_changed[0] += n


class SyncRuntime:
    def __init__(
        self,
        home_dir: str,
        workspace_dir: str,
        selection: Selection,
        backup_root: str = "",
        app_version: str = "dev",
    ):
        self.home_dir = home_dir
        self.workspace_dir = workspace_dir
        self.selection = selection
        self.agent_ids = selection.agents
        self.backup_root = backup_root or os.path.join(home_dir, ".gentle-ai", "backups")
        self.app_version = app_version
        self._state: dict[str, Any] = {}
        self.files_changed: list[int] = [0]

    def stage_plan(self):
        from dxrk.pipeline import StagePlan

        adapters = _resolve_adapters(self.agent_ids)
        targets = _sync_backup_targets(self.home_dir, self.selection, adapters)

        prepare: list[Step] = [
            PrepareBackupStep(
                step_id="prepare:backup-snapshot",
                snapshot_dir=os.path.join(
                    self.backup_root,
                    datetime.now(UTC).strftime("%Y%m%d%H%M%S.%f"),
                ),
                targets=targets,
                state=self._state,
                backup_root=self.backup_root,
                source="sync",
                description="instantánea previa a la sincronización",
                app_version=self.app_version,
            ),
        ]

        apply: list[Step] = [
            RollbackRestoreStep("apply:rollback-restore", self._state),
        ]

        for component in self.selection.components:
            apply.append(
                ComponentSyncStep(
                    step_id=f"sync:component:{component.value}",
                    component=component,
                    home_dir=self.home_dir,
                    workspace_dir=self.workspace_dir,
                    agents=self.agent_ids,
                    selection=self.selection,
                    files_changed=self.files_changed,
                )
            )

        return StagePlan(prepare=prepare, apply=apply)


def _sync_backup_targets(home_dir: str, selection: Selection, adapters: list[Any]) -> list[str]:
    paths: set[str] = set()
    for component in selection.components:
        for p in _component_paths(home_dir, selection, adapters, component):
            paths.add(p)
    return sorted(paths)


# ─── InstallResult ──────────────────────────────────────────────────────────


@dataclass
class InstallResult:
    selection: Selection = field(default_factory=Selection)
    resolved: ResolvedPlan | None = None
    review: ReviewPayload | None = None
    plan: Any = None
    execution: Any = None
    verify: _VerifyReport = field(default_factory=_VerifyReport)
    dependencies: Any = None
    dry_run: bool = False
    error: str = ""


# ─── ResolveInstallProfile ─────────────────────────────────────────────────


def resolve_install_profile(detection: DetectionResult) -> PlatformProfile:
    if detection.system.profile.os:
        return detection.system.profile
    return PlatformProfile(os="darwin", package_manager="brew", supported=True)


# ─── BuildStagePlan ─────────────────────────────────────────────────────────


def build_stage_plan(selection: Selection, resolved: ResolvedPlan) -> Any:
    from dxrk.pipeline import StagePlan

    prepare: list[Step] = [
        NoopStep("prepare:system-check"),
        NoopStep("prepare:check-dependencies"),
    ]
    apply: list[Step] = []

    for agent in resolved.agents:
        apply.append(NoopStep(f"agent:{agent.value}"))
    for component in resolved.ordered_components:
        apply.append(NoopStep(f"component:{component.value}"))

    if not selection.agents and not resolved.ordered_components:
        prepare = []

    return StagePlan(prepare=prepare, apply=apply)


app_version = "dev"


# ─── RunInstall ─────────────────────────────────────────────────────────────


def run_install(args: list[str], detection: DetectionResult) -> InstallResult:
    from dxrk.planner import build_review_payload, new_resolver

    flags = parse_install_flags(args)
    input_data = normalize_install_flags(flags, detection)

    resolved = new_resolver().resolve(input_data.selection)
    profile = resolve_install_profile(detection)
    resolved.platform_decision = platform_decision_from_profile(profile)

    review = build_review_payload(input_data.selection, resolved)
    stage_plan = build_stage_plan(input_data.selection, resolved)

    result = InstallResult(
        selection=input_data.selection,
        resolved=resolved,
        review=review,
        plan=stage_plan,
        dry_run=input_data.dry_run,
    )

    if input_data.dry_run:
        return result

    home_dir = os.path.expanduser("~")

    try:
        rt = InstallRuntime(home_dir, os.getcwd(), input_data.selection, resolved, profile)
    except Exception as e:
        return InstallResult(error=str(e))

    from dxrk.system import format_missing_deps_message

    assert detection.dependencies is not None, "la detección no proporcionó dependencias"
    if not detection.dependencies.all_present:
        missing = ", ".join(detection.dependencies.missing_required)
        log.warning(
            "dependencias faltantes: %s\n%s",
            missing,
            format_missing_deps_message(detection.dependencies),
        )

    stage_plan = rt.stage_plan()
    result.plan = stage_plan

    from dxrk.pipeline import default_rollback_policy, new_orchestrator

    orchestrator = new_orchestrator(default_rollback_policy())
    result.execution = orchestrator.execute(stage_plan)

    if result.execution.error:
        return InstallResult(
            selection=result.selection,
            resolved=result.resolved,
            plan=stage_plan,
            execution=result.execution,
            error=f"error al ejecutar el pipeline de install: {result.execution.error}",
        )

    result.verify = _run_post_apply_verification(home_dir, input_data.selection, resolved)
    result.verify = _with_post_install_notes(result.verify, resolved, profile)

    if not result.verify.ready:
        return result

    from dxrk.state import InstallState
    from dxrk.state import write as state_write

    agent_ids = [a.value for a in input_data.selection.agents]
    model_assignments = _model_assignments_to_state(input_data.selection.model_assignments)
    state_write(
        home_dir,
        InstallState(
            installed_agents=agent_ids,
            claude_model_assignments=input_data.selection.claude_model_assignments or None,
            model_assignments=model_assignments,
        ),
    )

    return result


def _with_post_install_notes(report: _VerifyReport, resolved: ResolvedPlan, profile: PlatformProfile) -> _VerifyReport:
    if _has_component(resolved.ordered_components, ComponentID.DXRK_GUARDIAN) and report.ready:
        note = "\n\nDXRK_GUARDIAN ya está instalado globalmente. Para activar los hooks del proyecto, ejecuta en cada repo:\n- DXRK_GUARDIAN init\n- DXRK_GUARDIAN install"
        if note not in report.final_note:
            report.final_note += note
    if _has_component(resolved.ordered_components, ComponentID.DXRK_MEMORY):
        if profile.package_manager != "brew":
            bin_dir = _go_install_bin_dir()
            if not _is_in_path(bin_dir):
                guidance = _memory_path_guidance(os.environ.get("SHELL", ""))
                report.final_note += (
                    f"\n\nEl binario de memoria se instaló en {bin_dir}.\nAgrégalo a tu PATH: {guidance}"
                )
    return report


def _go_install_bin_dir() -> str:
    gobin = os.environ.get("GOBIN")
    if gobin:
        return gobin
    gopath = os.environ.get("GOPATH")
    if gopath:
        return os.path.join(gopath, "bin")
    home = os.path.expanduser("~")
    return os.path.join(home, "go", "bin")


def _is_in_path(dir_path: str) -> bool:
    norm = os.path.normpath(dir_path)
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if os.path.normpath(p) == norm:
            return True
    return False


def _memory_path_guidance(shell_path: str) -> str:
    bin_dir = _go_install_bin_dir()
    if "fish" in shell_path:
        return f"set -Ux fish_user_paths {bin_dir} $fish_user_paths"
    if "zsh" in shell_path:
        return f"echo 'export PATH=\"{bin_dir}:$PATH\"' >> ~/.zshrc && source ~/.zshrc"
    if "bash" in shell_path:
        return f"echo 'export PATH=\"{bin_dir}:$PATH\"' >> ~/.bashrc && source ~/.bashrc"
    return f"Agrega {bin_dir} al PATH de tu shell y reinicia la terminal."


def _has_component(components: list[ComponentID], target: ComponentID) -> bool:
    return target in components


def _contains_agent(agents: list[AgentID], target: AgentID) -> bool:
    return target in agents


# ─── BuildRealStagePlan ─────────────────────────────────────────────────────


def build_real_stage_plan(
    home_dir: str,
    selection: Selection,
    resolved: ResolvedPlan,
    profile: PlatformProfile,
) -> Any:

    backup_root = os.path.join(home_dir, ".gentle-ai", "backups")
    os.makedirs(backup_root, mode=0o755, exist_ok=True)

    try:
        rt = InstallRuntime(home_dir, os.getcwd(), selection, resolved, profile, backup_root=backup_root)
    except Exception as e:
        raise RuntimeError(f"error al crear el runtime de install: {e}") from e
    return rt.stage_plan()


# ─── RunSync ────────────────────────────────────────────────────────────────


def build_sync_selection(flags: SyncFlags, agent_ids: list[AgentID]) -> Selection:
    components: list[ComponentID] = [
        ComponentID.SDD,
        ComponentID.DXRK_MEMORY,
        ComponentID.CONTEXT7,
        ComponentID.DXRK_GUARDIAN,
        ComponentID.SKILLS,
    ]
    if flags.include_permissions:
        components.append(ComponentID.PERMISSIONS)
    if flags.include_theme:
        components.append(ComponentID.THEME)

    sdd_mode = SDDModeID(flags.sdd_mode) if flags.sdd_mode else SDDModeID.SINGLE
    skill_ids = [SkillID(s) for s in flags.skills]

    return Selection(
        agents=agent_ids,
        components=components,
        sdd_mode=sdd_mode,
        sdd_profile_strategy=SDDProfileStrategyID(flags.sdd_profile_strategy)
        if flags.sdd_profile_strategy
        else SDDProfileStrategyID.GENERATED_MULTI,
        strict_tdd=flags.strict_tdd,
        skills=skill_ids,
        preset=PresetID.FULL_DXRK,
    )


def discover_agents(home_dir: str) -> list[AgentID]:
    from dxrk.state import read as state_read

    try:
        s = state_read(home_dir)
        if s.installed_agents:
            return [AgentID(a) for a in s.installed_agents]
    except Exception:
        pass

    from dxrk.agents.discovery import discover_installed
    from dxrk.agents.factory import create_registry

    reg = create_registry()
    installed = discover_installed(reg, home_dir)
    return [a.id for a in installed]


def _to_agent_ids(strings: list[str]) -> list[AgentID]:
    return [AgentID(s) for s in strings]


def run_sync_with_selection(home_dir: str, selection: Selection) -> SyncResult:
    agent_ids = selection.agents

    result = SyncResult(agents=agent_ids, selection=selection)

    if not agent_ids:
        result.no_op = True
        return result

    rt = SyncRuntime(home_dir, os.getcwd(), selection)
    stage_plan = rt.stage_plan()
    result.plan = stage_plan

    from dxrk.pipeline import default_rollback_policy, new_orchestrator

    orchestrator = new_orchestrator(default_rollback_policy())
    result.execution = orchestrator.execute(stage_plan)

    if result.execution.error:
        return result

    result.files_changed = rt.files_changed[0]

    if result.files_changed == 0:
        result.no_op = True

    result.verify = _run_post_sync_verification(home_dir, selection)

    return result


def run_sync(args: list[str]) -> SyncResult:
    flags = parse_sync_flags(args)

    home_dir = os.path.expanduser("~")

    if flags.agents:
        agent_ids = _to_agent_ids(flags.agents)
    else:
        agent_ids = discover_agents(home_dir)
    agent_ids = _unique(agent_ids)

    selection = build_sync_selection(flags, agent_ids)

    from dxrk.state import read as state_read

    try:
        s = state_read(home_dir)
        if s.claude_model_assignments:
            selection.claude_model_assignments = s.claude_model_assignments
        if s.model_assignments:
            selection.model_assignments = {
                k: ModelAssignment(provider_id=v.provider_id, model_id=v.model_id)
                for k, v in s.model_assignments.items()
            }
    except Exception:
        pass

    if flags.dry_run:
        result = SyncResult(agents=agent_ids, selection=selection, dry_run=True)
        if not agent_ids:
            result.no_op = True
            return result
        rt = SyncRuntime(home_dir, os.getcwd(), selection)
        result.plan = rt.stage_plan()
        return result

    return run_sync_with_selection(home_dir, selection)


# ─── RunRestore ─────────────────────────────────────────────────────────────


def run_restore(args: list[str], stdout: Any = None) -> str | None:
    if stdout is None:
        stdout = sys.stdout

    home_dir = os.path.expanduser("~")

    positional: list[str] = []
    list_flag = False
    yes_flag = False

    for a in args:
        if a in ("--list", "-list"):
            list_flag = True
        elif a in ("--yes", "-yes", "-y"):
            yes_flag = True
        elif a.startswith("-"):
            raise ValueError(f"flag desconocido {a!r}")
        else:
            positional.append(a)

    backups = _list_backups(home_dir)

    if list_flag:
        _render_restore_list(backups, stdout)
        return None

    if not positional:
        return "uso: dxrk-py restore [--list | latest | <id>] [--yes]"

    target = positional[0]
    manifest = _resolve_restore_target(target, backups)

    if not yes_flag:
        confirmed = _prompt_restore_confirm(manifest, stdout)
        if not confirmed:
            print("restauración cancelada", file=stdout)
            return None

    manifest_dir = manifest.get("_dir", "")

    for entry in manifest.get("entries", []):
        dest_path = entry.get("source", "")
        rel = entry.get("dest", "")
        src_path = os.path.join(manifest_dir, rel) if manifest_dir else ""
        if os.path.isfile(src_path) and dest_path:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            import shutil

            shutil.copy2(src_path, dest_path)

    label = manifest.get("description", "") or manifest.get("source", "") or target
    print(f"restauración completa — copia {target} restaurada ({label})", file=stdout)
    return None


def _list_backups(home_dir: str) -> list[dict[str, Any]]:
    backup_root = os.path.join(home_dir, ".gentle-ai", "backups")
    if not os.path.isdir(backup_root):
        return []

    manifests: list[dict[str, Any]] = []
    for entry in sorted(os.listdir(backup_root), reverse=True):
        entry_path = os.path.join(backup_root, entry)
        if not os.path.isdir(entry_path):
            continue
        manifest_path = os.path.join(entry_path, "manifest.json")
        if os.path.isfile(manifest_path):
            try:
                import json

                with open(manifest_path) as f:
                    m = json.load(f)
                m["_dir"] = entry_path
                m["_id"] = entry
                manifests.append(m)
            except Exception:
                continue

    manifests.sort(key=lambda m: m.get("_id", ""), reverse=True)
    return manifests


def _render_restore_list(backups: list[dict[str, Any]], stdout: Any) -> None:
    if not backups:
        print("no se encontraron copias de seguridad", file=stdout)
        return
    print(f"Copias disponibles ({len(backups)}):", file=stdout)
    for i, m in enumerate(backups):
        bid = m.get("_id", "?")
        source = m.get("source", "desconocido")
        count = len(m.get("entries", []))
        version = m.get("created_by_version", "")
        line = f"  [{i + 1}] {bid}  source={source} files={count}"
        if version:
            line += f"  [v{version}]"
        print(line, file=stdout)


def _resolve_restore_target(target: str, backups: list[dict[str, Any]]) -> dict[str, Any]:
    if target == "latest":
        if not backups:
            raise ValueError("no hay copias disponibles para restaurar")
        return backups[0]
    for m in backups:
        if m.get("_id") == target:
            return m
    raise ValueError(f"copia {target!r} no encontrada — usa `dxrk-py restore --list` para ver las copias disponibles")


def _prompt_restore_confirm(manifest: dict[str, Any], stdout: Any) -> bool:
    bid = manifest.get("_id", "?")
    source = manifest.get("source", "desconocido")
    count = len(manifest.get("entries", []))
    print(f"¿Restaurar la copia {bid} (source={source}, files={count})?", file=stdout)
    print(
        "Esto sobrescribirá tu configuración actual. Escribe 'yes' para confirmar: ",
        end="",
        file=stdout,
    )
    try:
        answer = input().strip()
    except EOFError:
        return False
    return answer.lower() == "yes"


# ─── RunUninstall ───────────────────────────────────────────────────────────


def run_uninstall(args: list[str], stdout: Any = None) -> Any:
    if stdout is None:
        stdout = sys.stdout

    flags = parse_uninstall_flags(args)
    home_dir = os.path.expanduser("~")
    workspace_dir = os.getcwd()

    if not flags.yes:
        confirmed = _prompt_uninstall_confirm(flags, stdout)
        if not confirmed:
            print("desinstalación cancelada", file=stdout)
            return None

    from dxrk.components.uninstall import Service

    service = Service(home_dir=home_dir, workspace_dir=workspace_dir)

    if flags.all:
        return service.complete_uninstall()
    else:
        agent_ids = _to_agent_ids(flags.agents)
        component_ids = [ComponentID(c) for c in flags.components] if flags.components else []
        return service.partial_uninstall(agent_ids, component_ids)


def _prompt_uninstall_confirm(flags: UninstallFlags, stdout: Any) -> bool:
    if flags.all:
        print(
            "Esto eliminará la configuración gestionada de dxrk de todos los agentes compatibles.",
            file=stdout,
        )
    else:
        labels = ", ".join(flags.agents)
        print(
            f"Esto eliminará la configuración gestionada de dxrk de: {labels}",
            file=stdout,
        )

    if flags.components:
        print(f"Componentes: {', '.join(flags.components)}", file=stdout)
    else:
        print("Componentes: todos los componentes gestionados desinstalables", file=stdout)
    print("Se creará una instantánea de seguridad antes de modificar cualquier archivo.", file=stdout)
    print("Escribe 'yes' para confirmar: ", end="", file=stdout)
    try:
        answer = input().strip()
    except EOFError:
        return False
    return answer.lower() == "yes"


# ─── Dry Run ────────────────────────────────────────────────────────────────


def _join_agent_ids(values: list[AgentID]) -> str:
    if not values:
        return "ninguno"
    return ",".join(v.value for v in values)


def _join_component_ids(values: list[ComponentID]) -> str:
    if not values:
        return "ninguno"
    return ",".join(v.value for v in values)


def _format_platform_decision(decision: PlatformDecision | None) -> str:
    if decision is None:
        return "os=desconocido distro=n/a package-manager=n/a status=no compatible"
    os_name = decision.os or "desconocido"
    distro = decision.linux_distro or "n/a"
    mgr = decision.package_manager or "n/a"
    status = "compatible" if decision.supported else "no compatible"
    return f"os={os_name} distro={distro} package-manager={mgr} status={status}"


def render_dry_run(result: InstallResult) -> str:
    lines: list[str] = [
        "AI Gentle Stack (simulación)",
        "=====================",
        f"Agentes: {_join_agent_ids(result.resolved.agents) if result.resolved else 'ninguno'}",
        f"Agentes no compatibles: {_join_agent_ids(result.resolved.unsupported_agents) if result.resolved else 'ninguno'}",
        f"Persona: {result.selection.persona.value if result.selection.persona else ''}",
        f"Preset: {result.selection.preset.value if result.selection.preset else ''}",
    ]

    if result.selection.sdd_mode:
        lines.append(f"Modo SDD: {result.selection.sdd_mode.value}")

    if result.resolved:
        lines.append(f"Orden de componentes: {_join_component_ids(result.resolved.ordered_components)}")
        lines.append(
            f"Dependencias agregadas automáticamente: {_join_component_ids(result.resolved.added_dependencies)}"
        )

    if result.review and result.review.platform_decision:
        lines.append(f"Decisión de plataforma: {_format_platform_decision(result.review.platform_decision)}")

    if result.plan:
        lines.append(f"Pasos de preparación: {len(result.plan.prepare)}")
        lines.append(f"Pasos de aplicación: {len(result.plan.apply)}")

    return "\n".join(lines) + "\n"


# ─── Sync Report ────────────────────────────────────────────────────────────


def render_sync_report(result: SyncResult) -> str:
    lines: list[str] = []

    if result.no_op:
        lines.append("dxrk-py sync — no se necesitan acciones de sincronización gestionadas")
        if not result.agents:
            lines.append("No se encontraron ni se especificaron agentes. Nada que sincronizar.")
        else:
            lines.append(f"Agentes: {_join_agent_ids(result.agents)}")
            lines.append("Todos los recursos gestionados ya están actualizados. Ningún archivo cambió.")
        return "\n".join(lines)

    if result.dry_run:
        lines.append("dxrk-py sync — simulación")
        lines.append(f"Agentes: {_join_agent_ids(result.agents)}")
        comp_parts = [c.value for c in result.selection.components]
        if comp_parts:
            lines.append(f"Componentes gestionados: {', '.join(comp_parts)}")
        if result.plan:
            lines.append(f"Pasos de preparación: {len(result.plan.prepare)}")
            lines.append(f"Pasos de aplicación: {len(result.plan.apply)}")
        return "\n".join(lines)

    lines.append("dxrk-py sync — sincronización gestionada ejecutada")
    lines.append(f"Agentes sincronizados: {_join_agent_ids(result.agents)}")
    comp_parts = [c.value for c in result.selection.components]
    if comp_parts:
        lines.append(f"Componentes gestionados sincronizados: {', '.join(comp_parts)}")
    lines.append(f"Acciones de sincronización ejecutadas: {result.files_changed} archivos cambiados")

    if not result.verify.ready:
        lines.append("")
        lines.append("Verificación posterior a la sincronización:")
        lines.append(_render_report(result.verify))

    return "\n".join(lines)


# ─── Uninstall Report ───────────────────────────────────────────────────────


def render_uninstall_report(result: Any) -> str:
    lines: list[str] = []
    lines.append("Desinstalación gestionada completa")
    manifest = getattr(result, "Manifest", {})
    if manifest.get("entries"):
        backup_id = getattr(result, "BackupPath", "")
        if backup_id:
            lines.append(f"Ruta de la copia: {backup_id}")
    lines.append(f"Archivos cambiados: {len(getattr(result, 'ChangedFiles', []))}")
    lines.append(f"Archivos eliminados: {len(getattr(result, 'RemovedFiles', []))}")
    lines.append(f"Directorios eliminados: {len(getattr(result, 'RemovedDirectories', []))}")

    removed = getattr(result, "AgentsRemovedFromState", [])
    if removed:
        labels = ", ".join(a.value for a in removed)
        lines.append(f"state.json actualizado: se eliminó {labels}")

    for section_title, paths in [
        ("Archivos reescritos", getattr(result, "ChangedFiles", [])),
        ("Archivos eliminados", getattr(result, "RemovedFiles", [])),
        ("Directorios eliminados", getattr(result, "RemovedDirectories", [])),
        ("Limpieza manual requerida", getattr(result, "ManualActions", [])),
    ]:
        if paths:
            lines.append(f"\n{section_title}:")
            for p in sorted(paths):
                try:
                    rel = os.path.relpath(p)
                    if not rel.startswith(".."):
                        lines.append(f"  - {rel}")
                    else:
                        lines.append(f"  - {p}")
                except Exception:
                    lines.append(f"  - {p}")

    return "\n".join(lines)


# ─── Verification ───────────────────────────────────────────────────────────


def _run_post_apply_verification(home_dir: str, selection: Selection, resolved: ResolvedPlan) -> _VerifyReport:
    adapters = _resolve_adapters(resolved.agents)
    seen_path: set[str] = set()
    checks: list[Callable[[], str | None]] = []

    for component in resolved.ordered_components:
        for path in _component_paths(home_dir, selection, adapters, component):
            if not path or path in seen_path:
                continue
            seen_path.add(path)
            current_path = path

            def make_check(p: str) -> Callable[[], str | None]:
                def check() -> str | None:
                    if not os.path.exists(p):
                        return f"archivo no encontrado: {p}"
                    return None

                check._cid = f"verify:file:{p}"  # type: ignore
                check._desc = "el archivo requerido existe"  # type: ignore
                return check

            checks.append(make_check(current_path))

    check_results = _run_checks(checks)
    report = _build_report(check_results)

    if _has_component(resolved.ordered_components, ComponentID.DXRK_MEMORY):
        from dxrk.components.memory import verify_installed

        binary_check = lambda: verify_installed()
        binary_check._cid = "verify:memory:binary"  # type: ignore
        binary_check._desc = "binario de memoria en PATH"  # type: ignore
        binary_check._soft = True  # type: ignore
        results = _run_checks([binary_check])
        report.checks.extend(results)
        if not results[0].error:
            from dxrk.components.memory import verify_version

            version_check = lambda: verify_version()
            version_check._cid = "verify:memory:version"  # type: ignore
            version_check._desc = "la versión de memoria devuelve una salida válida"  # type: ignore
            version_check._soft = True  # type: ignore
            results2 = _run_checks([version_check])
            report.checks.extend(results2)

    collision_checks = _antigravity_collision_check(resolved.agents)
    if collision_checks:
        report.checks.extend(collision_checks)

    report.ready = all(not (c.error and not c.soft) for c in report.checks)
    return report


def _antigravity_collision_check(agents: list[AgentID]) -> list[_VerifyCheck]:
    has_antigravity = AgentID.ANTIGRAVITY in agents
    has_gemini = AgentID.GEMINI_CLI in agents
    if not has_antigravity or not has_gemini:
        return []
    return [
        _VerifyCheck(
            id="verify:antigravity:rules-collision",
            description="Antigravity y Gemini CLI comparten ~/.gemini/GEMINI.md",
            soft=True,
            error="Antigravity y Gemini CLI escriben reglas en ~/.gemini/GEMINI.md\n"
            "El contenido se combina, no se sobrescribe.\n"
            "Este es el comportamiento esperado. No se requiere ninguna acción.",
        ),
    ]


def _run_post_sync_verification(home_dir: str, selection: Selection) -> _VerifyReport:
    adapters = _resolve_adapters(selection.agents)
    seen_path: set[str] = set()
    checks: list[Callable[[], str | None]] = []

    for component in selection.components:
        for path in _component_paths(home_dir, selection, adapters, component):
            if not path or path in seen_path:
                continue
            seen_path.add(path)
            p = path

            def make_check(fp: str) -> Callable[[], str | None]:
                def check() -> str | None:
                    if not os.path.exists(fp):
                        return f"archivo sincronizado no encontrado: {fp}"
                    return None

                check._cid = f"verify:sync:file:{fp}"  # type: ignore
                check._desc = "el archivo sincronizado existe"  # type: ignore
                return check

            checks.append(make_check(p))

    results = _run_checks(checks)
    report = _build_report(results)
    report.ready = all(not (c.error and not c.soft) for c in report.checks)
    return report


def _model_assignments_to_state(
    m: dict[str, ModelAssignment] | None,
) -> dict[str, ModelAssignmentState] | None:
    if not m:
        return None
    return {k: ModelAssignmentState(provider_id=v.provider_id, model_id=v.model_id) for k, v in m.items()}


def _claude_aliases_to_strings(m: dict[str, Any] | None) -> dict[str, str] | None:
    if not m:
        return None
    return {k: str(v) for k, v in m.items()}
