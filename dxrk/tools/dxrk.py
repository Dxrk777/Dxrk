# SPDX-License-Identifier: MIT
"""Concrete Dxrk tools using the tools framework"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from dxrk import system
from dxrk.agents.discovery import discover_installed
from dxrk.agents.factory import create_registry
from dxrk.agents.registry import Registry as AgentRegistry
from dxrk.models import AgentID
from dxrk.tools import Registry, ToolDef, build

_RG_MISSING_MESSAGE = (
    "ripgrep (rg) is required but not found in PATH; install it via "
    "'brew install ripgrep', 'apt install ripgrep', or 'cargo install ripgrep'"
)

_DEFAULT_MAX_READ_SIZE = 1024 * 1024

_ADAPTER_REGISTRY: AgentRegistry | None = None


def register_all(reg: Registry, agent_reg: AgentRegistry | None) -> None:
    """Register all Dxrk tools into the given registry."""
    for fn in (
        register_detect_agents,
        register_detect_agent,
        register_system_info,
        register_list_skills,
        register_run_diagnostic,
        register_read_file,
        register_grep_search,
        register_glob_search,
    ):
        fn(reg, agent_reg)


def register_detect_agents(reg: Registry, agent_reg: AgentRegistry | None) -> None:
    def execute(_ctx: Any, input_: dict[str, Any] | None) -> tuple[Any, str | None]:
        home_dir = get_home_dir(input_)
        installed = (
            discover_installed(agent_reg, home_dir) if agent_reg is not None else []
        )
        if not installed:
            return {"agents": [], "count": 0}, None
        result = [
            {"id": agent_id_value(a.id), "config_dir": a.config_dir} for a in installed
        ]
        return {"agents": result, "count": len(result)}, None

    reg.register(
        build(
            ToolDef(
                name="detect_agents",
                description="List all installed AI coding agents with their config directories",
                input_schema={
                    "type": "object",
                    "properties": {
                        "home_dir": {
                            "type": "string",
                            "description": "Home directory (defaults to $HOME)",
                        },
                    },
                },
                execute=execute,
                is_read_only=True,
            )
        )
    )


def register_detect_agent(reg: Registry, _agent_reg: AgentRegistry | None) -> None:
    def validate(input_: dict[str, Any] | None) -> str | None:
        if input_ is None or input_.get("agent") is None:
            return "agent is required"
        return None

    def execute(_ctx: Any, input_: dict[str, Any] | None) -> tuple[Any, str | None]:
        home_dir = get_home_dir(input_)
        agent_id = str(input_.get("agent")) if input_ else ""
        adapter = _get_adapter(agent_id)
        if adapter is None:
            return None, f'unknown agent "{agent_id}"'
        try:
            result = adapter.detect(home_dir)
        except Exception as exc:  # noqa: BLE001 - tool errors surface as strings
            return None, f'detect "{agent_id}": {exc}'
        return {
            "agent": agent_id,
            "installed": bool(result.installed),
            "binary_path": result.binary_path,
            "config_path": result.config_path,
            "config_found": bool(result.config_found),
            "tier": tier_value(adapter),
        }, None

    reg.register(
        build(
            ToolDef(
                name="detect_agent",
                description="Check if a specific AI coding agent is installed",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent": {
                            "type": "string",
                            "description": "Agent ID (e.g. claude-code, opencode, cursor)",
                        },
                        "home_dir": {
                            "type": "string",
                            "description": "Home directory (defaults to $HOME)",
                        },
                    },
                    "required": ["agent"],
                },
                validate=validate,
                execute=execute,
                is_read_only=True,
            )
        )
    )


def register_system_info(reg: Registry, _agent_reg: AgentRegistry | None) -> None:
    def execute(_ctx: Any, _input_: dict[str, Any] | None) -> tuple[Any, str | None]:
        try:
            result = system.detect()
        except Exception as exc:  # noqa: BLE001 - tool errors surface as strings
            return None, f"system detect: {exc}"
        tools_out: dict[str, str] = {}
        for name, status in result.tools.items():
            tools_out[name] = status.path if status.installed else "(not installed)"
        configs = [
            {
                "agent": c.agent,
                "path": c.path,
                "exists": c.exists,
                "is_dir": c.is_directory,
            }
            for c in result.configs
        ]
        return {
            "os": result.system.os,
            "arch": result.system.arch,
            "shell": result.system.shell,
            "supported": result.system.supported,
            "tools": tools_out,
            "configs": configs,
            "dependencies": _dependencies_to_dict(result.dependencies),
        }, None

    reg.register(
        build(
            ToolDef(
                name="system_info",
                description="Get detailed system information (OS, arch, shell, tools, configs)",
                input_schema={
                    "type": "object",
                    "properties": {},
                },
                execute=execute,
                is_read_only=True,
            )
        )
    )


def register_list_skills(reg: Registry, _agent_reg: AgentRegistry | None) -> None:
    def execute(_ctx: Any, input_: dict[str, Any] | None) -> tuple[Any, str | None]:
        project_dir = get_project_dir(input_)
        home_dir = os.path.expanduser("~")
        dirs = find_skill_dirs(project_dir, home_dir)
        skills: list[dict[str, str]] = []
        seen: set[str] = set()
        for dir_ in dirs:
            try:
                entries = sorted(os.scandir(dir_), key=lambda e: e.name)
            except OSError:
                continue
            for entry in entries:
                if not entry.is_dir():
                    continue
                skill_path = os.path.join(dir_, entry.name, "SKILL.md")
                if not os.path.isfile(skill_path):
                    continue
                name = entry.name
                if name in seen:
                    continue
                seen.add(name)
                skills.append({"name": name, "path": skill_path, "type": "local"})
        skills.sort(key=lambda s: s["name"])
        return {"skills": skills, "count": len(skills)}, None

    reg.register(
        build(
            ToolDef(
                name="list_skills",
                description="List all available skills from project and user directories",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_dir": {
                            "type": "string",
                            "description": "Project directory (defaults to CWD)",
                        },
                    },
                },
                execute=execute,
                is_read_only=True,
            )
        )
    )


def register_run_diagnostic(reg: Registry, agent_reg: AgentRegistry | None) -> None:
    def execute(_ctx: Any, input_: dict[str, Any] | None) -> tuple[Any, str | None]:
        home_dir = os.path.expanduser("~")
        include_configs = True
        if input_ is not None and isinstance(input_.get("include_configs"), bool):
            include_configs = input_["include_configs"]

        try:
            sys_result = system.detect()
        except Exception as exc:  # noqa: BLE001 - tool errors surface as strings
            return None, str(exc)

        installed = (
            discover_installed(agent_reg, home_dir) if agent_reg is not None else []
        )
        agent_list = [agent_id_value(a.id) for a in installed]

        tool_list = [
            {"name": name, "installed": status.installed, "path": status.path}
            for name, status in sys_result.tools.items()
        ]
        tool_list.sort(key=lambda t: str(t["name"]))

        diag: dict[str, Any] = {
            "system": {
                "os": sys_result.system.os,
                "arch": sys_result.system.arch,
                "shell": sys_result.system.shell,
                "supported": sys_result.system.supported,
            },
            "agents": agent_list,
            "agent_count": len(agent_list),
            "tools": tool_list,
        }
        if include_configs:
            diag["configs"] = [
                {"agent": c.agent, "exists": c.exists} for c in sys_result.configs
            ]
        return diag, None

    reg.register(
        build(
            ToolDef(
                name="run_diagnostic",
                description="Run a comprehensive system diagnostic: agents, tools, configs, dependencies",
                input_schema={
                    "type": "object",
                    "properties": {
                        "include_configs": {
                            "type": "boolean",
                            "description": "Include detailed config file inspection (default: true)",
                        },
                    },
                },
                execute=execute,
                is_read_only=True,
            )
        )
    )


def register_read_file(reg: Registry, _agent_reg: AgentRegistry | None) -> None:
    def validate(input_: dict[str, Any] | None) -> str | None:
        if input_ is None or input_.get("path") is None:
            return "path is required"
        return None

    def execute(_ctx: Any, input_: dict[str, Any] | None) -> tuple[Any, str | None]:
        inp = input_ or {}
        path = str(inp.get("path"))
        max_size = _DEFAULT_MAX_READ_SIZE
        m = inp.get("max_size")
        if isinstance(m, (int, float)) and not isinstance(m, bool):
            max_size = int(m)
        try:
            info = os.stat(path)
        except OSError as exc:
            return None, f'stat "{path}": {exc}'
        if os.path.isdir(path):
            return None, f'"{path}" is a directory, not a file'
        if info.st_size > max_size:
            return None, f'file "{path}" exceeds max_size ({info.st_size} > {max_size})'
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            return None, f'read "{path}": {exc}'
        return {
            "path": path,
            "size": len(data),
            "content": data.decode("utf-8", errors="replace"),
        }, None

    reg.register(
        build(
            ToolDef(
                name="read_file",
                description="Read the contents of a file from disk",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file to read",
                        },
                        "max_size": {
                            "type": "integer",
                            "description": "Maximum bytes to read (default 1MB)",
                        },
                    },
                    "required": ["path"],
                },
                validate=validate,
                execute=execute,
                is_read_only=True,
            )
        )
    )


def register_grep_search(reg: Registry, _agent_reg: AgentRegistry | None) -> None:
    def validate(input_: dict[str, Any] | None) -> str | None:
        if input_ is None or input_.get("pattern") is None:
            return "pattern is required"
        return None

    def execute(_ctx: Any, input_: dict[str, Any] | None) -> tuple[Any, str | None]:
        missing = check_rg_available()
        if missing is not None:
            return {"error": missing, "results": [], "count": 0}, None
        inp = input_ or {}
        pattern = str(inp.get("pattern"))
        search_path = get_project_dir(inp)
        p = inp.get("path")
        if isinstance(p, str):
            search_path = p
        args = ["--no-heading", "--with-filename", "--line-number", "-i"]
        include = input_.get("include") if input_ else None
        if isinstance(include, str):
            args += ["--glob", include]
        max_results = 50
        m = input_.get("max_results") if input_ else None
        if isinstance(m, (int, float)) and not isinstance(m, bool):
            max_results = int(m)
        args += [pattern, search_path]
        proc = subprocess.run(["rg", *args], capture_output=True, text=True)
        if proc.returncode != 0:
            if proc.stderr:
                return None, f"rg: {proc.stderr}"
            return {
                "results": [],
                "count": 0,
                "error": f"exit status {proc.returncode}",
            }, None
        lines = proc.stdout.strip().split("\n")
        if len(lines) > max_results:
            lines = lines[:max_results]
        return {
            "results": lines,
            "count": len(lines),
            "truncated": len(lines) > max_results,
        }, None

    reg.register(
        build(
            ToolDef(
                name="grep_search",
                description="Search file contents using regex patterns (wraps ripgrep)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Regex pattern to search for",
                        },
                        "path": {
                            "type": "string",
                            "description": "Directory to search in (defaults to CWD)",
                        },
                        "include": {
                            "type": "string",
                            "description": "File glob pattern (e.g. *.go)",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results (default 50)",
                        },
                    },
                    "required": ["pattern"],
                },
                validate=validate,
                execute=execute,
                is_read_only=True,
            )
        )
    )


def register_glob_search(reg: Registry, _agent_reg: AgentRegistry | None) -> None:
    def validate(input_: dict[str, Any] | None) -> str | None:
        if input_ is None or input_.get("pattern") is None:
            return "pattern is required"
        return None

    def execute(_ctx: Any, input_: dict[str, Any] | None) -> tuple[Any, str | None]:
        missing = check_rg_available()
        if missing is not None:
            return {"error": missing, "files": [], "count": 0}, None
        inp = input_ or {}
        pattern = str(inp.get("pattern"))
        search_path = get_project_dir(inp)
        p = inp.get("path")
        if isinstance(p, str):
            search_path = p
        max_results = 100
        m = inp.get("max_results")
        if isinstance(m, (int, float)) and not isinstance(m, bool):
            max_results = int(m)
        proc = subprocess.run(
            ["rg", "--files", "--glob", pattern, search_path],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            if proc.stderr:
                return None, f"rg --files: {proc.stderr}"
            return {
                "files": [],
                "count": 0,
                "error": f"exit status {proc.returncode}",
            }, None
        files = proc.stdout.strip().split("\n")
        if len(files) > max_results:
            files = files[:max_results]
        return {
            "files": files,
            "count": len(files),
            "truncated": len(files) > max_results,
        }, None

    reg.register(
        build(
            ToolDef(
                name="glob_search",
                description="Search for files by glob pattern (wraps ripgrep --files)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Glob pattern (e.g. **/*.go)",
                        },
                        "path": {
                            "type": "string",
                            "description": "Directory to search in (defaults to CWD)",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results (default 100)",
                        },
                    },
                    "required": ["pattern"],
                },
                validate=validate,
                execute=execute,
                is_read_only=True,
            )
        )
    )


def get_home_dir(input_: dict[str, Any] | None) -> str:
    if input_ is not None:
        h = input_.get("home_dir")
        if isinstance(h, str) and h:
            return h
    return os.path.expanduser("~")


def get_project_dir(input_: dict[str, Any] | None) -> str:
    if input_ is not None:
        d = input_.get("project_dir")
        if isinstance(d, str) and d:
            return d
    return os.getcwd()


def project_skill_dirs(cwd: str) -> list[str]:
    return [
        os.path.join(cwd, "skills"),
        os.path.join(cwd, ".opencode", "skills"),
        os.path.join(cwd, ".claude", "skills"),
        os.path.join(cwd, ".gemini", "skills"),
        os.path.join(cwd, ".cursor", "skills"),
        os.path.join(cwd, ".github", "skills"),
        os.path.join(cwd, ".codex", "skills"),
        os.path.join(cwd, ".qwen", "skills"),
        os.path.join(cwd, ".kiro", "skills"),
        os.path.join(cwd, ".openclaw", "skills"),
        os.path.join(cwd, ".pi", "skills"),
        os.path.join(cwd, ".agent", "skills"),
        os.path.join(cwd, ".agents", "skills"),
        os.path.join(cwd, ".atl", "skills"),
    ]


def user_skill_dirs(home: str) -> list[str]:
    return [
        os.path.join(home, ".pi", "agent", "skills"),
        os.path.join(home, ".config", "agents", "skills"),
        os.path.join(home, ".agents", "skills"),
        os.path.join(home, ".kimi", "skills"),
        os.path.join(home, ".config", "opencode", "skills"),
        os.path.join(home, ".config", "kilo", "skills"),
        os.path.join(home, ".claude", "skills"),
        os.path.join(home, ".gemini", "skills"),
        os.path.join(home, ".gemini", "antigravity", "skills"),
        os.path.join(home, ".cursor", "skills"),
        os.path.join(home, ".copilot", "skills"),
        os.path.join(home, ".codex", "skills"),
        os.path.join(home, ".codeium", "windsurf", "skills"),
        os.path.join(home, ".qwen", "skills"),
        os.path.join(home, ".kiro", "skills"),
        os.path.join(home, ".openclaw", "skills"),
    ]


def find_skill_dirs(project_dir: str, home_dir: str) -> list[str]:
    dirs = project_skill_dirs(project_dir) + user_skill_dirs(home_dir)
    return [d for d in dirs if os.path.isdir(d)]


def check_rg_available() -> str | None:
    """Return an error message when ripgrep is missing, else None."""
    if shutil.which("rg") is None:
        return _RG_MISSING_MESSAGE
    return None


def _get_adapter(agent_id: str) -> Any | None:
    try:
        key = AgentID(agent_id)
    except ValueError:
        return None
    return _adapter_registry().get(key)


def _adapter_registry() -> AgentRegistry:
    global _ADAPTER_REGISTRY
    if _ADAPTER_REGISTRY is None:
        _ADAPTER_REGISTRY = create_registry()
    return _ADAPTER_REGISTRY


def agent_id_value(agent_id: AgentID) -> str:
    if isinstance(agent_id, AgentID):
        return agent_id.value
    return str(agent_id)


def tier_value(adapter: Any) -> str:
    tier = getattr(adapter, "tier", None)
    if tier is None:
        return ""
    if hasattr(tier, "value"):
        return str(tier.value)
    return str(tier)


def _dependencies_to_dict(report: Any) -> dict[str, Any]:
    deps = [
        {
            "Name": d.name,
            "Required": d.required,
            "MinVersion": d.min_version,
            "DetectCmd": list(d.detect_cmd),
            "Installed": d.installed,
            "Version": d.version,
            "InstallHint": d.install_hint,
        }
        for d in report.dependencies
    ]
    return {
        "Dependencies": deps,
        "AllPresent": report.all_present,
        "MissingRequired": list(report.missing_required),
        "MissingOptional": list(report.missing_optional),
    }
