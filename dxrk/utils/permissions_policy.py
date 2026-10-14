# SPDX-License-Identifier: MIT

"""Permission policy serialization, layering, merging, and loading."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import IntEnum
from typing import cast

from dxrk.utils.permissions_engine import NewPolicyEngine
from dxrk.utils.permissions_model import (
    _STR_PROJECT,
    _STR_UNKNOWN,
    Action,
    Condition,
    EvalContext,
    Policy,
    Rule,
    Strategy,
    _anonymous_enum_member,
    _as_int,
)

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
                    {"conditions": [{"field": c.field, "operator": c.operator, "value": c.value} for c in r.conditions]}
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


def marshal_policy_json(p: Policy) -> tuple[str | None, Exception | None]:
    """Serialize a policy to JSON bytes. Mirrors permissions.MarshalPolicyJSON."""
    return json.dumps(_policy_to_dict(p), indent=2), None


# Backwards-compatible alias (Go-style name).
MarshalPolicyJSON = marshal_policy_json


def unmarshal_policy_json(data: str | bytes) -> tuple[Policy | None, Exception | None]:
    """Deserialize a policy from JSON bytes. Mirrors permissions.UnmarshalPolicyJSON."""
    try:
        d = json.loads(data)
    except (json.JSONDecodeError, TypeError) as ex:
        return None, Exception(f"unmarshal policy: {ex}")
    if not isinstance(d, dict):
        return None, Exception("unmarshal policy: invalid JSON payload")
    return _policy_from_dict(d), None


# Backwards-compatible alias (Go-style name).
UnmarshalPolicyJSON = unmarshal_policy_json


def load_policy_file(path: str) -> tuple[Policy | None, Exception | None]:
    """Read and parse a policy from a JSON file."""
    try:
        with open(path, encoding="utf-8") as f:
            data = f.read()
    except OSError as ex:
        return None, Exception(f"read policy file {json.dumps(path)}: {ex}")
    return UnmarshalPolicyJSON(data)


# Backwards-compatible alias (Go-style name).
LoadPolicyFile = load_policy_file


def save_policy_file(p: Policy, path: str) -> Exception | None:
    """Write a policy to a JSON file."""
    data, _err = MarshalPolicyJSON(p)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(data or "")
    except OSError as ex:
        return Exception(f"write policy file {json.dumps(path)}: {ex}")
    return None


# Backwards-compatible alias (Go-style name).
SavePolicyFile = save_policy_file


# ---- Layer Definitions ----


class Layer(IntEnum):
    """A permission source layer with evaluation priority."""

    LayerDefault = 0
    LayerSession = 1
    LayerUser = 2
    LayerProject = 3
    LayerOrganization = 4

    def to_string(self) -> str:
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

    # Backwards-compatible alias (Go-style name).
    String = to_string

    @classmethod
    def _missing_(cls, value: object) -> Layer:
        """Support arbitrary integer values, like type conversion."""
        return cast(Layer, _anonymous_enum_member(cls, value))

    def priority(self) -> int:
        """Return the numeric priority (higher = evaluated first)."""
        return int(self)

    # Backwards-compatible alias (Go-style name).
    Priority = priority


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
        self.layers: list[LayerPolicy] = [LayerPolicy(layer=Layer.LayerDefault, policy=_default_policy())]
        self.fallback: Policy = _default_policy()

    def evaluate(self, ctx: EvalContext) -> tuple[Action, Rule | None, str, Exception | None]:
        """Evaluate all layers from highest to lowest priority.

        Returns the first definitive action (Allow/Deny). If all layers return
        Ask, Ask is returned with layer ``"none"``.
        """
        for lp_entry in self._sorted_layers():
            engine = NewPolicyEngine(lp_entry.policy)
            action, rule, _err = engine.Evaluate(ctx)
            if action == Action.Deny:
                return Action.Deny, rule, lp_entry.layer.String(), None
            if action == Action.Allow:
                return Action.Allow, rule, lp_entry.layer.String(), None
        return Action.Ask, None, "none", None

    # Backwards-compatible alias (Go-style name).
    Evaluate = evaluate

    def _sorted_layers(self) -> list[LayerPolicy]:
        return sorted(self.layers, key=lambda lp: lp.layer.Priority(), reverse=True)

    def add_layer(self, layer: Layer, p: Policy) -> None:
        """Add or replace a layer."""
        for i, entry in enumerate(self.layers):
            if entry.layer == layer:
                self.layers[i] = LayerPolicy(layer=layer, policy=p)
                return
        self.layers.append(LayerPolicy(layer=layer, policy=p))

    # Backwards-compatible alias (Go-style name).
    AddLayer = add_layer

    def remove_layer(self, layer: Layer) -> None:
        """Remove a layer by kind."""
        for i, entry in enumerate(self.layers):
            if entry.layer == layer:
                del self.layers[i]
                return

    # Backwards-compatible alias (Go-style name).
    RemoveLayer = remove_layer

    def get_layers(self) -> list[LayerPolicy]:
        """Return all configured layers."""
        return list(self.layers)

    # Backwards-compatible alias (Go-style name).
    Layers = get_layers


def new_layered_policy() -> LayeredPolicy:
    """Create a layered policy with default configuration."""
    return LayeredPolicy()


# Backwards-compatible alias (Go-style name).
NewLayeredPolicy = new_layered_policy


# ---- Layer Merge ----


def layer_merge(base: list[Rule], override: list[Rule]) -> list[Rule]:
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


# Backwards-compatible alias (Go-style name).
LayerMerge = layer_merge


# ---- File Loading ----


def load_project_policy(directory: str) -> tuple[Policy | None, Exception | None]:
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
        loaded = cast(Policy, p)
        merged.rules.extend(loaded.rules)
        if loaded.default_action == Action.Deny:
            merged.default_action = Action.Deny

    return merged, None


# Backwards-compatible alias (Go-style name).
LoadProjectPolicy = load_project_policy


def load_user_policy(config_dir: str) -> tuple[Policy | None, Exception | None]:
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


# Backwards-compatible alias (Go-style name).
LoadUserPolicy = load_user_policy


def marshal_layered_policy_json(lp: LayeredPolicy) -> tuple[str | None, Exception | None]:
    """Serialize a layered policy to JSON."""
    return (
        json.dumps(
            [{"Layer": int(e.layer), "Policy": _policy_to_dict(e.policy)} for e in lp.get_layers()],
            indent=2,
        ),
        None,
    )


# Backwards-compatible alias (Go-style name).
MarshalLayeredPolicyJSON = marshal_layered_policy_json
