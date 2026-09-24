# SPDX-License-Identifier: MIT
"""Sync runtime: re-apply managed components and entry points."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dxrk.cli.install_flags import SyncFlags, parse_sync_flags
from dxrk.cli.install_normalize import _unique
from dxrk.cli.install_steps import (
    PrepareBackupStep,
    RollbackRestoreStep,
    _resolve_adapters,
    _selected_skill_ids,
)
from dxrk.cli.install_verify import _VerifyReport
from dxrk.cli.runtime_paths import _sync_backup_targets
from dxrk.cli.runtime_verify import _run_post_sync_verification
from dxrk.models import (
    AgentID,
    ComponentID,
    ModelAssignment,
    PresetID,
    SDDModeID,
    SDDProfileStrategyID,
    Selection,
    SkillID,
)
from dxrk.pipeline import Step


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
