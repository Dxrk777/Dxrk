# SPDX-License-Identifier: MIT
"""Hook event, match, result, and config dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from dxrk.utils.hooks_model_types import HookType, PreToolUse


@dataclass
class HookEvent:
    """Represents a hook trigger event with context. Mirrors hooks.HookEvent."""

    type: HookType = PreToolUse
    tool_name: str = ""
    tool_input: Any = None
    tool_output: Any = None
    prompt: str = ""
    message: str = ""
    metadata: dict[str, str] | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    session_id: str = ""


@dataclass
class HookMatch:
    """Defines pattern matching criteria for a hook. Mirrors hooks.HookMatch."""

    tool_name: str = ""
    tool_names: list[str] = field(default_factory=list)
    path: str = ""
    paths: list[str] = field(default_factory=list)
    glob: str = ""
    regex: str = ""
    command: str = ""
    commands: list[str] = field(default_factory=list)


@dataclass
class HookResult:
    """Represents the outcome of hook execution. Mirrors hooks.HookResult."""

    success: bool = False
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    duration: timedelta = timedelta(0)
    modified_input: Any = None
    skip_tool: bool = False
    abort_reason: str = ""
    metadata: dict[str, str] | None = None


@dataclass
class HookConfig:
    """Holds the configuration for a single hook. Mirrors hooks.HookConfig."""

    id: str = ""
    type: HookType = PreToolUse
    match: HookMatch = field(default_factory=HookMatch)
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: list[str] = field(default_factory=list)
    timeout: timedelta = timedelta(0)
    max_retries: int = 0
    retry_delay: timedelta = timedelta(0)
    enabled: bool = False
    description: str = ""
    priority: int = 0


@dataclass
class HookExecutionContext:
    """Provides runtime context for hook execution. Mirrors hooks.HookExecutionContext."""

    event: HookEvent = field(default_factory=HookEvent)
    config: HookConfig = field(default_factory=HookConfig)
    start_time: datetime = field(default_factory=datetime.now)
    attempt: int = 0


@dataclass
class HookConfigFile:
    """Represents the on-disk hook configuration format. Mirrors hooks.HookConfigFile."""

    version: str = ""
    hooks: list[HookConfig] = field(default_factory=list)
