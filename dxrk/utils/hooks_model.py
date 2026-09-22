# SPDX-License-Identifier: MIT
"""Hook types, config, and JSON serialization."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Any

# Mirrors dxrk/strconst.StrUnknown / dxrk/strconst.StrError.
_STR_UNKNOWN = "unknown"
_STR_ERROR = "error"

_DISCARD = "<discard>"


class HookType(IntEnum):
    """Represents the type of hook event. Mirrors hooks.HookType."""

    PRE_TOOL_USE = 0
    POST_TOOL_USE = 1
    USER_PROMPT_SUBMIT = 2
    NOTIFICATION = 3
    STOP = 4
    SUBAGENT_STOP = 5

    def string(self) -> str:
        """Return the hook type name. Mirrors HookType.String()."""
        names = (
            "pre_tool_use",
            "post_tool_use",
            "user_prompt_submit",
            "notification",
            "stop",
            "subagent_stop",
        )
        if int(self) < len(names):
            return names[int(self)]
        return _STR_UNKNOWN


PreToolUse = HookType.PRE_TOOL_USE
PostToolUse = HookType.POST_TOOL_USE
UserPromptSubmit = HookType.USER_PROMPT_SUBMIT
Notification = HookType.NOTIFICATION
Stop = HookType.STOP
SubagentStop = HookType.SUBAGENT_STOP


def _hook_type_name(ht: HookType | int) -> str:
    """Name of a hook type, allowing out-of-range ints."""
    if isinstance(ht, HookType):
        return ht.string()
    names = (
        "pre_tool_use",
        "post_tool_use",
        "user_prompt_submit",
        "notification",
        "stop",
        "subagent_stop",
    )
    if 0 <= int(ht) < len(names):
        return names[int(ht)]
    return _STR_UNKNOWN


def ParseHookType(s: str) -> tuple[HookType, bool]:
    """Parse a hook type name. Mirrors hooks.ParseHookType."""
    if s == "pre_tool_use":
        return PreToolUse, True
    if s == "post_tool_use":
        return PostToolUse, True
    if s == "user_prompt_submit":
        return UserPromptSubmit, True
    if s == "notification":
        return Notification, True
    if s == "stop":
        return Stop, True
    if s == "subagent_stop":
        return SubagentStop, True
    return HookType.PRE_TOOL_USE, False


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


class HookError(Exception):
    """Represents a hook package error. Mirrors hooks error values."""

    def __init__(self, msg: str) -> None:
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


ErrConfigNotFound = HookError("hooks: config not found")
ErrConfigParse = HookError("hooks: config parse error")
ErrHookNotFound = HookError("hooks: hook not found")
ErrHookDisabled = HookError("hooks: hook is disabled")
ErrInvalidConfig = HookError("hooks: invalid configuration")
ErrRegistryClosed = HookError("hooks: registry is closed")
ErrDuplicateHookID = HookError("hooks: duplicate hook ID")
ErrExecutionTimeout = HookError("hooks: execution timeout")
ErrMaxRetriesExceeded = HookError("hooks: max retries exceeded")
ErrCircuitOpen = HookError("hooks: circuit breaker open")
ErrHookAborted = HookError("hooks: hook execution aborted")
ErrQueueClosed = HookError("hooks: queue is closed")
ErrQueueFull = HookError("hooks: queue is full")
ErrWorkerStopped = HookError("hooks: worker stopped")
ErrLoggerClosed = HookError("hooks: logger is closed")


def _go_time_fmt(dt: datetime) -> str:
    """Format a datetime as RFC 3339 nano JSON (UTC, Z)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    micro = dt.microsecond
    if micro == 0:
        return base + "Z"
    frac = f"{micro:06d}".rstrip("0")
    return base + "." + frac + "Z"


def _go_time_parse(text: str) -> datetime:
    """Parse an RFC 3339 time string (JSON format)."""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _td_ns(td: timedelta) -> int:
    """Convert a timedelta to nanoseconds (time.Duration JSON)."""
    return int(td.total_seconds() * 1_000_000_000)


def _ns_td(ns: int) -> timedelta:
    """Convert nanoseconds to a timedelta."""
    return timedelta(microseconds=ns // 1000)


def _raw_dump(value: Any) -> Any:
    """Normalize a json.RawMessage-style value for dumping."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _raw_load(value: Any) -> Any:
    """Normalize a parsed JSON value for RawMessage-style fields."""
    return value


def _odict(cond: bool, key: str, value: Any) -> dict[str, Any] | None:
    """Build a JSON dictionary entry honoring 'omitempty' semantics."""
    if not cond:
        return None
    return {key: value}


def _evt_dump(event: HookEvent) -> dict[str, Any]:
    d: dict[str, Any] = {"type": int(event.type)}
    if event.tool_name:
        d["tool_name"] = event.tool_name
    if event.tool_input is not None:
        d["tool_input"] = _raw_dump(event.tool_input)
    if event.tool_output is not None:
        d["tool_output"] = _raw_dump(event.tool_output)
    if event.prompt:
        d["prompt"] = event.prompt
    if event.message:
        d["message"] = event.message
    if event.metadata:
        d["metadata"] = event.metadata
    d["timestamp"] = _go_time_fmt(event.timestamp)
    if event.session_id:
        d["session_id"] = event.session_id
    return d


def _evt_load(d: dict[str, Any]) -> HookEvent:
    e = HookEvent(type=HookType(int(d.get("type", 0))))
    e.tool_name = d.get("tool_name", "")
    if "tool_input" in d:
        e.tool_input = _raw_load(d["tool_input"])
    if "tool_output" in d:
        e.tool_output = _raw_load(d["tool_output"])
    e.prompt = d.get("prompt", "")
    e.message = d.get("message", "")
    e.metadata = d.get("metadata")
    if "timestamp" in d:
        e.timestamp = _go_time_parse(d["timestamp"])
    e.session_id = d.get("session_id", "")
    return e


def _result_dump(result: HookResult) -> dict[str, Any]:
    d: dict[str, Any] = {"success": result.success}
    if result.exit_code:
        d["exit_code"] = result.exit_code
    if result.stdout:
        d["stdout"] = result.stdout
    if result.stderr:
        d["stderr"] = result.stderr
    if result.error:
        d["error"] = result.error
    d["duration"] = _td_ns(result.duration)
    if result.modified_input is not None:
        d["modified_input"] = _raw_dump(result.modified_input)
    if result.skip_tool:
        d["skip_tool"] = True
    if result.abort_reason:
        d["abort_reason"] = result.abort_reason
    if result.metadata:
        d["metadata"] = result.metadata
    return d


def _result_load(d: dict[str, Any]) -> HookResult:
    r = HookResult(success=bool(d.get("success", False)))
    r.exit_code = int(d.get("exit_code", 0))
    r.stdout = d.get("stdout", "")
    r.stderr = d.get("stderr", "")
    r.error = d.get("error", "")
    if "duration" in d:
        r.duration = _ns_td(int(d["duration"]))
    if "modified_input" in d:
        r.modified_input = _raw_load(d["modified_input"])
    r.skip_tool = bool(d.get("skip_tool", False))
    r.abort_reason = d.get("abort_reason", "")
    r.metadata = d.get("metadata")
    return r


def _match_dump(match: HookMatch) -> dict[str, Any]:
    d: dict[str, Any] = {}
    if match.tool_name:
        d["tool_name"] = match.tool_name
    if match.tool_names:
        d["tool_names"] = match.tool_names
    if match.path:
        d["path"] = match.path
    if match.paths:
        d["paths"] = match.paths
    if match.glob:
        d["glob"] = match.glob
    if match.regex:
        d["regex"] = match.regex
    if match.command:
        d["command"] = match.command
    if match.commands:
        d["commands"] = match.commands
    return d


def _match_load(d: dict[str, Any]) -> HookMatch:
    m = HookMatch()
    m.tool_name = d.get("tool_name", "")
    m.tool_names = list(d.get("tool_names", []))
    m.path = d.get("path", "")
    m.paths = list(d.get("paths", []))
    m.glob = d.get("glob", "")
    m.regex = d.get("regex", "")
    m.command = d.get("command", "")
    m.commands = list(d.get("commands", []))
    return m


def _cfg_dump(cfg: HookConfig) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": cfg.id,
        "type": int(cfg.type),
        "match": _match_dump(cfg.match),
        "command": cfg.command,
        "enabled": cfg.enabled,
    }
    if cfg.args:
        d["args"] = cfg.args
    if cfg.env:
        d["env"] = cfg.env
    if cfg.timeout != timedelta(0):
        d["timeout"] = _td_ns(cfg.timeout)
    if cfg.max_retries:
        d["max_retries"] = cfg.max_retries
    if cfg.retry_delay != timedelta(0):
        d["retry_delay"] = _td_ns(cfg.retry_delay)
    if cfg.description:
        d["description"] = cfg.description
    if cfg.priority:
        d["priority"] = cfg.priority
    return d


def _cfg_load(d: dict[str, Any]) -> HookConfig:
    c = HookConfig(id=d.get("id", ""), command=d.get("command", ""))
    c.type = HookType(int(d.get("type", 0)))
    if "match" in d:
        c.match = _match_load(d["match"])
    c.args = list(d.get("args", []))
    c.env = list(d.get("env", []))
    if "timeout" in d:
        c.timeout = _ns_td(int(d["timeout"]))
    if "max_retries" in d:
        c.max_retries = int(d["max_retries"])
    if "retry_delay" in d:
        c.retry_delay = _ns_td(int(d["retry_delay"]))
    c.enabled = bool(d.get("enabled", False))
    c.description = d.get("description", "")
    c.priority = int(d.get("priority", 0))
    return c


def _file_dump(cfg: HookConfigFile) -> dict[str, Any]:
    return {"version": cfg.version, "hooks": [_cfg_dump(h) for h in cfg.hooks]}


def _file_load(d: dict[str, Any]) -> HookConfigFile:
    if not isinstance(d, dict):
        raise ValueError("config must be a JSON object")
    cfg = HookConfigFile(version=d.get("version", ""))
    hooks = d.get("hooks")
    if not isinstance(hooks, list):
        raise ValueError("hooks must be a JSON array")
    for item in hooks:
        if not isinstance(item, dict):
            raise ValueError("hook entry must be a JSON object")
        cfg.hooks.append(_cfg_load(item))
    return cfg


def DefaultConfig() -> HookConfigFile:
    """Return a default hook configuration. Mirrors hooks.DefaultConfig."""
    return HookConfigFile(version="1.0", hooks=[])


def LoadConfig(path: str) -> tuple[HookConfigFile | None, Any]:
    """Load hook configuration from a file. Mirrors hooks.LoadConfig.

    A missing file yields the default config; unreadable or unparseable
    files yield ``ErrConfigNotFound`` / ``ErrConfigParse``.
    """
    try:
        with open(os.path.abspath(path), encoding="utf-8") as f:
            data = f.read()
    except FileNotFoundError:
        return DefaultConfig(), None
    except OSError:
        return None, ErrConfigNotFound

    try:
        raw = json.loads(data)
        cfg = _file_load(raw)
    except (ValueError, TypeError):
        return None, ErrConfigParse

    if cfg.version == "":
        cfg.version = "1.0"
    for hook in cfg.hooks:
        if hook.timeout == timedelta(0):
            hook.timeout = timedelta(seconds=30)
        if hook.max_retries < 0:
            hook.max_retries = 0
        if hook.retry_delay == timedelta(0):
            hook.retry_delay = timedelta(seconds=1)
    return cfg, None


def SaveConfig(path: str, cfg: HookConfigFile) -> Any:
    """Save hook configuration to a file. Mirrors hooks.SaveConfig."""
    try:
        data = json.dumps(_file_dump(cfg), indent=2)
    except (ValueError, TypeError):
        return ErrConfigParse

    dirname = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(dirname, exist_ok=True, mode=0o700)
    except OSError as e:
        return HookError(str(e))
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        os.chmod(path, 0o600)
    except OSError as e:
        return HookError(str(e))
    return None


def ValidateConfig(cfg: HookConfigFile | None) -> Any:
    """Validate a hook configuration. Mirrors hooks.ValidateConfig."""
    if cfg is None:
        return ErrConfigParse

    ids: set[str] = set()
    for hook in cfg.hooks:
        if hook.id == "":
            return ErrConfigParse
        if hook.id in ids:
            return ErrInvalidConfig
        ids.add(hook.id)

        if hook.command == "":
            return ErrConfigParse

        if not ParseHookType(_hook_type_name(hook.type))[1]:
            return ErrConfigParse

        if hook.timeout < timedelta(0):
            return ErrConfigParse
        if hook.max_retries < 0:
            return ErrConfigParse
        if hook.retry_delay < timedelta(0):
            return ErrConfigParse
    return None


def MergeConfigs(*configs: HookConfigFile | None) -> HookConfigFile:
    """Merge multiple hook configurations. Mirrors hooks.MergeConfigs.

    The first configuration that defines a hook ID wins.
    """
    merged = DefaultConfig()
    ids: set[str] = set()
    for cfg in configs:
        if cfg is None:
            continue
        for hook in cfg.hooks:
            if hook.id not in ids:
                merged.hooks.append(hook)
                ids.add(hook.id)
    return merged


def FilterByType(cfg: HookConfigFile, ht: HookType) -> list[HookConfig]:
    """Return hooks of a specific type. Mirrors hooks.FilterByType."""
    return [hook for hook in cfg.hooks if hook.type == ht]


def FilterEnabled(cfg: HookConfigFile) -> list[HookConfig]:
    """Return only enabled hooks. Mirrors hooks.FilterEnabled."""
    return [hook for hook in cfg.hooks if hook.enabled]
