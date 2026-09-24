# SPDX-License-Identifier: MIT
"""Install/sync/restore/uninstall runtimes, results and entry points.

Facade over the runtime_* submodules. Bodies live in the submodules;
this module re-exports the full namespace so existing imports
(`dxrk.cli.install`, patch targets in tests) keep working.
"""

from __future__ import annotations

from dxrk.cli.install_steps import _resolve_adapters as _resolve_adapters
from dxrk.cli.install_steps import _selected_skill_ids as _selected_skill_ids
from dxrk.cli.install_verify import _build_report as _build_report
from dxrk.cli.install_verify import _render_report as _render_report
from dxrk.cli.install_verify import _run_checks as _run_checks
from dxrk.cli.install_verify import _VerifyCheck as _VerifyCheck
from dxrk.cli.install_verify import _VerifyReport as _VerifyReport
from dxrk.cli.runtime_install import InstallResult as InstallResult
from dxrk.cli.runtime_install import InstallRuntime as InstallRuntime
from dxrk.cli.runtime_install import RuntimeState as RuntimeState
from dxrk.cli.runtime_install import app_version as app_version
from dxrk.cli.runtime_install import build_real_stage_plan as build_real_stage_plan
from dxrk.cli.runtime_install import build_stage_plan as build_stage_plan
from dxrk.cli.runtime_install import resolve_install_profile as resolve_install_profile
from dxrk.cli.runtime_paths import _backup_targets as _backup_targets
from dxrk.cli.runtime_paths import _component_paths as _component_paths
from dxrk.cli.runtime_paths import _sync_backup_targets as _sync_backup_targets
from dxrk.cli.runtime_reports import _format_platform_decision as _format_platform_decision
from dxrk.cli.runtime_reports import _join_agent_ids as _join_agent_ids
from dxrk.cli.runtime_reports import _join_component_ids as _join_component_ids
from dxrk.cli.runtime_reports import render_dry_run as render_dry_run
from dxrk.cli.runtime_reports import render_sync_report as render_sync_report
from dxrk.cli.runtime_reports import render_uninstall_report as render_uninstall_report
from dxrk.cli.runtime_restore import _list_backups as _list_backups
from dxrk.cli.runtime_restore import _prompt_restore_confirm as _prompt_restore_confirm
from dxrk.cli.runtime_restore import _render_restore_list as _render_restore_list
from dxrk.cli.runtime_restore import _resolve_restore_target as _resolve_restore_target
from dxrk.cli.runtime_restore import run_restore as run_restore
from dxrk.cli.runtime_run import _go_install_bin_dir as _go_install_bin_dir
from dxrk.cli.runtime_run import _is_in_path as _is_in_path
from dxrk.cli.runtime_run import _memory_path_guidance as _memory_path_guidance
from dxrk.cli.runtime_run import _with_post_install_notes as _with_post_install_notes
from dxrk.cli.runtime_run import run_install as run_install
from dxrk.cli.runtime_sync import ComponentSyncStep as ComponentSyncStep
from dxrk.cli.runtime_sync import SyncResult as SyncResult
from dxrk.cli.runtime_sync import SyncRuntime as SyncRuntime
from dxrk.cli.runtime_sync import _to_agent_ids as _to_agent_ids
from dxrk.cli.runtime_sync import build_sync_selection as build_sync_selection
from dxrk.cli.runtime_sync import discover_agents as discover_agents
from dxrk.cli.runtime_sync import run_sync as run_sync
from dxrk.cli.runtime_sync import run_sync_with_selection as run_sync_with_selection
from dxrk.cli.runtime_uninstall import _prompt_uninstall_confirm as _prompt_uninstall_confirm
from dxrk.cli.runtime_uninstall import run_uninstall as run_uninstall
from dxrk.cli.runtime_verify import _antigravity_collision_check as _antigravity_collision_check
from dxrk.cli.runtime_verify import _claude_aliases_to_strings as _claude_aliases_to_strings
from dxrk.cli.runtime_verify import _contains_agent as _contains_agent
from dxrk.cli.runtime_verify import _has_component as _has_component
from dxrk.cli.runtime_verify import _model_assignments_to_state as _model_assignments_to_state
from dxrk.cli.runtime_verify import _run_post_apply_verification as _run_post_apply_verification
from dxrk.cli.runtime_verify import _run_post_sync_verification as _run_post_sync_verification
