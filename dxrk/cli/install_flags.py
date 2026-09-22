# SPDX-License-Identifier: MIT
"""Flag dataclasses and parsers for install/sync/uninstall."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Any

from dxrk.models import ModelAssignment, Profile

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
        raise ValueError(f"argumento de install inesperado {unknown[0]!r}")

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


def _parse_profile_sync_strategy(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value in ("generated-multi", "external-single-active"):
        return value
    raise ValueError(f"sdd-profile-strategy no compatible {raw!r} (válidos: generated-multi, external-single-active)")


def _parse_profile_flag(raw: str) -> Profile:
    from dxrk.components.sdd import validate_profile_name
    from dxrk.models import Profile

    colon_idx = raw.find(":")
    if colon_idx <= 0:
        raise ValueError(f"--profile {raw!r}: formato no válido, se esperaba name:provider/model")
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
        raise ValueError(f"--profile-phase {raw!r}: formato no válido, se esperaba name:phase:provider/model")
    name, phase, model_spec = parts

    if not name:
        raise ValueError(f"--profile-phase {raw!r}: el nombre del perfil no debe estar vacío")
    err = validate_profile_name(name)
    if err:
        raise ValueError(f"--profile-phase {raw!r}: {err}")
    if not phase:
        raise ValueError(f"--profile-phase {raw!r}: la fase no debe estar vacía")

    known = profile_phase_order()
    if phase not in known:
        raise ValueError(f"--profile-phase {raw!r}: fase desconocida {phase!r}; las fases válidas son: {known}")

    assignment = _parse_model_spec(model_spec)
    return name, phase, assignment


def _parse_model_spec(spec: str) -> ModelAssignment:
    sep = -1
    for i, c in enumerate(spec):
        if c in ("/", ":"):
            sep = i
            break
    if sep <= 0:
        raise ValueError(f"especificación de modelo no válida {spec!r}: se esperaba provider/model o provider:model")
    provider_id = spec[:sep]
    model_id = spec[sep + 1 :]
    if not provider_id or not model_id:
        raise ValueError(f"especificación de modelo no válida {spec!r}: provider y model no deben estar vacíos")
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
    parser.add_argument("--sdd-profile-strategy", type=str, default="", dest="sdd_profile_strategy")
    parser.add_argument("--strict-tdd", action="store_true", default=False, dest="strict_tdd")
    parser.add_argument(
        "--include-permissions",
        action="store_true",
        default=False,
        dest="include_permissions",
    )
    parser.add_argument("--include-theme", action="store_true", default=False, dest="include_theme")
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
        raise ValueError(f"argumento de sync inesperado {unknown[0]!r}")

    strategy = _parse_profile_sync_strategy(parsed.sdd_profile_strategy or "")

    agents = _flatten_list(parsed.agents_raw) if parsed.agents_raw else []
    skills = _flatten_list(parsed.skills_raw) if parsed.skills_raw else []
    raw_profiles = _flatten_list(parsed.raw_profiles) if parsed.raw_profiles else []
    raw_profile_phases = _flatten_list(parsed.raw_profile_phases) if parsed.raw_profile_phases else []

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
        raise ValueError(f"argumento de uninstall inesperado {unknown[0]!r}")

    opts = UninstallFlags(
        agents=_flatten_list(parsed.agents_raw) if parsed.agents_raw else [],
        components=_flatten_list(parsed.components_raw) if parsed.components_raw else [],
        all=parsed.all or False,
        yes=parsed.yes or False,
    )

    if opts.all and (opts.agents or opts.components):
        raise ValueError("--all no se puede combinar con --agent/--agents ni --component/--components")
    if not opts.all and not opts.agents:
        raise ValueError("la desinstalación parcial requiere al menos un --agent/--agents o usa --all")
    return opts
