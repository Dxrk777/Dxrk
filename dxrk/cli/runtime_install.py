# SPDX-License-Identifier: MIT
"""Install runtime, plan scaffolding, and result types."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dxrk.cli.install_steps import (
    AgentInstallStep,
    CheckDependenciesStep,
    ComponentApplyStep,
    KimiSystemPromptHubStep,
    NoopStep,
    OpenCodePluginInstallStep,
    PrepareBackupStep,
    RollbackRestoreStep,
)
from dxrk.cli.install_verify import _VerifyReport
from dxrk.cli.runtime_paths import _backup_targets
from dxrk.models import AgentID, Selection
from dxrk.pipeline import Step
from dxrk.planner import ResolvedPlan, ReviewPayload
from dxrk.system import DetectionResult, PlatformProfile


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


def resolve_install_profile(detection: DetectionResult) -> PlatformProfile:
    if detection.system.profile.os:
        return detection.system.profile
    return PlatformProfile(os="darwin", package_manager="brew", supported=True)


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
