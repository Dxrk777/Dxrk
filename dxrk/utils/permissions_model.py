# SPDX-License-Identifier: MIT

"""Permission model: actions, operators, strategies, conditions, rules, and policy types."""

from __future__ import annotations

import json
import operator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any, cast

# Mirrors dxrk/strconst constants.
_STR_UNKNOWN = "unknown"
_STR_MEDIUM = "medium"
_STR_CRITICAL = "critical"
_STR_WRITE = "Write"
_STR_EXECUTE = "Execute"
_STR_LISTFILES = "ListFiles"
_STR_WEBFETCH = "WebFetch"
_STR_WEBSEARCH = "WebSearch"
_STR_TODOREAD = "TodoRead"
_STR_FORMAT = "format"
_STR_PROJECT = "project"

_ZERO_TIME = datetime.fromtimestamp(0, tz=UTC)


def _now() -> datetime:
    """Return the current UTC time. Mirrors time.Now()."""
    return datetime.now(UTC)


def _is_zero(dt: datetime) -> bool:
    """Return True for a zero (unset) time. Mirrors time.Time.IsZero()."""
    return dt == _ZERO_TIME or dt.timestamp() == 0.0


def _go_time_fmt(dt: datetime) -> str:
    """Format a datetime as RFC 3339 nano JSON (UTC, Z)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    micro = dt.microsecond
    if micro == 0:
        return base + "Z"
    frac = str(micro).rstrip("0")
    if not frac:
        return base + "Z"
    return f"{base}.{frac}Z"


def _rfc3339(dt: datetime) -> str:
    """Format a datetime like time.RFC3339."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_go_time(s: str) -> datetime:
    """Parse an RFC3339Nano timestamp; zero time on failure."""
    if not s or s == _go_time_fmt(_ZERO_TIME):
        return _ZERO_TIME
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return _ZERO_TIME


def _as_int(value: object, default: int = 0) -> int:
    """Coerce a JSON-decoded value to an int, falling back to default."""
    if isinstance(value, int):
        return value
    return default


def _anonymous_enum_member(cls: type[IntEnum], value: object) -> Any:
    """Create a pseudo-member with an arbitrary value, like a type cast.

    Enum types accept any int and their ``String()`` methods fall back to
    ``"unknown"`` (or ``"first_match"`` for ``Strategy``); Python's ``IntEnum``
    rejects unknown values, so this constructs the member directly.
    """
    idx = operator.index(value)  # type: ignore[arg-type]
    member = int.__new__(cls, idx)  # type: ignore[arg-type]
    member._name_ = None  # type: ignore[assignment]
    member._value_ = idx
    return member


# ---- Actions ----


class Action(IntEnum):
    """The outcome of a permission evaluation. Mirrors permissions.Action."""

    Allow = 0
    Deny = 1
    Ask = 2

    def String(self) -> str:
        if self == Action.Allow:
            return "allow"
        if self == Action.Deny:
            return "deny"
        if self == Action.Ask:
            return "ask"
        return _STR_UNKNOWN

    @classmethod
    def _missing_(cls, value: object) -> Action:
        """Support arbitrary integer values, like type conversion."""
        return cast(Action, _anonymous_enum_member(cls, value))


def ParseAction(s: str) -> tuple[Action, Exception | None]:
    """Convert a string to an Action. Mirrors permissions.ParseAction."""
    lower = s.lower()
    if lower == "allow":
        return Action.Allow, None
    if lower == "deny":
        return Action.Deny, None
    if lower == "ask":
        return Action.Ask, None
    return Action.Allow, Exception(f"unknown action: {json.dumps(s)}")


# ---- Operators ----


class Operator(IntEnum):
    """A condition comparison operator. Mirrors permissions.Operator."""

    OpEq = 0
    OpNeq = 1
    OpGlob = 2
    OpRegex = 3
    OpIn = 4
    OpGt = 5
    OpLt = 6

    def String(self) -> str:
        if self == Operator.OpEq:
            return "eq"
        if self == Operator.OpNeq:
            return "neq"
        if self == Operator.OpGlob:
            return "glob"
        if self == Operator.OpRegex:
            return "regex"
        if self == Operator.OpIn:
            return "in"
        if self == Operator.OpGt:
            return "gt"
        if self == Operator.OpLt:
            return "lt"
        return _STR_UNKNOWN

    @classmethod
    def _missing_(cls, value: object) -> Operator:
        """Support arbitrary integer values, like type conversion."""
        return cast(Operator, _anonymous_enum_member(cls, value))


def ParseOperator(s: str) -> tuple[Operator, Exception | None]:
    """Convert a string to an Operator. Mirrors permissions.ParseOperator."""
    lower = s.lower()
    if lower == "eq":
        return Operator.OpEq, None
    if lower == "neq":
        return Operator.OpNeq, None
    if lower == "glob":
        return Operator.OpGlob, None
    if lower == "regex":
        return Operator.OpRegex, None
    if lower == "in":
        return Operator.OpIn, None
    if lower == "gt":
        return Operator.OpGt, None
    if lower == "lt":
        return Operator.OpLt, None
    return Operator.OpEq, Exception(f"unknown operator: {json.dumps(s)}")


# ---- Rule Strategy ----


class Strategy(IntEnum):
    """How rules are evaluated. Mirrors permissions.Strategy."""

    FirstMatch = 0
    MostRestrictive = 1

    def String(self) -> str:
        if self == Strategy.FirstMatch:
            return "first_match"
        if self == Strategy.MostRestrictive:
            return "most_restrictive"
        return "first_match"

    @classmethod
    def _missing_(cls, value: object) -> Strategy:
        """Support arbitrary integer values, like type conversion."""
        return cast(Strategy, _anonymous_enum_member(cls, value))


# ---- Conditions / Rules / Context ----


@dataclass
class Condition:
    """A single predicate that must match for a rule to apply."""

    field: str = ""
    operator: str = "eq"
    value: str = ""


@dataclass
class Rule:
    """A single permission rule with subject, resource, action, and conditions."""

    id: str = ""
    subject: str = ""
    resource: str = ""
    action: Action = Action.Allow
    conditions: list[Condition] = field(default_factory=list)
    priority: int = 0


@dataclass
class EvalContext:
    """All state needed for a single permission evaluation."""

    tool_name: str = ""
    resource: str = ""
    user: str = ""
    working_dir: str = ""
    env_vars: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = _ZERO_TIME
    metadata: dict[str, str] = field(default_factory=dict)

    def fieldValue(self, field: str) -> str:
        """Return the value of a named field from the context."""
        lower = field.lower()
        if lower in ("tool_name", "tool"):
            return self.tool_name
        if lower == "resource":
            return self.resource
        if lower == "user":
            return self.user
        if lower in ("working_dir", "dir"):
            return self.working_dir
        if self.env_vars:
            v = self.env_vars.get(field)
            if v is not None:
                return v
        if self.metadata:
            v = self.metadata.get(field)
            if v is not None:
                return v
        return ""


@dataclass
class Policy:
    """A named collection of rules with versioning and a default action."""

    name: str = ""
    version: str = ""
    rules: list[Rule] = field(default_factory=list)
    default_action: Action = Action.Allow
    strategy: Strategy = Strategy.FirstMatch
