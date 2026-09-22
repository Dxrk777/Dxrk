# SPDX-License-Identifier: MIT
"""Normalization from raw CLI flags to a validated InstallInput."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from dxrk.cli.install_flags import InstallFlags
from dxrk.models import (
    AgentID,
    ComponentID,
    PersonaID,
    PresetID,
    SDDModeID,
    Selection,
    SkillID,
)
from dxrk.system import DetectionResult

log = logging.getLogger("dxrk.cli.install")

# ─── InstallInput / Normalize ──────────────────────────────────────────────


@dataclass
class InstallInput:
    selection: Selection = field(default_factory=Selection)
    dry_run: bool = False


def normalize_persona(value: str) -> PersonaID:
    v = value.strip()
    if not v:
        return PersonaID.DXRK
    try:
        return PersonaID(v)
    except ValueError:
        raise ValueError(f"persona no compatible {value!r}")


def normalize_preset(value: str) -> PresetID:
    v = value.strip()
    if not v:
        return PresetID.FULL_DXRK
    try:
        return PresetID(v)
    except ValueError:
        raise ValueError(f"preset no compatible {value!r}")


def components_for_preset(preset: PresetID) -> list[ComponentID]:
    if preset == PresetID.MINIMAL:
        return [ComponentID.DXRK_MEMORY]
    if preset == PresetID.ECOSYSTEM_ONLY:
        return [
            ComponentID.DXRK_MEMORY,
            ComponentID.SDD,
            ComponentID.SKILLS,
            ComponentID.CONTEXT7,
            ComponentID.DXRK_GUARDIAN,
        ]
    if preset == PresetID.CUSTOM:
        return []
    return [
        ComponentID.DXRK_MEMORY,
        ComponentID.SDD,
        ComponentID.SKILLS,
        ComponentID.CONTEXT7,
        ComponentID.PERSONA,
        ComponentID.PERMISSIONS,
        ComponentID.DXRK_GUARDIAN,
    ]


def normalize_components(values: list[str], preset: PresetID) -> list[ComponentID]:
    from dxrk.catalog import mvp_components

    if not values:
        return components_for_preset(preset)

    allowed: set[ComponentID] = set(c.id for c in mvp_components())

    components: list[ComponentID] = []
    for raw in values:
        try:
            cid = ComponentID(raw)
        except ValueError:
            raise ValueError(f"componente no compatible {raw!r}")
        if cid not in allowed:
            raise ValueError(f"componente no compatible {raw!r}")
        components.append(cid)
    return _unique(components)


def normalize_skills(values: list[str]) -> list[SkillID]:
    from dxrk.catalog import mvp_skills

    if not values:
        return []

    allowed: set[SkillID] = set(s.id for s in mvp_skills())

    skills: list[SkillID] = []
    for raw in values:
        try:
            sid = SkillID(raw)
        except ValueError:
            raise ValueError(f"skill no compatible {raw!r}")
        if sid not in allowed:
            raise ValueError(f"skill no compatible {raw!r}")
        skills.append(sid)
    return _unique(skills)


def normalize_sdd_mode(value: str) -> SDDModeID | None:
    v = value.strip()
    if not v:
        return None
    if v == SDDModeID.SINGLE:
        return SDDModeID.SINGLE
    if v == SDDModeID.MULTI:
        return SDDModeID.MULTI
    raise ValueError(f"sdd-mode no compatible {value!r} (válidos: single, multi)")


def default_agents_from_detection(detection: DetectionResult) -> list[AgentID]:
    agents: list[AgentID] = []
    for state in detection.configs:
        if not state.exists:
            continue
        try:
            aid = AgentID(state.agent.replace("-", "_").upper())
        except ValueError:
            continue
        if aid in AgentID:
            agents.append(aid)

    if agents:
        return agents

    from dxrk.models import AGENTS

    return list(AGENTS)


def _as_agent_ids(values: list[str]) -> list[AgentID]:
    result: list[AgentID] = []
    for v in values:
        try:
            result.append(AgentID(v))
        except ValueError:
            log.warning("ID de agente desconocido: %s", v)
    return result


def _unique(items: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def normalize_install_flags(flags: InstallFlags, detection: DetectionResult) -> InstallInput:
    selection = Selection()

    agents = default_agents_from_detection(detection)
    if flags.agents:
        agents = _as_agent_ids(flags.agents)
    selection.agents = _unique(agents)

    persona = normalize_persona(flags.persona)
    selection.persona = persona

    preset = normalize_preset(flags.preset)
    selection.preset = preset

    components = normalize_components(flags.components, preset)
    selection.components = components

    skills = normalize_skills(flags.skills)
    selection.skills = skills

    sdd_mode = normalize_sdd_mode(flags.sdd_mode)
    if sdd_mode:
        selection.sdd_mode = sdd_mode

    return InstallInput(selection=selection, dry_run=flags.dry_run)
