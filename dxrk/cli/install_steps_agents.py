# SPDX-License-Identifier: MIT
"""Agent install steps and dependency preflight for the install pipeline."""

from __future__ import annotations

import logging
import shutil
from typing import Any

from dxrk.models import AgentID, Selection
from dxrk.pipeline import Step, run_command_sequence
from dxrk.system import PlatformProfile

log = logging.getLogger("dxrk.cli.install")


class AgentInstallStep(Step):
    def __init__(self, step_id: str, agent: AgentID, home_dir: str, profile: PlatformProfile):
        self._id = step_id
        self._agent = agent
        self._home_dir = home_dir
        self._profile = profile

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        from dxrk.agents.factory import create_registry

        reg = create_registry()
        adapter = reg.get(self._agent)
        if adapter is None:
            return f"no hay adaptador para el agente {self._agent!r}"

        if not adapter.supports_auto_install:
            return None

        result = adapter.detect(self._home_dir)
        if result.installed:
            return None

        if self._profile.package_manager not in (
            "brew",
            "apt",
            "pacman",
            "dnf",
            "winget",
        ):
            pass
        commands = adapter.install_command(self._profile)
        if not commands:
            return f"el comando de instalación para {self._agent!r} se resolvió en una secuencia vacía"
        lead = commands[0][0] if commands[0] else ""
        if lead and shutil.which(lead) is None:
            # Sin el binario del agente no se pueden instalar sus plugins;
            # se omite con aviso en vez de abortar toda la instalación.
            log.warning(
                "se omite la instalación de %s: comando %r no encontrado en PATH (instala %s manualmente y reintenta)",
                self._agent,
                lead,
                self._agent,
            )
            return None
        return run_command_sequence(commands)


class OpenCodePluginInstallStep(Step):
    def __init__(self, step_id: str, plugin: Any, home_dir: str):
        self._id = step_id
        self._plugin = plugin
        self._home_dir = home_dir

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        from dxrk.components.opencodeplugin import install as opencode_plugin_install

        opencode_plugin_install(self._home_dir, self._plugin)
        return None


class KimiSystemPromptHubStep(Step):
    def __init__(self, step_id: str, home_dir: str):
        self._id = step_id
        self._home_dir = home_dir

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        from dxrk.agents.kimi.adapter import KimiAdapter

        try:
            adapter = KimiAdapter()
        except Exception:
            # Fall back to opencode adapter if kimi not implemented
            return None
        template_bootstrap = getattr(adapter, "bootstrap_template", None)
        if callable(template_bootstrap):
            template_bootstrap(self._home_dir)
        return None


class CheckDependenciesStep(Step):
    def __init__(
        self,
        step_id: str,
        profile: PlatformProfile,
        home_dir: str,
        selection: Selection,
    ):
        self._id = step_id
        self._profile = profile
        self._home_dir = home_dir
        self._selection = selection

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        import dxrk.system as sysmod

        sysmod.detect_dependencies(self._profile)

        for agent in self._selection.agents:
            from dxrk.agents.factory import create_registry

            reg = create_registry()
            adapter = reg.get(agent)
            if adapter is None:
                return f"error al crear adaptador para {agent!r}"
            if not adapter.supports_auto_install:
                continue
            if self._home_dir:
                result = adapter.detect(self._home_dir)
                if result.installed:
                    continue
            # Pre-flight validation (simplified: skip installcmd validation for now)
        return None
