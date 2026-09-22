# SPDX-License-Identifier: MIT

"""Tool and resource classification with risk assessment."""

from __future__ import annotations

import os
from enum import IntEnum
from typing import cast

from dxrk.utils.permissions_model import _STR_CRITICAL as _STR_CRITICAL
from dxrk.utils.permissions_model import _STR_EXECUTE as _STR_EXECUTE
from dxrk.utils.permissions_model import _STR_FORMAT as _STR_FORMAT
from dxrk.utils.permissions_model import _STR_LISTFILES as _STR_LISTFILES
from dxrk.utils.permissions_model import _STR_MEDIUM as _STR_MEDIUM
from dxrk.utils.permissions_model import _STR_TODOREAD as _STR_TODOREAD
from dxrk.utils.permissions_model import _STR_UNKNOWN as _STR_UNKNOWN
from dxrk.utils.permissions_model import _STR_WEBFETCH as _STR_WEBFETCH
from dxrk.utils.permissions_model import _STR_WEBSEARCH as _STR_WEBSEARCH
from dxrk.utils.permissions_model import _STR_WRITE as _STR_WRITE
from dxrk.utils.permissions_model import _anonymous_enum_member as _anonymous_enum_member

# ---- Tool Classification ----


class ToolCategory(IntEnum):
    """Classifies a tool by its primary function."""

    FileSystem = 0
    Shell = 1
    Network = 2
    UserInteraction = 3
    Internal = 4

    def String(self) -> str:
        if self == ToolCategory.FileSystem:
            return "filesystem"
        if self == ToolCategory.Shell:
            return "shell"
        if self == ToolCategory.Network:
            return "network"
        if self == ToolCategory.UserInteraction:
            return "user_interaction"
        if self == ToolCategory.Internal:
            return "internal"
        return _STR_UNKNOWN

    @classmethod
    def _missing_(cls, value: object) -> ToolCategory:
        """Support arbitrary integer values, like type conversion."""
        return cast(ToolCategory, _anonymous_enum_member(cls, value))


class ResourceType(IntEnum):
    """Identifies what kind of resource is being accessed."""

    File = 0
    Directory = 1
    URL = 2
    Command = 3
    EnvVar = 4
    Config = 5

    def String(self) -> str:
        if self == ResourceType.File:
            return "file"
        if self == ResourceType.Directory:
            return "directory"
        if self == ResourceType.URL:
            return "url"
        if self == ResourceType.Command:
            return "command"
        if self == ResourceType.EnvVar:
            return "env_var"
        if self == ResourceType.Config:
            return "config"
        return _STR_UNKNOWN

    @classmethod
    def _missing_(cls, value: object) -> ResourceType:
        """Support arbitrary integer values, like type conversion."""
        return cast(ResourceType, _anonymous_enum_member(cls, value))


class RiskLevel(IntEnum):
    """Represents the severity of a permission request."""

    Low = 0
    Medium = 1
    High = 2
    Critical = 3

    def String(self) -> str:
        if self == RiskLevel.Low:
            return "low"
        if self == RiskLevel.Medium:
            return _STR_MEDIUM
        if self == RiskLevel.High:
            return "high"
        if self == RiskLevel.Critical:
            return _STR_CRITICAL
        return _STR_UNKNOWN

    @classmethod
    def _missing_(cls, value: object) -> RiskLevel:
        """Support arbitrary integer values, like type conversion."""
        return cast(RiskLevel, _anonymous_enum_member(cls, value))


def RequireConfirmation(level: RiskLevel) -> bool:
    """Return true if the risk level warrants user confirmation."""
    return level >= RiskLevel.Medium


# ---- Classification Maps ----

tool_categories: dict[str, ToolCategory] = {
    "Read": ToolCategory.FileSystem,
    _STR_WRITE: ToolCategory.FileSystem,
    "Edit": ToolCategory.FileSystem,
    "Glob": ToolCategory.FileSystem,
    "Grep": ToolCategory.FileSystem,
    "LS": ToolCategory.FileSystem,
    _STR_LISTFILES: ToolCategory.FileSystem,
    "Bash": ToolCategory.Shell,
    _STR_EXECUTE: ToolCategory.Shell,
    _STR_WEBFETCH: ToolCategory.Network,
    _STR_WEBSEARCH: ToolCategory.Network,
    _STR_TODOREAD: ToolCategory.Internal,
    "TodoWrite": ToolCategory.Internal,
    "Webpage": ToolCategory.Network,
    "Task": ToolCategory.Internal,
    "AskUser": ToolCategory.UserInteraction,
    "Confirm": ToolCategory.UserInteraction,
    "Notify": ToolCategory.UserInteraction,
}

read_only_tools: dict[str, bool] = {
    "Read": True,
    "Glob": True,
    "Grep": True,
    "LS": True,
    _STR_LISTFILES: True,
    _STR_WEBFETCH: True,
    _STR_WEBSEARCH: True,
    _STR_TODOREAD: True,
    "AskUser": True,
}

sensitive_tool_resources: dict[str, RiskLevel] = {
    "Bash": RiskLevel.High,
    _STR_EXECUTE: RiskLevel.High,
    _STR_WRITE: RiskLevel.Medium,
    "Edit": RiskLevel.Medium,
    _STR_WEBFETCH: RiskLevel.Low,
    "Read": RiskLevel.Low,
    "Glob": RiskLevel.Low,
    "Grep": RiskLevel.Low,
    "LS": RiskLevel.Low,
}

DangerousCommandPrefixes: list[str] = [
    "rm ",
    "rm\t",
    "rmdir",
    "sudo",
    "su ",
    "doas",
    "dd ",
    "mkfs",
    _STR_FORMAT,
    "curl ",
    "wget ",
    "eval ",
    "exec ",
    "chmod 777",
    "chown root",
    "> /dev/",
    ">> /dev/",
    "git push",
    "git commit",
    "npm publish",
    "pip upload",
    "docker run",
    "kubectl exec",
    "DROP TABLE",
    "DELETE FROM",
    "TRUNCATE",
]

# ---- Classification Functions ----


def ClassifyTool(toolName: str) -> ToolCategory:
    """Return the category of a tool by name."""
    return tool_categories.get(toolName, ToolCategory.Internal)


def ClassifyResource(resource: str) -> ResourceType:
    """Determine the resource type from a resource string."""
    if resource == "":
        return ResourceType.Command
    lower = resource.lower()

    if lower.startswith("http://") or lower.startswith("https://"):
        return ResourceType.URL
    if lower.startswith("$") or lower.startswith("env:"):
        return ResourceType.EnvVar
    if (
        "config" in lower
        or lower.endswith(".json")
        or lower.endswith(".yaml")
        or lower.endswith(".yml")
        or lower.endswith(".toml")
        or lower.endswith(".env")
    ):
        return ResourceType.Config
    if resource.endswith("/") or resource == "." or resource == "..":
        return ResourceType.Directory
    ext = os.path.splitext(resource)[1]
    if ext != "":
        return ResourceType.File
    if any(ch in resource for ch in ";&|`$(){}[]!"):
        return ResourceType.Command
    return ResourceType.File


def AssessRisk(tool: str, resource: str) -> RiskLevel:
    """Evaluate the combined risk of a tool and resource."""
    base = sensitive_tool_resources.get(tool, RiskLevel.Medium)

    if tool == "Bash" or tool == _STR_EXECUTE:
        for prefix in DangerousCommandPrefixes:
            if prefix.lower() in resource.lower():
                if base < RiskLevel.High:
                    base = RiskLevel.High
                pl = prefix.lower()
                if (
                    pl.startswith("rm ")
                    or pl.startswith("sudo")
                    or pl.startswith("dd ")
                    or "drop table" in pl
                ):
                    return RiskLevel.Critical

    if ClassifyResource(resource) == ResourceType.URL and base < RiskLevel.Medium:
        base = RiskLevel.Medium

    if tool == _STR_WRITE or tool == "Edit":
        if ".." in resource or resource.startswith("/"):
            if base < RiskLevel.High:
                base = RiskLevel.High

    return base


def IsReadOnly(tool: str) -> bool:
    """Return true if the tool performs no side effects."""
    return read_only_tools.get(tool, False)


def ToolRiskSummary(tool: str, resource: str) -> str:
    """Return a human-readable risk summary for a tool+resource pair."""
    level = AssessRisk(tool, resource)
    cat = ClassifyTool(tool)
    resType = ClassifyResource(resource)

    return " ".join(
        [
            "tool=" + tool,
            "category=" + cat.String(),
            "resource_type=" + resType.String(),
            "risk=" + level.String(),
        ]
    )
