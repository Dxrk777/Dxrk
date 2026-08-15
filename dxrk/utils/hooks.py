# SPDX-License-Identifier: MIT
"""Hook system utilities.

Provides hook types/events, a pattern matcher (glob/regex), a thread-safe
hook registry, a circuit breaker, an executor with timeout/retry, an async
worker-pool queue, and a structured logger with metrics.

Concurrency mapping:

* ``time.Duration`` -> ``datetime.timedelta``
* ``json.RawMessage`` -> ``Any`` (``bytes``/``str``/``dict``/``list``)
* ``io.Writer`` -> a text-mode file-like object
* ``context.Context`` -> the private :class:`_Context` (module-local)
* channels -> ``queue.Queue`` / ``threading.Event``-based watchers

Fidelity notes (mirrored intentionally):

* ``HookMatcher.MatchEvent`` matches the *tool name* against tool-name,
  path and command criteria.
* The registry's hook matching (``matchesHook``) uses ``filepath.Match``
  semantics for globs (``*`` does not cross ``/``) and ignores ``Path``
  and ``Paths`` criteria, while the matcher's ``matchGlob`` compiles
  globs to regexes (``*`` -> ``.*``).
* ``ValidateConfig`` validates a hook's type via
  ``ParseHookType(Type.String())``, so an out-of-range type value is a
  parse error.
* JSON: durations marshal as integer nanoseconds, the logger writes a
  compact JSON line per entry and ``SaveConfig`` writes 2-space
  indented JSON.
"""

from __future__ import annotations

import json
import os
import queue
import re as _re
import subprocess
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Any, TextIO

# Mirrors dxrk/strconst.StrUnknown / dxrk/strconst.StrError.
_STR_UNKNOWN = "unknown"
_STR_ERROR = "error"

_DISCARD = "<discard>"

_CTX_CANCELED = "context canceled"
_CTX_DEADLINE = "context deadline exceeded"


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
        os.makedirs(dirname, exist_ok=True, mode=0o755)
    except OSError as e:
        return HookError(str(e))
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
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


@dataclass
class HookDefaults:
    """Holds default values for hook configuration. Mirrors hooks.HookDefaults."""

    timeout: timedelta = timedelta(0)
    max_retries: int = 0
    retry_delay: timedelta = timedelta(0)

    def ApplyDefaults(self, cfg: HookConfig) -> None:
        """Apply default values to a hook config. Mirrors HookDefaults.ApplyDefaults."""
        if cfg.timeout == timedelta(0):
            cfg.timeout = self.timeout
        if cfg.max_retries < 0:
            cfg.max_retries = self.max_retries
        if cfg.retry_delay == timedelta(0):
            cfg.retry_delay = self.retry_delay


def DefaultHookDefaults() -> HookDefaults:
    """Return the default hook defaults. Mirrors hooks.DefaultHookDefaults."""
    return HookDefaults(
        timeout=timedelta(seconds=30), max_retries=3, retry_delay=timedelta(seconds=1)
    )


class HookMatcher:
    """Provides pattern matching for hook events. Mirrors hooks.HookMatcher."""

    def __init__(self) -> None:
        self._glob_cache: dict[str, tuple[str, _re.Pattern[str]]] = {}
        self._regex_cache: dict[str, _re.Pattern[str]] = {}

    def MatchToolName(self, match: HookMatch, tool_name: str) -> bool:
        """Check if a tool name matches the match criteria. Mirrors MatchToolName."""
        if match.tool_name != "" and match.tool_name != tool_name:
            return False
        if len(match.tool_names) > 0:
            if tool_name not in match.tool_names:
                return False
        return True

    def MatchPath(self, match: HookMatch, path: str) -> bool:
        """Check if a path matches the match criteria. Mirrors MatchPath."""
        if match.path != "" and match.path != path:
            return False
        if len(match.paths) > 0:
            if path not in match.paths:
                return False
        if match.glob != "":
            if not self._match_glob(match.glob, path)[0]:
                return False
        if match.regex != "":
            if not self._match_regex(match.regex, path)[0]:
                return False
        return True

    def MatchCommand(self, match: HookMatch, command: str) -> bool:
        """Check if a command matches the match criteria. Mirrors MatchCommand."""
        if match.command != "" and match.command != command:
            return False
        if len(match.commands) > 0:
            if command not in match.commands:
                return False
        return True

    def MatchEvent(self, match: HookMatch, event: HookEvent) -> bool:
        """Check if an event matches all criteria. Mirrors hooks.MatchEvent.

        ``event.ToolName`` is used for the path and command criteria
        too; this is mirrored intentionally.
        """
        return (
            self.MatchToolName(match, event.tool_name)
            and self.MatchPath(match, event.tool_name)
            and self.MatchCommand(match, event.tool_name)
        )

    def _match_glob(self, pattern: str, name: str) -> tuple[bool, Any]:
        cached = self._glob_cache.get(pattern)
        if cached is not None:
            return bool(cached[1].match(name)), None

        regex_pattern = _glob_to_regex(pattern)
        try:
            re_obj = _re.compile(regex_pattern)
        except _re.error as e:
            return False, HookError(str(e))
        self._glob_cache[pattern] = (pattern, re_obj)
        return bool(re_obj.match(name)), None

    def _match_regex(self, pattern: str, name: str) -> tuple[bool, Any]:
        cached = self._regex_cache.get(pattern)
        if cached is not None:
            return bool(cached.match(name)), None

        try:
            re_obj = _re.compile(pattern)
        except _re.error as e:
            return False, HookError(str(e))
        self._regex_cache[pattern] = re_obj
        return bool(re_obj.match(name)), None

    def ClearCache(self) -> None:
        """Clear the pattern caches. Mirrors hooks.ClearCache."""
        self._glob_cache = {}
        self._regex_cache = {}


def _glob_to_regex(pattern: str) -> str:
    """Convert a glob pattern to a regex. Mirrors hooks.globToRegex."""
    result: list[str] = ["^"]
    in_char_class = False
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if not in_char_class:
                result.append(".*")
            else:
                result.append(c)
        elif c == "?":
            if not in_char_class:
                result.append(".")
            else:
                result.append(c)
        elif c == "[":
            in_char_class = True
            result.append(c)
        elif c == "]":
            in_char_class = False
            result.append(c)
        elif c == "\\":
            if i + 1 < len(pattern):
                result.append(c)
                result.append(pattern[i + 1])
                i += 1
            else:
                result.append(c)
        elif c in ".+()^${}|":
            result.append("\\")
            result.append(c)
        else:
            result.append(c)
        i += 1
    result.append("$")
    return "".join(result)


def _filepath_match(pattern: str, name: str) -> bool:
    """Match a glob against a name with filepath.Match semantics.

    ``*`` matches a sequence of non-separator characters and does not
    cross ``/``; ``?`` matches one non-separator character; ``[...]``
    matches a character class (``^`` negates); ``\\`` escapes.
    """

    def match_chunk(pat: str, nam: str) -> tuple[bool, int]:
        if pat == "":
            return len(nam) == 0, 0
        c = pat[0]
        if c == "*":
            rest = pat[1:]
            end = len(nam)
            for i in range(end + 1):
                if "/" in nam[:i]:
                    break
                ok, consumed = match_chunk(rest, nam[i:])
                if ok:
                    return True, i + consumed
            return False, 0
        if nam == "":
            return False, 0
        if c == "?":
            if nam[0] == "/":
                return False, 0
            ok, consumed = match_chunk(pat[1:], nam[1:])
            return ok, 1 + consumed
        if c == "\\":
            if len(pat) == 1:
                return False, 0
            e = pat[1]
            if e == "/":
                return False, 0
            if nam[0] != e:
                return False, 0
            ok, consumed = match_chunk(pat[2:], nam[1:])
            return ok, 1 + consumed
        if c == "[":
            close = pat.find("]", 1)
            if close < 0:
                return False, 0
            cls = pat[1:close]
            negate = cls.startswith("^")
            if negate:
                cls = cls[1:]
            if nam[0] == "/":
                return False, 0
            matched = False
            k = 0
            while k < len(cls):
                lo = cls[k]
                if k + 2 < len(cls) and cls[k + 1] == "-":
                    hi = cls[k + 2]
                    if lo <= nam[0] <= hi:
                        matched = True
                    k += 3
                else:
                    if nam[0] == lo:
                        matched = True
                    k += 1
            if matched == negate:
                return False, 0
            ok, consumed = match_chunk(pat[close + 1 :], nam[1:])
            return ok, 1 + consumed
        if nam[0] != c:
            return False, 0
        ok, consumed = match_chunk(pat[1:], nam[1:])
        return ok, 1 + consumed

    ok, _ = match_chunk(pattern, name)
    return ok


class _Watcher:
    """Buffered-1 watch channel backed by an event. Mirrors <-chan struct{}."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._closed = False

    def recv(self, timeout: float | None = None) -> bool:
        """Block until a notification or close; return True on notification."""
        self._event.wait(timeout)
        was_closed = self._closed
        self._event.clear()
        return not was_closed

    def _notify(self) -> None:
        if self._closed:
            return
        self._event.set()

    def _close(self) -> None:
        self._closed = True
        self._event.set()


class HookRegistry:
    """Manages hook registrations and lookups. Mirrors hooks.HookRegistry."""

    def __init__(self) -> None:
        self._mu = threading.RLock()
        self._hooks: dict[str, HookConfig] = {}
        self._by_type: dict[HookType, list[str]] = {}
        self._closed = False
        self._watchers: list[_Watcher] = []

    def Register(self, config: HookConfig) -> Any:
        """Add a hook to the registry. Mirrors hooks.Register."""
        if config.id == "":
            return ErrInvalidConfig
        if config.command == "":
            return ErrInvalidConfig

        with self._mu:
            if self._closed:
                return ErrRegistryClosed
            if config.id in self._hooks:
                return ErrDuplicateHookID

            cfg = replace(config)
            if cfg.timeout == timedelta(0):
                cfg.timeout = timedelta(seconds=30)
            if cfg.max_retries < 0:
                cfg.max_retries = 0
            if cfg.retry_delay == timedelta(0):
                cfg.retry_delay = timedelta(seconds=1)

            self._hooks[cfg.id] = cfg
            self._by_type.setdefault(cfg.type, []).append(cfg.id)
            self._notify_watchers()
        return None

    def Unregister(self, id: str) -> bool:
        """Remove a hook by ID. Mirrors hooks.Unregister."""
        with self._mu:
            if self._closed:
                return False
            cfg = self._hooks.get(id)
            if cfg is None:
                return False
            del self._hooks[id]
            self._remove_from_type_index(cfg.type, id)
            self._notify_watchers()
        return True

    def Get(self, id: str) -> tuple[HookConfig | None, bool]:
        """Retrieve a hook by ID. Mirrors hooks.Get."""
        with self._mu:
            cfg = self._hooks.get(id)
            if cfg is None:
                return None, False
            return cfg, True

    def GetByType(self, ht: HookType) -> list[str]:
        """Return all hook IDs for a given type. Mirrors hooks.GetByType."""
        with self._mu:
            return list(self._by_type.get(ht, []))

    def List(self) -> list[HookConfig]:
        """Return all registered hooks. Mirrors hooks.List."""
        with self._mu:
            return list(self._hooks.values())

    def Match(self, event: HookEvent) -> list[HookConfig]:
        """Return enabled hooks matching the given event. Mirrors hooks.Match."""
        with self._mu:
            if self._closed:
                return []
            matched: list[HookConfig] = []
            for id in self._by_type.get(event.type, []):
                cfg = self._hooks.get(id)
                if cfg is not None and cfg.enabled:
                    if _matches_hook(cfg, event):
                        matched.append(cfg)
            return matched

    def Watch(self, ctx: _Context | None = None) -> _Watcher:
        """Create a watcher that receives notifications on registry changes."""
        ctx = ctx if ctx is not None else _background()
        w = _Watcher()
        with self._mu:
            self._watchers.append(w)

        def cleanup() -> None:
            while True:
                if w._closed:
                    return
                if not ctx._done.wait(0.05):
                    continue
                with self._mu:
                    for i, watcher in enumerate(self._watchers):
                        if watcher is w:
                            self._watchers.pop(i)
                            break
                w._close()
                return

        threading.Thread(target=cleanup, daemon=True).start()
        return w

    def Close(self) -> None:
        """Mark the registry as closed. Mirrors hooks.Close."""
        with self._mu:
            self._closed = True
            for w in self._watchers:
                w._close()
            self._watchers = []

    def _remove_from_type_index(self, ht: HookType, id: str) -> None:
        ids = self._by_type.get(ht, [])
        if id in ids:
            ids.remove(id)
            self._by_type[ht] = ids

    def _notify_watchers(self) -> None:
        for w in self._watchers:
            w._notify()


def _matches_hook(cfg: HookConfig, event: HookEvent) -> bool:
    """Check a config against an event. Mirrors hooks.matchesHook.

    Uses ``filepath.Match`` semantics for the glob and ignores the
    ``Path``/``Paths`` criteria.
    """
    m = cfg.match

    if m.tool_name != "" and m.tool_name != event.tool_name:
        return False
    if len(m.tool_names) > 0:
        if event.tool_name not in m.tool_names:
            return False

    if m.glob != "":
        if not _filepath_match(m.glob, event.tool_name):
            return False

    if m.regex != "":
        try:
            re_obj = _re.compile(m.regex)
        except _re.error:
            return False
        if not re_obj.match(event.tool_name):
            return False

    if m.command != "" and m.command != event.tool_name:
        return False
    if len(m.commands) > 0:
        if event.tool_name not in m.commands:
            return False

    return True


class CircuitBreakerState(IntEnum):
    """Represents the state of a circuit breaker. Mirrors CircuitBreakerState."""

    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


CircuitClosed = CircuitBreakerState.CLOSED
CircuitOpen = CircuitBreakerState.OPEN
CircuitHalfOpen = CircuitBreakerState.HALF_OPEN


class CircuitBreaker:
    """Implements the circuit breaker pattern. Mirrors hooks.CircuitBreaker."""

    def __init__(
        self,
        failure_threshold: int,
        success_threshold: int,
        timeout: timedelta,
    ) -> None:
        self._mu = threading.Lock()
        self._state = CircuitClosed
        self._failures = 0
        self._successes = 0
        self._last_failure: datetime | None = None
        if failure_threshold <= 0:
            failure_threshold = 5
        if success_threshold <= 0:
            success_threshold = 2
        if timeout == timedelta(0):
            timeout = timedelta(seconds=30)
        self._failure_threshold = failure_threshold
        self._success_threshold = success_threshold
        self._timeout = timeout

    def Execute(self, ctx: _Context, fn: Any) -> Any:
        """Run the given function with circuit breaker protection. Mirrors Execute."""
        if not self._allow_request():
            return ErrCircuitOpen
        err = fn(ctx)
        self._record_result(err)
        return err

    def _allow_request(self) -> bool:
        with self._mu:
            if self._state == CircuitClosed:
                return True
            if self._state == CircuitOpen:
                if (
                    self._last_failure is not None
                    and datetime.now() - self._last_failure >= self._timeout
                ):
                    self._state = CircuitHalfOpen
                    self._successes = 0
                    return True
                return False
            if self._state == CircuitHalfOpen:
                return True
        return False

    def _record_result(self, err: Any) -> None:
        with self._mu:
            if err is not None:
                self._failures += 1
                self._last_failure = datetime.now()
                if self._state == CircuitHalfOpen:
                    self._state = CircuitOpen
                elif self._failures >= self._failure_threshold:
                    self._state = CircuitOpen
            else:
                self._successes += 1
                if (
                    self._state == CircuitHalfOpen
                    and self._successes >= self._success_threshold
                ):
                    self._state = CircuitClosed
                    self._failures = 0

    def State(self) -> CircuitBreakerState:
        """Return the current circuit breaker state. Mirrors hooks.State."""
        with self._mu:
            return self._state

    def Reset(self) -> None:
        """Reset the circuit breaker to closed state. Mirrors hooks.Reset."""
        with self._mu:
            self._state = CircuitClosed
            self._failures = 0
            self._successes = 0


def NewCircuitBreaker(
    failure_threshold: int, success_threshold: int, timeout: timedelta
) -> CircuitBreaker:
    """Create a new circuit breaker. Mirrors hooks.NewCircuitBreaker."""
    return CircuitBreaker(failure_threshold, success_threshold, timeout)


class _Context:
    """Minimal context mirroring the original context behavior used by hooks."""

    __slots__ = ("_done", "_err", "_deadline", "_parent")

    def __init__(
        self, parent: _Context | None = None, deadline: float | None = None
    ) -> None:
        self._done = threading.Event()
        self._err: str | None = None
        self._deadline = deadline
        self._parent = parent

    def _set(self, err: str) -> None:
        if self._deadline is not None and time.monotonic() >= self._deadline:
            err = _CTX_DEADLINE
        if not self._done.is_set():
            self._done.set()
            self._err = err

    def err(self) -> str | None:
        """Return the context error, if any."""
        if self._parent is not None:
            perr = self._parent.err()
            if perr is not None:
                self._set(perr)
        if self._done.is_set():
            return self._err
        if self._deadline is not None and time.monotonic() >= self._deadline:
            self._set(_CTX_DEADLINE)
            return self._err
        return None

    def remaining(self) -> float | None:
        """Seconds until the deadline, or None."""
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())


def _background() -> _Context:
    """Return a never-cancelled context. Mirrors context.Background()."""
    return _Context()


def _with_cancel(parent: _Context) -> tuple[_Context, Any]:
    """Return a child context with a cancel function. Mirrors context.WithCancel."""
    child = _Context(parent=parent)
    return child, lambda: child._set(_CTX_CANCELED)


def _with_timeout(parent: _Context, timeout: timedelta) -> tuple[_Context, Any]:
    """Return a child context with a timeout. Mirrors context.WithTimeout."""
    parent_remaining = parent.remaining()
    deadline = time.monotonic() + timeout.total_seconds()
    if parent_remaining is not None:
        deadline = min(deadline, time.monotonic() + parent_remaining)
    child = _Context(parent=parent, deadline=deadline)
    return child, lambda: child._set(_CTX_CANCELED)


def _exec_env(config: HookConfig) -> dict[str, str]:
    """Build a subprocess environment from the current env plus config.Env."""
    env = dict(os.environ)
    for entry in config.env:
        if "=" in entry:
            key, _, value = entry.partition("=")
            env[key] = value
        else:
            env.pop(entry, None)
    return env


def _exec_not_found(command: str) -> HookError:
    return HookError(f'exec: "{command}": executable file not found in $PATH')


class HookExecutor:
    """Executes hooks with timeout, retry, and circuit breaker. Mirrors hooks.HookExecutor."""

    def __init__(
        self,
        timeout: timedelta,
        max_retries: int,
        retry_delay: timedelta,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._circuit_breaker = circuit_breaker

    def Execute(
        self, ctx: _Context, config: HookConfig, event: HookEvent
    ) -> HookResult:
        """Run a hook command with the given context and configuration."""
        start = datetime.now()
        result = HookResult(success=False, duration=timedelta(0))

        last_err: Any = None
        attempt = 0
        while attempt <= self._max_retries:
            if attempt > 0:
                if ctx.err() is not None:
                    result.error = ctx.err() or ""
                    result.duration = datetime.now() - start
                    return result
                time.sleep(self._retry_delay.total_seconds())

            exec_ctx, cancel = _with_timeout(ctx, self._timeout)
            err = self._execute_once(exec_ctx, config, event, result, attempt)
            cancel()

            if err is None:
                result.success = True
                result.duration = datetime.now() - start
                return result

            last_err = err
            if err is ErrExecutionTimeout or err is ErrHookAborted:
                break
            attempt += 1

        result.success = False
        result.error = str(last_err) if last_err is not None else ""
        result.duration = datetime.now() - start
        return result

    def _execute_once(
        self,
        ctx: _Context,
        config: HookConfig,
        event: HookEvent,
        result: HookResult,
        attempt: int,
    ) -> Any:
        del event, attempt  # HookEvent and attempt are ignored here

        def inner(inner_ctx: _Context) -> Any:
            del inner_ctx
            cmd = [config.command, *config.args]
            env = _exec_env(config)

            timeout = self._timeout.total_seconds()
            remaining = ctx.remaining()
            if remaining is not None:
                timeout = min(timeout, remaining)

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    env=env,
                    timeout=timeout if timeout > 0 else None,
                )
            except FileNotFoundError:
                result.exit_code = -1
                return _exec_not_found(config.command)
            except subprocess.TimeoutExpired as exc:
                result.exit_code = -1
                stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
                stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
                result.stdout = stdout.decode("utf-8", errors="replace")
                result.stderr = stderr.decode("utf-8", errors="replace")
                if ctx.err() is not None:
                    return ErrExecutionTimeout
                return HookError(_CTX_DEADLINE)

            result.exit_code = proc.returncode if proc.returncode >= 0 else -1
            result.stdout = proc.stdout.decode("utf-8", errors="replace")
            result.stderr = proc.stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                if ctx.err() == _CTX_DEADLINE:
                    return ErrExecutionTimeout
                return HookError(f"exit status {proc.returncode}")
            return None

        return self._circuit_breaker.Execute(ctx, inner)


HookExecutorOption = Any


def WithExecutorTimeout(d: timedelta) -> HookExecutorOption:
    """Set the execution timeout. Mirrors hooks.WithExecutorTimeout."""

    def opt(e: HookExecutor) -> None:
        e._timeout = d

    return opt


def WithExecutorRetries(n: int) -> HookExecutorOption:
    """Set the max retries. Mirrors hooks.WithExecutorRetries."""

    def opt(e: HookExecutor) -> None:
        e._max_retries = n

    return opt


def WithExecutorRetryDelay(d: timedelta) -> HookExecutorOption:
    """Set the retry delay. Mirrors hooks.WithExecutorRetryDelay."""

    def opt(e: HookExecutor) -> None:
        e._retry_delay = d

    return opt


def WithCircuitBreaker(cb: CircuitBreaker) -> HookExecutorOption:
    """Set a custom circuit breaker. Mirrors hooks.WithCircuitBreaker."""

    def opt(e: HookExecutor) -> None:
        e._circuit_breaker = cb

    return opt


def NewHookExecutor(*opts: HookExecutorOption) -> HookExecutor:
    """Create a new hook executor. Mirrors hooks.NewHookExecutor."""
    e = HookExecutor(
        timeout=timedelta(seconds=30),
        max_retries=3,
        retry_delay=timedelta(seconds=1),
        circuit_breaker=NewCircuitBreaker(5, 2, timedelta(seconds=30)),
    )
    for opt in opts:
        opt(e)
    return e


@dataclass
class HookTask:
    """Represents a hook execution task. Mirrors hooks.HookTask."""

    event: HookEvent = field(default_factory=HookEvent)
    config: HookConfig = field(default_factory=HookConfig)
    result: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=1))
    context: _Context = field(default_factory=_background)
    cancel: Any = None


@dataclass
class QueueStats:
    """Holds queue statistics. Mirrors hooks.QueueStats."""

    processed: int = 0
    failed: int = 0
    workers: int = 0
    queue_len: int = 0
    queue_cap: int = 0
    uptime: timedelta = timedelta(0)


_SENTINEL = object()


class HookQueue:
    """Manages async hook execution with a worker pool. Mirrors hooks.HookQueue."""

    def __init__(
        self,
        *,
        tasks: queue.Queue,
        workers: int,
        executor: HookExecutor,
        started_at: datetime,
    ) -> None:
        self._mu = threading.RLock()
        self._tasks = tasks
        self._workers = workers
        self._worker_threads: list[threading.Thread] = []
        self._closed = False
        self._executor = executor
        self._processed = 0
        self._failed = 0
        self._started_at = started_at

    def Start(self) -> None:
        """Launch the worker pool. Mirrors hooks.Start."""
        with self._mu:
            if self._closed:
                return
            for _ in range(self._workers):
                t = threading.Thread(target=self._worker, daemon=True)
                self._worker_threads.append(t)
                t.start()

    def Stop(self, ctx: _Context | None = None) -> Any:
        """Gracefully shut down the queue. Mirrors hooks.Stop."""
        ctx = ctx if ctx is not None else _background()
        with self._mu:
            if self._closed:
                return None
            self._closed = True
        for _ in range(self._workers):
            self._tasks.put(_SENTINEL)

        deadline = ctx.remaining()
        for t in self._worker_threads:
            t.join(timeout=deadline)
            if ctx.remaining() == 0:
                return ctx.err()
        return None

    def Submit(
        self, ctx: _Context, event: HookEvent, config: HookConfig
    ) -> tuple[HookResult, Any]:
        """Add a task to the queue and wait for its result. Mirrors hooks.Submit."""
        child_ctx, cancel = _with_cancel(ctx)
        result_ch: queue.Queue = queue.Queue(maxsize=1)

        if child_ctx.err() is not None:
            cancel()
            return HookResult(), child_ctx.err()

        try:
            self._tasks.put_nowait(
                HookTask(
                    event=event,
                    config=config,
                    result=result_ch,
                    context=child_ctx,
                    cancel=cancel,
                )
            )
            self._processed += 1
        except queue.Full:
            cancel()
            return HookResult(), ErrQueueFull

        while True:
            if child_ctx.err() is not None:
                cancel()
                return HookResult(), child_ctx.err()
            try:
                result = result_ch.get(timeout=0.05)
                break
            except queue.Empty:
                continue

        if not result.success:
            self._failed += 1
        return result, None

    def SubmitAsync(self, event: HookEvent, config: HookConfig) -> Any:
        """Add a task without waiting for a result. Mirrors hooks.SubmitAsync."""
        child_ctx, cancel = _with_cancel(_background())
        result_ch: queue.Queue = queue.Queue(maxsize=1)

        try:
            self._tasks.put_nowait(
                HookTask(
                    event=event,
                    config=config,
                    result=result_ch,
                    context=child_ctx,
                    cancel=cancel,
                )
            )
            self._processed += 1
        except queue.Full:
            cancel()
            return ErrQueueFull

        def drain() -> None:
            try:
                result_ch.get()
            except queue.Empty:
                pass

        threading.Thread(target=drain, daemon=True).start()
        return None

    def Stats(self) -> QueueStats:
        """Return queue statistics. Mirrors hooks.Stats."""
        return QueueStats(
            processed=self._processed,
            failed=self._failed,
            workers=self._workers,
            queue_len=self._tasks.qsize(),
            queue_cap=self._tasks.maxsize,
            uptime=datetime.now() - self._started_at,
        )

    def IsRunning(self) -> bool:
        """Return True if the queue is running. Mirrors hooks.IsRunning."""
        with self._mu:
            return not self._closed

    def _worker(self) -> None:
        while True:
            try:
                task = self._tasks.get()
            except queue.Empty:
                continue
            if task is _SENTINEL:
                return
            if task.context.err() is not None:
                continue

            result = self._executor.Execute(task.context, task.config, task.event)
            while True:
                if task.context.err() is not None:
                    break
                try:
                    task.result.put_nowait(result)
                    break
                except queue.Full:
                    time.sleep(0.01)


def WithQueueWorkers(n: int) -> Any:
    """Set the number of worker goroutines. Mirrors hooks.WithQueueWorkers."""

    def opt(q: HookQueue) -> None:
        q._workers = n

    return opt


def WithQueueExecutor(e: HookExecutor) -> Any:
    """Set a custom executor. Mirrors hooks.WithQueueExecutor."""

    def opt(q: HookQueue) -> None:
        q._executor = e

    return opt


def WithQueueBuffer(n: int) -> Any:
    """Set the task queue buffer size. Mirrors hooks.WithQueueBuffer."""

    def opt(q: HookQueue) -> None:
        if n > 0:
            q._tasks = queue.Queue(maxsize=n)

    return opt


def NewHookQueue(*opts: Any) -> HookQueue:
    """Create a new hook queue with a worker pool. Mirrors hooks.NewHookQueue."""
    q = HookQueue(
        tasks=queue.Queue(maxsize=100),
        workers=4,
        executor=NewHookExecutor(),
        started_at=datetime.now(),
    )
    for opt in opts:
        opt(q)
    return q


class LogLevel(IntEnum):
    """Represents the log severity level. Mirrors hooks.LogLevel."""

    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3

    def string(self) -> str:
        """Return the level name. Mirrors LogLevel.String()."""
        names = ("debug", "info", "warn", _STR_ERROR)
        if int(self) < len(names):
            return names[int(self)]
        return _STR_UNKNOWN


LogLevelDebug = LogLevel.DEBUG
LogLevelInfo = LogLevel.INFO
LogLevelWarn = LogLevel.WARN
LogLevelError = LogLevel.ERROR


@dataclass
class HookLogEntry:
    """Represents a single hook execution log entry. Mirrors hooks.HookLogEntry."""

    timestamp: datetime = field(default_factory=datetime.now)
    level: LogLevel = LogLevelDebug
    hook_id: str = ""
    hook_type: HookType = PreToolUse
    event: HookEvent = field(default_factory=HookEvent)
    result: HookResult = field(default_factory=HookResult)
    duration: timedelta = timedelta(0)
    attempt: int = 0
    error: str = ""
    metadata: dict[str, str] | None = None


def _entry_dump(entry: HookLogEntry) -> dict[str, Any]:
    d: dict[str, Any] = {
        "timestamp": _go_time_fmt(entry.timestamp),
        "level": int(entry.level),
        "hook_id": entry.hook_id,
        "hook_type": int(entry.hook_type),
        "event": _evt_dump(entry.event),
        "result": _result_dump(entry.result),
        "duration": _td_ns(entry.duration),
        "attempt": entry.attempt,
    }
    if entry.error:
        d["error"] = entry.error
    if entry.metadata:
        d["metadata"] = entry.metadata
    return d


@dataclass
class TypeMetrics:
    """Per-type execution metrics. Mirrors hooks.TypeMetrics."""

    count: int = 0
    success: int = 0
    failure: int = 0
    total_dur: timedelta = timedelta(0)


@dataclass
class HookMetricsEntry:
    """Per-hook execution metrics. Mirrors hooks.HookMetricsEntry."""

    id: str = ""
    type: HookType = PreToolUse
    count: int = 0
    success: int = 0
    failure: int = 0
    total_dur: timedelta = timedelta(0)
    avg_dur: timedelta = timedelta(0)
    last_exec: datetime = field(default_factory=datetime.now)
    last_result: HookResult = field(default_factory=HookResult)


class HookMetrics:
    """Holds aggregated hook execution metrics. Mirrors hooks.HookMetrics."""

    def __init__(self) -> None:
        self._mu = threading.RLock()
        self._total_executions = 0
        self._success_count = 0
        self._failure_count = 0
        self._total_duration = timedelta(0)
        self._by_type: dict[HookType, TypeMetrics] = {}
        self._by_hook: dict[str, HookMetricsEntry] = {}


@dataclass
class TypeMetricsSnapshot:
    """Read-only snapshot of type metrics. Mirrors hooks.TypeMetricsSnapshot."""

    count: int = 0
    success: int = 0
    failure: int = 0
    total_dur: timedelta = timedelta(0)
    avg_dur: timedelta = timedelta(0)


@dataclass
class HookMetricsEntrySnapshot:
    """Read-only snapshot of hook metrics. Mirrors hooks.HookMetricsEntrySnapshot."""

    id: str = ""
    type: HookType = PreToolUse
    count: int = 0
    success: int = 0
    failure: int = 0
    total_dur: timedelta = timedelta(0)
    avg_dur: timedelta = timedelta(0)
    last_exec: datetime = field(default_factory=datetime.now)


@dataclass
class HookMetricsSnapshot:
    """Read-only snapshot of metrics. Mirrors hooks.HookMetricsSnapshot."""

    total_executions: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_duration: timedelta = timedelta(0)
    by_type: dict[HookType, TypeMetricsSnapshot] = field(default_factory=dict)
    by_hook: dict[str, HookMetricsEntrySnapshot] = field(default_factory=dict)


class _DiscardWriter:
    """Writer that discards output. Mirrors io.Discard."""

    def write(self, s: str) -> int:
        return len(s)


class HookLogger:
    """Handles structured logging and metrics. Mirrors hooks.HookLogger."""

    def __init__(self, output: TextIO | None, level: LogLevel) -> None:
        self._mu = threading.Lock()
        self._output: Any = output if output is not None else _DiscardWriter()
        self._level = level
        self._metrics = HookMetrics()
        self._entries: list[HookLogEntry] = []
        self._max_entries = 1000
        self._closed = False
        self._hooks: list[Any] = []

    def SetLevel(self, level: LogLevel) -> None:
        """Set the minimum log level. Mirrors hooks.SetLevel."""
        with self._mu:
            self._level = level

    def AddHook(self, fn: Any) -> None:
        """Add a callback for log entries. Mirrors hooks.AddHook."""
        with self._mu:
            self._hooks.append(fn)

    def Log(self, entry: HookLogEntry) -> None:
        """Log a hook execution entry. Mirrors hooks.Log."""
        with self._mu:
            if self._closed:
                return
            if entry.level < self._level:
                return

            self._entries.append(entry)
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[1:]

            self._update_metrics(entry)
            self._write_entry(entry)
            for h in self._hooks:
                h(entry)

    def _write_entry(self, entry: HookLogEntry) -> None:
        try:
            data = json.dumps(_entry_dump(entry), separators=(",", ":"))
        except (ValueError, TypeError):
            data = "{}"
        self._output.write(data + "\n")

    def _update_metrics(self, entry: HookLogEntry) -> None:
        m = self._metrics
        m._total_executions += 1
        if entry.result.success:
            m._success_count += 1
        else:
            m._failure_count += 1

        with m._mu:
            m._total_duration += entry.duration

            tm = m._by_type.get(entry.hook_type)
            if tm is None:
                tm = TypeMetrics()
                m._by_type[entry.hook_type] = tm
            tm.count += 1
            if entry.result.success:
                tm.success += 1
            else:
                tm.failure += 1
            tm.total_dur += entry.duration

            hme = m._by_hook.get(entry.hook_id)
            if hme is None:
                hme = HookMetricsEntry(id=entry.hook_id, type=entry.hook_type)
                m._by_hook[entry.hook_id] = hme
            hme.count += 1
            if entry.result.success:
                hme.success += 1
            else:
                hme.failure += 1
            hme.total_dur += entry.duration
            hme.avg_dur = hme.total_dur / max(hme.count, 1)
            hme.last_exec = entry.timestamp
            hme.last_result = entry.result

    def Metrics(self) -> HookMetricsSnapshot:
        """Return a snapshot of current metrics. Mirrors hooks.Metrics."""
        m = self._metrics
        with m._mu:
            by_type: dict[HookType, TypeMetricsSnapshot] = {}
            for k, v in m._by_type.items():
                by_type[k] = TypeMetricsSnapshot(
                    count=v.count,
                    success=v.success,
                    failure=v.failure,
                    total_dur=v.total_dur,
                    avg_dur=v.total_dur / max(v.count, 1),
                )
            by_hook: dict[str, HookMetricsEntrySnapshot] = {}
            for hook_key, metrics_entry in m._by_hook.items():
                by_hook[hook_key] = HookMetricsEntrySnapshot(
                    id=metrics_entry.id,
                    type=metrics_entry.type,
                    count=metrics_entry.count,
                    success=metrics_entry.success,
                    failure=metrics_entry.failure,
                    total_dur=metrics_entry.total_dur,
                    avg_dur=metrics_entry.avg_dur,
                    last_exec=metrics_entry.last_exec,
                )
            return HookMetricsSnapshot(
                total_executions=m._total_executions,
                success_count=m._success_count,
                failure_count=m._failure_count,
                total_duration=m._total_duration,
                by_type=by_type,
                by_hook=by_hook,
            )

    def RecentEntries(self, n: int) -> list[HookLogEntry]:
        """Return the most recent log entries. Mirrors hooks.RecentEntries."""
        with self._mu:
            if n <= 0 or n > len(self._entries):
                n = len(self._entries)
            start = len(self._entries) - n
            return list(self._entries[start:])

    def Close(self) -> None:
        """Close the logger. Mirrors hooks.Close."""
        with self._mu:
            self._closed = True

    def LogHookExecution(
        self,
        ctx: _Context,
        config: HookConfig,
        event: HookEvent,
        result: HookResult,
        attempt: int,
    ) -> None:
        """Log a hook execution conveniently. Mirrors hooks.LogHookExecution."""
        del ctx
        level = LogLevelInfo
        if not result.success:
            level = LogLevelError
        elif result.duration > timedelta(seconds=5):
            level = LogLevelWarn

        entry = HookLogEntry(
            timestamp=datetime.now(),
            level=level,
            hook_id=config.id,
            hook_type=config.type,
            event=event,
            result=result,
            duration=result.duration,
            attempt=attempt,
        )
        if result.error != "":
            entry.error = result.error

        self.Log(entry)


def NewHookLogger(output: TextIO | None, level: LogLevel) -> HookLogger:
    """Create a new hook logger. Mirrors hooks.NewHookLogger."""
    return HookLogger(output, level)
