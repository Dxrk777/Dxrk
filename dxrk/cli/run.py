# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from dxrk.models import AgentID, ComponentID, Selection
from dxrk.system import DetectionResult

__all__ = [
    "InstallResult",
    "build_stage_plan",
    "resolve_install_profile",
    "run_install",
]


@dataclass
class InstallResult:
    selection: Selection = field(default_factory=Selection)
    resolved: Any = None
    review: Any = None
    plan: Any = None
    execution: Any = None
    verify: Any = None
    dependencies: Any = None
    dry_run: bool = False
    error: str = ""


def run_install(args: list[str], detection: DetectionResult) -> InstallResult:
    from dxrk.cli.install import (
        InstallRuntime,
        normalize_install_flags,
        parse_install_flags,
    )
    from dxrk.cli.install import resolve_install_profile as resolve_profile

    flags = parse_install_flags(args)
    input_data = normalize_install_flags(flags, detection)

    from dxrk.planner import (
        build_review_payload,
        new_resolver,
        platform_decision_from_profile,
    )

    resolved = new_resolver().resolve(input_data.selection)
    profile = resolve_profile(detection)
    resolved.platform_decision = platform_decision_from_profile(profile)

    review = build_review_payload(input_data.selection, resolved)
    stage_plan = build_stage_plan(input_data.selection, resolved)

    result = InstallResult(
        selection=input_data.selection,
        resolved=resolved,
        review=review,
        plan=stage_plan,
        dependencies=detection.dependencies,
        dry_run=input_data.dry_run,
    )

    if input_data.dry_run:
        return result

    home_dir = os.path.expanduser("~")

    rt = InstallRuntime(
        home_dir=home_dir,
        workspace_dir=os.getcwd(),
        selection=input_data.selection,
        resolved=resolved,
        profile=profile,
    )

    assert detection.dependencies is not None, "detection did not populate dependencies"
    if not detection.dependencies.all_present:
        import logging

        from dxrk.system import format_missing_deps_message

        log = logging.getLogger(__name__)
        missing = ", ".join(detection.dependencies.missing_required)
        log.warning(
            "missing dependencies: %s\n\n%s",
            missing,
            format_missing_deps_message(detection.dependencies),
        )

    stage_plan = rt.stage_plan()
    result.plan = stage_plan

    from dxrk.pipeline import default_rollback_policy, new_orchestrator

    orchestrator = new_orchestrator(default_rollback_policy())
    result.execution = orchestrator.execute(stage_plan)

    if result.execution.error:
        result.error = f"execute install pipeline: {result.execution.error}"
        return result

    from dxrk.state import write as state_write

    verify_result = _run_post_apply_verification(
        home_dir, input_data.selection, resolved
    )
    add_post_install_notes(verify_result, resolved)
    result.verify = verify_result

    if not getattr(verify_result, "ready", True):
        result.error = "post-apply verification failed"
        return result

    agent_ids = [a.value for a in input_data.selection.agents]
    from dxrk.cli.install import _model_assignments_to_state
    from dxrk.state import InstallState

    state_write(
        home_dir,
        InstallState(
            installed_agents=agent_ids,
            claude_model_assignments=input_data.selection.claude_model_assignments
            or None,
            model_assignments=_model_assignments_to_state(
                input_data.selection.model_assignments
            ),
        ),
    )

    return result


def _run_post_apply_verification(
    home_dir: str,
    selection: Selection,
    resolved: Any,
) -> Any:
    from dxrk.cli.install import (
        _build_report,
        _component_paths,
        _run_checks,
    )
    from dxrk.models import ComponentID

    adapters = _resolve_adapters(resolved.agents)

    seen_path: set[str] = set()
    unique_paths: list[str] = []

    for component in resolved.ordered_components:
        for path in _component_paths(home_dir, selection, adapters, component):
            if not path:
                continue
            if path in seen_path:
                continue
            seen_path.add(path)
            unique_paths.append(path)

    checks: list[Any] = []
    for path in unique_paths:
        checks.append(_verify_file_exists(path))

    if has_component(resolved.ordered_components, ComponentID.DXRK_MEMORY):
        checks.extend(_DXRK_MEMORY_health_checks())

    checks.extend(_antigravity_collision_check(resolved.agents))

    return _build_report(_run_checks(checks))


def _verify_file_exists(path: str):
    def check() -> str | None:
        if not os.path.isfile(path):
            return f"required file does not exist: {path}"
        return None

    check._cid = f"verify:file:{path}"  # type: ignore
    check._desc = "required file exists"  # type: ignore
    return check


def _DXRK_MEMORY_health_checks() -> list:
    checks = []

    def binary_check():
        if not _look_path("memory"):
            return "memory binary not on PATH (restart shell if missing)"
        return None

    binary_check._cid = "verify:memory:binary"  # type: ignore
    binary_check._desc = "memory binary on PATH (restart shell if missing)"  # type: ignore
    binary_check._soft = True  # type: ignore

    def version_check():
        if not _look_path("memory"):
            return None
        import subprocess

        try:
            r = subprocess.run(
                ["memory", "version"], capture_output=True, text=True, timeout=10
            )
            if r.returncode != 0:
                return "memory version command failed"
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return f"memory version check failed: {e}"
        return None

    version_check._cid = "verify:memory:version"  # type: ignore
    version_check._desc = "memory version returns valid output"  # type: ignore
    version_check._soft = True  # type: ignore

    checks.append(binary_check)
    checks.append(version_check)
    return checks


def _antigravity_collision_check(agents: list) -> list:
    from dxrk.models import AgentID

    has_antigravity = AgentID.ANTIGRAVITY in agents
    has_gemini = AgentID.GEMINI_CLI in agents
    if not has_antigravity or not has_gemini:
        return []

    def check():
        return (
            "both Antigravity and Gemini CLI write rules to ~/.gemini/GEMINI.md\n"
            "Content is merged, not overwritten — rules from both agents coexist in the same file.\n"
            "This is expected behavior. No action required unless you want to separate them manually."
        )

    check._cid = "verify:antigravity:rules-collision"  # type: ignore
    check._desc = "Antigravity and Gemini CLI share ~/.gemini/GEMINI.md"  # type: ignore
    check._soft = True  # type: ignore
    return [check]


def _look_path(name: str) -> str:
    import shutil

    return shutil.which(name) or ""


def _resolve_adapters(agent_ids: list[AgentID]) -> list[Any]:
    from dxrk.agents.factory import create_registry

    reg = create_registry()
    adapters: list[Any] = []
    for aid in agent_ids:
        try:
            adapter = reg.get(aid)
            if adapter:
                adapters.append(adapter)
        except Exception:
            continue
    return adapters


def add_post_install_notes(report: Any, resolved: Any) -> None:
    from dxrk.models import ComponentID

    if has_component(
        resolved.ordered_components, ComponentID.DXRK_GUARDIAN
    ) and getattr(report, "ready", True):
        note = getattr(report, "final_note", "")
        note += "\n\nDXRK_GUARDIAN is now installed globally. To enable project hooks, run in each repo:\n- DXRK_GUARDIAN init\n- DXRK_GUARDIAN install"
        report.final_note = note


def has_component(components: list, target: ComponentID) -> bool:
    return target in components


def resolve_install_profile(detection: DetectionResult) -> Any:
    from dxrk.cli.install import resolve_install_profile as _resolve

    return _resolve(detection)


def build_stage_plan(selection: Selection, resolved: Any) -> Any:
    from dxrk.cli.install import NoopStep
    from dxrk.pipeline import StagePlan, Step

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
