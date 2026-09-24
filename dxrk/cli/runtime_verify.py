# SPDX-License-Identifier: MIT
"""Post-apply verification for the install/sync runtimes."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from dxrk.cli.install_steps import _resolve_adapters
from dxrk.cli.install_verify import _build_report, _run_checks, _VerifyCheck, _VerifyReport
from dxrk.cli.runtime_paths import _component_paths
from dxrk.models import AgentID, ComponentID, ModelAssignment, Selection
from dxrk.state import ModelAssignmentState


def _has_component(components: list[ComponentID], target: ComponentID) -> bool:
    return target in components


def _contains_agent(agents: list[AgentID], target: AgentID) -> bool:
    return target in agents


def _run_post_apply_verification(home_dir: str, selection: Selection, resolved: Any) -> _VerifyReport:
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
