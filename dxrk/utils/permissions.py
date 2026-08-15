# SPDX-License-Identifier: MIT
"""Permission management, policy evaluation, and access control utilities.

Implements a multi-layered permission system: a rule-based policy engine with
conditions/priorities, a 5-layer policy hierarchy (Organization > Project >
User > Session > Default), a thread-safe TTL/LRU permission cache with disk
persistence, tool/resource classification with risk assessment, and a
ring-buffer audit trail with query, export, and streaming.

Concurrency mapping:

* ``time.Time`` -> ``datetime`` (UTC; zero time is ``_ZERO_TIME``)
* ``time.Duration`` -> ``datetime.timedelta``
* ``sync.RWMutex`` -> ``threading.RLock`` (``sync.Mutex`` -> ``threading.Lock``)
* channels -> ``queue.Queue``

Fidelity notes (mirrored intentionally, including upstream quirks):

* ``ParseAction``/``ParseOperator`` are case-insensitive.
* ``Operator`` strings are ``eq``/``neq``/``glob``/``regex``/``in``/``gt``/``lt``;
  ``Condition.operator`` is a string parsed at evaluation time, and an invalid
  operator fails the condition.
* ``EvalContext.fieldValue`` lowercases field names, accepts the aliases
  ``tool``/``dir``, and falls back to ``env_vars`` then ``metadata``.
* ``matchesRule`` matches ``rule.resource`` against BOTH the tool name and the
  resource value.
* ``PolicyEngine.Evaluate`` with ``Strategy.FirstMatch`` returns the matching
  rule with the highest priority; ``MostRestrictive`` returns the first
  matching rule alongside the most restrictive action.
* ``PolicyEngine.Merge`` appends every rule from the other engine (no dedup).
* ``NewPolicyEngine``/``UnmarshalPolicyJSON`` default a zero strategy to
  ``FirstMatch``.
* Policy JSON mirrors the original json tags exactly: lowercase keys (``name``/
  ``version``/``rules``/``default_action``/``strategy``, rule fields
  ``id``/``subject``/``resource``/``action``/``conditions``/``priority``,
  ``conditions`` omitted when empty) and actions/strategies serialized as ints.
  The layered-policy wrapper uses capitalized ``Layer``/``Policy`` keys because
  the original ``LayerPolicy`` struct has no json tags.
* ``_policy_from_dict`` returns an empty ``Policy()`` when ``rules`` is not a
  list, and drops non-dict entries defensively (JSON may carry ``null``).
* ``LayeredPolicy.Evaluate`` falls through Ask results and returns Ask with
  layer ``"none"`` when no layer decides; ``LayeredPolicy`` is not internally
  synchronized.
* ``LayerMerge`` takes rule slices (not policies), de-duplicates by ID with
  override precedence, and sorts by priority descending.
* ``AuditLog.ExportJSON`` appends a trailing newline (as ``json.Encoder``).
* ``AuditStreamer.Close`` marks the streamer closed; later ``Send`` calls are
  no-ops (the original would panic sending on a closed channel).
* ``AuditFilter.min_risk_level`` only applies when the entry records a risk
  level; ``PermissionCache.Purge`` returns the number of removed entries.
* ``CacheKey`` is the hex of the first 16 bytes of the SHA-256 digest.
"""

from __future__ import annotations

import csv
import hashlib
import json
import operator
import os
import queue
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Any, TextIO, cast

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


# ---- Policy Engine ----


def _match_glob(pattern: str, s: str) -> bool:
    """Simple glob matching (* and ?). Mirrors permissions.matchGlob."""
    pi, si = 0, 0
    star_pi, star_si = -1, -1

    while si < len(s):
        if pi < len(pattern) and (pattern[pi] == "?" or pattern[pi] == s[si]):
            pi += 1
            si += 1
            continue
        if pi < len(pattern) and pattern[pi] == "*":
            star_pi = pi
            star_si = si
            pi += 1
            continue
        if star_pi >= 0:
            pi = star_pi + 1
            star_si += 1
            si = star_si
            continue
        return False

    while pi < len(pattern) and pattern[pi] == "*":
        pi += 1
    return pi == len(pattern)


def _match_field(pattern: str, value: str) -> bool:
    """Match a field value against a pattern. Mirrors permissions.matchField."""
    if pattern == "" or pattern == "*":
        return True
    return _match_glob(pattern, value)


class PolicyEngine:
    """Evaluates rules against contexts. Mirrors permissions.PolicyEngine."""

    def __init__(self, p: Policy) -> None:
        if p.strategy == 0:
            p = Policy(
                name=p.name,
                version=p.version,
                rules=p.rules,
                default_action=p.default_action,
                strategy=Strategy.FirstMatch,
            )
        self._mu = threading.RLock()
        self._policy = p
        self._compiled: dict[str, re.Pattern[str]] = {}

    def Evaluate(
        self, ctx: EvalContext
    ) -> tuple[Action, Rule | None, Exception | None]:
        """Evaluate all rules against the context."""
        with self._mu:
            matches: list[Rule] = []
            for rule in self._policy.rules:
                if self._matches_rule(rule, ctx):
                    matches.append(rule)

            if not matches:
                return self._policy.default_action, None, None

            if self._policy.strategy == Strategy.MostRestrictive:
                return self._most_restrictive(matches), matches[0], None

            best = matches[0]
            for m in matches[1:]:
                if m.priority > best.priority:
                    best = m
            return best.action, best, None

    def _most_restrictive(self, rules: list[Rule]) -> Action:
        best = Action.Allow
        for r in rules:
            if r.action == Action.Deny:
                return Action.Deny
            if r.action == Action.Ask and best == Action.Allow:
                best = Action.Ask
        return best

    def AddRule(self, rule: Rule) -> None:
        """Append a rule to the policy."""
        with self._mu:
            self._policy.rules.append(rule)

    def RemoveRule(self, rule_id: str) -> bool:
        """Remove a rule by ID."""
        with self._mu:
            for i, r in enumerate(self._policy.rules):
                if r.id == rule_id:
                    del self._policy.rules[i]
                    return True
        return False

    def GetRules(self) -> list[Rule]:
        """Return a copy of all rules."""
        with self._mu:
            return list(self._policy.rules)

    def Merge(self, other: PolicyEngine) -> None:
        """Combine rules from another engine into this one (no dedup)."""
        other_rules = other.GetRules()
        with self._mu:
            self._policy.rules.extend(other_rules)

    def Validate(self) -> Exception | None:
        """Check for empty IDs and duplicate rule IDs."""
        with self._mu:
            seen: dict[str, int] = {}
            for i, r in enumerate(self._policy.rules):
                if r.id == "":
                    return Exception(f"rule at index {i} has empty ID")
                prev = seen.get(r.id)
                if prev is not None:
                    return Exception(
                        f"duplicate rule ID {json.dumps(r.id)} at indices {prev} and {i}"
                    )
                seen[r.id] = i
        return None

    def Policy(self) -> Policy:
        """Return a copy of the underlying policy."""
        with self._mu:
            return Policy(
                name=self._policy.name,
                version=self._policy.version,
                rules=list(self._policy.rules),
                default_action=self._policy.default_action,
                strategy=self._policy.strategy,
            )

    # ---- Rule matching ----

    def _matches_rule(self, r: Rule, ctx: EvalContext) -> bool:
        if not _match_field(r.subject, ctx.user):
            return False
        if not _match_field(r.resource, ctx.tool_name) and not _match_field(
            r.resource, ctx.resource
        ):
            return False
        for cond in r.conditions:
            if not self._eval_condition(cond, ctx):
                return False
        return True

    def _eval_condition(self, c: Condition, ctx: EvalContext) -> bool:
        val = ctx.fieldValue(c.field)
        op, err = ParseOperator(c.operator)
        if err is not None:
            return False

        if op == Operator.OpEq:
            return val == c.value
        if op == Operator.OpNeq:
            return val != c.value
        if op == Operator.OpGlob:
            return _match_glob(c.value, val)
        if op == Operator.OpRegex:
            return self._eval_regex(c.value, val)
        if op == Operator.OpIn:
            for item in c.value.split(","):
                if item.strip() == val:
                    return True
            return False
        if op == Operator.OpGt:
            return val > c.value
        if op == Operator.OpLt:
            return val < c.value
        return False

    def _eval_regex(self, pattern: str, value: str) -> bool:
        re_pat = self._compiled.get(pattern)
        if re_pat is not None:
            return re_pat.search(value) is not None
        try:
            re_pat = re.compile(pattern)
        except re.error:
            return False
        self._compiled[pattern] = re_pat
        return re_pat.search(value) is not None


def NewPolicyEngine(p: Policy) -> PolicyEngine:
    """Create an engine from a policy. Mirrors permissions.NewPolicyEngine."""
    return PolicyEngine(p)


# ---- Serialization ----


def _policy_to_dict(p: Policy) -> dict[str, object]:
    return {
        "name": p.name,
        "version": p.version,
        "rules": [
            {
                "id": r.id,
                "subject": r.subject,
                "resource": r.resource,
                "action": int(r.action),
                **(
                    {
                        "conditions": [
                            {"field": c.field, "operator": c.operator, "value": c.value}
                            for c in r.conditions
                        ]
                    }
                    if r.conditions
                    else {}
                ),
                "priority": r.priority,
            }
            for r in p.rules
        ],
        "default_action": int(p.default_action),
        "strategy": int(p.strategy),
    }


def _policy_from_dict(d: dict[str, object]) -> Policy:
    rules_raw = d.get("rules", [])
    rules: list[Rule] = []
    if not isinstance(rules_raw, list):
        return Policy()
    for rd in rules_raw:
        if not isinstance(rd, dict):
            continue
        conds_raw = rd.get("conditions", [])
        conds: list[Condition] = []
        if isinstance(conds_raw, list):
            for cd in conds_raw:
                if isinstance(cd, dict):
                    conds.append(
                        Condition(
                            field=str(cd.get("field", "")),
                            operator=str(cd.get("operator", "eq")),
                            value=str(cd.get("value", "")),
                        )
                    )
        rules.append(
            Rule(
                id=str(rd.get("id", "")),
                subject=str(rd.get("subject", "")),
                resource=str(rd.get("resource", "")),
                action=Action(_as_int(rd.get("action", 0))),
                conditions=conds,
                priority=_as_int(rd.get("priority", 0)),
            )
        )
    strategy = Strategy(_as_int(d.get("strategy", 0)))
    if strategy == 0:
        strategy = Strategy.FirstMatch
    return Policy(
        name=str(d.get("name", "")),
        version=str(d.get("version", "")),
        rules=rules,
        default_action=Action(_as_int(d.get("default_action", 0))),
        strategy=strategy,
    )


def MarshalPolicyJSON(p: Policy) -> tuple[str | None, Exception | None]:
    """Serialize a policy to JSON bytes. Mirrors permissions.MarshalPolicyJSON."""
    return json.dumps(_policy_to_dict(p), indent=2), None


def UnmarshalPolicyJSON(data: str | bytes) -> tuple[Policy | None, Exception | None]:
    """Deserialize a policy from JSON bytes. Mirrors permissions.UnmarshalPolicyJSON."""
    try:
        d = json.loads(data)
    except (json.JSONDecodeError, TypeError) as ex:
        return None, Exception(f"unmarshal policy: {ex}")
    if not isinstance(d, dict):
        return None, Exception("unmarshal policy: invalid JSON payload")
    return _policy_from_dict(d), None


def LoadPolicyFile(path: str) -> tuple[Policy | None, Exception | None]:
    """Read and parse a policy from a JSON file."""
    try:
        with open(path, encoding="utf-8") as f:
            data = f.read()
    except OSError as ex:
        return None, Exception(f"read policy file {json.dumps(path)}: {ex}")
    return UnmarshalPolicyJSON(data)


def SavePolicyFile(p: Policy, path: str) -> Exception | None:
    """Write a policy to a JSON file."""
    data, err = MarshalPolicyJSON(p)
    if err is not None:
        return err
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(data or "")
    except OSError as ex:
        return Exception(f"write policy file {json.dumps(path)}: {ex}")
    return None


# ---- Layer Definitions ----


class Layer(IntEnum):
    """A permission source layer with evaluation priority."""

    LayerDefault = 0
    LayerSession = 1
    LayerUser = 2
    LayerProject = 3
    LayerOrganization = 4

    def String(self) -> str:
        if self == Layer.LayerDefault:
            return "default"
        if self == Layer.LayerSession:
            return "session"
        if self == Layer.LayerUser:
            return "user"
        if self == Layer.LayerProject:
            return _STR_PROJECT
        if self == Layer.LayerOrganization:
            return "organization"
        return _STR_UNKNOWN

    @classmethod
    def _missing_(cls, value: object) -> Layer:
        """Support arbitrary integer values, like type conversion."""
        return cast(Layer, _anonymous_enum_member(cls, value))

    def Priority(self) -> int:
        """Return the numeric priority (higher = evaluated first)."""
        return int(self)


@dataclass
class LayerPolicy:
    """Associates rules with a specific layer."""

    layer: Layer = Layer.LayerDefault
    policy: Policy = field(default_factory=Policy)


def _default_policy() -> Policy:
    return Policy(
        name="default",
        version="1.0",
        default_action=Action.Ask,
        strategy=Strategy.FirstMatch,
        rules=[
            Rule(
                id="default-read",
                subject="*",
                resource="Read",
                action=Action.Allow,
                priority=0,
            ),
            Rule(
                id="default-glob",
                subject="*",
                resource="Glob",
                action=Action.Allow,
                priority=0,
            ),
            Rule(
                id="default-grep",
                subject="*",
                resource="Grep",
                action=Action.Allow,
                priority=0,
            ),
            Rule(
                id="default-ls",
                subject="*",
                resource="LS",
                action=Action.Allow,
                priority=0,
            ),
            Rule(
                id="default-bash",
                subject="*",
                resource="Bash",
                action=Action.Ask,
                priority=0,
            ),
        ],
    )


class LayeredPolicy:
    """Manages rules across multiple ordered layers. Mirrors permissions.LayeredPolicy."""

    def __init__(self) -> None:
        self.layers: list[LayerPolicy] = [
            LayerPolicy(layer=Layer.LayerDefault, policy=_default_policy())
        ]
        self.fallback: Policy = _default_policy()

    def Evaluate(
        self, ctx: EvalContext
    ) -> tuple[Action, Rule | None, str, Exception | None]:
        """Evaluate all layers from highest to lowest priority.

        Returns the first definitive action (Allow/Deny). If all layers return
        Ask, Ask is returned with layer ``"none"``.
        """
        for lp_entry in self._sorted_layers():
            engine = NewPolicyEngine(lp_entry.policy)
            action, rule, err = engine.Evaluate(ctx)
            if err is not None:
                return (
                    Action.Ask,
                    None,
                    lp_entry.layer.String(),
                    Exception(f"evaluate layer {lp_entry.layer.String()}: {err}"),
                )
            if action == Action.Deny:
                return Action.Deny, rule, lp_entry.layer.String(), None
            if action == Action.Allow:
                return Action.Allow, rule, lp_entry.layer.String(), None
        return Action.Ask, None, "none", None

    def _sorted_layers(self) -> list[LayerPolicy]:
        return sorted(self.layers, key=lambda lp: lp.layer.Priority(), reverse=True)

    def AddLayer(self, layer: Layer, p: Policy) -> None:
        """Add or replace a layer."""
        for i, entry in enumerate(self.layers):
            if entry.layer == layer:
                self.layers[i] = LayerPolicy(layer=layer, policy=p)
                return
        self.layers.append(LayerPolicy(layer=layer, policy=p))

    def RemoveLayer(self, layer: Layer) -> None:
        """Remove a layer by kind."""
        for i, entry in enumerate(self.layers):
            if entry.layer == layer:
                del self.layers[i]
                return

    def Layers(self) -> list[LayerPolicy]:
        """Return all configured layers."""
        return list(self.layers)


def NewLayeredPolicy() -> LayeredPolicy:
    """Create a layered policy with default configuration."""
    return LayeredPolicy()


# ---- Layer Merge ----


def LayerMerge(base: list[Rule], override: list[Rule]) -> list[Rule]:
    """Merge rules from base and override, with override taking precedence
    on duplicate IDs. Sorted by priority descending."""
    by_id: dict[str, Rule] = {}
    for r in base:
        by_id[r.id] = r
    for r in override:
        by_id[r.id] = r
    result = list(by_id.values())
    result.sort(key=lambda r: -r.priority)
    return result


# ---- File Loading ----


def LoadProjectPolicy(directory: str) -> tuple[Policy | None, Exception | None]:
    """Load a policy from a ``.dxrk/policies/`` directory. Reads all JSON files
    and merges them."""
    policy_dir = os.path.join(directory, ".dxrk", "policies")
    try:
        entries = sorted(os.listdir(policy_dir))
    except FileNotFoundError:
        return (
            Policy(
                name=_STR_PROJECT,
                default_action=Action.Ask,
                strategy=Strategy.FirstMatch,
            ),
            None,
        )
    except OSError as ex:
        return None, Exception(f"read project policies dir: {ex}")

    merged = Policy(
        name=_STR_PROJECT,
        version="1.0",
        default_action=Action.Ask,
        strategy=Strategy.FirstMatch,
    )

    for name in entries:
        path = os.path.join(policy_dir, name)
        if not os.path.isfile(path) or os.path.splitext(name)[1] != ".json":
            continue
        p, err = LoadPolicyFile(path)
        if err is not None:
            return None, Exception(f"load project policy {json.dumps(path)}: {err}")
        if p is None:
            continue
        merged.rules.extend(p.rules)
        if p.default_action == Action.Deny:
            merged.default_action = Action.Deny

    return merged, None


def LoadUserPolicy(config_dir: str) -> tuple[Policy | None, Exception | None]:
    """Load a policy from the user's config directory."""
    path = os.path.join(config_dir, "permissions", "policy.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = f.read()
    except FileNotFoundError:
        return (
            Policy(
                name="user",
                default_action=Action.Ask,
                strategy=Strategy.FirstMatch,
            ),
            None,
        )
    except OSError as ex:
        return None, Exception(f"load user policy: {ex}")
    return UnmarshalPolicyJSON(data)


def MarshalLayeredPolicyJSON(lp: LayeredPolicy) -> tuple[str | None, Exception | None]:
    """Serialize a layered policy to JSON."""
    return (
        json.dumps(
            [
                {"Layer": int(e.layer), "Policy": _policy_to_dict(e.policy)}
                for e in lp.Layers()
            ],
            indent=2,
        ),
        None,
    )


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


# ---- Audit Entry / Filter ----


@dataclass
class AuditEntry:
    """Records a single permission decision."""

    timestamp: datetime = _ZERO_TIME
    tool: str = ""
    resource: str = ""
    action: Action = Action.Allow
    rule_id: str = ""
    layer: str = ""
    user: str = ""
    risk_level: str = ""
    details: str = ""


@dataclass
class AuditFilter:
    """Defines query criteria for audit entries."""

    from_: datetime = _ZERO_TIME
    to: datetime = _ZERO_TIME
    tool: str = ""
    action: Action | None = None
    min_risk_level: RiskLevel = RiskLevel.Low


def _parse_risk_level(s: str) -> RiskLevel:
    if s == "low":
        return RiskLevel.Low
    if s == _STR_MEDIUM:
        return RiskLevel.Medium
    if s == "high":
        return RiskLevel.High
    if s == _STR_CRITICAL:
        return RiskLevel.Critical
    return RiskLevel.Low


# ---- Audit Log ----


class AuditLog:
    """A thread-safe ring-buffer audit trail. Mirrors permissions.AuditLog."""

    def __init__(self, max_entries: int) -> None:
        if max_entries <= 0:
            max_entries = 4096
        self._mu = threading.RLock()
        self._entries: list[AuditEntry] = [AuditEntry() for _ in range(max_entries)]
        self._max_entries = max_entries
        self._head = 0
        self._full = False

    def Log(self, entry: AuditEntry) -> None:
        """Append an audit entry to the ring buffer."""
        with self._mu:
            if _is_zero(entry.timestamp):
                entry.timestamp = _now()
            self._entries[self._head] = entry
            self._head = (self._head + 1) % self._max_entries
            if self._head == 0:
                self._full = True

    def Query(self, filter_: AuditFilter) -> list[AuditEntry]:
        """Return entries matching the filter, ordered oldest to newest."""
        with self._mu:
            count = self._max_entries if self._full else self._head
            result: list[AuditEntry] = []
            for i in range(count):
                idx = (self._head + i) % self._max_entries if self._full else i
                entry = self._entries[idx]
                if self._matches_filter(entry, filter_):
                    result.append(entry)
            return result

    def _matches_filter(self, entry: AuditEntry, f: AuditFilter) -> bool:
        if not _is_zero(f.from_) and entry.timestamp < f.from_:
            return False
        if not _is_zero(f.to) and entry.timestamp > f.to:
            return False
        if f.tool != "" and entry.tool != f.tool:
            return False
        if f.action is not None and entry.action != f.action:
            return False
        if f.min_risk_level > RiskLevel.Low and entry.risk_level != "":
            level = _parse_risk_level(entry.risk_level)
            if level < f.min_risk_level:
                return False
        return True

    def Len(self) -> int:
        """Return the number of stored entries."""
        with self._mu:
            if self._full:
                return self._max_entries
            return self._head

    def _ordered_entries(self) -> list[AuditEntry]:
        count = self._max_entries if self._full else self._head
        result: list[AuditEntry] = []
        for i in range(count):
            idx = (self._head + i) % self._max_entries if self._full else i
            result.append(self._entries[idx])
        return result

    def ExportJSON(self, w: TextIO) -> Exception | None:
        """Write all entries as a JSON array to w (trailing newline included)."""
        with self._mu:
            entries = self._ordered_entries()
        payload = [
            {
                "timestamp": _go_time_fmt(e.timestamp),
                "tool": e.tool,
                "resource": e.resource,
                "action": int(e.action),
                **({"rule_id": e.rule_id} if e.rule_id else {}),
                **({"layer": e.layer} if e.layer else {}),
                **({"user": e.user} if e.user else {}),
                **({"risk_level": e.risk_level} if e.risk_level else {}),
                **({"details": e.details} if e.details else {}),
            }
            for e in entries
        ]
        try:
            w.write(json.dumps(payload, indent=2) + "\n")
        except OSError as ex:
            return Exception(f"encode audit json: {ex}")
        return None

    def ExportCSV(self, w: TextIO) -> Exception | None:
        """Write all entries as CSV to w."""
        with self._mu:
            entries = self._ordered_entries()
        wr = csv.writer(w, lineterminator="\n")
        try:
            wr.writerow(
                [
                    "timestamp",
                    "tool",
                    "resource",
                    "action",
                    "rule_id",
                    "layer",
                    "user",
                    "risk_level",
                    "details",
                ]
            )
            for e in entries:
                wr.writerow(
                    [
                        _rfc3339(e.timestamp),
                        e.tool,
                        e.resource,
                        e.action.String(),
                        e.rule_id,
                        e.layer,
                        e.user,
                        e.risk_level,
                        e.details,
                    ]
                )
        except OSError as ex:
            return Exception(f"write csv row: {ex}")
        return None


def NewAuditLog(max_entries: int) -> AuditLog:
    """Create an audit log with a fixed maximum entry count."""
    return AuditLog(max_entries)


# ---- Streaming ----


class AuditStreamer:
    """Sends entries to a channel as they are logged. Mirrors permissions.AuditStreamer."""

    def __init__(self, buf_size: int = 256) -> None:
        if buf_size <= 0:
            buf_size = 256
        self._ch: queue.Queue[AuditEntry] = queue.Queue(maxsize=buf_size)
        self._dropped = 0
        self._closed = False

    def Channel(self) -> queue.Queue[AuditEntry]:
        """Return the queue of streamed entries."""
        return self._ch

    def Dropped(self) -> int:
        """Return the count of dropped entries (buffer full)."""
        return self._dropped

    def Send(self, entry: AuditEntry) -> None:
        """Push an entry to the streamer. Drops if the buffer is full."""
        if self._closed:
            return
        try:
            self._ch.put_nowait(entry)
        except queue.Full:
            self._dropped += 1

    def Close(self) -> None:
        """Mark the streamer closed; later Send calls are no-ops."""
        self._closed = True


def NewAuditStreamer(buf_size: int = 256) -> AuditStreamer:
    """Create a streamer with a buffered channel."""
    return AuditStreamer(buf_size)


class StreamingAuditLog:
    """Wraps AuditLog and fans out to registered streamers."""

    def __init__(self, max_entries: int) -> None:
        self._log = AuditLog(max_entries)
        self._streamers: list[AuditStreamer] = []
        self._mu = threading.Lock()

    def Log(self, entry: AuditEntry) -> None:
        """Append an entry and broadcast to all streamers."""
        self._log.Log(entry)
        with self._mu:
            for s in self._streamers:
                s.Send(entry)

    def AddStreamer(self, s: AuditStreamer) -> None:
        """Register a streamer for future entries."""
        with self._mu:
            self._streamers.append(s)

    def Query(self, filter_: AuditFilter) -> list[AuditEntry]:
        """Delegate to the underlying audit log."""
        return self._log.Query(filter_)

    def ExportJSON(self, w: TextIO) -> Exception | None:
        """Delegate to the underlying audit log."""
        return self._log.ExportJSON(w)

    def ExportCSV(self, w: TextIO) -> Exception | None:
        """Delegate to the underlying audit log."""
        return self._log.ExportCSV(w)


def NewStreamingAuditLog(max_entries: int) -> StreamingAuditLog:
    """Create a streaming audit log."""
    return StreamingAuditLog(max_entries)


# ---- Permission Cache ----


@dataclass
class CacheEntry:
    """A single cached permission decision."""

    key: str = ""
    action: Action = Action.Allow
    rule_id: str = ""
    expiry: datetime = _ZERO_TIME
    timestamp: datetime = _ZERO_TIME

    def IsExpired(self) -> bool:
        """Report whether the entry has expired."""
        return not _is_zero(self.expiry) and _now() > self.expiry


class PermissionCache:
    """A thread-safe LRU permission cache with TTL. Mirrors permissions.PermissionCache."""

    def __init__(self, ttl: timedelta, max_size: int = 1024) -> None:
        if max_size <= 0:
            max_size = 1024
        self._mu = threading.RLock()
        self._entries: dict[str, CacheEntry] = {}
        self._order: list[str] = []
        self._max_size = max_size
        self._ttl = ttl

    def _touch_locked(self, key: str) -> None:
        for i, k in enumerate(self._order):
            if k == key:
                del self._order[i]
                self._order.append(key)
                return

    def _remove_locked(self, key: str) -> None:
        if key not in self._entries:
            return
        del self._entries[key]
        for i, k in enumerate(self._order):
            if k == key:
                del self._order[i]
                return

    def _evict_oldest_locked(self) -> None:
        if not self._order:
            return
        oldest = self._order[0]
        del self._entries[oldest]
        self._order = self._order[1:]

    def Get(self, key: str) -> tuple[CacheEntry | None, bool]:
        """Retrieve a cache entry by key. Returns (None, False) if missing or expired."""
        with self._mu:
            entry = self._entries.get(key)
            if entry is None:
                return None, False
            if entry.IsExpired():
                self._remove_locked(key)
                return None, False
            self._touch_locked(key)
            return entry, True

    def Set(self, key: str, entry: CacheEntry) -> None:
        """Store a cache entry. Evicts the least recently used entry when full."""
        with self._mu:
            existing = self._entries.get(key)
            if existing is not None:
                self._touch_locked(key)
                entry.timestamp = _now()
                if _is_zero(entry.expiry) and not _is_zero(existing.expiry):
                    entry.expiry = existing.expiry
                self._entries[key] = entry
                return

            while len(self._order) >= self._max_size:
                self._evict_oldest_locked()

            entry.timestamp = _now()
            if _is_zero(entry.expiry) and self._ttl > timedelta(0):
                entry.expiry = _now() + self._ttl
            self._entries[key] = entry
            self._order.append(key)

    def SetWithTTL(self, key: str, entry: CacheEntry, ttl: timedelta) -> None:
        """Store a cache entry with a custom TTL, overriding the default."""
        entry.expiry = _now() + ttl
        self.Set(key, entry)

    def Invalidate(self, key: str) -> None:
        """Remove a single cache entry."""
        with self._mu:
            self._remove_locked(key)

    def InvalidateAll(self) -> None:
        """Clear the entire cache."""
        with self._mu:
            self._entries = {}
            self._order = []

    def Size(self) -> int:
        """Return the number of entries in the cache."""
        with self._mu:
            return len(self._entries)

    def Purge(self) -> int:
        """Remove all expired entries; return the number removed."""
        with self._mu:
            removed = 0
            remaining: list[str] = []
            for key in self._order:
                entry = self._entries.get(key)
                if entry is not None and entry.IsExpired():
                    del self._entries[key]
                    removed += 1
                else:
                    remaining.append(key)
            self._order = remaining
            return removed

    # ---- Disk persistence ----

    def PersistToDisk(self, path: str) -> Exception | None:
        """Write the cache to a JSON file."""
        with self._mu:
            snapshot: list[CacheEntry] = []
            for entry in self._entries.values():
                if not entry.IsExpired():
                    snapshot.append(entry)
        payload = {
            "entries": [
                {
                    "key": e.key,
                    "action": int(e.action),
                    **({"rule_id": e.rule_id} if e.rule_id else {}),
                    "expiry": _go_time_fmt(e.expiry),
                    "timestamp": _go_time_fmt(e.timestamp),
                }
                for e in snapshot
            ]
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(payload, indent=2))
        except OSError as ex:
            return Exception(f"write cache file {json.dumps(path)}: {ex}")
        return None

    def LoadFromDisk(self, path: str) -> Exception | None:
        """Load a cache from a JSON file."""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except OSError as ex:
            return Exception(f"read cache file: {ex}")
        except json.JSONDecodeError as ex:
            return Exception(f"unmarshal cache: {ex}")
        if not isinstance(data, dict):
            return Exception("unmarshal cache: invalid JSON payload")
        entries = data.get("entries", [])
        if not isinstance(entries, list):
            return Exception("unmarshal cache: invalid JSON payload")

        with self._mu:
            for ed in entries:
                if not isinstance(ed, dict):
                    continue
                try:
                    entry = CacheEntry(
                        key=str(ed.get("key", "")),
                        action=Action(int(ed.get("action", 0))),
                        rule_id=str(ed.get("rule_id", "")),
                        expiry=_parse_go_time(str(ed.get("expiry", ""))),
                        timestamp=_parse_go_time(str(ed.get("timestamp", ""))),
                    )
                except (ValueError, TypeError):
                    continue
                if entry.IsExpired():
                    continue
                if len(self._order) >= self._max_size:
                    self._evict_oldest_locked()
                self._entries[entry.key] = entry
                self._order.append(entry.key)
        return None


def NewPermissionCache(ttl: timedelta, max_size: int = 1024) -> PermissionCache:
    """Create a cache with the given TTL and max entries. Use ttl=0 for
    session-only entries (no expiry). MaxSize of 0 defaults to 1024."""
    return PermissionCache(ttl, max_size)


def CacheKey(tool: str, resource: str, extra: str) -> str:
    """Build a cache key from tool, resource, and optional context hash."""
    h = hashlib.sha256()
    h.update(tool.encode("utf-8"))
    h.update(b"\x00")
    h.update(resource.encode("utf-8"))
    if extra != "":
        h.update(b"\x00")
        h.update(extra.encode("utf-8"))
    return h.digest()[:16].hex()
