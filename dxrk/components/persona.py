# SPDX-License-Identifier: MIT
"""Persona component — ports internal/components/persona/.

Persona content injection into system prompts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dxrk.components import filemerge
from dxrk.components.assets import must_read as _must_read
from dxrk.models import AgentID, PersonaID, SystemPromptStrategy


@dataclass
class InjectionResult:
    Changed: bool = False
    Files: list[str] = field(default_factory=list)


_OUTPUT_STYLE_OVERLAY_JSON = b'{\n  "outputStyle": "Gentleman"\n}\n'

_OPENCODE_AGENT_OVERLAY_JSON = (
    b'{\n  "agent": {\n'
    b'    "gentleman": {\n      "mode": "primary",\n'
    b'      "description": "Senior Architect mentor - helpful first, challenging when it matters",\n'
    b'      "prompt": "{file:./AGENTS.md}",\n'
    b'      "tools": {\n        "write": true,\n        "edit": true\n      }\n    },\n'
    b'    "sdd-orchestrator": {\n      "mode": "all",\n'
    b'      "description": "Gentleman personality + SDD delegate-only orchestrator",\n'
    b'      "prompt": "{file:./AGENTS.md}",\n'
    b'      "tools": {\n        "read": true,\n        "write": true,\n        "edit": true,\n        "bash": true\n      }\n    }\n  }\n}\n'
)


# ─── Agent-specific persona asset paths ────────────────────────────────────


def _persona_content(agent: AgentID, persona: PersonaID) -> str:
    if persona == PersonaID.NEUTRAL:
        return _must_read("generic/persona-neutral.md")
    if persona == PersonaID.CUSTOM:
        return ""

    mapping: dict[AgentID, str] = {
        AgentID.CLAUDE_CODE: "claude/persona-dxrk.md",
        AgentID.OPENCODE: "opencode/persona-dxrk.md",
        AgentID.KILOCODE: "opencode/persona-dxrk.md",
        AgentID.KIMI: "kimi/persona-dxrk.md",
        AgentID.KIRO_IDE: "kiro/persona-dxrk.md",
    }

    path = mapping.get(agent, "generic/persona-dxrk.md")
    return _must_read(path)


# ─── Legacy detection helpers ──────────────────────────────────────────────

_LEGACY_VSCODE_FINGERPRINTS = ["## Personality", "Senior Architect"]

_LEGACY_PERSONA_ASSET_PATHS = [
    "opencode/persona-gentleman.md",
    "generic/persona-gentleman.md",
    "generic/persona-neutral.md",
]


def _is_exact_legacy_persona_asset(existing: str) -> bool:
    trimmed = existing.strip()
    if not trimmed:
        return False
    for path in _LEGACY_PERSONA_ASSET_PATHS:
        asset = _must_read(path).strip()
        if trimmed == asset:
            return True
    return False


def _should_strip_managed_legacy_persona(existing: str) -> bool:
    return "<!-- dxrk:persona -->" in existing


def _is_legacy_unwrapped_persona(content: str) -> bool:
    if content.startswith("---\n"):
        return False
    for fp in _LEGACY_VSCODE_FINGERPRINTS:
        if fp not in content:
            return False
    return True


def _legacy_vscode_persona_paths(home_dir: str) -> list[str]:
    return [os.path.join(home_dir, ".github", "copilot-instructions.md")]


def _clean_legacy_vscode_persona(home_dir: str) -> bool:
    cleaned = False
    for old_path in _legacy_vscode_persona_paths(home_dir):
        try:
            with open(old_path) as f:
                data = f.read()
        except FileNotFoundError:
            continue
        except OSError as e:
            raise OSError(f"read legacy vscode persona {old_path!r}: {e}") from e

        if not _is_legacy_unwrapped_persona(data):
            continue

        try:
            os.remove(old_path)
            cleaned = True
        except FileNotFoundError:
            pass
    return cleaned


# ─── Managed section preservation ──────────────────────────────────────────


def _preserve_managed_sections(
    existing: str, new_persona: str, persona: PersonaID
) -> tuple[str, bool]:
    if not existing or persona == PersonaID.DXRK:
        return "", False
    idx = existing.find("<!-- dxrk:")
    if idx < 0:
        return "", False

    managed_suffix = existing[idx:]
    updated = new_persona
    if not updated.endswith("\n"):
        updated += "\n"
    if idx > 0:
        updated += "\n"
    updated += managed_suffix
    return updated, True


# ─── Wrappers ──────────────────────────────────────────────────────────────


def _wrap_instructions_file(content: str) -> str:
    frontmatter = (
        "---\n"
        "name: Dxrk AI Persona\n"
        "description: Teaching-oriented persona with SDD orchestration and Dxrk Memory protocol\n"
        'applyTo: "**"\n'
        "---\n\n"
    )
    return frontmatter + content


def _wrap_steering_file(content: str) -> str:
    frontmatter = "---\ninclusion: always\n---\n\n"
    return frontmatter + content


# ─── Main inject function ──────────────────────────────────────────────────


def inject(home_dir: str, adapter, persona: PersonaID) -> InjectionResult:
    if not adapter.supports_system_prompt:
        return InjectionResult()
    if persona == PersonaID.CUSTOM:
        return InjectionResult()

    files: list[str] = []
    changed = False
    content = _persona_content(adapter.agent, persona)
    if not content:
        return InjectionResult()

    sps = adapter.system_prompt_strategy

    # 1. Inject persona content
    if sps == SystemPromptStrategy.MARKDOWN_SECTIONS:
        prompt_path = adapter.system_prompt_file(home_dir)
        existing = _read_file_or_empty(prompt_path)
        healed = filemerge.strip_legacy_persona_block(existing)
        healed = filemerge.strip_legacy_atl_block(healed)
        updated = filemerge.inject_markdown_section(healed, "persona", content)
        wr = filemerge.write_file_atomic(prompt_path, updated.encode("utf-8"), 0o644)
        changed = changed or wr.Changed
        files.append(prompt_path)

    elif sps == SystemPromptStrategy.FILE_REPLACE:
        prompt_path = adapter.system_prompt_file(home_dir)
        if adapter.agent == AgentID.OPENCODE:
            existing = _read_file_or_empty(prompt_path)
            healed = existing
            if _should_strip_managed_legacy_persona(existing):
                healed = filemerge.strip_legacy_persona_block(existing)
            elif _is_exact_legacy_persona_asset(existing):
                healed = ""
            healed = filemerge.strip_legacy_atl_block(healed)
            updated = filemerge.inject_markdown_section(healed, "persona", content)
            wr = filemerge.write_file_atomic(
                prompt_path, updated.encode("utf-8"), 0o644
            )
            changed = changed or wr.Changed
            files.append(prompt_path)
        else:
            existing = _read_file_or_empty(prompt_path)
            preserved, ok = _preserve_managed_sections(existing, content, persona)
            if ok:
                wr = filemerge.write_file_atomic(
                    prompt_path, preserved.encode("utf-8"), 0o644
                )
                changed = changed or wr.Changed
                files.append(prompt_path)
            else:
                wr = filemerge.write_file_atomic(
                    prompt_path, content.encode("utf-8"), 0o644
                )
                changed = changed or wr.Changed
                files.append(prompt_path)

    elif sps == SystemPromptStrategy.INSTRUCTIONS_FILE:
        prompt_path = adapter.system_prompt_file(home_dir)
        try:
            if _clean_legacy_vscode_persona(home_dir):
                changed = True
        except OSError:
            pass
        existing = _read_file_or_empty(prompt_path)
        preserved, ok = _preserve_managed_sections(
            existing, _wrap_instructions_file(content), persona
        )
        if ok:
            wr = filemerge.write_file_atomic(
                prompt_path, preserved.encode("utf-8"), 0o644
            )
        else:
            wr = filemerge.write_file_atomic(
                prompt_path, _wrap_instructions_file(content).encode("utf-8"), 0o644
            )
        changed = changed or wr.Changed
        files.append(prompt_path)

    elif sps == SystemPromptStrategy.STEERING_FILE:
        prompt_path = adapter.system_prompt_file(home_dir)
        existing = _read_file_or_empty(prompt_path)
        preserved, ok = _preserve_managed_sections(
            existing, _wrap_steering_file(content), persona
        )
        steering_content = preserved if ok else _wrap_steering_file(content)
        os.makedirs(os.path.dirname(prompt_path), mode=0o755, exist_ok=True)
        wr = filemerge.write_file_atomic(
            prompt_path, steering_content.encode("utf-8"), 0o644
        )
        changed = changed or wr.Changed
        files.append(prompt_path)

    elif sps == SystemPromptStrategy.APPEND_TO_FILE:
        prompt_path = adapter.system_prompt_file(home_dir)
        existing = _read_file_or_empty(prompt_path)
        if content.strip() in existing:
            return InjectionResult(Changed=changed, Files=[prompt_path])
        updated = existing
        if updated and not updated.endswith("\n"):
            updated += "\n"
        if updated:
            updated += "\n"
        updated += content
        wr = filemerge.write_file_atomic(prompt_path, updated.encode("utf-8"), 0o644)
        changed = changed or wr.Changed
        files.append(prompt_path)

    elif sps == SystemPromptStrategy.JINJA_MODULES:
        if hasattr(adapter, "bootstrap_template"):
            adapter.bootstrap_template(home_dir)
            files.append(adapter.system_prompt_file(home_dir))
            files.append(adapter.settings_path(home_dir))

        config_dir = adapter.global_config_dir(home_dir)
        persona_path = os.path.join(config_dir, "persona.md")
        wr1 = filemerge.write_file_atomic(persona_path, content.encode("utf-8"), 0o644)
        changed = changed or wr1.Changed
        files.append(persona_path)

        output_style_content = ""
        if persona == PersonaID.DXRK:
            output_style_content = _must_read("kimi/output-style-dxrk.md")
        output_style_path = os.path.join(config_dir, "output-style.md")
        wr2 = filemerge.write_file_atomic(
            output_style_path, output_style_content.encode("utf-8"), 0o644
        )
        changed = changed or wr2.Changed
        files.append(output_style_path)

    # 2. OpenCode/Kilocode tab-switchable agents
    if (
        adapter.agent in (AgentID.OPENCODE, AgentID.KILOCODE)
        and persona != PersonaID.CUSTOM
    ):
        settings_path = adapter.settings_path(home_dir)
        if settings_path:
            agent_result, _ = _merge_json_file(
                settings_path, _OPENCODE_AGENT_OVERLAY_JSON
            )
            changed = changed or agent_result.Changed
            files.append(settings_path)

    # 3. Dxrk output style
    if persona == PersonaID.DXRK and adapter.supports_output_styles:
        output_style_dir = adapter.output_style_dir(home_dir)
        if output_style_dir:
            output_style_path = os.path.join(output_style_dir, "dxrk.md")
            output_style_content = _must_read("claude/output-style-dxrk.md")
            style_result = filemerge.write_file_atomic(
                output_style_path, output_style_content.encode("utf-8"), 0o644
            )
            changed = changed or style_result.Changed
            files.append(output_style_path)

        settings_path = adapter.settings_path(home_dir)
        if settings_path:
            settings_result, _ = _merge_json_file(
                settings_path, _OUTPUT_STYLE_OVERLAY_JSON
            )
            changed = changed or settings_result.Changed
            files.append(settings_path)

    return InjectionResult(Changed=changed, Files=files)


def _merge_json_file(
    path: str, overlay: bytes
) -> tuple[filemerge.WriteResult, bytes | None]:
    base_json = _os_read_file(path)
    merged = filemerge.merge_json_objects(base_json, overlay)
    wr = filemerge.write_file_atomic(path, merged, 0o644)
    return wr, merged


def _os_read_file(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return b""


def _read_file_or_empty(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""
