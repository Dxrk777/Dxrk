# SPDX-License-Identifier: MIT
"""
CLI installer — ports internal/cli/ (run.go, install.go, sync.go, restore.go, uninstall.go, dryrun.go, validate.go).
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)


# ─── Minimal verify types (internal/verify pending) ──────────────────


@dataclass
class _VerifyCheck:
    id: str = ""
    description: str = ""
    soft: bool = False
    error: str = ""


@dataclass
class _VerifyReport:
    checks: list[_VerifyCheck] = field(default_factory=list)
    ready: bool = True
    final_note: str = ""


def _run_checks(checks: list[Callable[[], str | None]]) -> list[_VerifyCheck]:
    results: list[_VerifyCheck] = []
    for i, check_fn in enumerate(checks):
        cid = getattr(check_fn, "_cid", f"check:{i}")
        desc = getattr(check_fn, "_desc", "")
        soft = getattr(check_fn, "_soft", False)
        err = check_fn()
        results.append(
            _VerifyCheck(id=cid, description=desc, soft=soft, error=err or "")
        )
    return results


def _build_report(checks: list[_VerifyCheck]) -> _VerifyReport:
    ready = True
    for c in checks:
        if c.error and not c.soft:
            ready = False
    return _VerifyReport(checks=checks, ready=ready)


def _render_report(report: _VerifyReport) -> str:
    lines: list[str] = []
    for c in report.checks:
        if c.error:
            marker = "WARN" if c.soft else "FAIL"
            lines.append(f"  [{marker}] {c.id}: {c.error}")
        else:
            lines.append(f"  [PASS] {c.id}")
    if report.final_note:
        lines.append("")
        lines.append(report.final_note)
    return "\n".join(lines)


# ─── InstallFlags ───────────────────────────────────────────────────────────


@dataclass
class InstallFlags:
    agents: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    persona: str = ""
    preset: str = ""
    sdd_mode: str = ""
    dry_run: bool = False


def _csv_append_type(value: str) -> list[str]:
    return [p.strip() for p in value.split(",") if p.strip()]


def _flatten_list(nested: list[list[str]]) -> list[str]:
    result: list[str] = []
    for sub in nested:
        result.extend(sub)
    return result


def parse_install_flags(args: list[str]) -> InstallFlags:
    parser = argparse.ArgumentParser(prog="install", add_help=False)
    parser.add_argument(
        "--agent",
        "--agents",
        action="append",
        type=_csv_append_type,
        default=[],
        dest="agents",
    )
    parser.add_argument(
        "--component",
        "--components",
        action="append",
        type=_csv_append_type,
        default=[],
        dest="components",
    )
    parser.add_argument(
        "--skill",
        "--skills",
        action="append",
        type=_csv_append_type,
        default=[],
        dest="skills",
    )
    parser.add_argument("--persona", type=str, default="", dest="persona")
    parser.add_argument("--preset", type=str, default="", dest="preset")
    parser.add_argument("--sdd-mode", type=str, default="", dest="sdd_mode")
    parser.add_argument("--dry-run", action="store_true", default=False, dest="dry_run")

    parsed, unknown = parser.parse_known_args(args)
    if unknown:
        raise ValueError(f"unexpected install argument {unknown[0]!r}")

    return InstallFlags(
        agents=_flatten_list(parsed.agents) if parsed.agents else [],
        components=_flatten_list(parsed.components) if parsed.components else [],
        skills=_flatten_list(parsed.skills) if parsed.skills else [],
        persona=parsed.persona or "",
        preset=parsed.preset or "",
        sdd_mode=parsed.sdd_mode or "",
        dry_run=parsed.dry_run or False,
    )


# ─── SyncFlags ──────────────────────────────────────────────────────────────


@dataclass
class SyncFlags:
    agents: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    sdd_mode: str = ""
    sdd_profile_strategy: str = ""
    strict_tdd: bool = False
    include_permissions: bool = False
    include_theme: bool = False
    dry_run: bool = False
    profiles: list[dict[str, Any]] = field(default_factory=list)
    _raw_profiles: list[str] = field(default_factory=list)
    _raw_profile_phases: list[str] = field(default_factory=list)


from dxrk.models import ModelAssignment, Profile, SDDProfileStrategyID
from dxrk.state import ModelAssignmentState


def _parse_profile_sync_strategy(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value in ("generated-multi", "external-single-active"):
        return value
    raise ValueError(
        f"unsupported sdd-profile-strategy {raw!r} (valid: generated-multi, external-single-active)"
    )


def _parse_profile_flag(raw: str) -> Profile:
    from dxrk.components.sdd import validate_profile_name
    from dxrk.models import Profile

    colon_idx = raw.find(":")
    if colon_idx <= 0:
        raise ValueError(
            f"--profile {raw!r}: invalid format, expected name:provider/model"
        )
    name = raw[:colon_idx]
    model_spec = raw[colon_idx + 1 :]

    err = validate_profile_name(name)
    if err:
        raise ValueError(f"--profile {raw!r}: {err}")

    assignment = _parse_model_spec(model_spec)
    return Profile(name=name, orchestrator_model=assignment, phase_assignments={})


def _parse_profile_phase_flag(raw: str) -> tuple[str, str, ModelAssignment]:
    from dxrk.components.sdd import profile_phase_order, validate_profile_name

    parts = raw.split(":", 2)
    if len(parts) != 3:
        raise ValueError(
            f"--profile-phase {raw!r}: invalid format, expected name:phase:provider/model"
        )
    name, phase, model_spec = parts

    if not name:
        raise ValueError(f"--profile-phase {raw!r}: profile name must not be empty")
    err = validate_profile_name(name)
    if err:
        raise ValueError(f"--profile-phase {raw!r}: {err}")
    if not phase:
        raise ValueError(f"--profile-phase {raw!r}: phase must not be empty")

    known = profile_phase_order()
    if phase not in known:
        raise ValueError(
            f"--profile-phase {raw!r}: unknown phase {phase!r}; valid phases are: {known}"
        )

    assignment = _parse_model_spec(model_spec)
    return name, phase, assignment


def _parse_model_spec(spec: str) -> ModelAssignment:
    sep = -1
    for i, c in enumerate(spec):
        if c in ("/", ":"):
            sep = i
            break
    if sep <= 0:
        raise ValueError(
            f"invalid model spec {spec!r}: expected provider/model or provider:model"
        )
    provider_id = spec[:sep]
    model_id = spec[sep + 1 :]
    if not provider_id or not model_id:
        raise ValueError(
            f"invalid model spec {spec!r}: provider and model must both be non-empty"
        )
    return ModelAssignment(provider_id=provider_id, model_id=model_id)


def _parse_profiles(raw_profiles: list[str], raw_phases: list[str]) -> list[Profile]:
    profile_map: dict[str, Profile] = {}
    profile_order: list[str] = []

    for raw in raw_profiles:
        p = _parse_profile_flag(raw)
        profile_map[p.name] = p
        profile_order.append(p.name)

    for raw in raw_phases:
        name, phase, assignment = _parse_profile_phase_flag(raw)
        if name not in profile_map:
            new_p = Profile(name=name, phase_assignments={})
            profile_map[name] = new_p
            profile_order.append(name)
        entry = profile_map[name]
        entry.phase_assignments[phase] = assignment

    seen: set[str] = set()
    profiles: list[Profile] = []
    for name in profile_order:
        if name in seen:
            continue
        seen.add(name)
        profiles.append(profile_map[name])
    return profiles


def parse_sync_flags(args: list[str]) -> SyncFlags:
    parser = argparse.ArgumentParser(prog="sync", add_help=False)
    parser.add_argument(
        "--agent",
        "--agents",
        action="append",
        type=_csv_append_type,
        default=[],
        dest="agents_raw",
    )
    parser.add_argument(
        "--skill",
        "--skills",
        action="append",
        type=_csv_append_type,
        default=[],
        dest="skills_raw",
    )
    parser.add_argument("--sdd-mode", type=str, default="", dest="sdd_mode")
    parser.add_argument(
        "--sdd-profile-strategy", type=str, default="", dest="sdd_profile_strategy"
    )
    parser.add_argument(
        "--strict-tdd", action="store_true", default=False, dest="strict_tdd"
    )
    parser.add_argument(
        "--include-permissions",
        action="store_true",
        default=False,
        dest="include_permissions",
    )
    parser.add_argument(
        "--include-theme", action="store_true", default=False, dest="include_theme"
    )
    parser.add_argument("--dry-run", action="store_true", default=False, dest="dry_run")
    parser.add_argument(
        "--profile",
        action="append",
        type=_csv_append_type,
        default=[],
        dest="raw_profiles",
    )
    parser.add_argument(
        "--profile-phase",
        action="append",
        type=_csv_append_type,
        default=[],
        dest="raw_profile_phases",
    )

    parsed, unknown = parser.parse_known_args(args)
    if unknown:
        raise ValueError(f"unexpected sync argument {unknown[0]!r}")

    strategy = _parse_profile_sync_strategy(parsed.sdd_profile_strategy or "")

    agents = _flatten_list(parsed.agents_raw) if parsed.agents_raw else []
    skills = _flatten_list(parsed.skills_raw) if parsed.skills_raw else []
    raw_profiles = _flatten_list(parsed.raw_profiles) if parsed.raw_profiles else []
    raw_profile_phases = (
        _flatten_list(parsed.raw_profile_phases) if parsed.raw_profile_phases else []
    )

    profiles: list[Profile] = []
    if raw_profiles or raw_profile_phases:
        profiles = _parse_profiles(raw_profiles, raw_profile_phases)

    return SyncFlags(
        agents=agents,
        skills=skills,
        sdd_mode=parsed.sdd_mode or "",
        sdd_profile_strategy=strategy,
        strict_tdd=parsed.strict_tdd or False,
        include_permissions=parsed.include_permissions or False,
        include_theme=parsed.include_theme or False,
        dry_run=parsed.dry_run or False,
        profiles=[p.__dict__ for p in profiles] if profiles else [],
    )


# ─── UninstallFlags ─────────────────────────────────────────────────────────


@dataclass
class UninstallFlags:
    agents: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    all: bool = False
    yes: bool = False


def parse_uninstall_flags(args: list[str]) -> UninstallFlags:
    parser = argparse.ArgumentParser(prog="uninstall", add_help=False)
    parser.add_argument(
        "--agent",
        "--agents",
        action="append",
        type=_csv_append_type,
        default=[],
        dest="agents_raw",
    )
    parser.add_argument(
        "--component",
        "--components",
        action="append",
        type=_csv_append_type,
        default=[],
        dest="components_raw",
    )
    parser.add_argument("--all", action="store_true", default=False, dest="all")
    parser.add_argument("--yes", "-y", action="store_true", default=False, dest="yes")

    parsed, unknown = parser.parse_known_args(args)
    if unknown:
        raise ValueError(f"unexpected uninstall argument {unknown[0]!r}")

    opts = UninstallFlags(
        agents=_flatten_list(parsed.agents_raw) if parsed.agents_raw else [],
        components=_flatten_list(parsed.components_raw)
        if parsed.components_raw
        else [],
        all=parsed.all or False,
        yes=parsed.yes or False,
    )

    if opts.all and (opts.agents or opts.components):
        raise ValueError(
            "--all cannot be combined with --agent/--agents or --component/--components"
        )
    if not opts.all and not opts.agents:
        raise ValueError(
            "partial uninstall requires at least one --agent/--agents or use --all"
        )
    return opts


# ─── InstallInput / Normalize ──────────────────────────────────────────────

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
        raise ValueError(f"unsupported persona {value!r}")


def normalize_preset(value: str) -> PresetID:
    v = value.strip()
    if not v:
        return PresetID.FULL_DXRK
    try:
        return PresetID(v)
    except ValueError:
        raise ValueError(f"unsupported preset {value!r}")


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
            raise ValueError(f"unsupported component {raw!r}")
        if cid not in allowed:
            raise ValueError(f"unsupported component {raw!r}")
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
            raise ValueError(f"unsupported skill {raw!r}")
        if sid not in allowed:
            raise ValueError(f"unsupported skill {raw!r}")
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
    raise ValueError(f"unsupported sdd-mode {value!r} (valid: single, multi)")


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
            log.warning("unknown agent ID: %s", v)
    return result


def _unique(items: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def normalize_install_flags(
    flags: InstallFlags, detection: DetectionResult
) -> InstallInput:
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


# ─── Pipeline Steps ────────────────────────────────────────────────────────

from dxrk.pipeline import (
    RollbackStep,
    Step,
    execute_command,
    run_command_sequence,
)
from dxrk.planner import PlatformDecision, ResolvedPlan, platform_decision_from_profile
from dxrk.system import PlatformProfile


class NoopStep(Step):
    def __init__(self, step_id: str):
        self._id = step_id

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        return None


def _resolve_adapters(agent_ids: list[AgentID]) -> list[Any]:
    from dxrk.agents.registry import Registry

    reg = Registry()
    adapters: list[Any] = []
    for aid in agent_ids:
        try:
            adapter = reg.get(aid) or _create_agent_adapter(aid)
            if adapter:
                adapters.append(adapter)
        except Exception:
            continue
    return adapters


def _create_agent_adapter(agent_id: AgentID) -> Any:
    from dxrk.agents.factory import create_registry

    reg = create_registry()
    return reg.get(agent_id)


class AgentInstallStep(Step):
    def __init__(
        self, step_id: str, agent: AgentID, home_dir: str, profile: PlatformProfile
    ):
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
            return f"no adapter for agent {self._agent!r}"

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
            return f"install command for {self._agent!r} resolved to an empty sequence"
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
                return f"create adapter for {agent!r}"
            if not adapter.supports_auto_install:
                continue
            if self._home_dir:
                result = adapter.detect(self._home_dir)
                if result.installed:
                    continue
            # Pre-flight validation (simplified: skip installcmd validation for now)
        return None


class PrepareBackupStep(RollbackStep):
    def __init__(
        self,
        step_id: str,
        snapshot_dir: str,
        targets: list[str],
        state: dict[str, Any],
        backup_root: str = "",
        source: str = "",
        description: str = "",
        app_version: str = "",
    ):
        self._id = step_id
        self._snapshot_dir = snapshot_dir
        self._targets = targets
        self._state = state
        self._backup_root = backup_root
        self._source = source
        self._description = description
        self._app_version = app_version

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        if not self._targets:
            return None
        os.makedirs(self._snapshot_dir, mode=0o755, exist_ok=True)
        manifest: dict[str, Any] = {"entries": []}
        for target in self._targets:
            if os.path.isfile(target):
                rel = os.path.relpath(target, "/").lstrip("/")
                dest = os.path.join(self._snapshot_dir, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                try:
                    import shutil

                    shutil.copy2(target, dest)
                    manifest["entries"].append({"source": target, "dest": rel})
                except OSError as e:
                    log.warning("backup: could not copy %s: %s", target, e)
        manifest["source"] = self._source
        manifest["description"] = self._description
        manifest["created_by_version"] = self._app_version
        manifest_path = os.path.join(self._snapshot_dir, "manifest.json")
        try:
            import json

            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)
        except OSError as e:
            log.warning("backup: could not write manifest: %s", e)
        self._state["manifest"] = manifest
        return None

    def rollback(self) -> str | None:
        manifest = self._state.get("manifest", {})
        entries = manifest.get("entries", [])
        if not entries:
            return None
        for entry in entries:
            dest = os.path.join(self._snapshot_dir, entry.get("dest", ""))
            source = entry.get("source", "")
            if os.path.isfile(dest) and source:
                try:
                    import shutil

                    shutil.copy2(dest, source)
                except OSError as e:
                    log.warning("rollback: could not restore %s: %s", source, e)
        return None


class RollbackRestoreStep(RollbackStep):
    def __init__(self, step_id: str, state: dict[str, Any]):
        self._id = step_id
        self._state = state

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        return None

    def rollback(self) -> str | None:
        manifest = self._state.get("manifest", {})
        entries = manifest.get("entries", [])
        if not entries:
            return None
        import shutil

        for entry in entries:
            dest_path = os.path.join(
                os.path.dirname(manifest.get("_backup_root", "")),
                entry.get("dest", ""),
            )
            source = entry.get("source", "")
            if os.path.isfile(dest_path) and source:
                try:
                    shutil.copy2(dest_path, source)
                except OSError as e:
                    log.warning("rollback: could not restore %s: %s", source, e)
        return None


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
            from dxrk.components.engram import (
                download_latest_binary,
                parse_setup_mode,
                parse_setup_strict,
                setup_agent_slug,
                should_attempt_setup,
            )

            if self._profile.package_manager == "brew":
                err = run_command_sequence(
                    [
                        ["brew", "tap", "gentleman-programming/tap"],
                        ["brew", "install", "DXRK_MEMORY"],
                    ]
                )
                if err:
                    return err
            elif shutil.which("DXRK_MEMORY") is None:
                # Download engram binary
                try:
                    download_latest_binary(self._profile)
                except Exception as e:
                    return f"download engram binary: {e}"

            setup_mode = parse_setup_mode(
                os.environ.get("GENTLE_AI_ENGRAM_SETUP_MODE", "")
            )
            setup_strict = parse_setup_strict(
                os.environ.get("GENTLE_AI_ENGRAM_SETUP_STRICT", "")
            )
            attempted_slugs: set[str] = set()

            for adapter in adapters:
                if should_attempt_setup(setup_mode, adapter.agent):
                    slug, _ = setup_agent_slug(adapter.agent)
                    if slug not in attempted_slugs:
                        err = execute_command("engram", "setup", slug)
                        if err and setup_strict:
                            return f"engram setup for {adapter.agent!r}: {err}"
                        attempted_slugs.add(slug)

                from dxrk.components.engram import inject as engram_inject_fn

                res_engram = engram_inject_fn(self._home_dir, adapter)
                if res_engram.Changed:
                    log.info(
                        "engram injected for %s: %s", adapter.agent, res_engram.Files
                    )
            return None

        if c == ComponentID.CONTEXT7:
            from dxrk.components.context7 import inject as mcp_inject

            for adapter in adapters:
                res_mcp = mcp_inject(self._home_dir, adapter)
                if res_mcp.Changed:
                    log.info("context7 injected for %s", adapter.agent)
            return None

        if c == ComponentID.PERSONA:
            from dxrk.components.persona import inject as persona_inject

            for adapter in adapters:
                res_persona = persona_inject(
                    self._home_dir, adapter, self._selection.persona
                )
                if res_persona.Changed:
                    log.info("persona injected for %s", adapter.agent)
            return None

        if c == ComponentID.PERMISSIONS:
            from dxrk.components.permissions import inject as perm_inject

            for adapter in adapters:
                res_perms = perm_inject(self._home_dir, adapter)
                if res_perms.Changed:
                    log.info("permissions injected for %s", adapter.agent)
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
                res_sdd = sdd_inject(
                    self._home_dir, adapter, self._selection.sdd_mode, opts
                )
                if res_sdd.Changed:
                    log.info("sdd injected for %s", adapter.agent)
            return None

        if c == ComponentID.SKILLS:
            skill_ids = _selected_skill_ids(self._selection)
            if not skill_ids:
                return None
            from dxrk.components.skills import inject as skills_inject

            for adapter in adapters:
                res_skills = skills_inject(self._home_dir, adapter, skill_ids)
                if res_skills.Changed:
                    log.info("skills injected for %s", adapter.agent)
            return None

        if c == ComponentID.DXRK_GUARDIAN:
            from dxrk.components.gga import ensure_runtime_assets
            from dxrk.components.gga import inject as gga_inject

            if not _gga_available(self._profile):
                if self._profile.package_manager == "brew":
                    err = run_command_sequence([["brew", "install", "DXRK_GUARDIAN"]])
                else:
                    err = run_command_sequence(
                        [
                            [
                                "bash",
                                "-c",
                                "$(curl -fsSL https://raw.githubusercontent.com/gentleman-programming/gga/main/install.sh)",
                            ],
                        ]
                    )
                if err:
                    if _gga_available(self._profile):
                        log.warning(
                            "gga install reported error but gga is available: %s", err
                        )
                    else:
                        return err

            ensure_runtime_assets(self._home_dir)

            res_gga = gga_inject(self._home_dir, self._agents)
            log.info(
                "gga injected: config_changed=%s agents_changed=%s",
                res_gga.ConfigChanged,
                res_gga.AgentsChanged,
            )
            return None

        if c == ComponentID.THEME:
            from dxrk.components.theme import inject as theme_inject

            for adapter in adapters:
                res_theme = theme_inject(self._home_dir, adapter)
                if res_theme.Changed:
                    log.info("theme injected for %s", adapter.agent)
            return None

        return f"component {c!r} is not supported in install runtime"


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


# ─── Runtime ─────────────────────────────────────────────────────────────────


@dataclass
class RuntimeState:
    manifest: dict[str, Any] = field(default_factory=dict)


class InstallRuntime:
    def __init__(
        self,
        home_dir: str,
        workspace_dir: str,
        selection: Selection,
        resolved: ResolvedPlan,
        profile: PlatformProfile,
        backup_root: str = "",
        app_version: str = "dev",
    ):
        self.home_dir = home_dir
        self.workspace_dir = workspace_dir
        self.selection = selection
        self.resolved = resolved
        self.profile = profile
        self.backup_root = backup_root or os.path.join(
            home_dir, ".gentle-ai", "backups"
        )
        self.app_version = app_version
        self._state: dict[str, Any] = {}

    def stage_plan(self):
        from dxrk.pipeline import StagePlan

        targets = _backup_targets(self.home_dir, self.selection, self.resolved)

        prepare: list[Step] = [
            CheckDependenciesStep(
                "prepare:check-dependencies",
                self.profile,
                self.home_dir,
                self.selection,
            ),
            PrepareBackupStep(
                step_id="prepare:backup-snapshot",
                snapshot_dir=os.path.join(
                    self.backup_root,
                    datetime.now(UTC).strftime("%Y%m%d%H%M%S.%f"),
                ),
                targets=targets,
                state=self._state,
                backup_root=self.backup_root,
                source="install",
                description="pre-install snapshot",
                app_version=self.app_version,
            ),
        ]

        apply: list[Step] = [
            RollbackRestoreStep("apply:rollback-restore", self._state),
        ]

        for agent in self.resolved.agents:
            if agent == AgentID.KIMI:
                apply.append(
                    KimiSystemPromptHubStep("agent:kimi-prompt-hub", self.home_dir)
                )

        for agent in self.resolved.agents:
            apply.append(
                AgentInstallStep(
                    f"agent:{agent.value}", agent, self.home_dir, self.profile
                )
            )

        if any(a == AgentID.OPENCODE for a in self.resolved.agents):
            for plugin in self.selection.opencode_plugins:
                apply.append(
                    OpenCodePluginInstallStep(
                        f"opencode-plugin:{plugin.value}",
                        plugin,
                        self.home_dir,
                    )
                )

        for component in self.resolved.ordered_components:
            apply.append(
                ComponentApplyStep(
                    step_id=f"component:{component.value}",
                    component=component,
                    home_dir=self.home_dir,
                    workspace_dir=self.workspace_dir,
                    agents=self.resolved.agents,
                    selection=self.selection,
                    profile=self.profile,
                )
            )

        if not self.selection.agents and not self.resolved.ordered_components:
            prepare = []

        return StagePlan(prepare=prepare, apply=apply)


def _backup_targets(
    home_dir: str, selection: Selection, resolved: ResolvedPlan
) -> list[str]:
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
                result.append(adapter.mcp_config_path(home_dir, "engram"))
            elif mcps == MCPStrategy.MERGE_INTO_SETTINGS:
                p = adapter.settings_path(home_dir)
                if p:
                    result.append(p)
            elif mcps == MCPStrategy.TOML_FILE:
                p = adapter.mcp_config_path(home_dir, "engram")
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
            elif mcps in (MCPStrategy.MERGE_INTO_SETTINGS, MCPStrategy.MCP_CONFIG_FILE):
                p = adapter.settings_path(home_dir)
                if p:
                    result.append(p)
                result.append(adapter.mcp_config_path(home_dir, "context7"))

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
                    result.append(
                        os.path.join(adapter.output_style_dir(home_dir), "gentleman.md")
                    )
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
            p = adapter.settings_path(home_dir)
            if p:
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


# ─── Sync Runtime ───────────────────────────────────────────────────────────


@dataclass
class SyncResult:
    agents: list[AgentID] = field(default_factory=list)
    selection: Selection = field(default_factory=Selection)
    plan: Any = None
    execution: Any = None
    verify: _VerifyReport = field(default_factory=_VerifyReport)
    dry_run: bool = False
    no_op: bool = False
    files_changed: int = 0


class ComponentSyncStep(Step):
    def __init__(
        self,
        step_id: str,
        component: ComponentID,
        home_dir: str,
        workspace_dir: str,
        agents: list[AgentID],
        selection: Selection,
        files_changed: list[int],
    ):
        self._id = step_id
        self._component = component
        self._home_dir = home_dir
        self._workspace_dir = workspace_dir
        self._agents = agents
        self._selection = selection
        self._files_changed = files_changed

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        adapters = _resolve_adapters(self._agents)
        c = self._component

        if c == ComponentID.DXRK_MEMORY:
            from dxrk.components.engram import inject as engram_inject

            for adapter in adapters:
                res_engram = engram_inject(self._home_dir, adapter)
                self._count_changed(int(res_engram.Changed))
            return None

        if c == ComponentID.CONTEXT7:
            from dxrk.components.context7 import inject as mcp_inject

            for adapter in adapters:
                res_mcp = mcp_inject(self._home_dir, adapter)
                self._count_changed(int(res_mcp.Changed))
            return None

        if c == ComponentID.SDD:
            from dxrk.components.sdd import (
                InjectOptions,
                detect_profiles,
                resolve_profile_strategy,
            )
            from dxrk.components.sdd import (
                inject as sdd_inject,
            )

            profile_strategy = resolve_profile_strategy(
                self._home_dir, self._selection.sdd_profile_strategy
            )
            profiles = list(self._selection.profiles)

            if not profiles and profile_strategy != "external-single-active":
                for adapter in adapters:
                    if adapter.agent == AgentID.OPENCODE:
                        settings_path = adapter.settings_path(self._home_dir)
                        if settings_path:
                            try:
                                detected = detect_profiles(settings_path)
                                profiles = detected
                            except Exception:
                                pass
                        break

            sdd_mode = self._selection.sdd_mode
            if profile_strategy == "external-single-active":
                sdd_mode = SDDModeID.MULTI if sdd_mode is None else sdd_mode
            elif profiles and (sdd_mode is None or sdd_mode == ""):
                sdd_mode = SDDModeID.MULTI

            for adapter in adapters:
                opts = InjectOptions(
                    opencode_model_assignments=self._selection.model_assignments,
                    claude_model_assignments=self._selection.claude_model_assignments,
                    kiro_model_assignments=self._selection.kiro_model_assignments,
                    workspace_dir=self._workspace_dir,
                    strict_tdd=self._selection.strict_tdd,
                    preserve_opencode_orchestrator_prompt=(
                        profile_strategy == "external-single-active"
                    ),
                    profiles=profiles,
                )
                res_sdd = sdd_inject(
                    self._home_dir,
                    adapter,
                    sdd_mode or SDDModeID.SINGLE,
                    opts,
                )
                self._count_changed(int(res_sdd.Changed))
            return None

        if c == ComponentID.SKILLS:
            skill_ids = _selected_skill_ids(self._selection)
            if not skill_ids:
                return None
            from dxrk.components.skills import inject as skills_inject

            for adapter in adapters:
                res_skills = skills_inject(self._home_dir, adapter, skill_ids)
                self._count_changed(int(res_skills.Changed))
            return None

        if c == ComponentID.DXRK_GUARDIAN:
            from dxrk.components.gga import ensure_runtime_assets
            from dxrk.components.gga import inject as gga_inject

            ensure_runtime_assets(self._home_dir)

            res_gga = gga_inject(self._home_dir, self._agents)
            self._count_changed(int(res_gga.ConfigChanged) + int(res_gga.AgentsChanged))
            return None

        if c == ComponentID.PERMISSIONS:
            from dxrk.components.permissions import inject as perm_inject

            for adapter in adapters:
                res_perms = perm_inject(self._home_dir, adapter)
                self._count_changed(int(res_perms.Changed))
            return None

        if c == ComponentID.THEME:
            from dxrk.components.theme import inject as theme_inject

            for adapter in adapters:
                res_theme = theme_inject(self._home_dir, adapter)
                self._count_changed(int(res_theme.Changed))
            return None

        return None

    def _count_changed(self, n: int) -> None:
        if n > 0 and self._files_changed:
            self._files_changed[0] += n


class SyncRuntime:
    def __init__(
        self,
        home_dir: str,
        workspace_dir: str,
        selection: Selection,
        backup_root: str = "",
        app_version: str = "dev",
    ):
        self.home_dir = home_dir
        self.workspace_dir = workspace_dir
        self.selection = selection
        self.agent_ids = selection.agents
        self.backup_root = backup_root or os.path.join(
            home_dir, ".gentle-ai", "backups"
        )
        self.app_version = app_version
        self._state: dict[str, Any] = {}
        self.files_changed: list[int] = [0]

    def stage_plan(self):
        from dxrk.pipeline import StagePlan

        adapters = _resolve_adapters(self.agent_ids)
        targets = _sync_backup_targets(self.home_dir, self.selection, adapters)

        prepare: list[Step] = [
            PrepareBackupStep(
                step_id="prepare:backup-snapshot",
                snapshot_dir=os.path.join(
                    self.backup_root,
                    datetime.now(UTC).strftime("%Y%m%d%H%M%S.%f"),
                ),
                targets=targets,
                state=self._state,
                backup_root=self.backup_root,
                source="sync",
                description="pre-sync snapshot",
                app_version=self.app_version,
            ),
        ]

        apply: list[Step] = [
            RollbackRestoreStep("apply:rollback-restore", self._state),
        ]

        for component in self.selection.components:
            apply.append(
                ComponentSyncStep(
                    step_id=f"sync:component:{component.value}",
                    component=component,
                    home_dir=self.home_dir,
                    workspace_dir=self.workspace_dir,
                    agents=self.agent_ids,
                    selection=self.selection,
                    files_changed=self.files_changed,
                )
            )

        return StagePlan(prepare=prepare, apply=apply)


def _sync_backup_targets(
    home_dir: str, selection: Selection, adapters: list[Any]
) -> list[str]:
    paths: set[str] = set()
    for component in selection.components:
        for p in _component_paths(home_dir, selection, adapters, component):
            paths.add(p)
    return sorted(paths)


# ─── InstallResult ──────────────────────────────────────────────────────────

from dxrk.planner import ReviewPayload


@dataclass
class InstallResult:
    selection: Selection = field(default_factory=Selection)
    resolved: ResolvedPlan | None = None
    review: ReviewPayload | None = None
    plan: Any = None
    execution: Any = None
    verify: _VerifyReport = field(default_factory=_VerifyReport)
    dependencies: Any = None
    dry_run: bool = False
    error: str = ""


# ─── ResolveInstallProfile ─────────────────────────────────────────────────


def resolve_install_profile(detection: DetectionResult) -> PlatformProfile:
    if detection.system.profile.os:
        return detection.system.profile
    return PlatformProfile(os="darwin", package_manager="brew", supported=True)


# ─── BuildStagePlan ─────────────────────────────────────────────────────────


def build_stage_plan(selection: Selection, resolved: ResolvedPlan) -> Any:
    from dxrk.pipeline import StagePlan

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


app_version = "dev"


# ─── RunInstall ─────────────────────────────────────────────────────────────


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
        rt = InstallRuntime(
            home_dir, os.getcwd(), input_data.selection, resolved, profile
        )
    except Exception as e:
        return InstallResult(error=str(e))

    from dxrk.system import format_missing_deps_message

    assert detection.dependencies is not None, "detection did not populate dependencies"
    if not detection.dependencies.all_present:
        missing = ", ".join(detection.dependencies.missing_required)
        log.warning(
            "missing dependencies: %s\n%s",
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
            error=f"execute install pipeline: {result.execution.error}",
        )

    result.verify = _run_post_apply_verification(
        home_dir, input_data.selection, resolved
    )
    result.verify = _with_post_install_notes(result.verify, resolved, profile)

    if not result.verify.ready:
        return result

    from dxrk.state import InstallState
    from dxrk.state import write as state_write

    agent_ids = [a.value for a in input_data.selection.agents]
    model_assignments = _model_assignments_to_state(
        input_data.selection.model_assignments
    )
    state_write(
        home_dir,
        InstallState(
            installed_agents=agent_ids,
            claude_model_assignments=input_data.selection.claude_model_assignments
            or None,
            model_assignments=model_assignments,
        ),
    )

    return result


def _with_post_install_notes(
    report: _VerifyReport, resolved: ResolvedPlan, profile: PlatformProfile
) -> _VerifyReport:
    if (
        _has_component(resolved.ordered_components, ComponentID.DXRK_GUARDIAN)
        and report.ready
    ):
        note = "\n\nDXRK_GUARDIAN is now installed globally. To enable project hooks, run in each repo:\n- DXRK_GUARDIAN init\n- DXRK_GUARDIAN install"
        if note not in report.final_note:
            report.final_note += note
    if _has_component(resolved.ordered_components, ComponentID.DXRK_MEMORY):
        if profile.package_manager != "brew":
            bin_dir = _go_install_bin_dir()
            if not _is_in_path(bin_dir):
                guidance = _engram_path_guidance(os.environ.get("SHELL", ""))
                report.final_note += f"\n\nThe engram binary was installed to {bin_dir}.\nAdd it to your PATH: {guidance}"
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


def _engram_path_guidance(shell_path: str) -> str:
    bin_dir = _go_install_bin_dir()
    if "fish" in shell_path:
        return f"set -Ux fish_user_paths {bin_dir} $fish_user_paths"
    if "zsh" in shell_path:
        return f"echo 'export PATH=\"{bin_dir}:$PATH\"' >> ~/.zshrc && source ~/.zshrc"
    if "bash" in shell_path:
        return (
            f"echo 'export PATH=\"{bin_dir}:$PATH\"' >> ~/.bashrc && source ~/.bashrc"
        )
    return f"Add {bin_dir} to your shell PATH and restart the terminal."


def _has_component(components: list[ComponentID], target: ComponentID) -> bool:
    return target in components


def _contains_agent(agents: list[AgentID], target: AgentID) -> bool:
    return target in agents


# ─── BuildRealStagePlan ─────────────────────────────────────────────────────


def build_real_stage_plan(
    home_dir: str,
    selection: Selection,
    resolved: ResolvedPlan,
    profile: PlatformProfile,
) -> Any:

    backup_root = os.path.join(home_dir, ".gentle-ai", "backups")
    os.makedirs(backup_root, mode=0o755, exist_ok=True)

    try:
        rt = InstallRuntime(
            home_dir, os.getcwd(), selection, resolved, profile, backup_root=backup_root
        )
    except Exception as e:
        raise RuntimeError(f"create install runtime: {e}") from e
    return rt.stage_plan()


# ─── RunSync ────────────────────────────────────────────────────────────────


def build_sync_selection(flags: SyncFlags, agent_ids: list[AgentID]) -> Selection:
    components: list[ComponentID] = [
        ComponentID.SDD,
        ComponentID.DXRK_MEMORY,
        ComponentID.CONTEXT7,
        ComponentID.DXRK_GUARDIAN,
        ComponentID.SKILLS,
    ]
    if flags.include_permissions:
        components.append(ComponentID.PERMISSIONS)
    if flags.include_theme:
        components.append(ComponentID.THEME)

    sdd_mode = SDDModeID(flags.sdd_mode) if flags.sdd_mode else SDDModeID.SINGLE
    skill_ids = [SkillID(s) for s in flags.skills]

    return Selection(
        agents=agent_ids,
        components=components,
        sdd_mode=sdd_mode,
        sdd_profile_strategy=SDDProfileStrategyID(flags.sdd_profile_strategy)
        if flags.sdd_profile_strategy
        else SDDProfileStrategyID.GENERATED_MULTI,
        strict_tdd=flags.strict_tdd,
        skills=skill_ids,
        preset=PresetID.FULL_DXRK,
    )


def discover_agents(home_dir: str) -> list[AgentID]:
    from dxrk.state import read as state_read

    try:
        s = state_read(home_dir)
        if s.installed_agents:
            return [AgentID(a) for a in s.installed_agents]
    except Exception:
        pass

    from dxrk.agents.discovery import discover_installed
    from dxrk.agents.factory import create_registry

    reg = create_registry()
    installed = discover_installed(reg, home_dir)
    return [a.id for a in installed]


def _to_agent_ids(strings: list[str]) -> list[AgentID]:
    return [AgentID(s) for s in strings]


def run_sync_with_selection(home_dir: str, selection: Selection) -> SyncResult:
    agent_ids = selection.agents

    result = SyncResult(agents=agent_ids, selection=selection)

    if not agent_ids:
        result.no_op = True
        return result

    rt = SyncRuntime(home_dir, os.getcwd(), selection)
    stage_plan = rt.stage_plan()
    result.plan = stage_plan

    from dxrk.pipeline import default_rollback_policy, new_orchestrator

    orchestrator = new_orchestrator(default_rollback_policy())
    result.execution = orchestrator.execute(stage_plan)

    if result.execution.error:
        return result

    result.files_changed = rt.files_changed[0]

    if result.files_changed == 0:
        result.no_op = True

    result.verify = _run_post_sync_verification(home_dir, selection)

    return result


def run_sync(args: list[str]) -> SyncResult:
    flags = parse_sync_flags(args)

    home_dir = os.path.expanduser("~")

    if flags.agents:
        agent_ids = _to_agent_ids(flags.agents)
    else:
        agent_ids = discover_agents(home_dir)
    agent_ids = _unique(agent_ids)

    selection = build_sync_selection(flags, agent_ids)

    from dxrk.state import read as state_read

    try:
        s = state_read(home_dir)
        if s.claude_model_assignments:
            selection.claude_model_assignments = s.claude_model_assignments
        if s.model_assignments:
            selection.model_assignments = {
                k: ModelAssignment(provider_id=v.provider_id, model_id=v.model_id)
                for k, v in s.model_assignments.items()
            }
    except Exception:
        pass

    if flags.dry_run:
        result = SyncResult(agents=agent_ids, selection=selection, dry_run=True)
        if not agent_ids:
            result.no_op = True
            return result
        rt = SyncRuntime(home_dir, os.getcwd(), selection)
        result.plan = rt.stage_plan()
        return result

    return run_sync_with_selection(home_dir, selection)


# ─── RunRestore ─────────────────────────────────────────────────────────────


def run_restore(args: list[str], stdout: Any = None) -> str | None:
    if stdout is None:
        stdout = sys.stdout

    home_dir = os.path.expanduser("~")

    positional: list[str] = []
    list_flag = False
    yes_flag = False

    for a in args:
        if a in ("--list", "-list"):
            list_flag = True
        elif a in ("--yes", "-yes", "-y"):
            yes_flag = True
        elif a.startswith("-"):
            raise ValueError(f"unknown flag {a!r}")
        else:
            positional.append(a)

    backups = _list_backups(home_dir)

    if list_flag:
        _render_restore_list(backups, stdout)
        return None

    if not positional:
        return "usage: gentle-ai restore [--list | latest | <id>] [--yes]"

    target = positional[0]
    manifest = _resolve_restore_target(target, backups)

    if not yes_flag:
        confirmed = _prompt_restore_confirm(manifest, stdout)
        if not confirmed:
            print("restore cancelled", file=stdout)
            return None

    manifest_dir = manifest.get("_dir", "")

    for entry in manifest.get("entries", []):
        dest_path = entry.get("source", "")
        rel = entry.get("dest", "")
        src_path = os.path.join(manifest_dir, rel) if manifest_dir else ""
        if os.path.isfile(src_path) and dest_path:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            import shutil

            shutil.copy2(src_path, dest_path)

    label = manifest.get("description", "") or manifest.get("source", "") or target
    print(f"restore complete — restored backup {target} ({label})", file=stdout)
    return None


def _list_backups(home_dir: str) -> list[dict[str, Any]]:
    backup_root = os.path.join(home_dir, ".gentle-ai", "backups")
    if not os.path.isdir(backup_root):
        return []

    manifests: list[dict[str, Any]] = []
    for entry in sorted(os.listdir(backup_root), reverse=True):
        entry_path = os.path.join(backup_root, entry)
        if not os.path.isdir(entry_path):
            continue
        manifest_path = os.path.join(entry_path, "manifest.json")
        if os.path.isfile(manifest_path):
            try:
                import json

                with open(manifest_path) as f:
                    m = json.load(f)
                m["_dir"] = entry_path
                m["_id"] = entry
                manifests.append(m)
            except Exception:
                continue

    manifests.sort(key=lambda m: m.get("_id", ""), reverse=True)
    return manifests


def _render_restore_list(backups: list[dict[str, Any]], stdout: Any) -> None:
    if not backups:
        print("no backups found", file=stdout)
        return
    print(f"Available backups ({len(backups)}):", file=stdout)
    for i, m in enumerate(backups):
        bid = m.get("_id", "?")
        source = m.get("source", "unknown")
        count = len(m.get("entries", []))
        version = m.get("created_by_version", "")
        line = f"  [{i + 1}] {bid}  source={source} files={count}"
        if version:
            line += f"  [v{version}]"
        print(line, file=stdout)


def _resolve_restore_target(
    target: str, backups: list[dict[str, Any]]
) -> dict[str, Any]:
    if target == "latest":
        if not backups:
            raise ValueError("no backups available to restore")
        return backups[0]
    for m in backups:
        if m.get("_id") == target:
            return m
    raise ValueError(
        f"backup {target!r} not found — use `gentle-ai restore --list` to see available backups"
    )


def _prompt_restore_confirm(manifest: dict[str, Any], stdout: Any) -> bool:
    bid = manifest.get("_id", "?")
    source = manifest.get("source", "unknown")
    count = len(manifest.get("entries", []))
    print(f"Restore backup {bid} (source={source}, files={count})?", file=stdout)
    print(
        "This will overwrite your current configuration. Type 'yes' to confirm: ",
        end="",
        file=stdout,
    )
    try:
        answer = input().strip()
    except EOFError:
        return False
    return answer.lower() == "yes"


# ─── RunUninstall ───────────────────────────────────────────────────────────


def run_uninstall(args: list[str], stdout: Any = None) -> Any:
    if stdout is None:
        stdout = sys.stdout

    flags = parse_uninstall_flags(args)
    home_dir = os.path.expanduser("~")
    workspace_dir = os.getcwd()

    if not flags.yes:
        confirmed = _prompt_uninstall_confirm(flags, stdout)
        if not confirmed:
            print("uninstall cancelled", file=stdout)
            return None

    from dxrk.components.uninstall import Service

    service = Service(home_dir=home_dir, workspace_dir=workspace_dir)

    if flags.all:
        return service.complete_uninstall()
    else:
        agent_ids = _to_agent_ids(flags.agents)
        component_ids = (
            [ComponentID(c) for c in flags.components] if flags.components else []
        )
        return service.partial_uninstall(agent_ids, component_ids)


def _prompt_uninstall_confirm(flags: UninstallFlags, stdout: Any) -> bool:
    if flags.all:
        print(
            "This will remove gentle-ai managed configuration from all supported agents.",
            file=stdout,
        )
    else:
        labels = ", ".join(flags.agents)
        print(
            f"This will remove gentle-ai managed configuration from: {labels}",
            file=stdout,
        )

    if flags.components:
        print(f"Components: {', '.join(flags.components)}", file=stdout)
    else:
        print("Components: all managed uninstallable components", file=stdout)
    print("A backup snapshot will be created before any file is modified.", file=stdout)
    print("Type 'yes' to confirm: ", end="", file=stdout)
    try:
        answer = input().strip()
    except EOFError:
        return False
    return answer.lower() == "yes"


# ─── Dry Run ────────────────────────────────────────────────────────────────


def _join_agent_ids(values: list[AgentID]) -> str:
    if not values:
        return "none"
    return ",".join(v.value for v in values)


def _join_component_ids(values: list[ComponentID]) -> str:
    if not values:
        return "none"
    return ",".join(v.value for v in values)


def _format_platform_decision(decision: PlatformDecision | None) -> str:
    if decision is None:
        return "os=unknown distro=n/a package-manager=n/a status=unsupported"
    os_name = decision.os or "unknown"
    distro = decision.linux_distro or "n/a"
    mgr = decision.package_manager or "n/a"
    status = "supported" if decision.supported else "unsupported"
    return f"os={os_name} distro={distro} package-manager={mgr} status={status}"


def render_dry_run(result: InstallResult) -> str:
    lines: list[str] = [
        "AI Gentle Stack dry-run",
        "=====================",
        f"Agents: {_join_agent_ids(result.resolved.agents) if result.resolved else 'none'}",
        f"Unsupported agents: {_join_agent_ids(result.resolved.unsupported_agents) if result.resolved else 'none'}",
        f"Persona: {result.selection.persona.value if result.selection.persona else ''}",
        f"Preset: {result.selection.preset.value if result.selection.preset else ''}",
    ]

    if result.selection.sdd_mode:
        lines.append(f"SDD mode: {result.selection.sdd_mode.value}")

    if result.resolved:
        lines.append(
            f"Components order: {_join_component_ids(result.resolved.ordered_components)}"
        )
        lines.append(
            f"Auto-added dependencies: {_join_component_ids(result.resolved.added_dependencies)}"
        )

    if result.review and result.review.platform_decision:
        lines.append(
            f"Platform decision: {_format_platform_decision(result.review.platform_decision)}"
        )

    if result.plan:
        lines.append(f"Prepare steps: {len(result.plan.prepare)}")
        lines.append(f"Apply steps: {len(result.plan.apply)}")

    return "\n".join(lines) + "\n"


# ─── Sync Report ────────────────────────────────────────────────────────────


def render_sync_report(result: SyncResult) -> str:
    lines: list[str] = []

    if result.no_op:
        lines.append("gentle-ai sync — no managed sync actions needed")
        if not result.agents:
            lines.append("No agents were discovered or specified. Nothing to sync.")
        else:
            lines.append(f"Agents: {_join_agent_ids(result.agents)}")
            lines.append("All managed assets are already up to date. No files changed.")
        return "\n".join(lines)

    if result.dry_run:
        lines.append("gentle-ai sync — dry-run")
        lines.append(f"Agents: {_join_agent_ids(result.agents)}")
        comp_parts = [c.value for c in result.selection.components]
        if comp_parts:
            lines.append(f"Managed components: {', '.join(comp_parts)}")
        if result.plan:
            lines.append(f"Prepare steps: {len(result.plan.prepare)}")
            lines.append(f"Apply steps: {len(result.plan.apply)}")
        return "\n".join(lines)

    lines.append("gentle-ai sync — managed sync executed")
    lines.append(f"Agents synced: {_join_agent_ids(result.agents)}")
    comp_parts = [c.value for c in result.selection.components]
    if comp_parts:
        lines.append(f"Managed components synced: {', '.join(comp_parts)}")
    lines.append(f"Sync actions executed: {result.files_changed} files changed")

    if not result.verify.ready:
        lines.append("")
        lines.append("Post-sync verification:")
        lines.append(_render_report(result.verify))

    return "\n".join(lines)


# ─── Uninstall Report ───────────────────────────────────────────────────────


def render_uninstall_report(result: Any) -> str:
    lines: list[str] = []
    lines.append("Managed uninstall complete")
    manifest = getattr(result, "Manifest", {})
    if manifest.get("entries"):
        backup_id = getattr(result, "BackupPath", "")
        if backup_id:
            lines.append(f"Backup path: {backup_id}")
    lines.append(f"Changed files: {len(getattr(result, 'ChangedFiles', []))}")
    lines.append(f"Removed files: {len(getattr(result, 'RemovedFiles', []))}")
    lines.append(
        f"Removed directories: {len(getattr(result, 'RemovedDirectories', []))}"
    )

    removed = getattr(result, "AgentsRemovedFromState", [])
    if removed:
        labels = ", ".join(a.value for a in removed)
        lines.append(f"Updated state.json: removed {labels}")

    for section_title, paths in [
        ("Rewritten files", getattr(result, "ChangedFiles", [])),
        ("Deleted files", getattr(result, "RemovedFiles", [])),
        ("Deleted directories", getattr(result, "RemovedDirectories", [])),
        ("Manual cleanup required", getattr(result, "ManualActions", [])),
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


# ─── Verification ───────────────────────────────────────────────────────────


def _run_post_apply_verification(
    home_dir: str, selection: Selection, resolved: ResolvedPlan
) -> _VerifyReport:
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
                        return f"file not found: {p}"
                    return None

                check._cid = f"verify:file:{p}"  # type: ignore
                check._desc = "required file exists"  # type: ignore
                return check

            checks.append(make_check(current_path))

    check_results = _run_checks(checks)
    report = _build_report(check_results)

    if _has_component(resolved.ordered_components, ComponentID.DXRK_MEMORY):
        from dxrk.components.engram import verify_installed

        binary_check = lambda: verify_installed()
        binary_check._cid = "verify:engram:binary"  # type: ignore
        binary_check._desc = "engram binary on PATH"  # type: ignore
        binary_check._soft = True  # type: ignore
        results = _run_checks([binary_check])
        report.checks.extend(results)
        if not results[0].error:
            from dxrk.components.engram import verify_version

            version_check = lambda: verify_version()
            version_check._cid = "verify:engram:version"  # type: ignore
            version_check._desc = "engram version returns valid output"  # type: ignore
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
            description="Antigravity and Gemini CLI share ~/.gemini/GEMINI.md",
            soft=True,
            error="both Antigravity and Gemini CLI write rules to ~/.gemini/GEMINI.md\n"
            "Content is merged, not overwritten.\n"
            "This is expected behavior. No action required.",
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
                        return f"synced file not found: {fp}"
                    return None

                check._cid = f"verify:sync:file:{fp}"  # type: ignore
                check._desc = "synced file exists"  # type: ignore
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
    return {
        k: ModelAssignmentState(provider_id=v.provider_id, model_id=v.model_id)
        for k, v in m.items()
    }


def _claude_aliases_to_strings(m: dict[str, Any] | None) -> dict[str, str] | None:
    if not m:
        return None
    return {k: str(v) for k, v in m.items()}


# ─── Exported symbols ───────────────────────────────

__all__ = [
    "ComponentApplyStep",
    "ComponentSyncStep",
    "InstallFlags",
    "InstallInput",
    "InstallResult",
    "InstallRuntime",
    "NoopStep",
    "Step",
    "SyncFlags",
    "SyncResult",
    "SyncRuntime",
    "UninstallFlags",
    "build_real_stage_plan",
    "build_stage_plan",
    "build_sync_selection",
    "discover_agents",
    "normalize_install_flags",
    "parse_install_flags",
    "parse_sync_flags",
    "parse_uninstall_flags",
    "render_dry_run",
    "render_sync_report",
    "render_uninstall_report",
    "resolve_install_profile",
    "run_install",
    "run_restore",
    "run_sync",
    "run_sync_with_selection",
    "run_uninstall",
]
