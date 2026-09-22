# SPDX-License-Identifier: MIT

"""Permission policy serialization, layering, merging, and loading."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import IntEnum
from typing import cast

from dxrk.utils.permissions_engine import NewPolicyEngine as NewPolicyEngine
from dxrk.utils.permissions_model import _STR_PROJECT as _STR_PROJECT
from dxrk.utils.permissions_model import _STR_UNKNOWN as _STR_UNKNOWN
from dxrk.utils.permissions_model import Action as Action
from dxrk.utils.permissions_model import Condition as Condition
from dxrk.utils.permissions_model import EvalContext as EvalContext
from dxrk.utils.permissions_model import Policy as Policy
from dxrk.utils.permissions_model import Rule as Rule
from dxrk.utils.permissions_model import Strategy as Strategy
from dxrk.utils.permissions_model import _anonymous_enum_member as _anonymous_enum_member
from dxrk.utils.permissions_model import _as_int as _as_int

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
