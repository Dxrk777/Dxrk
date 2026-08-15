# SPDX-License-Identifier: MIT
"""Context7 MCP component — ports internal/components/mcp/context7.go.

Context7 MCP server injection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dxrk.components import filemerge
from dxrk.models import AgentID, MCPStrategy

# ─── Context7 JSON payloads ────────────────────────────────────────────────

_DEFAULT_CONTEXT7_SERVER_JSON = b'{\n  "command": "npx",\n  "args": [\n    "-y",\n    "@upstash/context7-mcp"\n  ]\n}\n'

_DEFAULT_CONTEXT7_OVERLAY_JSON = (
    b'{\n  "mcpServers": {\n    "context7": {\n'
    b'      "command": "npx",\n      "args": [\n        "-y",\n        "@upstash/context7-mcp"\n      ]\n    }\n  }\n}\n'
)

_OPENCODE_CONTEXT7_OVERLAY_JSON = (
    b'{\n  "mcp": {\n    "context7": {\n'
    b'      "type": "remote",\n      "url": "https://mcp.context7.com/mcp",\n      "enabled": true\n    }\n  }\n}\n'
)

_VSCODE_CONTEXT7_OVERLAY_JSON = (
    b'{\n  "servers": {\n    "context7": {\n'
    b'      "type": "http",\n      "url": "https://mcp.context7.com/mcp"\n    }\n  }\n}\n'
)

_ANTIGRAVITY_CONTEXT7_OVERLAY_JSON = (
    b'{\n  "mcpServers": {\n    "context7": {\n'
    b'      "serverUrl": "https://mcp.context7.com/mcp"\n    }\n  }\n}\n'
)

_KIMI_CONTEXT7_OVERLAY_JSON = (
    b'{\n  "mcpServers": {\n    "context7": {\n'
    b'      "transport": "http",\n      "url": "https://mcp.context7.com/mcp"\n    }\n  }\n}\n'
)


def default_context7_server_json() -> bytes:
    return _DEFAULT_CONTEXT7_SERVER_JSON


def default_context7_overlay_json() -> bytes:
    return _DEFAULT_CONTEXT7_OVERLAY_JSON


def opencode_context7_overlay_json() -> bytes:
    return _OPENCODE_CONTEXT7_OVERLAY_JSON


def vscode_context7_overlay_json() -> bytes:
    return _VSCODE_CONTEXT7_OVERLAY_JSON


def antigravity_context7_overlay_json() -> bytes:
    return _ANTIGRAVITY_CONTEXT7_OVERLAY_JSON


def kimi_context7_overlay_json() -> bytes:
    return _KIMI_CONTEXT7_OVERLAY_JSON


# ─── Injection ─────────────────────────────────────────────────────────────


@dataclass
class InjectionResult:
    Changed: bool = False
    Files: list[str] = field(default_factory=list)


def inject(home_dir: str, adapter) -> InjectionResult:
    if not adapter.supports_mcp:
        return InjectionResult()

    strategy = adapter.mcp_strategy
    if strategy == MCPStrategy.SEPARATE_MCP_FILES:
        return _inject_separate_file(home_dir, adapter)
    elif strategy == MCPStrategy.MERGE_INTO_SETTINGS:
        return _inject_merge_into_settings(home_dir, adapter)
    elif strategy == MCPStrategy.MCP_CONFIG_FILE:
        return _inject_mcp_config_file(home_dir, adapter)
    elif strategy == MCPStrategy.TOML_FILE:
        return InjectionResult()
    else:
        raise ValueError(
            f"context7 injector does not support MCP strategy {strategy} for agent {adapter.agent!r}"
        )


def _inject_separate_file(home_dir: str, adapter) -> InjectionResult:
    path = adapter.mcp_config_path(home_dir, "context7")
    wr = filemerge.write_file_atomic(path, default_context7_server_json(), 0o644)
    return InjectionResult(Changed=wr.Changed, Files=[path])


def _inject_merge_into_settings(home_dir: str, adapter) -> InjectionResult:
    settings_path = adapter.settings_path(home_dir)
    if not settings_path:
        return InjectionResult()

    if adapter.agent in (AgentID.OPENCODE, AgentID.KILOCODE):
        overlay = opencode_context7_overlay_json()
    else:
        overlay = default_context7_overlay_json()

    sw, _ = _merge_json_file(settings_path, overlay)
    return InjectionResult(Changed=sw.Changed, Files=[settings_path])


def _inject_mcp_config_file(home_dir: str, adapter) -> InjectionResult:
    path = adapter.mcp_config_path(home_dir, "context7")
    if not path:
        return InjectionResult()

    if adapter.agent == AgentID.VSCODE_COPILOT:
        overlay = vscode_context7_overlay_json()
    elif adapter.agent == AgentID.ANTIGRAVITY:
        overlay = antigravity_context7_overlay_json()
    elif adapter.agent == AgentID.KIMI:
        overlay = kimi_context7_overlay_json()
    else:
        overlay = default_context7_overlay_json()

    sw, _ = _merge_json_file(path, overlay)
    return InjectionResult(Changed=sw.Changed, Files=[path])


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
