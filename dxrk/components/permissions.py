# SPDX-License-Identifier: MIT
"""Permissions component — ports internal/components/permissions/.

Injection of bypassPermissions / auto-edit / auto-approve settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dxrk.components import filemerge
from dxrk.models import AgentID


@dataclass
class InjectionResult:
    Changed: bool = False
    Files: list[str] = field(default_factory=list)


_CLAUDE_CODE_OVERLAY_JSON = (
    b'{\n  "permissions": {\n    "defaultMode": "bypassPermissions",\n'
    b'    "deny": [\n      "Bash(rm -rf /)",\n      "Bash(sudo rm -rf /)",\n'
    b'      "Bash(rm -rf ~)",\n      "Bash(sudo rm -rf ~)",\n'
    b'      "Read(.env)",\n      "Read(.env.*)",\n      "Edit(.env)",\n      "Edit(.env.*)"\n    ]\n  }\n}\n'
)

_OPENCODE_OVERLAY_JSON = (
    b'{\n  "permission": {\n    "bash": {\n'
    b'      "*": "allow",\n      "git commit *": "ask",\n      "git push *": "ask",\n'
    b'      "git push": "ask",\n      "git push --force *": "ask",\n'
    b'      "git rebase *": "ask",\n      "git reset --hard *": "ask"\n    },\n'
    b'    "read": {\n      "*": "allow",\n      "*.env": "deny",\n'
    b'      "*.env.*": "deny",\n      "**/.env": "deny",\n'
    b'      "**/.env.*": "deny",\n      "**/secrets/**": "deny",\n'
    b'      "**/credentials.json": "deny"\n    }\n  }\n}\n'
)

_GEMINI_CLI_OVERLAY_JSON = (
    b'{\n  "general": {\n    "defaultApprovalMode": "auto_edit"\n  }\n}\n'
)

_QWEN_CODE_OVERLAY_JSON = (
    b'{\n  "permissions": {\n    "defaultMode": "auto_edit"\n  }\n}\n'
)

_VSCODE_COPILOT_OVERLAY_JSON = (
    b'{\n  "chat.tools.autoApprove": true\n}\n'
)


def _agent_overlay(agent_id: AgentID) -> bytes | None:
    mapping = {
        AgentID.CLAUDE_CODE: _CLAUDE_CODE_OVERLAY_JSON,
        AgentID.OPENCODE: _OPENCODE_OVERLAY_JSON,
        AgentID.KILOCODE: _OPENCODE_OVERLAY_JSON,
        AgentID.GEMINI_CLI: _GEMINI_CLI_OVERLAY_JSON,
        AgentID.QWEN_CODE: _QWEN_CODE_OVERLAY_JSON,
        AgentID.VSCODE_COPILOT: _VSCODE_COPILOT_OVERLAY_JSON,
    }
    return mapping.get(agent_id)


def inject(home_dir: str, adapter) -> InjectionResult:
    settings_path = adapter.settings_path(home_dir)
    if not settings_path:
        return InjectionResult()

    overlay = _agent_overlay(adapter.agent)
    if overlay is None:
        return InjectionResult()

    wr, _ = _merge_json_file(settings_path, overlay)
    return InjectionResult(Changed=wr.Changed, Files=[settings_path])


def _merge_json_file(path: str, overlay: bytes) -> tuple[filemerge.WriteResult, bytes | None]:
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
