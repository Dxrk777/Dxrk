# SPDX-License-Identifier: MIT
"""Hook pattern matching and registry."""

from __future__ import annotations

import re as _re
import threading
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from dxrk.utils.hooks_exec import _background, _Context
from dxrk.utils.hooks_model import (
    ErrDuplicateHookID,
    ErrInvalidConfig,
    ErrRegistryClosed,
    HookConfig,
    HookError,
    HookEvent,
    HookMatch,
    HookType,
)


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
    return HookDefaults(timeout=timedelta(seconds=30), max_retries=3, retry_delay=timedelta(seconds=1))


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
