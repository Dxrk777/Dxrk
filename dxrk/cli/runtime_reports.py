# SPDX-License-Identifier: MIT
"""Human-readable reports for dry-run, sync, and uninstall results."""

from __future__ import annotations

import os
from typing import Any

from dxrk.cli.install_verify import _render_report
from dxrk.cli.runtime_install import InstallResult
from dxrk.cli.runtime_sync import SyncResult
from dxrk.models import AgentID, ComponentID
from dxrk.planner import PlatformDecision


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
