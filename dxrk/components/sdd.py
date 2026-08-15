# SPDX-License-Identifier: MIT
"""SDD component — ports internal/components/sdd/.

Profiles, injection, prompts, commands, model assignments.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from dxrk.components import filemerge
from dxrk.components.assets import (
    must_read as _must_read,
)
from dxrk.components.assets import (
    sdd_commands_asset_dir,
)
from dxrk.models import (
    AgentID,
    ClaudeModelAlias,
    ModelAssignment,
    Profile,
    SDDModeID,
    SDDProfileStrategyID,
    SystemPromptStrategy,
)

_PROFILE_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

_RESERVED_PROFILE_NAMES = {"default": True, "sdd-orchestrator": True}

_PROFILE_PHASE_ORDER = [
    "sdd-init",
    "sdd-explore",
    "sdd-propose",
    "sdd-spec",
    "sdd-design",
    "sdd-tasks",
    "sdd-apply",
    "sdd-verify",
    "sdd-archive",
    "sdd-onboard",
]

_SDD_ORCHESTRATOR_MARKERS = [
    "## Agent Teams Orchestrator",
    "## Spec-Driven Development (SDD) Orchestrator",
    "## Spec-Driven Development (SDD)",
    "# SDD Orchestrator for Cascade",
]


# ─── Profile helpers ───────────────────────────────────────────────────────


def validate_profile_name(name: str) -> str | None:
    if not name:
        return "profile name must not be empty"
    if name in _RESERVED_PROFILE_NAMES:
        return f"profile name {name!r} is reserved"
    if not _PROFILE_NAME_RE.match(name):
        return (
            f"profile name {name!r} must match ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ "
            "(lowercase, hyphens only, no trailing hyphens, no underscores or spaces)"
        )
    return None


def profile_phase_order() -> list[str]:
    return list(_PROFILE_PHASE_ORDER)


def resolve_profile_strategy(
    home_dir: str, explicit: SDDProfileStrategyID
) -> SDDProfileStrategyID:
    if explicit:
        return explicit
    if has_external_profile_files(home_dir):
        return SDDProfileStrategyID.EXTERNAL_SINGLE_ACTIVE
    return SDDProfileStrategyID.GENERATED_MULTI


def has_external_profile_files(home_dir: str) -> bool:
    if not home_dir.strip():
        return False
    profiles_dir = os.path.join(home_dir, ".config", "opencode", "profiles")
    try:
        entries = os.listdir(profiles_dir)
    except FileNotFoundError:
        return False
    for entry in entries:
        full = os.path.join(profiles_dir, entry)
        if os.path.isfile(full) and entry.lower().endswith(".json"):
            return True
    return False


def profile_agent_keys(name: str) -> list[str]:
    suffix = f"-{name}" if name else ""
    keys = [f"sdd-orchestrator{suffix}"]
    for phase in _PROFILE_PHASE_ORDER:
        keys.append(f"{phase}{suffix}")
    return keys


def detect_profiles(settings_path: str) -> list[Profile]:
    try:
        with open(settings_path) as f:
            data = f.read()
    except FileNotFoundError:
        return []

    try:
        root = json.loads(data)
    except json.JSONDecodeError:
        return []

    agent_raw = root.get("agent")
    if not isinstance(agent_raw, dict):
        return []

    orch_prefix = "sdd-orchestrator-"
    profile_names: list[str] = []
    seen: set[str] = set()
    for key in agent_raw:
        if not key.startswith(orch_prefix):
            continue
        pname = key[len(orch_prefix) :]
        if not pname or pname in seen:
            continue
        seen.add(pname)
        profile_names.append(pname)

    if not profile_names:
        return []

    profile_names.sort()
    profiles: list[Profile] = []
    for pname in profile_names:
        orch_key = f"sdd-orchestrator-{pname}"
        orch_raw = agent_raw.get(orch_key, {})
        orch_map = orch_raw if isinstance(orch_raw, dict) else {}
        orch_model = _extract_model_from_agent(orch_map)

        phase_assignments: dict[str, ModelAssignment] = {}
        for phase in _PROFILE_PHASE_ORDER:
            agent_key = f"{phase}-{pname}"
            agent_raw2 = agent_raw.get(agent_key, {})
            agent_map2 = agent_raw2 if isinstance(agent_raw2, dict) else {}
            m = _extract_model_from_agent(agent_map2)
            if m.provider_id:
                phase_assignments[phase] = m

        profiles.append(
            Profile(
                name=pname,
                orchestrator_model=orch_model,
                phase_assignments=phase_assignments,
            )
        )
    return profiles


def _extract_model_from_agent(agent_map: dict[str, Any]) -> ModelAssignment:
    if not isinstance(agent_map, dict):
        return ModelAssignment()
    model_str = agent_map.get("model", "")
    if not isinstance(model_str, str) or not model_str:
        return ModelAssignment()

    idx = model_str.find(":")
    if idx <= 0:
        idx = model_str.find("/")
    if idx <= 0:
        return ModelAssignment()
    provider_id = model_str[:idx]
    model_id = model_str[idx + 1 :]
    if not model_id:
        return ModelAssignment()
    return ModelAssignment(provider_id=provider_id, model_id=model_id)


def generate_profile_overlay(profile: Profile, home_dir: str) -> bytes:
    if not profile.name or profile.name == "default":
        raise ValueError(
            "GenerateProfileOverlay: profile name must be non-empty and not 'default'"
        )

    suffix = f"-{profile.name}"
    orchestrator_key = f"sdd-orchestrator{suffix}"

    orchestrator_prompt = _build_profile_orchestrator_prompt(profile)
    prompt_dir = shared_prompt_dir(home_dir)

    phase_descriptions = {
        "sdd-init": "Bootstrap SDD context and project configuration",
        "sdd-explore": "Investigate codebase and think through ideas",
        "sdd-propose": "Create change proposals from explorations",
        "sdd-spec": "Write detailed specifications from proposals",
        "sdd-design": "Create technical design from proposals",
        "sdd-tasks": "Break down specs and designs into implementation tasks",
        "sdd-apply": "Implement code changes from task definitions",
        "sdd-verify": "Validate implementation against specs",
        "sdd-archive": "Archive completed change artifacts",
        "sdd-onboard": "Guide user through a complete SDD cycle using their real codebase",
    }

    task_perms: dict[str, str] = {"*": "deny"}
    for phase in _PROFILE_PHASE_ORDER:
        task_perms[f"{phase}{suffix}"] = "allow"

    orch_entry: dict[str, Any] = {
        "mode": "primary",
        "description": f"SDD Orchestrator ({profile.name} profile) - coordinates sub-agents, never does work inline",
        "prompt": orchestrator_prompt,
        "permission": {
            "task": {"__replace__": task_perms},
        },
        "tools": {
            "read": True,
            "write": True,
            "edit": True,
            "bash": True,
            "delegate": True,
            "delegation_read": True,
            "delegation_list": True,
        },
    }
    if profile.orchestrator_model.provider_id and profile.orchestrator_model.model_id:
        orch_entry["model"] = profile.orchestrator_model.full_id()

    agent_map: dict[str, Any] = {orchestrator_key: orch_entry}

    for phase in _PROFILE_PHASE_ORDER:
        key = f"{phase}{suffix}"
        entry: dict[str, Any] = {
            "mode": "subagent",
            "hidden": True,
            "description": phase_descriptions.get(phase, ""),
            "prompt": "{file:" + os.path.join(prompt_dir, f"{phase}.md") + "}",
            "tools": {"read": True, "write": True, "edit": True, "bash": True},
        }
        assignment = profile.phase_assignments.get(phase)
        if assignment and assignment.provider_id and assignment.model_id:
            entry["model"] = assignment.full_id()
        agent_map[key] = entry

    overlay = {"agent": agent_map}
    result = (json.dumps(overlay, indent=2) + "\n").encode("utf-8")
    return result


def _build_profile_orchestrator_prompt(profile: Profile) -> str:
    base = _must_read(_sdd_orchestrator_asset(AgentID.OPENCODE))

    open_marker = "<!-- dxrk:sdd-model-assignments -->"
    close_marker = "<!-- /dxrk:sdd-model-assignments -->"
    start = base.find(open_marker)
    end = base.find(close_marker)
    if start != -1 and end != -1 and end > start:
        table = _render_profile_model_assignments_section(profile)
        after_open = start + len(open_marker)
        base = base[:after_open] + "\n" + table + base[end:]

    suffix = f"-{profile.name}"
    for phase in _PROFILE_PHASE_ORDER:
        base = _replace_phase_ref(base, phase, f"{phase}{suffix}")
    base = _replace_phase_ref(base, "sdd-orchestrator", f"sdd-orchestrator{suffix}")
    return base


def _replace_phase_ref(content: str, from_: str, to: str) -> str:
    suffix = to[len(from_) :] if to.startswith(from_) else ""
    if not suffix:
        return content

    result = []
    remaining = content
    while True:
        idx = remaining.find(from_)
        if idx < 0:
            result.append(remaining)
            break
        after_idx = idx + len(from_)
        if remaining[after_idx:].startswith(suffix):
            result.append(remaining[:after_idx])
            remaining = remaining[after_idx:]
            continue
        result.append(remaining[:idx])
        result.append(to)
        remaining = remaining[after_idx:]
    return "".join(result)


def _render_profile_model_assignments_section(profile: Profile) -> str:
    lines = ["## Model Assignments\n"]
    lines.append(
        "Read this table at session start (or before first delegation) and cache it for the session. "
        "Treat each row as the authoritative configured model for that agent. "
        "If a phase is missing, use the default OpenCode runtime model and continue.\n"
    )
    lines.append("| Phase | Model | Reason |\n")
    lines.append("|-------|-------|--------|\n")

    orch_model = (
        profile.orchestrator_model.full_id()
        if profile.orchestrator_model.provider_id
        else "—"
    )
    lines.append(f"| orchestrator | {orch_model} | Coordinates, makes decisions |\n")

    phase_reasons = {
        "sdd-init": "Bootstrap SDD context",
        "sdd-explore": "Reads code, structural - not architectural",
        "sdd-propose": "Architectural decisions",
        "sdd-spec": "Structured writing",
        "sdd-design": "Architecture decisions",
        "sdd-tasks": "Mechanical breakdown",
        "sdd-apply": "Implementation",
        "sdd-verify": "Validation against spec",
        "sdd-archive": "Copy and close",
        "sdd-onboard": "Guided walkthrough",
    }
    for phase in _PROFILE_PHASE_ORDER:
        m = profile.phase_assignments.get(phase)
        phase_model = m.full_id() if (m and m.provider_id) else "—"
        reason = phase_reasons.get(phase, "")
        lines.append(f"| {phase} | {phase_model} | {reason} |\n")
    lines.append("\n")
    return "".join(lines)


def remove_profile_agents(settings_path: str, profile_name: str) -> None:
    if not profile_name or profile_name == "default":
        raise ValueError(
            f"RemoveProfileAgents: cannot remove default profile (name={profile_name!r})"
        )

    try:
        with open(settings_path) as f:
            data = f.read()
    except FileNotFoundError:
        return

    try:
        root = json.loads(data)
    except json.JSONDecodeError:
        return

    agent_raw = root.get("agent")
    if not isinstance(agent_raw, dict):
        return

    keys_to_delete = profile_agent_keys(profile_name)
    deleted = 0
    for key in keys_to_delete:
        if key in agent_raw:
            del agent_raw[key]
            deleted += 1

    if deleted == 0:
        return

    root["agent"] = agent_raw
    out = (json.dumps(root, indent=2) + "\n").encode("utf-8")
    filemerge.write_file_atomic(settings_path, out, 0o644)


# ─── Prompts ───────────────────────────────────────────────────────────────


def shared_prompt_dir(home_dir: str) -> str:
    return os.path.join(home_dir, ".config", "opencode", "prompts", "sdd")


_SUB_AGENT_PROMPT_CONTENT = {
    "sdd-init": (
        "You are an SDD executor for the init phase, not the orchestrator. "
        "Do this phase's work yourself. Do NOT delegate, Do NOT call task/delegate, "
        "and Do NOT launch sub-agents. Read your skill file at "
        "~/.config/opencode/skills/sdd-init/SKILL.md and follow it exactly."
    ),
    "sdd-explore": (
        "You are an SDD executor for the explore phase, not the orchestrator. "
        "Do this phase's work yourself. Do NOT delegate, Do NOT call task/delegate, "
        "and Do NOT launch sub-agents. Read your skill file at "
        "~/.config/opencode/skills/sdd-explore/SKILL.md and follow it exactly."
    ),
    "sdd-propose": (
        "You are an SDD executor for the propose phase, not the orchestrator. "
        "Do this phase's work yourself. Do NOT delegate, Do NOT call task/delegate, "
        "and Do NOT launch sub-agents. Read your skill file at "
        "~/.config/opencode/skills/sdd-propose/SKILL.md and follow it exactly."
    ),
    "sdd-spec": (
        "You are an SDD executor for the spec phase, not the orchestrator. "
        "Do this phase's work yourself. Do NOT delegate, Do NOT call task/delegate, "
        "and Do NOT launch sub-agents. Read your skill file at "
        "~/.config/opencode/skills/sdd-spec/SKILL.md and follow it exactly."
    ),
    "sdd-design": (
        "You are an SDD executor for the design phase, not the orchestrator. "
        "Do this phase's work yourself. Do NOT delegate, Do NOT call task/delegate, "
        "and Do NOT launch sub-agents. Read your skill file at "
        "~/.config/opencode/skills/sdd-design/SKILL.md and follow it exactly."
    ),
    "sdd-tasks": (
        "You are an SDD executor for the tasks phase, not the orchestrator. "
        "Do this phase's work yourself. Do NOT delegate, Do NOT call task/delegate, "
        "and Do NOT launch sub-agents. Read your skill file at "
        "~/.config/opencode/skills/sdd-tasks/SKILL.md and follow it exactly."
    ),
    "sdd-apply": (
        "You are an SDD executor for the apply phase, not the orchestrator. "
        "Do this phase's work yourself. Do NOT delegate, Do NOT call task/delegate, "
        "and Do NOT launch sub-agents. Read your skill file at "
        "~/.config/opencode/skills/sdd-apply/SKILL.md and follow it exactly."
    ),
    "sdd-verify": (
        "You are an SDD executor for the verify phase, not the orchestrator. "
        "Do this phase's work yourself. Do NOT delegate, Do NOT call task/delegate, "
        "and Do NOT launch sub-agents. Read your skill file at "
        "~/.config/opencode/skills/sdd-verify/SKILL.md and follow it exactly."
    ),
    "sdd-archive": (
        "You are an SDD executor for the archive phase, not the orchestrator. "
        "Do this phase's work yourself. Do NOT delegate, Do NOT call task/delegate, "
        "and Do NOT launch sub-agents. Read your skill file at "
        "~/.config/opencode/skills/sdd-archive/SKILL.md and follow it exactly."
    ),
    "sdd-onboard": (
        "You are an SDD executor for the onboard phase, not the orchestrator. "
        "Do this phase's work yourself. Do NOT delegate, Do NOT call task/delegate, "
        "and Do NOT launch sub-agents. Read your skill file at "
        "~/.config/opencode/skills/sdd-onboard/SKILL.md and follow it exactly."
    ),
}


def shared_prompt_phases() -> list[str]:
    return profile_phase_order()


def write_shared_prompt_files(home_dir: str) -> bool:
    prompt_dir = shared_prompt_dir(home_dir)
    any_changed = False
    phases = profile_phase_order()

    for phase in phases:
        content = _SUB_AGENT_PROMPT_CONTENT.get(phase)
        if content is None:
            continue
        path = os.path.join(prompt_dir, f"{phase}.md")
        result = filemerge.write_file_atomic(path, content.encode("utf-8"), 0o644)
        if result.Changed:
            any_changed = True
    return any_changed


# ─── Commands ──────────────────────────────────────────────────────────────


@dataclass
class OpenCodeCommand:
    name: str
    description: str
    body: str


def opencode_commands() -> list[OpenCodeCommand]:
    return [
        OpenCodeCommand("sdd-init", "Initialize SDD context", "/sdd-init"),
        OpenCodeCommand("sdd-new", "Start a new SDD change", "/sdd-new ${change-name}"),
        OpenCodeCommand(
            "sdd-continue",
            "Continue next pending artifact",
            "/sdd-continue ${change-name}",
        ),
        OpenCodeCommand(
            "sdd-explore", "Explore an idea before committing", "/sdd-explore ${topic}"
        ),
        OpenCodeCommand(
            "sdd-ff", "Generate all planning artifacts", "/sdd-ff ${change-name}"
        ),
        OpenCodeCommand("sdd-apply", "Implement tasks", "/sdd-apply ${change-name}"),
        OpenCodeCommand(
            "sdd-verify", "Verify implementation", "/sdd-verify ${change-name}"
        ),
        OpenCodeCommand(
            "sdd-archive", "Archive completed change", "/sdd-archive ${change-name}"
        ),
        OpenCodeCommand("sdd-onboard", "Guided SDD walkthrough", "/sdd-onboard"),
    ]


# ─── Injection ─────────────────────────────────────────────────────────────


@dataclass
class InjectionResult:
    Changed: bool = False
    Files: list[str] = field(default_factory=list)


@dataclass
class InjectOptions:
    opencode_model_assignments: dict[str, ModelAssignment] = field(default_factory=dict)
    claude_model_assignments: dict[str, str] = field(default_factory=dict)
    kiro_model_assignments: dict[str, str] = field(default_factory=dict)
    workspace_dir: str = ""
    strict_tdd: bool = False
    profiles: list[Profile] = field(default_factory=list)
    preserve_opencode_orchestrator_prompt: bool = False


_MONOREPO_ROOT_MARKERS = [
    "pnpm-workspace.yaml",
    "pnpm-workspace.yml",
    "nx.json",
    "turbo.json",
    "lerna.json",
    "rush.json",
]
_STRONG_PROJECT_MARKERS = [
    ".git",
    "go.mod",
    "Cargo.toml",
    "pyproject.toml",
    "pom.xml",
    "build.gradle",
]
_MAX_ANCESTOR_DEPTH = 20


def _find_project_root(dir: str) -> str | None:
    if not dir:
        return None
    current = os.path.normpath(dir)
    best_candidate: str | None = None

    for _ in range(_MAX_ANCESTOR_DEPTH):
        for marker in _MONOREPO_ROOT_MARKERS:
            if os.path.isfile(os.path.join(current, marker)):
                return current
        for marker in _STRONG_PROJECT_MARKERS:
            if os.path.isfile(os.path.join(current, marker)) or os.path.isdir(
                os.path.join(current, marker)
            ):
                return current
        if os.path.isfile(os.path.join(current, "package.json")):
            best_candidate = current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    return best_candidate


def _sdd_orchestrator_asset(agent: AgentID) -> str:
    mapping: dict[AgentID, str] = {
        AgentID.GEMINI_CLI: "gemini/sdd-orchestrator.md",
        AgentID.CODEX: "codex/sdd-orchestrator.md",
        AgentID.ANTIGRAVITY: "antigravity/sdd-orchestrator.md",
        AgentID.WINDSURF: "windsurf/sdd-orchestrator.md",
        AgentID.CURSOR: "cursor/sdd-orchestrator.md",
        AgentID.KIMI: "kimi/sdd-orchestrator.md",
        AgentID.QWEN_CODE: "qwen/sdd-orchestrator.md",
        AgentID.KIRO_IDE: "kiro/sdd-orchestrator.md",
        AgentID.OPENCODE: "opencode/sdd-orchestrator.md",
    }
    return mapping.get(agent, "generic/sdd-orchestrator.md")


def _overlay_asset_path(sdd_mode: SDDModeID) -> str:
    if sdd_mode == SDDModeID.MULTI:
        return "opencode/sdd-overlay-multi.json"
    return "opencode/sdd-overlay-single.json"


def inject(
    home_dir: str,
    adapter,
    sdd_mode: SDDModeID,
    options: InjectOptions | None = None,
    **extra: Any,
) -> InjectionResult:
    if options is None:
        opts = InjectOptions(
            **{
                k: v
                for k, v in extra.items()
                if k in InjectOptions.__dataclass_fields__
            }
        )
    else:
        opts = options

    if not adapter.supports_system_prompt:
        return InjectionResult()

    files: list[str] = []
    changed = False

    # 1. Inject SDD orchestrator into system prompt (non-OpenCode agents)
    if adapter.agent not in (AgentID.OPENCODE, AgentID.KILOCODE):
        sps = adapter.system_prompt_strategy

        if sps == SystemPromptStrategy.MARKDOWN_SECTIONS:
            result = _inject_markdown_sections(
                home_dir, adapter, opts.claude_model_assignments
            )
            changed = changed or result.Changed
            files.extend(result.Files)

        elif sps in (
            SystemPromptStrategy.FILE_REPLACE,
            SystemPromptStrategy.APPEND_TO_FILE,
            SystemPromptStrategy.INSTRUCTIONS_FILE,
            SystemPromptStrategy.STEERING_FILE,
        ):
            result = _inject_file_append(home_dir, adapter)
            changed = changed or result.Changed
            files.extend(result.Files)

        elif sps == SystemPromptStrategy.JINJA_MODULES:
            if hasattr(adapter, "bootstrap_template"):
                adapter.bootstrap_template(home_dir)
            config_dir = adapter.global_config_dir(home_dir)
            content = _must_read(_sdd_orchestrator_asset(adapter.agent))
            module_path = os.path.join(config_dir, "sdd-orchestrator.md")
            wr = filemerge.write_file_atomic(
                module_path, content.encode("utf-8"), 0o644
            )
            changed = changed or wr.Changed
            files.append(module_path)

    # 1b. Strict TDD mode
    if opts.strict_tdd and adapter.agent not in (AgentID.OPENCODE, AgentID.KILOCODE):
        if adapter.system_prompt_strategy == SystemPromptStrategy.JINJA_MODULES:
            config_dir = adapter.global_config_dir(home_dir)
            content = "Strict TDD Mode: enabled"
            module_path = os.path.join(config_dir, "strict-tdd-mode.md")
            wr = filemerge.write_file_atomic(
                module_path, content.encode("utf-8"), 0o644
            )
            changed = changed or wr.Changed
            files.append(module_path)
        else:
            prompt_path = adapter.system_prompt_file(home_dir)
            existing = _read_file_or_empty(prompt_path)
            updated = filemerge.inject_markdown_section(
                existing, "strict-tdd-mode", "Strict TDD Mode: enabled"
            )
            wr = filemerge.write_file_atomic(
                prompt_path, updated.encode("utf-8"), 0o644
            )
            changed = changed or wr.Changed
            if prompt_path not in files:
                files.append(prompt_path)

    # 2. Slash commands
    if adapter.supports_slash_commands:
        commands_dir = adapter.commands_dir(home_dir)
        if commands_dir:
            asset_dir = sdd_commands_asset_dir(adapter.agent)
            for fname in os.listdir(os.path.join(_asset_root, asset_dir)):
                fpath = os.path.join(asset_dir, fname)
                content = _must_read(fpath)
                out_path = os.path.join(commands_dir, fname)
                wr = filemerge.write_file_atomic(
                    out_path, content.encode("utf-8"), 0o644
                )
                changed = changed or wr.Changed
                files.append(out_path)

    # 2b. OpenCode agent definitions merge
    merged_settings_bytes: bytes | None = None
    if adapter.agent in (AgentID.OPENCODE, AgentID.KILOCODE):
        settings_path = adapter.settings_path(home_dir)
        if settings_path:
            overlay_content = _must_read(_overlay_asset_path(sdd_mode))
            overlay_bytes = overlay_content.encode("utf-8")

            if sdd_mode == SDDModeID.MULTI:
                prompts_changed = write_shared_prompt_files(home_dir)
                changed = changed or prompts_changed

            overlay_bytes = _inline_opencode_sdd_prompts(
                overlay_bytes,
                home_dir,
                settings_path,
                opts.preserve_opencode_orchestrator_prompt,
            )

            assignments = (
                opts.opencode_model_assignments if sdd_mode == SDDModeID.MULTI else {}
            )
            if sdd_mode == SDDModeID.MULTI and assignments:
                root_model_id = _read_opencode_root_model(settings_path)
                existing_agent_keys = _read_existing_agent_models(settings_path)
                overlay_bytes = _inject_model_assignments(
                    overlay_bytes, assignments, root_model_id, existing_agent_keys
                )

            agent_result = _merge_json_file(settings_path, overlay_bytes)
            changed = changed or agent_result[0].Changed
            files.append(settings_path)
            merged_settings_bytes = agent_result[1]

            # Named profile overlays
            for profile in opts.profiles:
                if not profile.name or profile.name == "default":
                    continue
                profile_overlay = generate_profile_overlay(profile, home_dir)
                profile_result = _merge_json_file(settings_path, profile_overlay)
                changed = changed or profile_result[0].Changed
                merged_settings_bytes = profile_result[1]

    # 3. SDD skill files
    if adapter.supports_skills:
        skill_dir = adapter.skills_dir(home_dir)
        if skill_dir:
            shared_files = [
                "SKILL.md",
                "persistence-contract.md",
                "engram-convention.md",
                "openspec-convention.md",
                "sdd-phase-common.md",
                "skill-resolver.md",
            ]
            for fname in shared_files:
                content = _must_read(f"skills/_shared/{fname}")
                out_path = os.path.join(skill_dir, "_shared", fname)
                wr = filemerge.write_file_atomic(
                    out_path, content.encode("utf-8"), 0o644
                )
                changed = changed or wr.Changed
                files.append(out_path)

            sdd_skill_names = [
                "sdd-init",
                "sdd-explore",
                "sdd-propose",
                "sdd-spec",
                "sdd-design",
                "sdd-tasks",
                "sdd-apply",
                "sdd-verify",
                "sdd-archive",
                "sdd-onboard",
                "judgment-day",
            ]
            for skill_name in sdd_skill_names:
                embedded_dir = f"skills/{skill_name}"
                skill_abs = os.path.join(_asset_root, embedded_dir)
                for fname in os.listdir(skill_abs):
                    fpath = os.path.join(skill_abs, fname)
                    if os.path.isdir(fpath):
                        continue
                    content = _must_read(f"{embedded_dir}/{fname}")
                    out_path = os.path.join(skill_dir, skill_name, fname)
                    wr = filemerge.write_file_atomic(
                        out_path, content.encode("utf-8"), 0o644
                    )
                    changed = changed or wr.Changed
                    files.append(out_path)

    # 3b. Workflow files
    if hasattr(adapter, "supports_workflows") and adapter.supports_workflows:
        project_root = _find_project_root(opts.workspace_dir)
        if project_root:
            workflows_dir = os.path.join(
                project_root, ".windsurf", "workflows"
            )  # default
            if hasattr(adapter, "workflows_dir"):
                workflows_dir = adapter.workflows_dir(project_root)
            embed_dir = "windsurf/workflows"  # default
            if hasattr(adapter, "embedded_workflows_dir"):
                embed_dir = adapter.embedded_workflows_dir()
            for fname in os.listdir(os.path.join(_asset_root, embed_dir)):
                content = _must_read(f"{embed_dir}/{fname}")
                out_path = os.path.join(workflows_dir, fname)
                wr = filemerge.write_file_atomic(
                    out_path, content.encode("utf-8"), 0o644
                )
                changed = changed or wr.Changed
                files.append(out_path)

    # 3c. Sub-agent files
    if adapter.supports_sub_agents:
        agents_dir = adapter.sub_agents_dir(home_dir)
        os.makedirs(agents_dir, mode=0o755, exist_ok=True)
        embedded_dir = adapter.embedded_sub_agents_dir()
        for fname in os.listdir(os.path.join(_asset_root, embedded_dir)):
            content = _must_read(f"{embedded_dir}/{fname}")
            if hasattr(adapter, "kiro_model_id"):
                phase = fname.rsplit(".", 1)[0]
                alias = (
                    opts.kiro_model_assignments.get(phase)
                    or opts.kiro_model_assignments.get("default")
                    or opts.claude_model_assignments.get(phase)
                    or opts.claude_model_assignments.get("default")
                    or "sonnet"
                )
                content = content.replace(
                    "{{KIRO_MODEL}}", adapter.kiro_model_id(ClaudeModelAlias(alias))
                )
            if hasattr(adapter, "claude_model_id"):
                phase = fname.rsplit(".", 1)[0]
                alias = _resolve_claude_model_alias(
                    opts.claude_model_assignments, phase
                )
                content = content.replace(
                    "{{CLAUDE_MODEL}}", adapter.claude_model_id(alias)
                )
            out_path = os.path.join(agents_dir, fname)
            wr = filemerge.write_file_atomic(out_path, content.encode("utf-8"), 0o644)
            changed = changed or wr.Changed
            if wr.Changed:
                files.append(out_path)

    return InjectionResult(Changed=changed, Files=files)


def _inline_opencode_sdd_prompts(
    overlay_bytes: bytes,
    home_dir: str,
    settings_path: str,
    preserve_orchestrator_prompt: bool,
) -> bytes:
    try:
        overlay = json.loads(overlay_bytes)
    except json.JSONDecodeError:
        return overlay_bytes

    agents_raw = overlay.get("agent")
    if not isinstance(agents_raw, dict):
        return overlay_bytes

    orch_raw = agents_raw.get("sdd-orchestrator")
    if not isinstance(orch_raw, dict):
        return overlay_bytes

    if preserve_orchestrator_prompt:
        existing_prompt = _read_opencode_agent_prompt(settings_path, "sdd-orchestrator")
        if existing_prompt:
            orch_raw["prompt"] = existing_prompt
        else:
            orch_raw["prompt"] = _must_read(_sdd_orchestrator_asset(AgentID.OPENCODE))
    else:
        orch_raw["prompt"] = _must_read(_sdd_orchestrator_asset(AgentID.OPENCODE))

    if home_dir:
        prompt_dir = shared_prompt_dir(home_dir)
        for phase in _PROFILE_PHASE_ORDER:
            agent_raw = agents_raw.get(phase)
            if not isinstance(agent_raw, dict):
                continue
            placeholder = f"__PROMPT_FILE_{phase}__"
            if agent_raw.get("prompt") == placeholder:
                agent_raw["prompt"] = (
                    "{file:" + os.path.join(prompt_dir, f"{phase}.md") + "}"
                )

    return (json.dumps(overlay, indent=2) + "\n").encode("utf-8")


def _read_opencode_agent_prompt(settings_path: str, agent_key: str) -> str | None:
    if not settings_path.strip() or not agent_key.strip():
        return None
    try:
        with open(settings_path) as f:
            data = f.read()
    except FileNotFoundError:
        return None
    try:
        root = json.loads(data)
    except json.JSONDecodeError:
        return None
    agents_raw = root.get("agent")
    if not isinstance(agents_raw, dict):
        return None
    agent_raw = agents_raw.get(agent_key)
    if not isinstance(agent_raw, dict):
        return None
    prompt = agent_raw.get("prompt")
    return prompt if isinstance(prompt, str) else None


def _read_opencode_root_model(path: str) -> str | None:
    try:
        with open(path) as f:
            data = f.read()
    except FileNotFoundError:
        return None
    try:
        root = json.loads(data)
    except json.JSONDecodeError:
        return None
    model = root.get("model")
    return model if isinstance(model, str) else None


def _read_existing_agent_models(path: str) -> dict[str, bool]:
    try:
        with open(path) as f:
            data = f.read()
    except FileNotFoundError:
        return {}
    try:
        root = json.loads(data)
    except json.JSONDecodeError:
        return {}
    agent_raw = root.get("agent")
    if not isinstance(agent_raw, dict):
        return {}
    return {k: True for k in agent_raw}


def _inject_model_assignments(
    overlay_bytes: bytes,
    assignments: dict[str, ModelAssignment],
    root_model_id: str | None,
    existing_agent_keys: dict[str, bool],
) -> bytes:
    try:
        overlay = json.loads(overlay_bytes)
    except json.JSONDecodeError:
        return overlay_bytes

    agents_raw = overlay.get("agent")
    if not isinstance(agents_raw, dict):
        return overlay_bytes

    for phase, agent_def in agents_raw.items():
        if not isinstance(agent_def, dict):
            continue
        assignment = assignments.get(phase)

        if assignment and assignment.provider_id and assignment.model_id:
            agent_def["model"] = assignment.full_id()
        elif existing_agent_keys.get(phase):
            continue
        elif root_model_id:
            agent_def["model"] = root_model_id

    # Mirror orchestrator model to gentleman
    orch_assignment = assignments.get("sdd-orchestrator")
    if (
        orch_assignment
        and orch_assignment.provider_id
        and orch_assignment.model_id
        and existing_agent_keys.get("gentleman")
    ):
        if "gentleman" not in agents_raw:
            agents_raw["gentleman"] = {}
        gent = agents_raw["gentleman"]
        if isinstance(gent, dict):
            gent["model"] = orch_assignment.full_id()

    return (json.dumps(overlay, indent=2) + "\n").encode("utf-8")


_CLAUDE_MODEL_ASSIGNMENT_ROW_ORDER = [
    "orchestrator",
    "sdd-explore",
    "sdd-propose",
    "sdd-spec",
    "sdd-design",
    "sdd-tasks",
    "sdd-apply",
    "sdd-verify",
    "sdd-archive",
    "default",
]

_CLAUDE_MODEL_ASSIGNMENT_REASONS = {
    "orchestrator": "Coordinates, makes decisions",
    "sdd-explore": "Reads code, structural - not architectural",
    "sdd-propose": "Architectural decisions",
    "sdd-spec": "Structured writing",
    "sdd-design": "Architecture decisions",
    "sdd-tasks": "Mechanical breakdown",
    "sdd-apply": "Implementation",
    "sdd-verify": "Validation against spec",
    "sdd-archive": "Copy and close",
    "default": "Non-SDD general delegation",
}


def _inject_claude_model_assignments(content: str, assignments: dict[str, str]) -> str:
    open_marker = "<!-- dxrk:sdd-model-assignments -->"
    close_marker = "<!-- /dxrk:sdd-model-assignments -->"
    start = content.find(open_marker)
    end = content.find(close_marker)
    if start == -1 or end == -1 or end < start:
        raise ValueError("sdd orchestrator asset missing model assignment markers")

    from dxrk.models import claude_model_preset_balanced

    merged = {k: v.value for k, v in claude_model_preset_balanced().items()}
    for key, alias in assignments.items():
        try:
            a = ClaudeModelAlias(alias)
            if a.valid():
                merged[key] = a.value
        except ValueError:
            pass

    replacement = _render_claude_model_assignments_section(merged)
    start += len(open_marker)
    return content[:start] + "\n" + replacement + content[end:]


def _resolve_claude_model_alias(
    assignments: dict[str, str], phase: str
) -> ClaudeModelAlias:
    from dxrk.models import claude_model_preset_balanced

    merged = claude_model_preset_balanced()
    for key, alias_str in assignments.items():
        try:
            a = ClaudeModelAlias(alias_str)
            if a.valid():
                merged[key] = a
        except ValueError:
            pass
    if alias := merged.get(phase):
        return alias
    if alias := merged.get("default"):
        return alias
    return ClaudeModelAlias.SONNET


def _render_claude_model_assignments_section(assignments: Mapping[str, str]) -> str:
    lines = ["## Model Assignments\n"]
    lines.append(
        "Read this table at session start (or before first delegation), cache it "
        "for the session, and pass the mapped alias in every Agent tool call via "
        "the `model` parameter. If a phase is missing, use the `default` row. "
        "If you do not have access to the assigned model (for example, no Opus access), "
        "substitute `sonnet` and continue.\n"
    )
    lines.append("| Phase | Default Model | Reason |\n")
    lines.append("|-------|---------------|--------|\n")
    for key in _CLAUDE_MODEL_ASSIGNMENT_ROW_ORDER:
        alias = assignments.get(key, "sonnet")
        reason = _CLAUDE_MODEL_ASSIGNMENT_REASONS.get(key, "")
        lines.append(f"| {key} | {alias} | {reason} |\n")
    lines.append("\n")
    return "".join(lines)


def _inject_markdown_sections(
    home_dir: str, adapter, assignments: dict[str, str]
) -> InjectionResult:
    prompt_path = adapter.system_prompt_file(home_dir)
    content = _must_read("claude/sdd-orchestrator.md")
    if assignments:
        content = _inject_claude_model_assignments(content, assignments)

    existing = _read_file_or_empty(prompt_path)
    existing = filemerge.strip_legacy_atl_block(existing)

    if (
        _has_sdd_orchestrator(existing)
        and "<!-- dxrk:sdd-orchestrator -->" not in existing
    ):
        existing = _strip_bare_orchestrator_section(existing)

    updated = filemerge.inject_markdown_section(existing, "sdd-orchestrator", content)
    wr = filemerge.write_file_atomic(prompt_path, updated.encode("utf-8"), 0o644)
    return InjectionResult(Changed=wr.Changed, Files=[prompt_path])


def _has_sdd_orchestrator(content: str) -> bool:
    for marker in _SDD_ORCHESTRATOR_MARKERS:
        if marker in content:
            return True
    return False


def _strip_bare_orchestrator_section(content: str) -> str:
    lines = content.split("\n")
    start_line = -1
    for i, line in enumerate(lines):
        trimmed = line.strip()
        for marker in _SDD_ORCHESTRATOR_MARKERS:
            if trimmed == marker:
                start_line = i
                break
        if start_line >= 0:
            break

    if start_line < 0:
        return content

    end_line = len(lines)
    for i in range(start_line + 1, len(lines)):
        trimmed = lines[i].strip()
        if trimmed.startswith("## "):
            end_line = i
            break

    before = lines[:start_line]
    after = lines[end_line:]

    while before and not before[-1].strip():
        before.pop()
    while after and not after[0].strip():
        after.pop(0)

    parts = []
    if before:
        parts.append("\n".join(before))
    if after:
        parts.append("\n".join(after))

    result = "\n\n".join(parts)
    return result + "\n" if result else ""


def _inject_file_append(home_dir: str, adapter) -> InjectionResult:
    prompt_path = adapter.system_prompt_file(home_dir)
    existing = _read_file_or_empty(prompt_path)
    content = _must_read(_sdd_orchestrator_asset(adapter.agent))

    if (
        adapter.system_prompt_strategy
        in (
            SystemPromptStrategy.INSTRUCTIONS_FILE,
            SystemPromptStrategy.STEERING_FILE,
        )
        and not existing.strip()
    ):
        if adapter.system_prompt_strategy == SystemPromptStrategy.INSTRUCTIONS_FILE:
            existing = '---\nname: Gentle AI Persona\ndescription: Gentleman persona with SDD orchestration and Engram Protocol\napplyTo: "**"\n---\n'
        else:
            existing = "---\ninclusion: always\n---\n"

    if _has_legacy_bare_orchestrator(existing):
        existing = _strip_bare_orchestrator_for_file_prompt(existing)

    updated = filemerge.inject_markdown_section(existing, "sdd-orchestrator", content)
    wr = filemerge.write_file_atomic(prompt_path, updated.encode("utf-8"), 0o644)
    return InjectionResult(Changed=wr.Changed, Files=[prompt_path])


def _has_legacy_bare_orchestrator(content: str) -> bool:
    marked_idx = content.find("<!-- dxrk:sdd-orchestrator -->")
    if marked_idx >= 0:
        prefix = content[:marked_idx]
        if "# Agent Teams Lite — Orchestrator Instructions" in prefix:
            return True
    first_heading = -1
    for marker in _SDD_ORCHESTRATOR_MARKERS:
        idx = content.find(marker)
        if idx >= 0 and (first_heading == -1 or idx < first_heading):
            first_heading = idx
    if first_heading < 0:
        return False
    if marked_idx < 0:
        return True
    return first_heading < marked_idx


def _strip_bare_orchestrator_for_file_prompt(content: str) -> str:
    marked_idx = content.find("<!-- dxrk:sdd-orchestrator -->")
    if marked_idx >= 0:
        prefix = content[:marked_idx]
        start = prefix.find("# Agent Teams Lite — Orchestrator Instructions")
        if start >= 0:
            before = content[:start].rstrip("\n")
            after = content[marked_idx:].lstrip("\n")
            if not before:
                return after + "\n" if not after.endswith("\n") else after
            result = before + "\n\n" + after
            return result + "\n" if not result.endswith("\n") else result

    start = -1
    for marker in _SDD_ORCHESTRATOR_MARKERS:
        idx = content.find(marker)
        if idx >= 0 and (start == -1 or idx < start):
            start = idx
    if start < 0:
        return content

    end = len(content)
    rel = content[start:].find("<!-- dxrk:")
    if rel >= 0:
        end = start + rel

    before = content[:start].rstrip("\n")
    after = content[end:].lstrip("\n")
    if not before and not after:
        return ""
    if not before:
        return after + "\n"
    if not after:
        return before + "\n"
    result = before + "\n\n" + after
    return result + "\n"


# ─── Read assignments ──────────────────────────────────────────────────────


_SDD_PHASE_SET = set(profile_phase_order())
_SDD_PHASE_SET.add("sdd-orchestrator")


def read_current_profiles(settings_path: str) -> list[Profile]:
    return detect_profiles(settings_path)


def read_current_model_assignments(settings_path: str) -> dict[str, ModelAssignment]:
    try:
        with open(settings_path) as f:
            data = f.read()
    except FileNotFoundError:
        return {}
    try:
        root = json.loads(data)
    except json.JSONDecodeError:
        return {}

    agent_raw = root.get("agent")
    if not isinstance(agent_raw, dict):
        return {}

    result: dict[str, ModelAssignment] = {}
    for name, def_raw in agent_raw.items():
        if name not in _SDD_PHASE_SET:
            continue
        if not isinstance(def_raw, dict):
            continue
        model_str = def_raw.get("model", "")
        if not isinstance(model_str, str) or not model_str:
            continue
        idx = model_str.find(":")
        if idx <= 0:
            idx = model_str.find("/")
        if idx <= 0:
            continue
        provider_id = model_str[:idx]
        model_id = model_str[idx + 1 :]
        if not model_id:
            continue
        result[name] = ModelAssignment(provider_id=provider_id, model_id=model_id)
    return result


# ─── Internal helpers ──────────────────────────────────────────────────────

_asset_root = os.path.join(os.path.dirname(__file__), "..", "assets")


def _merge_json_file(
    path: str, overlay: bytes
) -> tuple[filemerge.WriteResult, bytes | None]:
    try:
        with open(path, "rb") as f:
            base_json = f.read()
    except FileNotFoundError:
        base_json = b""
    merged = filemerge.merge_json_objects(base_json, overlay)
    wr = filemerge.write_file_atomic(path, merged, 0o644)
    return wr, merged


def _read_file_or_empty(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""
