# SPDX-License-Identifier: MIT
"""Tool framework: registry and builder for LLM-invokable tools. and internal/tools/registry.go. A tool is built
from a ToolDef via build() and registered in a Registry. Lifecycle:
validate -> execute -> (result, error). Execute functions return a tuple of
``(result, error)`` where error is None on success.
"""

from __future__ import annotations

import builtins
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, List, Protocol

ExecuteFn = Callable[[Any, dict[str, Any] | None], tuple[Any, str | None]]
ValidateFn = Callable[[dict[str, Any] | None], str | None]


class ToolError(Exception):
    """Raised when a tool cannot be registered (mirrors tools.ErrDuplicateTool)."""


class Tool:
    """Immutable runtime representation of a tool, created via build()."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        execute: ExecuteFn,
        validate: ValidateFn | None = None,
        is_enabled: bool = True,
        is_read_only: bool = False,
        is_concurrent_safe: bool = False,
    ) -> None:
        self._name = name
        self._description = description
        self._input_schema = input_schema
        self._execute = execute
        self._validate = validate
        self._is_enabled = is_enabled
        self._is_read_only = is_read_only
        self._is_concurrent_safe = is_concurrent_safe

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return self._description

    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    def is_enabled(self) -> bool:
        return self._is_enabled

    def is_read_only(self) -> bool:
        return self._is_read_only

    def is_concurrent_safe(self) -> bool:
        return self._is_concurrent_safe

    def validate(self, input_: dict[str, Any] | None) -> str | None:
        if self._validate is None:
            return None
        return self._validate(input_)

    def execute(
        self, ctx: Any, input_: dict[str, Any] | None
    ) -> tuple[Any, str | None]:
        if not self._is_enabled:
            return None, f'tool "{self._name}" is not enabled'
        err = self.validate(input_)
        if err is not None:
            return None, f'validate "{self._name}": {err}'
        return self._execute(ctx, input_)


@dataclass
class ToolDef:
    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    execute: ExecuteFn | None = None
    validate: ValidateFn | None = None
    is_enabled: bool | None = None
    is_read_only: bool | None = None
    is_concurrent_safe: bool | None = None


def build(def_: ToolDef) -> Tool:
    """Create an immutable Tool from a ToolDef, applying fail-closed defaults."""
    if not def_.name:
        raise ValueError("tool name is required")
    if def_.execute is None:
        raise ValueError(f'tool "{def_.name}": execute function is required')
    return Tool(
        name=def_.name,
        description=def_.description,
        input_schema=def_.input_schema,
        execute=def_.execute,
        validate=def_.validate,
        is_enabled=def_.is_enabled if def_.is_enabled is not None else True,
        is_read_only=def_.is_read_only if def_.is_read_only is not None else False,
        is_concurrent_safe=def_.is_concurrent_safe
        if def_.is_concurrent_safe is not None
        else False,
    )


class Registry:
    """Manages a set of tools"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name() in self._tools:
            raise ToolError(f'tool already registered: "{tool.name()}"')
        self._tools[tool.name()] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return [self._tools[name] for name in sorted(self._tools)]

    def list_enabled(self) -> builtins.list[Tool]:
        return [t for t in self.list() if t.is_enabled()]

    def remove(self, name: str) -> None:
        if name not in self._tools:
            raise ToolError(f'tool not found: "{name}"')
        del self._tools[name]

    def __len__(self) -> int:
        return len(self._tools)


class Condition(Protocol):
    """Determines whether a conditional tool activates for a given input.
    """

    def match(self, input_: dict[str, Any] | None) -> bool: ...

    def description(self) -> str: ...


def _match_path(pattern: str, path: str) -> bool:
    """Replicate filepath.Match: '*' and '?' never cross path separators."""
    i, n = 0, len(pattern)
    parts: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "*":
            parts.append("[^/]*")
        elif c == "?":
            parts.append("[^/]")
        elif c == "[":
            j = i + 1
            if j < n and pattern[j] in "!^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                parts.append(r"\[")
            else:
                inner = pattern[i + 1 : j]
                if inner.startswith("!"):
                    inner = "^" + inner[1:]
                inner = inner.replace("\\", r"\\")
                parts.append("[" + inner + "]")
                i = j
        elif c == "\\":
            if i + 1 < n:
                i += 1
                parts.append(re.escape(pattern[i]))
            else:
                parts.append(re.escape(c))
        else:
            parts.append(re.escape(c))
        i += 1
    return re.fullmatch("".join(parts), path) is not None


def _extract_paths(input_: dict[str, Any] | None) -> list[str]:
    paths: list[str] = []
    if input_ is None:
        return paths
    for key in ("path", "paths", "files"):
        value = input_.get(key)
        if isinstance(value, str):
            paths.append(value)
        elif isinstance(value, list):
            paths.extend(str(v) for v in value)
    return paths


class PathCondition:
    """Activates or deactivates when the input references matching paths."""

    def __init__(self, patterns: list[str], include: bool = True) -> None:
        self._patterns = patterns
        self._include = include

    def match(self, input_: dict[str, Any] | None) -> bool:
        for p in _extract_paths(input_):
            for pattern in self._patterns:
                if _match_path(pattern, p) or _match_path(pattern, os.path.basename(p)):
                    return self._include
        return not self._include

    def description(self) -> str:
        verb = "activates" if self._include else "deactivates"
        return f"{verb} when paths match [{', '.join(self._patterns)}]"


class KeyValueCondition:
    """Activates when input[key] equals value."""

    def __init__(self, key: str, value: str) -> None:
        self._key = key
        self._value = value

    def match(self, input_: dict[str, Any] | None) -> bool:
        if input_ is None or input_.get(self._key) is None:
            return False
        v = input_[self._key]
        if isinstance(v, bool):
            rendered = "true" if v else "false"
        elif isinstance(v, str):
            rendered = v
        else:
            rendered = str(v)
        return rendered == self._value

    def description(self) -> str:
        return f'activates when "{self._key}" = "{self._value}"'


class AlwaysCondition:
    """Always activates."""

    def match(self, input_: dict[str, Any] | None) -> bool:
        return True

    def description(self) -> str:
        return "always active"


class NeverCondition:
    """Never activates."""

    def match(self, input_: dict[str, Any] | None) -> bool:
        return False

    def description(self) -> str:
        return "never active"


class AndCondition:
    """Activates when all sub-conditions match."""

    def __init__(self, conditions: list[Condition]) -> None:
        self._conditions = conditions

    def match(self, input_: dict[str, Any] | None) -> bool:
        return all(c.match(input_) for c in self._conditions)

    def description(self) -> str:
        return "all of: " + " + ".join(c.description() for c in self._conditions)


class OrCondition:
    """Activates when any sub-condition matches."""

    def __init__(self, conditions: list[Condition]) -> None:
        self._conditions = conditions

    def match(self, input_: dict[str, Any] | None) -> bool:
        return any(c.match(input_) for c in self._conditions)

    def description(self) -> str:
        return "any of: " + " | ".join(c.description() for c in self._conditions)


def with_condition(def_: ToolDef, condition: Condition) -> ToolDef:
    """Attach a condition to a tool definition (no-op on the definition)."""
    return def_


class ConditionalTool:
    """Wraps a Tool with a condition controlling activation."""

    def __init__(self, tool: Tool, condition: Condition) -> None:
        self._tool = tool
        self._condition = condition

    def is_active(self, input_: dict[str, Any] | None) -> bool:
        return self._condition.match(input_)

    def description(self) -> str:
        return (
            f"{self._tool.description()} [condition: {self._condition.description()}]"
        )

    def name(self) -> str:
        return self._tool.name()

    def is_enabled(self) -> bool:
        return self._tool.is_enabled()

    def is_read_only(self) -> bool:
        return self._tool.is_read_only()

    def is_concurrent_safe(self) -> bool:
        return self._tool.is_concurrent_safe()

    def input_schema(self) -> dict[str, Any]:
        return self._tool.input_schema()

    def validate(self, input_: dict[str, Any] | None) -> str | None:
        return self._tool.validate(input_)

    def execute(
        self, ctx: Any, input_: dict[str, Any] | None
    ) -> tuple[Any, str | None]:
        return self._tool.execute(ctx, input_)


def filter_active(tools: list[Tool], input_: dict[str, Any] | None) -> list[Tool]:
    """Return tools that are enabled (mirrors tools.FilterActive)."""
    return [t for t in tools if t.is_enabled()]


def filter_conditional_active(
    tools: list[ConditionalTool], input_: dict[str, Any] | None
) -> list[ConditionalTool]:
    """Return conditional tools whose condition matches (mirrors FilterConditionalActive)."""
    return [t for t in tools if t.is_active(input_)]
