# SPDX-License-Identifier: MIT
"""Partial/complete uninstall of managed configuration."""

from __future__ import annotations

import os
import sys
from typing import Any

from dxrk.cli.install_flags import UninstallFlags, parse_uninstall_flags
from dxrk.cli.runtime_sync import _to_agent_ids
from dxrk.models import ComponentID


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
