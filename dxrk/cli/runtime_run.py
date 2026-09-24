# SPDX-License-Identifier: MIT
"""run_install orchestration with post-install notes and PATH guidance."""

from __future__ import annotations

import logging
import os

from dxrk.cli.install_flags import parse_install_flags
from dxrk.cli.install_normalize import normalize_install_flags
from dxrk.cli.install_verify import _VerifyReport
from dxrk.cli.runtime_install import InstallResult, InstallRuntime, build_stage_plan, resolve_install_profile
from dxrk.cli.runtime_verify import _has_component, _model_assignments_to_state, _run_post_apply_verification
from dxrk.models import ComponentID
from dxrk.planner import ResolvedPlan, platform_decision_from_profile
from dxrk.system import DetectionResult, PlatformProfile

log = logging.getLogger("dxrk.cli.install")


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
