# SPDX-License-Identifier: MIT
"""Backup-target computation for the install/sync runtimes."""

from __future__ import annotations

import os
from typing import Any

from dxrk.cli.install_steps import _resolve_adapters, _selected_skill_ids
from dxrk.models import AgentID, ComponentID, PersonaID, Selection


def _backup_targets(home_dir: str, selection: Selection, resolved: Any) -> list[str]:
    paths: set[str] = set()
    adapters = _resolve_adapters(resolved.agents)

    for component in resolved.ordered_components:
        for p in _component_paths(home_dir, selection, adapters, component):
            paths.add(p)

    return sorted(paths)


def _component_paths(
    home_dir: str,
    selection: Selection,
    adapters: list[Any],
    component: ComponentID,
) -> list[str]:
    result: list[str] = []
    for adapter in adapters:
        if not adapter:
            continue

        if component == ComponentID.DXRK_MEMORY:
            from dxrk.models import MCPStrategy

            mcps = adapter.mcp_strategy
            if mcps in (MCPStrategy.SEPARATE_MCP_FILES, MCPStrategy.MCP_CONFIG_FILE):
                result.append(adapter.mcp_config_path(home_dir, "DXRK_MEMORY"))
            elif mcps == MCPStrategy.MERGE_INTO_SETTINGS:
                p = adapter.settings_path(home_dir)
                if p:
                    result.append(p)
            elif mcps == MCPStrategy.TOML_FILE:
                p = adapter.mcp_config_path(home_dir, "memory")
                if p:
                    result.append(p)
            from dxrk.models import SystemPromptStrategy

            if adapter.system_prompt_strategy == SystemPromptStrategy.MARKDOWN_SECTIONS:
                result.append(adapter.system_prompt_file(home_dir))

        elif component == ComponentID.CONTEXT7:
            from dxrk.models import MCPStrategy

            mcps = adapter.mcp_strategy
            if mcps in (MCPStrategy.SEPARATE_MCP_FILES,):
                result.append(adapter.mcp_config_path(home_dir, "context7"))
            elif mcps == MCPStrategy.MERGE_INTO_SETTINGS:
                p = adapter.settings_path(home_dir)
                if p:
                    result.append(p)
            elif mcps == MCPStrategy.MCP_CONFIG_FILE:
                p = adapter.mcp_config_path(home_dir, "context7")
                if p:
                    result.append(p)

        elif component == ComponentID.SDD:
            if adapter.supports_system_prompt:
                from dxrk.models import SystemPromptStrategy

                if adapter.system_prompt_strategy != SystemPromptStrategy.JINJA_MODULES:
                    result.append(adapter.system_prompt_file(home_dir))
            if adapter.supports_slash_commands:
                cmd_dir = adapter.commands_dir(home_dir)
                if cmd_dir:
                    result.append(cmd_dir)
            if adapter.agent == AgentID.OPENCODE:
                result.append(adapter.settings_path(home_dir))
                result.append(
                    os.path.join(
                        home_dir,
                        ".config",
                        "opencode",
                        "plugins",
                        "background-agents.ts",
                    )
                )
            if adapter.supports_skills:
                sk_dir = adapter.skills_dir(home_dir)
                if sk_dir:
                    result.append(os.path.join(sk_dir, "_shared"))

        elif component == ComponentID.PERSONA:
            if selection.persona == PersonaID.CUSTOM:
                break
            if adapter.supports_system_prompt:
                from dxrk.models import SystemPromptStrategy

                if adapter.system_prompt_strategy != SystemPromptStrategy.JINJA_MODULES:
                    result.append(adapter.system_prompt_file(home_dir))
            if selection.persona == PersonaID.DXRK:
                if adapter.supports_output_styles:
                    result.append(os.path.join(adapter.output_style_dir(home_dir), "dxrk.md"))
                    p = adapter.settings_path(home_dir)
                    if p:
                        result.append(p)

        elif component == ComponentID.SKILLS:
            skill_ids = _selected_skill_ids(selection)
            for sid in skill_ids:
                from dxrk.components.skills import skill_path_for_agent

                p = skill_path_for_agent(home_dir, adapter, sid)
                if p:
                    result.append(p)

        elif component == ComponentID.PERMISSIONS:
            from dxrk.components import permissions as _permissions

            for p in _permissions.managed_paths(adapter, home_dir):
                result.append(p)

        elif component == ComponentID.DXRK_GUARDIAN:
            from dxrk.components.gga import agents_template_path, config_path

            result.append(config_path(home_dir))
            result.append(agents_template_path(home_dir))

        elif component == ComponentID.THEME:
            p = adapter.settings_path(home_dir)
            if p:
                result.append(p)

    return result


def _sync_backup_targets(home_dir: str, selection: Selection, adapters: list[Any]) -> list[str]:
    paths: set[str] = set()
    for component in selection.components:
        for p in _component_paths(home_dir, selection, adapters, component):
            paths.add(p)
    return sorted(paths)
