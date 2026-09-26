# SPDX-License-Identifier: MIT
"""Component apply step and skill/guardian helpers for the install pipeline."""

from __future__ import annotations

import logging
import os
import shutil

from dxrk.cli.install_steps_base import _resolve_adapters
from dxrk.models import AgentID, ComponentID, PresetID, Selection, SkillID
from dxrk.pipeline import Step, execute_command, run_command_sequence
from dxrk.system import PlatformProfile

log = logging.getLogger("dxrk.cli.install")


class ComponentApplyStep(Step):
    def __init__(
        self,
        step_id: str,
        component: ComponentID,
        home_dir: str,
        workspace_dir: str,
        agents: list[AgentID],
        selection: Selection,
        profile: PlatformProfile,
    ):
        self._id = step_id
        self._component = component
        self._home_dir = home_dir
        self._workspace_dir = workspace_dir
        self._agents = agents
        self._selection = selection
        self._profile = profile

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        adapters = _resolve_adapters(self._agents)
        c = self._component

        if c == ComponentID.DXRK_MEMORY:
            from dxrk.components.memory import (
                download_latest_binary,
                parse_setup_mode,
                parse_setup_strict,
                setup_agent_slug,
                should_attempt_setup,
            )

            # No live binary distribution exists for the external memory helper
            # (the old DXRK_MEMORY formula and Dxrk777/memory releases are gone):
            # Dxrk uses its native Python memory (dxrk.memory) instead.
            if self._profile.package_manager == "brew":
                log.warning(
                    "DXRK_MEMORY no tiene fórmula brew activa; se usará la memoria nativa de Python en su lugar"
                )
            elif shutil.which("DXRK_MEMORY") is None:
                # Download memory binary
                try:
                    download_latest_binary(self._profile)
                except Exception as e:
                    log.warning(
                        "binario de memoria no disponible (%s); se usará la memoria nativa de Python en su lugar", e
                    )

            setup_mode = parse_setup_mode(os.environ.get("GENTLE_AI_MEMORY_SETUP_MODE", ""))
            setup_strict = parse_setup_strict(os.environ.get("GENTLE_AI_MEMORY_SETUP_STRICT", ""))
            attempted_slugs: set[str] = set()

            for adapter in adapters:
                if should_attempt_setup(setup_mode, adapter.agent):
                    slug, _ = setup_agent_slug(adapter.agent)
                    if slug not in attempted_slugs:
                        err = execute_command("memory", "setup", slug)
                        if err and setup_strict:
                            return f"setup de memoria para {adapter.agent!r}: {err}"
                        attempted_slugs.add(slug)

                from dxrk.components.memory import inject as memory_inject_fn

                res_memory = memory_inject_fn(self._home_dir, adapter)
                if res_memory.Changed:
                    log.info("memoria inyectada para %s: %s", adapter.agent, res_memory.Files)
            return None

        if c == ComponentID.CONTEXT7:
            from dxrk.components.context7 import inject as mcp_inject

            for adapter in adapters:
                res_mcp = mcp_inject(self._home_dir, adapter)
                if res_mcp.Changed:
                    log.info("context7 inyectado para %s", adapter.agent)
            return None

        if c == ComponentID.PERSONA:
            from dxrk.components.persona import inject as persona_inject

            for adapter in adapters:
                res_persona = persona_inject(self._home_dir, adapter, self._selection.persona)
                if res_persona.Changed:
                    log.info("persona inyectada para %s", adapter.agent)
            return None

        if c == ComponentID.PERMISSIONS:
            from dxrk.components.permissions import inject as perm_inject

            for adapter in adapters:
                res_perms = perm_inject(self._home_dir, adapter)
                if res_perms.Changed:
                    log.info("permisos inyectados para %s", adapter.agent)
            return None

        if c == ComponentID.SDD:
            from dxrk.components.sdd import InjectOptions
            from dxrk.components.sdd import inject as sdd_inject

            for adapter in adapters:
                opts = InjectOptions(
                    opencode_model_assignments=self._selection.model_assignments,
                    claude_model_assignments=self._selection.claude_model_assignments,
                    kiro_model_assignments=self._selection.kiro_model_assignments,
                    workspace_dir=self._workspace_dir,
                    strict_tdd=self._selection.strict_tdd,
                )
                res_sdd = sdd_inject(self._home_dir, adapter, self._selection.sdd_mode, opts)
                if res_sdd.Changed:
                    log.info("sdd inyectado para %s", adapter.agent)
            return None

        if c == ComponentID.SKILLS:
            skill_ids = _selected_skill_ids(self._selection)
            if not skill_ids:
                return None
            from dxrk.components.skills import inject as skills_inject

            for adapter in adapters:
                res_skills = skills_inject(self._home_dir, adapter, skill_ids)
                if res_skills.Changed:
                    log.info("skills inyectados para %s", adapter.agent)
            return None

        if c == ComponentID.DXRK_GUARDIAN:
            from dxrk.components.gga import ensure_dxrk_guardian_shim, ensure_runtime_assets
            from dxrk.components.gga import inject as gga_inject

            if not _gga_available(self._profile):
                if self._profile.package_manager == "brew":
                    err = run_command_sequence(
                        [
                            ["brew", "tap", "gentleman-programming/homebrew-tap"],
                            ["brew", "install", "gga"],
                        ]
                    )
                else:
                    err = run_command_sequence(
                        [
                            [
                                "bash",
                                "-c",
                                "$(curl -fsSL https://raw.githubusercontent.com/Gentleman-Programming/gentleman-guardian-angel/main/install.sh)",
                            ],
                        ]
                    )
                # Bridge upstream `gga` to the `DXRK_GUARDIAN` name before
                # re-checking availability, so a working install is not
                # reported as an error.
                ensure_dxrk_guardian_shim(self._home_dir)
                if err:
                    if _gga_available(self._profile):
                        log.warning("la instalación de gga reportó un error, pero gga está disponible: %s", err)
                    else:
                        return err

            ensure_runtime_assets(self._home_dir)

            res_gga = gga_inject(self._home_dir, self._agents)
            log.info(
                "gga inyectado: config_changed=%s agents_changed=%s",
                res_gga.ConfigChanged,
                res_gga.AgentsChanged,
            )
            return None

        if c == ComponentID.THEME:
            from dxrk.components.theme import inject as theme_inject

            for adapter in adapters:
                res_theme = theme_inject(self._home_dir, adapter)
                if res_theme.Changed:
                    log.info("theme inyectado para %s", adapter.agent)
            return None

        return f"el componente {c!r} no es compatible con el runtime de install"


def _gga_available(profile: PlatformProfile) -> bool:
    if shutil.which("DXRK_GUARDIAN"):
        return True
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".local", "bin", "DXRK_GUARDIAN"),
        os.path.join(home, "bin", "DXRK_GUARDIAN"),
    ]
    if profile.os == "darwin" or profile.package_manager == "brew":
        candidates.extend(
            [
                "/opt/homebrew/bin/DXRK_GUARDIAN",
                "/usr/local/bin/DXRK_GUARDIAN",
            ]
        )
    for c in candidates:
        if os.path.isfile(c):
            return True
    return False


def _selected_skill_ids(selection: Selection) -> list[SkillID]:
    if selection.skills:
        return selection.skills
    return _skills_for_preset(selection.preset)


def _skills_for_preset(preset: PresetID) -> list[SkillID]:
    if preset == PresetID.FULL_DXRK:
        return [
            SkillID.SDD_INIT,
            SkillID.SDD_EXPLORE,
            SkillID.SDD_PROPOSE,
            SkillID.SDD_SPEC,
            SkillID.SDD_DESIGN,
            SkillID.SDD_TASKS,
            SkillID.SDD_APPLY,
            SkillID.SDD_VERIFY,
            SkillID.SDD_ARCHIVE,
            SkillID.SDD_ONBOARD,
            SkillID.GO_TESTING,
            SkillID.SKILL_CREATOR,
            SkillID.JUDGMENT_DAY,
            SkillID.BRANCH_PR,
            SkillID.ISSUE_CREATION,
            SkillID.SKILL_REGISTRY,
        ]
    return []
