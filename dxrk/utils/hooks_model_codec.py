# SPDX-License-Identifier: MIT
"""JSON and time serialization for hook models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from dxrk.utils.hooks_model_events import HookConfig, HookConfigFile, HookEvent, HookMatch, HookResult
from dxrk.utils.hooks_model_types import HookType


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
