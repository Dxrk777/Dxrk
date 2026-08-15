# SPDX-License-Identifier: MIT
"""Agent builder"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, cast

from dxrk.catalog import mvp_skills
from dxrk.models import (
    AgentCodex,
    AgentGeminiCLI,
    AgentID,
    AgentClaudeCode,
    AgentOpenCode,
)
from dxrk.strconst import StrClaude

__all__ = [
    "SDDStandalone",
    "SDDNewPhase",
    "SDDPhaseSupport",
    "SDDIntegrationMode",
    "SDDIntegration",
    "GeneratedAgent",
    "RegistryEntry",
    "Registry",
    "InstallResult",
    "AdapterInfo",
    "GenerationEngine",
    "ClaudeEngine",
    "OpenCodeEngine",
    "GeminiEngine",
    "CodexEngine",
    "MockEngine",
    "GenerationError",
    "InstallError",
    "SDDInjectError",
    "compose_prompt",
    "parse",
    "new_engine",
    "install",
    "load_registry",
    "save_registry",
    "has_conflict_with_builtin",
    "inject_sdd_reference",
]

# ── SDD integration modes ──────────────────────────────────────────────────

SDDIntegrationMode = str

SDDStandalone: SDDIntegrationMode = "standalone"
SDDNewPhase: SDDIntegrationMode = "new-phase"
SDDPhaseSupport: SDDIntegrationMode = "phase-support"


@dataclass
class SDDIntegration:
    Mode: SDDIntegrationMode = SDDStandalone
    TargetPhase: str = ""
    PhaseName: str = ""


# ── Types ──────────────────────────────────────────────────────────────────


@dataclass
class GeneratedAgent:
    Name: str = ""
    Title: str = ""
    Description: str = ""
    Trigger: str = ""
    Content: str = ""
    SDDConfig: SDDIntegration | None = None


@dataclass
class RegistryEntry:
    Name: str = ""
    Title: str = ""
    Description: str = ""
    CreatedAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    GenerationEngine: AgentID = cast(AgentID, "")
    SDDIntegration: SDDIntegration | None = None
    InstalledAgents: list[AgentID] = field(default_factory=list)


@dataclass
class Registry:
    Version: int = 1
    Agents: list[RegistryEntry] = field(default_factory=list)

    def add(self, entry: RegistryEntry) -> None:
        self.Agents.append(entry)

    def find_by_name(self, name: str) -> RegistryEntry | None:
        for entry in self.Agents:
            if entry.Name == name:
                return entry
        return None

    def remove_by_name(self, name: str) -> bool:
        for i, entry in enumerate(self.Agents):
            if entry.Name == name:
                del self.Agents[i]
                return True
        return False


@dataclass
class InstallResult:
    AgentID: AgentID = cast(AgentID, "")
    Path: str = ""
    Success: bool = False
    Err: Exception | None = None


@dataclass
class AdapterInfo:
    AgentID: AgentID = cast(AgentID, "")
    SkillsDir: str = ""


# ── Exceptions ─────────────────────────────────────────────────────────────


class GenerationError(Exception):
    pass


class InstallError(Exception):
    def __init__(self, message: str, results: list[InstallResult]) -> None:
        super().__init__(message)
        self.results = results


class SDDInjectError(Exception):
    pass


# ── Prompt ─────────────────────────────────────────────────────────────────

_system_prompt_base = """You are an expert AI agent skill designer for the Dxrk AI ecosystem.
Your task is to generate a complete SKILL.md file for a custom sub-agent skill.

The SKILL.md MUST include these exact sections in order:
1. # {Title} — A clear, descriptive title for the skill
2. ## Description — What this skill does and its purpose
3. ## Trigger — When to activate this skill (specific phrases, contexts, or conditions)
4. ## Instructions — Step-by-step instructions the agent must follow when this skill is active
5. ## Rules — Hard constraints and guardrails (what the agent must/must not do)
6. ## Examples — Concrete usage examples demonstrating the skill in action

Requirements:
- Write in clear, direct language that an AI agent can execute
- Instructions must be actionable and specific
- Rules must be unambiguous constraints
- Examples must be realistic and cover edge cases
- The Trigger section must be precise enough to avoid false activations

DxrkMemory Integration:
- After completing significant work triggered by this skill, the agent MUST call mem_save
- Include a "PROACTIVE SAVE TRIGGERS" list in the Instructions section
- Reference the DxrkMemory persistent memory protocol for cross-session continuity

Output ONLY the raw SKILL.md content, starting with "# {Title}".
Do NOT wrap the output in code fences or add any preamble."""


def _agent_id_str(agent_id: AgentID) -> str:
    return agent_id.value if isinstance(agent_id, AgentID) else str(agent_id)


def compose_prompt(
    user_input: str,
    sdd_config: SDDIntegration | None,
    installed_agents: list[AgentID],
) -> str:
    parts = [_system_prompt_base, "\n\n"]

    if installed_agents:
        parts.append("## Installed Agents Context\n")
        parts.append("This skill will be installed for the following agents:\n")
        for a in installed_agents:
            parts.append(f"- {_agent_id_str(a)}\n")
        parts.append("\n")

    if sdd_config is not None and sdd_config.Mode != SDDStandalone:
        parts.append("## SDD Integration Context\n")
        if sdd_config.Mode == SDDPhaseSupport:
            parts.append(
                f"This skill provides support for the existing SDD phase: {sdd_config.TargetPhase}\n"
                "It must reference and complement the existing phase without replacing it.\n"
                f"Include a section explaining how it interacts with `sdd-{sdd_config.TargetPhase}` triggers.\n"
            )
        elif sdd_config.Mode == SDDNewPhase:
            parts.append(
                f"This skill introduces a NEW SDD phase named: {sdd_config.PhaseName}\n"
                "It must integrate with the SDD dependency graph as a first-class phase.\n"
                f"Include a Trigger that follows the pattern: When the orchestrator launches you for the {sdd_config.PhaseName} phase.\n"
                f"The phase name to use in triggers: {sdd_config.PhaseName}\n"
            )
        parts.append("\n")

    parts.append("## User Request\n")
    parts.append(user_input)
    parts.append("\n")

    return "".join(parts)


# ── Parser ─────────────────────────────────────────────────────────────────

_re_code_fence_open = re.compile(r"(?m)^```[a-zA-Z]*\s*$")
_re_code_fence_close = re.compile(r"(?m)^```\s*$")
_re_h1 = re.compile(r"(?m)^#\s+(.+)$")


def parse(raw: str) -> GeneratedAgent:
    cleaned = _strip_code_fences(raw)
    cleaned = cleaned.strip()

    if not cleaned:
        raise ValueError("parse: empty content after stripping code fences")

    title = _extract_title(cleaned)
    description = _extract_section(cleaned, "Description")
    trigger = _extract_section(cleaned, "Trigger")
    _extract_section(cleaned, "Instructions")

    name = _title_to_name(title)
    if not name:
        raise ValueError(
            "parse: generated agent title produced no valid name characters"
        )

    return GeneratedAgent(
        Name=name,
        Title=title,
        Description=description.strip(),
        Trigger=trigger.strip(),
        Content=cleaned,
    )


def _strip_code_fences(raw: str) -> str:
    m = _re_code_fence_open.search(raw)
    if m is not None:
        if m.start() == 0:
            raw = raw[m.end() :]
        elif raw[: m.start()].strip() == "":
            raw = raw[m.end() :]

    close_matches = list(_re_code_fence_close.finditer(raw))
    if close_matches:
        last = close_matches[-1]
        if raw[last.end() :].strip() == "":
            raw = raw[: last.start()]

    return raw


def _extract_title(content: str) -> str:
    m = _re_h1.search(content)
    if m is None:
        raise ValueError("parse: missing '# Title' section")
    return m.group(1).strip()


def _extract_section(content: str, name: str) -> str:
    pattern = re.compile(r"(?ms)^##\s+" + re.escape(name) + r"\s*\n(.*?)(?:^##\s|\Z)")
    m = pattern.search(content)
    if m is None:
        raise ValueError(f"parse: missing '## {name}' section")
    body = m.group(1).strip()
    if not body:
        raise ValueError(f"parse: '## {name}' section is empty")
    return body


def _title_to_name(title: str) -> str:
    s = title.lower()
    out: list[str] = []
    prev_hyphen = False
    for r in s:
        if ("a" <= r <= "z") or ("0" <= r <= "9"):
            out.append(r)
            prev_hyphen = False
        elif not prev_hyphen and out:
            out.append("-")
            prev_hyphen = True
    return "".join(out).rstrip("-")


# ── Engine ─────────────────────────────────────────────────────────────────


class GenerationEngine:
    def agent(self) -> AgentID:
        raise NotImplementedError

    def generate(self, prompt: str) -> str:
        raise NotImplementedError

    def available(self) -> bool:
        raise NotImplementedError


def new_engine(agent_id: AgentID) -> GenerationEngine | None:
    if agent_id == AgentClaudeCode:
        return ClaudeEngine()
    if agent_id == AgentOpenCode:
        return OpenCodeEngine()
    if agent_id == AgentGeminiCLI:
        return GeminiEngine()
    if agent_id == AgentCodex:
        return CodexEngine()
    return None


def _run_cli(executable: str, args: list[str], prompt: str, name: str) -> str:
    try:
        result = subprocess.run(
            [executable, *args, prompt],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise GenerationError(f"{name} generate: binary not found on PATH") from None
    if result.returncode != 0:
        raise GenerationError(
            f"{name} generate: exit status {result.returncode}\nstderr: {result.stderr}"
        )
    return result.stdout


class ClaudeEngine(GenerationEngine):
    def agent(self) -> AgentID:
        return AgentClaudeCode

    def available(self) -> bool:
        return shutil.which(StrClaude) is not None

    def generate(self, prompt: str) -> str:
        return _run_cli(StrClaude, ["--print", "-p"], prompt, "claude")


class OpenCodeEngine(GenerationEngine):
    def agent(self) -> AgentID:
        return AgentOpenCode

    def available(self) -> bool:
        return shutil.which("opencode") is not None

    def generate(self, prompt: str) -> str:
        return _run_cli("opencode", ["run"], prompt, "opencode")


class GeminiEngine(GenerationEngine):
    def agent(self) -> AgentID:
        return AgentGeminiCLI

    def available(self) -> bool:
        return shutil.which("gemini") is not None

    def generate(self, prompt: str) -> str:
        return _run_cli("gemini", ["-p"], prompt, "gemini")


class CodexEngine(GenerationEngine):
    def agent(self) -> AgentID:
        return AgentCodex

    def available(self) -> bool:
        return shutil.which("codex") is not None

    def generate(self, prompt: str) -> str:
        return _run_cli("codex", ["exec"], prompt, "codex")


@dataclass
class MockEngine(GenerationEngine):
    AgentIDVal: AgentID = cast(AgentID, "")
    Output: str = ""
    Err: Exception | None = None
    IsAvailable: bool = False

    def agent(self) -> AgentID:
        return self.AgentIDVal

    def available(self) -> bool:
        return self.IsAvailable

    def generate(self, prompt: str) -> str:
        if self.Err is not None:
            raise self.Err
        return self.Output


# ── Installer ──────────────────────────────────────────────────────────────


def install(
    agent: GeneratedAgent | None,
    adapters: list[AdapterInfo],
    project_dir: str = "",
) -> list[InstallResult]:
    if agent is None:
        raise ValueError("install: agent must not be nil")

    results: list[InstallResult] = []
    written: list[str] = []

    for adapter in adapters:
        skill_dir = os.path.join(adapter.SkillsDir, agent.Name)
        skill_file = os.path.join(skill_dir, "SKILL.md")

        try:
            os.makedirs(skill_dir, mode=0o750, exist_ok=True)
        except OSError as e:
            _rollback(written)
            _mark_all_failed(results)
            results.append(
                InstallResult(
                    AgentID=adapter.AgentID,
                    Path=skill_file,
                    Success=False,
                    Err=e,
                )
            )
            raise InstallError(
                f"install failed for {adapter.AgentID}: create directory {skill_dir}: {e}",
                results,
            ) from e

        try:
            with open(skill_file, "w", encoding="utf-8") as f:
                f.write(agent.Content)
        except OSError as e:
            _rollback(written)
            _mark_all_failed(results)
            results.append(
                InstallResult(
                    AgentID=adapter.AgentID,
                    Path=skill_file,
                    Success=False,
                    Err=e,
                )
            )
            raise InstallError(
                f"install failed for {adapter.AgentID}: write {skill_file}: {e}",
                results,
            ) from e

        written.append(skill_file)
        results.append(
            InstallResult(AgentID=adapter.AgentID, Path=skill_file, Success=True)
        )

    return results


def _rollback(paths: list[str]) -> None:
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def _mark_all_failed(results: list[InstallResult]) -> None:
    for r in results:
        r.Success = False


# ── SDD integration ────────────────────────────────────────────────────────

_marker_format = "<!-- dxrk:custom-agent:%s -->"


def inject_sdd_reference(agent: GeneratedAgent | None, system_prompt_path: str) -> None:
    if (
        agent is None
        or agent.SDDConfig is None
        or agent.SDDConfig.Mode == SDDStandalone
    ):
        return

    try:
        with open(system_prompt_path, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        raise SDDInjectError(f"sdd inject: read {system_prompt_path}: {e}") from e

    marker = _marker_format % agent.Name
    block = _build_sdd_block(agent, marker)

    if marker in content:
        content = _replace_block(content, marker, block)
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += "\n" + block + "\n"

    try:
        with open(system_prompt_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        raise SDDInjectError(f"sdd inject: write {system_prompt_path}: {e}") from e


def _build_sdd_block(agent: GeneratedAgent, marker: str) -> str:
    cfg = agent.SDDConfig
    if cfg is None:
        raise ValueError("sdd: agent has no SDD config")

    if cfg.Mode == SDDPhaseSupport:
        body = (
            f"## Custom Agent: {agent.Title} (Phase Support)\n\n"
            f"This skill provides additional support for the `sdd-{cfg.TargetPhase}` phase.\n"
            f"When working on tasks related to `{cfg.TargetPhase}`, load the `{agent.Name}` skill for enhanced guidance.\n\n"
            f"Trigger phrases: {agent.Trigger}\n"
        )
    elif cfg.Mode == SDDNewPhase:
        phase_name = cfg.PhaseName
        if not phase_name:
            phase_name = agent.Name
        body = (
            f"## Custom Agent: {agent.Title} (New SDD Phase)\n\n"
            f"This skill adds a new phase `{phase_name}` to the SDD dependency graph.\n"
            f"Load the `{agent.Name}` skill when the orchestrator launches you for the `{phase_name}` phase.\n\n"
            f"Trigger phrases: {agent.Trigger}\n"
        )
    else:
        body = f"## Custom Agent: {agent.Title}\n\nTrigger: {agent.Trigger}\n"

    end_marker = f"<!-- /dxrk:custom-agent:{agent.Name} -->"
    return marker + "\n" + body + end_marker


def _replace_block(content: str, marker: str, new_block: str) -> str:
    end_marker = f"<!-- /dxrk:custom-agent:{_extract_name(marker)} -->"

    start = content.find(marker)
    if start == -1:
        return content + "\n" + new_block

    end = content.find(end_marker, start)
    if end == -1:
        line_end = content.find("\n", start)
        if line_end == -1:
            return content[:start] + new_block
        return content[:start] + new_block + content[start + line_end :]

    replace_end = end + len(end_marker)
    return content[:start] + new_block + content[replace_end:]


def _extract_name(marker: str) -> str:
    prefix = "<!-- dxrk:custom-agent:"
    suffix = " -->"
    if marker.startswith(prefix) and marker.endswith(suffix):
        return marker[len(prefix) : len(marker) - len(suffix)]
    return ""


# ── Registry ───────────────────────────────────────────────────────────────


def _builtin_skills() -> set[str]:
    return {s.name for s in mvp_skills()}


def has_conflict_with_builtin(name: str) -> bool:
    return name in _builtin_skills()


def load_registry(path: str) -> Registry:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return Registry(Version=1)
    return _registry_from_dict(data)


def save_registry(path: str, reg: Registry) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_registry_to_dict(reg), f, indent=2)


def _registry_to_dict(reg: Registry) -> dict:
    return {
        "version": reg.Version,
        "agents": [_entry_to_dict(e) for e in reg.Agents],
    }


def _registry_from_dict(data: dict) -> Registry:
    return Registry(
        Version=data.get("version", 0),
        Agents=[_entry_from_dict(e) for e in data.get("agents", [])],
    )


def _entry_to_dict(entry: RegistryEntry) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": entry.Name,
        "title": entry.Title,
        "description": entry.Description,
        "created_at": entry.CreatedAt.isoformat(),
        "generation_engine": _agent_id_str(entry.GenerationEngine),
        "installed_agents": [_agent_id_str(a) for a in entry.InstalledAgents],
    }
    if entry.SDDIntegration is not None:
        data["sdd_integration"] = _sdd_to_dict(entry.SDDIntegration)
    return data


def _entry_from_dict(data: dict) -> RegistryEntry:
    sdd_data = data.get("sdd_integration")
    return RegistryEntry(
        Name=data.get("name", ""),
        Title=data.get("title", ""),
        Description=data.get("description", ""),
        CreatedAt=datetime.fromisoformat(data["created_at"]),
        GenerationEngine=data.get("generation_engine", ""),
        SDDIntegration=_sdd_from_dict(sdd_data) if sdd_data is not None else None,
        InstalledAgents=list(data.get("installed_agents", [])),
    )


def _sdd_to_dict(cfg: SDDIntegration) -> dict:
    data = {"mode": cfg.Mode, "target_phase": cfg.TargetPhase}
    if cfg.PhaseName:
        data["phase_name"] = cfg.PhaseName
    return data


def _sdd_from_dict(data: dict) -> SDDIntegration:
    return SDDIntegration(
        Mode=data.get("mode", SDDStandalone),
        TargetPhase=data.get("target_phase", ""),
        PhaseName=data.get("phase_name", ""),
    )
