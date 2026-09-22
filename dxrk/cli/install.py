# SPDX-License-Identifier: MIT
"""CLI installer — facade over the install_* submodules.

Ports internal/cli/ (run.go, install.go, sync.go, restore.go, uninstall.go, dryrun.go, validate.go).
"""

from __future__ import annotations

import os as os

from dxrk.cli.install_flags import (
    InstallFlags,
    SyncFlags,
    UninstallFlags,
    parse_install_flags,
    parse_sync_flags,
    parse_uninstall_flags,
)
from dxrk.cli.install_flags import (
    _csv_append_type as _csv_append_type,
)
from dxrk.cli.install_flags import (
    _flatten_list as _flatten_list,
)
from dxrk.cli.install_flags import (
    _parse_model_spec as _parse_model_spec,
)
from dxrk.cli.install_flags import (
    _parse_profile_flag as _parse_profile_flag,
)
from dxrk.cli.install_flags import (
    _parse_profile_phase_flag as _parse_profile_phase_flag,
)
from dxrk.cli.install_flags import (
    _parse_profile_sync_strategy as _parse_profile_sync_strategy,
)
from dxrk.cli.install_flags import (
    _parse_profiles as _parse_profiles,
)
from dxrk.cli.install_normalize import (
    InstallInput,
    normalize_install_flags,
)
from dxrk.cli.install_normalize import (
    _as_agent_ids as _as_agent_ids,
)
from dxrk.cli.install_normalize import (
    _unique as _unique,
)
from dxrk.cli.install_normalize import (
    components_for_preset as components_for_preset,
)
from dxrk.cli.install_normalize import (
    default_agents_from_detection as default_agents_from_detection,
)
from dxrk.cli.install_normalize import (
    log as log,
)
from dxrk.cli.install_normalize import (
    normalize_components as normalize_components,
)
from dxrk.cli.install_normalize import (
    normalize_persona as normalize_persona,
)
from dxrk.cli.install_normalize import (
    normalize_preset as normalize_preset,
)
from dxrk.cli.install_normalize import (
    normalize_sdd_mode as normalize_sdd_mode,
)
from dxrk.cli.install_normalize import (
    normalize_skills as normalize_skills,
)
from dxrk.cli.install_runtime import (
    ComponentSyncStep,
    InstallResult,
    InstallRuntime,
    SyncResult,
    SyncRuntime,
    build_real_stage_plan,
    build_stage_plan,
    build_sync_selection,
    discover_agents,
    render_dry_run,
    render_sync_report,
    render_uninstall_report,
    resolve_install_profile,
    run_install,
    run_restore,
    run_sync,
    run_sync_with_selection,
    run_uninstall,
)
from dxrk.cli.install_runtime import (
    RuntimeState as RuntimeState,
)
from dxrk.cli.install_runtime import (
    _antigravity_collision_check as _antigravity_collision_check,
)
from dxrk.cli.install_runtime import (
    _backup_targets as _backup_targets,
)
from dxrk.cli.install_runtime import (
    _claude_aliases_to_strings as _claude_aliases_to_strings,
)
from dxrk.cli.install_runtime import (
    _component_paths as _component_paths,
)
from dxrk.cli.install_runtime import (
    _contains_agent as _contains_agent,
)
from dxrk.cli.install_runtime import (
    _format_platform_decision as _format_platform_decision,
)
from dxrk.cli.install_runtime import (
    _go_install_bin_dir as _go_install_bin_dir,
)
from dxrk.cli.install_runtime import (
    _has_component as _has_component,
)
from dxrk.cli.install_runtime import (
    _is_in_path as _is_in_path,
)
from dxrk.cli.install_runtime import (
    _join_agent_ids as _join_agent_ids,
)
from dxrk.cli.install_runtime import (
    _join_component_ids as _join_component_ids,
)
from dxrk.cli.install_runtime import (
    _list_backups as _list_backups,
)
from dxrk.cli.install_runtime import (
    _memory_path_guidance as _memory_path_guidance,
)
from dxrk.cli.install_runtime import (
    _model_assignments_to_state as _model_assignments_to_state,
)
from dxrk.cli.install_runtime import (
    _prompt_restore_confirm as _prompt_restore_confirm,
)
from dxrk.cli.install_runtime import (
    _prompt_uninstall_confirm as _prompt_uninstall_confirm,
)
from dxrk.cli.install_runtime import (
    _render_restore_list as _render_restore_list,
)
from dxrk.cli.install_runtime import (
    _resolve_restore_target as _resolve_restore_target,
)
from dxrk.cli.install_runtime import (
    _run_post_apply_verification as _run_post_apply_verification,
)
from dxrk.cli.install_runtime import (
    _run_post_sync_verification as _run_post_sync_verification,
)
from dxrk.cli.install_runtime import (
    _sync_backup_targets as _sync_backup_targets,
)
from dxrk.cli.install_runtime import (
    _to_agent_ids as _to_agent_ids,
)
from dxrk.cli.install_runtime import (
    _with_post_install_notes as _with_post_install_notes,
)
from dxrk.cli.install_runtime import (
    app_version as app_version,
)
from dxrk.cli.install_steps import (
    AgentInstallStep as AgentInstallStep,
)
from dxrk.cli.install_steps import (
    CheckDependenciesStep as CheckDependenciesStep,
)
from dxrk.cli.install_steps import (
    ComponentApplyStep,
    NoopStep,
)
from dxrk.cli.install_steps import (
    KimiSystemPromptHubStep as KimiSystemPromptHubStep,
)
from dxrk.cli.install_steps import (
    OpenCodePluginInstallStep as OpenCodePluginInstallStep,
)
from dxrk.cli.install_steps import (
    PrepareBackupStep as PrepareBackupStep,
)
from dxrk.cli.install_steps import (
    RollbackRestoreStep as RollbackRestoreStep,
)
from dxrk.cli.install_steps import (
    _create_agent_adapter as _create_agent_adapter,
)
from dxrk.cli.install_steps import (
    _gga_available as _gga_available,
)
from dxrk.cli.install_steps import (
    _resolve_adapters as _resolve_adapters,
)
from dxrk.cli.install_steps import (
    _selected_skill_ids as _selected_skill_ids,
)
from dxrk.cli.install_steps import (
    _skills_for_preset as _skills_for_preset,
)
from dxrk.cli.install_verify import (
    _build_report as _build_report,
)
from dxrk.cli.install_verify import (
    _render_report as _render_report,
)
from dxrk.cli.install_verify import (
    _run_checks as _run_checks,
)
from dxrk.cli.install_verify import (
    _VerifyCheck as _VerifyCheck,
)
from dxrk.cli.install_verify import (
    _VerifyReport as _VerifyReport,
)
from dxrk.pipeline import Step

__all__ = [
    "ComponentApplyStep",
    "ComponentSyncStep",
    "InstallFlags",
    "InstallInput",
    "InstallResult",
    "InstallRuntime",
    "NoopStep",
    "Step",
    "SyncFlags",
    "SyncResult",
    "SyncRuntime",
    "UninstallFlags",
    "build_real_stage_plan",
    "build_stage_plan",
    "build_sync_selection",
    "discover_agents",
    "normalize_install_flags",
    "parse_install_flags",
    "parse_sync_flags",
    "parse_uninstall_flags",
    "render_dry_run",
    "render_sync_report",
    "render_uninstall_report",
    "resolve_install_profile",
    "run_install",
    "run_restore",
    "run_sync",
    "run_sync_with_selection",
    "run_uninstall",
]
