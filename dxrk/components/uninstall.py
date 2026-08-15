# SPDX-License-Identifier: MIT
"""Uninstall component — ports internal/components/uninstall/.

Service and cleaners for managed file/tree removal.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from dxrk.components import filemerge
from dxrk.components import gga as _gga
from dxrk.components import sdd as _sdd
from dxrk.models import AgentID, ComponentID, DxrkMemoryUninstallScope

# ─── Constants ─────────────────────────────────────────────────────────────

_ALL_MANAGED_COMPONENTS = [
    ComponentID.PERSONA,
    ComponentID.DXRK_MEMORY,
    ComponentID.CONTEXT7,
    ComponentID.PERMISSIONS,
    ComponentID.SDD,
    ComponentID.SKILLS,
    ComponentID.THEME,
    ComponentID.DXRK_GUARDIAN,
]

_FULL_AGENT_REMOVAL_COMPONENTS = [
    ComponentID.PERSONA,
    ComponentID.DXRK_MEMORY,
    ComponentID.CONTEXT7,
    ComponentID.PERMISSIONS,
    ComponentID.SDD,
    ComponentID.SKILLS,
    ComponentID.THEME,
]

_SDD_PHASE_AGENTS = [
    "sdd-orchestrator",
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

_SDD_SKILL_PHASE_IDS = _SDD_PHASE_AGENTS[1:]

_MAX_MANAGED_FILE_SIZE = 16 << 20

_MANAGED_PERSONA_FINGERPRINTS = ["## Personality", "Senior Architect", "## Rules"]


# ─── Types ─────────────────────────────────────────────────────────────────


@dataclass
class Result:
    Manifest: dict[str, Any] = field(default_factory=dict)
    BackupPath: str = ""
    ChangedFiles: list[str] = field(default_factory=list)
    RemovedFiles: list[str] = field(default_factory=list)
    RemovedDirectories: list[str] = field(default_factory=list)
    ManualActions: list[str] = field(default_factory=list)
    AgentsRemovedFromState: list[AgentID] = field(default_factory=list)


class OpType:
    REWRITE_FILE = 0
    REMOVE_FILE = 1
    REMOVE_TREE = 2
    REMOVE_IF_EMPTY = 3


JsonPath = list[str]


@dataclass
class Operation:
    type_id: int
    path: str
    apply: Callable[[str], tuple[bool, bool, str | None]]


# ─── Service ───────────────────────────────────────────────────────────────


class Service:
    def __init__(
        self,
        home_dir: str,
        workspace_dir: str = "",
        app_version: str = "",
        backup_root: str = "",
    ):
        self.home_dir = home_dir
        self.workspace_dir = workspace_dir
        self.app_version = app_version
        self.backup_root = backup_root or os.path.join(
            home_dir, ".gentle-ai", "backups"
        )
        self.profile_names_to_remove: list[str] = []
        self.profile_selection_scoped = False
        self.DXRK_MEMORY_uninstall_scope = DxrkMemoryUninstallScope.GLOBAL

    def set_profile_names_to_remove(self, profile_names: list[str]) -> None:
        self.profile_names_to_remove = _dedupe_sorted_strings(profile_names)
        self.profile_selection_scoped = True

    def set_DXRK_MEMORY_uninstall_scope(self, scope: DxrkMemoryUninstallScope) -> None:
        self.DXRK_MEMORY_uninstall_scope = scope

    def partial_uninstall(
        self, agent_ids: list[AgentID], component_ids: list[ComponentID]
    ) -> Result:
        self.profile_names_to_remove = []
        self.profile_selection_scoped = False
        self.DXRK_MEMORY_uninstall_scope = DxrkMemoryUninstallScope.GLOBAL

        if not agent_ids:
            raise ValueError("partial uninstall requires at least one agent")

        components = component_ids if component_ids else list(_ALL_MANAGED_COMPONENTS)
        plan = self._build_plan(agent_ids, components)
        state_removals = _state_agents_to_remove(agent_ids, components)
        return self._execute_plan(plan, state_removals)

    def complete_uninstall(self) -> Result:
        self.profile_names_to_remove = []
        self.profile_selection_scoped = False
        self.DXRK_MEMORY_uninstall_scope = DxrkMemoryUninstallScope.GLOBAL
        all_agents = [a for a in AgentID]
        plan = self._build_plan(all_agents, _ALL_MANAGED_COMPONENTS)
        result = self._execute_plan(plan, all_agents)
        result.ManualActions.append(
            "To completely remove gentle-ai from your system, "
            "delete the executable (e.g., rm -f $(which gentle-ai))"
        )
        return result

    def _build_plan(
        self, agent_ids: list[AgentID], component_ids: list[ComponentID]
    ) -> tuple[list[str], list[Operation]]:
        backup_targets: dict[str, bool] = {}
        operations_by_key: dict[str, Operation] = {}

        for agent_id in agent_ids:
            adapter = self._get_adapter(agent_id)
            for component_id in component_ids:
                ops, targets = self._component_operations(adapter, component_id)
                for target in targets:
                    for f in _expand_backup_target(target):
                        backup_targets[f] = True
                for op in ops:
                    key = f"{op.type_id}:{op.path}"
                    if key in operations_by_key and op.type_id == OpType.REWRITE_FILE:
                        operations_by_key[key] = _merge_rewrite_ops(
                            operations_by_key[key], op
                        )
                    else:
                        operations_by_key[key] = op

        # GGA global backup targets
        for target in _global_backup_targets(self.home_dir):
            for f in _expand_backup_target(target):
                backup_targets[f] = True

        # State file
        from dxrk.state import state_path

        backup_targets[str(state_path(self.home_dir))] = True

        ordered_targets = sorted(backup_targets)
        operations = list(operations_by_key.values())
        return ordered_targets, operations

    def _get_adapter(self, agent_id: AgentID):
        from dxrk.agents.registry import Registry

        reg = Registry()
        return reg.get(agent_id)

    def _execute_plan(
        self, plan: tuple[list[str], list[Operation]], agents_to_remove: list[AgentID]
    ) -> Result:
        targets, operations = plan
        import datetime as dt

        snapshot_dir = os.path.join(
            self.backup_root, dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M%S.%f")
        )

        # Create snapshot
        manifest = {}
        for t in targets:
            if os.path.isfile(t):
                dest = os.path.join(snapshot_dir, os.path.relpath(t, "/").lstrip("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(t, dest)
        manifest["source"] = "uninstall"
        manifest["created_by_version"] = self.app_version

        result = Result(Manifest=manifest, BackupPath=snapshot_dir)
        for op in operations:
            changed, removed, error = op.apply(op.path)
            if error:
                raise RuntimeError(error)
            if op.type_id == OpType.REMOVE_IF_EMPTY and not removed:
                note = _manual_action_for_non_empty_directory(op.path)
                if note:
                    result.ManualActions.append(note)
            if not changed:
                continue
            if op.type_id == OpType.REWRITE_FILE:
                result.ChangedFiles.append(op.path)
            elif op.type_id == OpType.REMOVE_FILE and removed:
                result.RemovedFiles.append(op.path)
            elif op.type_id in (OpType.REMOVE_TREE, OpType.REMOVE_IF_EMPTY) and removed:
                result.RemovedDirectories.append(op.path)

        state_removed = _update_state_after_uninstall(self.home_dir, agents_to_remove)
        result.AgentsRemovedFromState = state_removed
        result.ManualActions = _dedupe_sorted_strings(result.ManualActions)
        return result

    def _component_operations(self, adapter, component_id: ComponentID):
        ops: list[Operation] = []
        targets: list[str] = []
        home = self.home_dir

        if component_id == ComponentID.PERSONA:
            if adapter.supports_system_prompt:
                path = adapter.system_prompt_file(home)
                targets.append(path)
                ops.append(
                    _rewrite_markdown_file(
                        path, lambda c: _remove_markdown_sections(c, "persona")
                    )
                )
            if adapter.supports_output_styles:
                path = os.path.join(adapter.output_style_dir(home), "dxrk.md")
                targets.append(path)
                ops.append(_remove_file(path))
                ops.append(_remove_dir_if_empty(adapter.output_style_dir(home)))
            sp = adapter.settings_path(home)
            if sp:
                targets.append(sp)
                paths = [["outputStyle"]]
                if adapter.agent == AgentID.OPENCODE:
                    paths.append(["agent", "dxrk"])
                ops.append(_rewrite_json_file(sp, *paths))

        elif component_id == ComponentID.CONTEXT7:
            targets.extend(_context7_targets(adapter, home))
            ops.extend(_context7_operations(adapter, home))

        elif component_id == ComponentID.DXRK_MEMORY:
            if self.DXRK_MEMORY_uninstall_scope == DxrkMemoryUninstallScope.PROJECT:
                project_data = os.path.join(self.workspace_dir, ".engram")
                if self.workspace_dir.strip():
                    targets.append(project_data)
                    ops.append(_remove_tree(project_data))
            else:
                targets.extend(_engram_targets(adapter, home))
                ops.extend(_engram_operations(adapter, home))
                if adapter.supports_system_prompt:
                    path = adapter.system_prompt_file(home)
                    targets.append(path)
                    ops.append(
                        _rewrite_markdown_file(
                            path,
                            lambda c: _remove_markdown_sections(c, "engram-protocol"),
                        )
                    )

        elif component_id == ComponentID.PERMISSIONS:
            sp = adapter.settings_path(home)
            if sp:
                targets.append(sp)
                agent = adapter.agent
                if agent == AgentID.CLAUDE_CODE:
                    ops.append(_rewrite_json_file(sp, ["permissions"]))
                elif agent == AgentID.OPENCODE:
                    ops.append(_rewrite_json_file(sp, ["permission"]))
                elif agent == AgentID.GEMINI_CLI:
                    ops.append(
                        _rewrite_json_file(sp, ["general", "defaultApprovalMode"])
                    )
                elif agent == AgentID.VSCODE_COPILOT:
                    ops.append(_rewrite_json_file(sp, ["chat.tools.autoApprove"]))

        elif component_id == ComponentID.THEME:
            sp = adapter.settings_path(home)
            if sp:
                targets.append(sp)
                ops.append(_rewrite_json_file(sp, ["theme"]))

        elif component_id == ComponentID.SKILLS:
            if not adapter.supports_skills:
                pass
            else:
                skill_dir = adapter.skills_dir(home)
                if skill_dir:
                    skills_root = os.path.join(
                        os.path.dirname(__file__), "..", "assets", "skills"
                    )
                    if os.path.isdir(skills_root):
                        for entry in os.listdir(skills_root):
                            if entry.startswith("sdd-") or entry == "_shared":
                                continue
                            dir_path = os.path.join(skill_dir, entry)
                            if os.path.isdir(dir_path):
                                targets.append(dir_path)
                                ops.append(_remove_tree(dir_path))
                                ops.append(_remove_dir_if_empty(skill_dir))

        elif component_id == ComponentID.SDD:
            if adapter.supports_system_prompt:
                path = adapter.system_prompt_file(home)
                targets.append(path)
                ops.append(
                    _rewrite_markdown_file(
                        path,
                        lambda c: _remove_markdown_sections(
                            c, "sdd-orchestrator", "strict-tdd-mode"
                        ),
                    )
                )
            if adapter.supports_slash_commands:
                commands_dir = adapter.commands_dir(home)
                asset_dir = "opencode/commands"
                full_asset_dir = os.path.join(
                    os.path.dirname(__file__), "..", "assets", asset_dir
                )
                if os.path.isdir(full_asset_dir):
                    for fname in os.listdir(full_asset_dir):
                        fpath = os.path.join(commands_dir, fname)
                        targets.append(fpath)
                        ops.append(_remove_file(fpath))
                ops.append(_remove_dir_if_empty(commands_dir))

            sp = adapter.settings_path(home)
            if sp and adapter.agent == AgentID.OPENCODE:
                targets.append(sp)
                sdd_paths: list[JsonPath] = [["agent", k] for k in _SDD_PHASE_AGENTS]
                profile_paths: list[JsonPath] = []

                if self.profile_selection_scoped:
                    for pname in self.profile_names_to_remove:
                        for agent_key in _sdd.profile_agent_keys(pname):
                            profile_paths.append(["agent", agent_key])
                else:
                    profiles = _sdd.detect_profiles(sp)
                    for profile in profiles:
                        for agent_key in _sdd.profile_agent_keys(profile.name):
                            profile_paths.append(["agent", agent_key])

                sdd_paths.extend(profile_paths)

                ops.append(_rewrite_json_file(sp, *sdd_paths))

                plugin_path = os.path.join(
                    home, ".config", "opencode", "plugins", "background-agents.ts"
                )
                targets.append(plugin_path)
                ops.append(_remove_file(plugin_path))
                ops.append(_remove_dir_if_empty(os.path.dirname(plugin_path)))

                dep_dir = os.path.join(
                    home,
                    ".config",
                    "opencode",
                    "node_modules",
                    "unique-names-generator",
                )
                targets.append(dep_dir)
                ops.append(_remove_tree(dep_dir))
                ops.append(_remove_dir_if_empty(os.path.dirname(dep_dir)))

            if adapter.supports_skills:
                skill_dir = adapter.skills_dir(home)
                shared_dir = os.path.join(skill_dir, "_shared")
                targets.append(shared_dir)
                ops.append(_remove_tree(shared_dir))
                for sid in _managed_sdd_skill_ids():
                    dir_path = os.path.join(skill_dir, sid)
                    targets.append(dir_path)
                    ops.append(_remove_tree(dir_path))
                ops.append(_remove_dir_if_empty(skill_dir))

        elif component_id == ComponentID.DXRK_GUARDIAN:
            for target in _global_backup_targets(home):
                targets.append(target)
                ops.append(_remove_file(target))
            ops.append(_remove_dir_if_empty(os.path.dirname(_gga.config_path(home))))

        return ops, targets


def _managed_sdd_skill_ids() -> list[str]:
    return list(_SDD_SKILL_PHASE_IDS) + ["judgment-day"]


# ─── Context7 helpers ─────────────────────────────────────────────────────


def _context7_targets(adapter, home_dir: str) -> list[str]:
    mcp = adapter.mcp_strategy
    if mcp in ("separate-files", "mcp-config-file"):
        return [adapter.mcp_config_path(home_dir, "context7")]
    return []


def _context7_operations(adapter, home_dir: str) -> list[Operation]:
    from dxrk.models import MCPStrategy

    mcp = adapter.mcp_strategy
    ops: list[Operation] = []

    if mcp == MCPStrategy.SEPARATE_MCP_FILES:
        path = adapter.mcp_config_path(home_dir, "context7")
        ops.append(_remove_file(path))
        ops.append(_remove_dir_if_empty(os.path.dirname(path)))

    elif mcp == MCPStrategy.MERGE_INTO_SETTINGS:
        path = adapter.settings_path(home_dir)
        if adapter.agent == AgentID.OPENCODE:
            ops.append(_rewrite_json_file(path, ["mcp", "context7"]))
        else:
            ops.append(_rewrite_json_file(path, ["mcpServers", "context7"]))

    elif mcp == MCPStrategy.MCP_CONFIG_FILE:
        path = adapter.mcp_config_path(home_dir, "context7")
        if adapter.agent == AgentID.VSCODE_COPILOT:
            ops.append(_rewrite_json_file(path, ["servers", "context7"]))
        else:
            ops.append(_rewrite_json_file(path, ["mcpServers", "context7"]))

    return ops


# ─── Engram helpers ────────────────────────────────────────────────────────


def _engram_targets(adapter, home_dir: str) -> list[str]:
    from dxrk.models import MCPStrategy

    mcp = adapter.mcp_strategy
    targets: list[str] = []
    if mcp in (MCPStrategy.SEPARATE_MCP_FILES, MCPStrategy.MCP_CONFIG_FILE):
        targets.append(adapter.mcp_config_path(home_dir, "engram"))
    elif mcp == MCPStrategy.MERGE_INTO_SETTINGS:
        targets.append(adapter.settings_path(home_dir))
    elif mcp == MCPStrategy.TOML_FILE:
        targets.append(adapter.mcp_config_path(home_dir, "DXRK_MEMORY"))
        targets.append(os.path.join(home_dir, ".codex", "DXRK_MEMORY-instructions.md"))
        targets.append(
            os.path.join(home_dir, ".codex", "DXRK_MEMORY-compact-prompt.md")
        )
    return targets


def _engram_operations(adapter, home_dir: str) -> list[Operation]:
    from dxrk.models import MCPStrategy

    mcp = adapter.mcp_strategy
    ops: list[Operation] = []

    if mcp == MCPStrategy.SEPARATE_MCP_FILES:
        path = adapter.mcp_config_path(home_dir, "engram")
        ops.append(_remove_file(path))
        ops.append(_remove_dir_if_empty(os.path.dirname(path)))

    elif mcp == MCPStrategy.MERGE_INTO_SETTINGS:
        path = adapter.settings_path(home_dir)
        if adapter.agent == AgentID.OPENCODE:
            ops.append(_rewrite_json_file(path, ["mcp", "engram"]))
        else:
            ops.append(_rewrite_json_file(path, ["mcpServers", "engram"]))

    elif mcp == MCPStrategy.MCP_CONFIG_FILE:
        path = adapter.mcp_config_path(home_dir, "DXRK_MEMORY")
        if adapter.agent == AgentID.VSCODE_COPILOT:
            ops.append(_rewrite_json_file(path, ["servers", "DXRK_MEMORY"]))
        else:
            ops.append(_rewrite_json_file(path, ["mcpServers", "DXRK_MEMORY"]))

    elif mcp == MCPStrategy.TOML_FILE:
        config_path = adapter.mcp_config_path(home_dir, "DXRK_MEMORY")
        instructions_path = os.path.join(
            home_dir, ".codex", "DXRK_MEMORY-instructions.md"
        )
        compact_path = os.path.join(home_dir, ".codex", "DXRK_MEMORY-compact-prompt.md")
        ops.append(_rewrite_toml_file(config_path, _clean_codex_toml))
        ops.append(_remove_file(instructions_path))
        ops.append(_remove_file(compact_path))
        ops.append(_remove_dir_if_empty(os.path.dirname(instructions_path)))

    return ops


# ─── Rewrite / Remove helpers ──────────────────────────────────────────────


def _rewrite_markdown_file(
    path: str, mutate: Callable[[str], tuple[str, bool]]
) -> Operation:
    def apply(p: str) -> tuple[bool, bool, str | None]:
        try:
            content = _read_managed_file(p)
        except FileNotFoundError:
            return False, False, None
        except OSError as e:
            return False, False, str(e)

        eol = "\r\n" if "\r\n" in content else "\n"
        updated, changed = mutate(content)
        if not changed:
            return False, False, None
        if eol != "\n":
            updated = updated.replace("\n", eol)
        if not updated.strip():
            _remove_file_if_exists(p)
            return True, True, None
        filemerge.write_file_atomic(p, updated.encode("utf-8"), 0o644)
        return True, False, None

    return Operation(OpType.REWRITE_FILE, path, apply)


def _rewrite_json_file(path: str, *json_paths: JsonPath) -> Operation:
    def apply(p: str) -> tuple[bool, bool, str | None]:
        try:
            raw = _read_managed_file(p)
        except FileNotFoundError:
            return False, False, None
        except OSError as e:
            return False, False, str(e)

        raw_bytes = raw.encode("utf-8")
        updated, changed = _remove_json_paths(raw_bytes, list(json_paths))
        if not changed:
            return False, False, None
        if _json_is_empty_object(updated):
            _remove_file_if_exists(p)
            return True, True, None
        filemerge.write_file_atomic(p, updated, 0o644)
        return True, False, None

    return Operation(OpType.REWRITE_FILE, path, apply)


def _rewrite_toml_file(
    path: str, mutate: Callable[[str], tuple[str, bool]]
) -> Operation:
    def apply(p: str) -> tuple[bool, bool, str | None]:
        try:
            content = _read_managed_file(p)
        except FileNotFoundError:
            return False, False, None
        except OSError as e:
            return False, False, str(e)

        eol = "\r\n" if "\r\n" in content else "\n"
        updated, changed = mutate(content)
        if not changed:
            return False, False, None
        if eol != "\n":
            updated = updated.replace("\n", eol)
        if not updated.strip():
            _remove_file_if_exists(p)
            return True, True, None
        filemerge.write_file_atomic(p, updated.encode("utf-8"), 0o644)
        return True, False, None

    return Operation(OpType.REWRITE_FILE, path, apply)


def _remove_file(path: str) -> Operation:
    def apply(p: str) -> tuple[bool, bool, str | None]:
        if not os.path.exists(p):
            return False, False, None
        try:
            os.remove(p)
            return True, True, None
        except OSError as e:
            return False, False, str(e)

    return Operation(OpType.REMOVE_FILE, path, apply)


def _remove_tree(path: str) -> Operation:
    def apply(p: str) -> tuple[bool, bool, str | None]:
        if not os.path.exists(p):
            return False, False, None
        try:
            shutil.rmtree(p)
            return True, True, None
        except OSError as e:
            return False, False, str(e)

    return Operation(OpType.REMOVE_TREE, path, apply)


def _remove_dir_if_empty(path: str) -> Operation:
    def apply(p: str) -> tuple[bool, bool, str | None]:
        if not p:
            return False, False, None
        removed = _remove_dir_if_empty_recursive(p)
        return removed, removed, None

    return Operation(OpType.REMOVE_IF_EMPTY, path, apply)


def _remove_dir_if_empty_recursive(path: str) -> bool:
    try:
        entries = os.listdir(path)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    if entries:
        return False
    try:
        os.rmdir(path)
        return True
    except OSError:
        return False


def _read_managed_file(path: str) -> str:
    st = os.lstat(path)
    if (st.st_mode & 0o170000) == 0o120000:
        raise PermissionError(f"refusing to read symlink {path!r}")
    if st.st_size > _MAX_MANAGED_FILE_SIZE:
        raise ValueError(
            f"file {path!r} exceeds max managed size {_MAX_MANAGED_FILE_SIZE} bytes"
        )
    with open(path) as f:
        return f.read()


def _remove_file_if_exists(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _expand_backup_target(path: str) -> list[str]:
    if not path:
        return []
    if not os.path.exists(path):
        return [path]
    if not os.path.isdir(path):
        return [path]

    files: list[str] = []
    for root, _dirs, names in os.walk(path):
        for name in names:
            files.append(os.path.join(root, name))
    return files


def _merge_rewrite_ops(a: Operation, b: Operation) -> Operation:
    def apply(p: str) -> tuple[bool, bool, str | None]:
        c1, r1, err1 = a.apply(p)
        if err1:
            return c1, r1, err1
        if r1:
            return c1, r1, None
        c2, r2, err2 = b.apply(p)
        return c1 or c2, r2, err2

    return Operation(OpType.REWRITE_FILE, a.path, apply)


def _manual_action_for_non_empty_directory(path: str) -> str | None:
    if not path:
        return None
    try:
        entries = os.listdir(path)
    except OSError:
        return None
    if not entries:
        return None
    return (
        f"Remove manually if no longer needed: {path} "
        f"(directory still contains non-managed files)"
    )


def _dedupe_sorted_strings(items: list[str]) -> list[str]:
    if not items:
        return []
    result = sorted(items)
    return list(dict.fromkeys(result))


def _global_backup_targets(home_dir: str) -> list[str]:
    return [
        _gga.config_path(home_dir),
        _gga.agents_template_path(home_dir),
    ]


def _state_agents_to_remove(
    agent_ids: list[AgentID], component_ids: list[ComponentID]
) -> list[AgentID]:
    selected = set(component_ids)
    for required in _FULL_AGENT_REMOVAL_COMPONENTS:
        if required not in selected:
            return []
    return list(agent_ids)


def _update_state_after_uninstall(
    home_dir: str, to_remove: list[AgentID]
) -> list[AgentID]:
    if not to_remove:
        return []
    from dxrk.state import read as state_read
    from dxrk.state import write as state_write

    try:
        current = state_read(home_dir)
    except FileNotFoundError:
        return []

    remove_set = set(to_remove)
    kept: list[str] = []
    removed: list[AgentID] = []
    for installed in current.installed_agents:
        if installed in remove_set:
            removed.append(AgentID(installed))
        else:
            kept.append(installed)

    if not removed:
        return []

    current.installed_agents = kept
    state_write(home_dir, current)
    return removed


# ─── Cleaners ──────────────────────────────────────────────────────────────


def _remove_markdown_sections(content: str, *section_ids: str) -> tuple[str, bool]:
    updated = content
    changed = False
    for sid in section_ids:
        nxt = filemerge.inject_markdown_section(updated, sid, "")
        if nxt != updated:
            changed = True
            updated = nxt
    return updated, changed


def _remove_managed_persona_preamble(content: str) -> tuple[str, bool]:
    normalized = content.replace("\r\n", "\n")
    marker_idx = normalized.find("<!-- dxrk:")
    prefix = normalized[:marker_idx] if marker_idx >= 0 else normalized
    suffix = normalized[marker_idx:] if marker_idx >= 0 else ""

    if not prefix.strip() or not _looks_like_managed_persona_prefix(prefix):
        return content, False
    if marker_idx < 0:
        return content, False
    suffix = suffix.lstrip("\n")
    return suffix, True


def _looks_like_managed_persona_prefix(prefix: str) -> bool:
    if (
        "name: Gentle AI Persona" in prefix
        and "description: Teaching-oriented persona" in prefix
    ):
        return True
    for fp in _MANAGED_PERSONA_FINGERPRINTS:
        if fp not in prefix:
            return False
    return True


def _remove_json_paths(raw: bytes, paths: list[JsonPath]) -> tuple[bytes, bool]:
    root = _unmarshal_json_object(raw)
    if root is None:
        return raw, False

    changed = False
    for path in paths:
        if _delete_json_path(root, path):
            changed = True
    if not changed:
        return raw, False

    encoded = json.dumps(root, indent=2, ensure_ascii=False).encode("utf-8")
    eol = "\r\n" if b"\r\n" in raw else "\n"
    if eol != "\n":
        encoded = encoded.replace(b"\n", eol.encode("utf-8"))
    return encoded + eol.encode("utf-8"), True


def _delete_json_path(root: dict[str, Any], path: JsonPath) -> bool:
    if not path:
        return False
    key = path[0]
    if key not in root:
        return False
    if len(path) == 1:
        del root[key]
        return True
    child = root[key]
    if not isinstance(child, dict):
        return False
    changed = _delete_json_path(child, path[1:])
    if changed and not child:
        del root[key]
    return changed


def _json_is_empty_object(raw: bytes) -> bool:
    root = _unmarshal_json_object(raw)
    return root is not None and len(root) == 0


def _clean_codex_toml(content: str) -> tuple[str, bool]:
    normalized = content.replace("\r\n", "\n")
    updated = _remove_toml_table(normalized, "mcp_servers.engram")
    updated = _remove_top_level_toml_keys(
        updated, "model_instructions_file", "experimental_compact_prompt_file"
    )
    updated = updated.strip()
    if updated:
        updated += "\n"
    return updated, updated != normalized


def _remove_toml_table(content: str, table_name: str) -> str:
    content = content.replace("\r\n", "\n")
    lines = content.split("\n")
    header = f"[{table_name}]"
    kept: list[str] = []
    i = 0
    while i < len(lines):
        trimmed = lines[i].strip()
        if trimmed == header:
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if nxt.startswith("[") and nxt.endswith("]"):
                    break
                i += 1
            continue
        kept.append(lines[i])
        i += 1
    return "\n".join(kept)


def _remove_top_level_toml_keys(content: str, *keys: str) -> str:
    content = content.replace("\r\n", "\n")
    lines = content.split("\n")
    key_set = set(keys)
    cleaned: list[str] = []
    in_table = False
    for line in lines:
        trimmed = line.strip()
        if trimmed.startswith("[") and trimmed.endswith("]"):
            in_table = True
            cleaned.append(line)
            continue
        if in_table:
            cleaned.append(line)
            continue
        remove = False
        for key in key_set:
            if trimmed.startswith(f"{key} ") or trimmed.startswith(f"{key}="):
                remove = True
                break
        if not remove:
            cleaned.append(line)
    return "\n".join(cleaned).strip()


def _unmarshal_json_object(raw: bytes) -> dict[str, Any] | None:
    if not raw.strip():
        return {}
    try:
        return cast(dict[str, Any], json.loads(raw))
    except json.JSONDecodeError:
        pass
    normalized = _normalize_json(raw)
    try:
        return cast(dict[str, Any], json.loads(normalized))
    except json.JSONDecodeError:
        return None


def _normalize_json(raw: bytes) -> bytes:
    return _strip_trailing_commas(_strip_json_comments(raw))


def _strip_json_comments(raw: bytes) -> bytes:
    out = bytearray()
    in_string = False
    escaped = False
    in_line = False
    in_block = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if in_line:
            if ch == ord("\n"):
                in_line = False
                out.append(ch)
            i += 1
            continue
        if in_block:
            if ch == ord("*") and i + 1 < len(raw) and raw[i + 1] == ord("/"):
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
                i += 1
                continue
            if ch == ord("\\"):
                escaped = True
                i += 1
                continue
            if ch == ord('"'):
                in_string = False
            i += 1
            continue
        if ch == ord('"'):
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ord("/") and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt == ord("/"):
                in_line = True
                i += 2
                continue
            if nxt == ord("*"):
                in_block = True
                i += 2
                continue
        out.append(ch)
        i += 1
    return bytes(out)


def _strip_trailing_commas(raw: bytes) -> bytes:
    out = bytearray()
    in_string = False
    escaped = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
                i += 1
                continue
            if ch == ord("\\"):
                escaped = True
                i += 1
                continue
            if ch == ord('"'):
                in_string = False
            i += 1
            continue
        if ch == ord('"'):
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ord(","):
            j = i + 1
            while j < len(raw):
                nxt = raw[j]
                if nxt in (ord(" "), ord("\t"), ord("\n"), ord("\r")):
                    j += 1
                    continue
                if nxt in (ord("}"), ord("]")):
                    ch = 0
                break
        if ch != 0:
            out.append(ch)
        i += 1
    return bytes(out)
