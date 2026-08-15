# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

__all__ = [
    "Model",
    "ModelCost",
    "ModelLimit",
    "OpencodeConfig",
    "Provider",
    "default_auth_path",
    "default_cache_path",
    "default_settings_path",
    "detect_available_providers",
    "filter_models_for_sdd",
    "load_models",
    "sdd_phases",
]


def default_settings_path() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, ".config", "opencode", "opencode.json")


def default_cache_path() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, ".cache", "opencode", "models.json")


def default_auth_path() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, ".local", "share", "opencode", "auth.json")


@dataclass
class OpencodeConfig:
    settings_path: str = ""
    cache_path: str = ""
    auth_path: str = ""


@dataclass
class ModelCost:
    input: float = 0.0
    output: float = 0.0


@dataclass
class ModelLimit:
    context: int = 0
    output: int = 0


@dataclass
class Model:
    id: str = ""
    name: str = ""
    family: str = ""
    tool_call: bool = False
    reasoning: bool = False
    cost: ModelCost = field(default_factory=ModelCost)
    limit: ModelLimit = field(default_factory=ModelLimit)


@dataclass
class Provider:
    id: str = ""
    name: str = ""
    env: list[str] = field(default_factory=list)
    models: dict[str, Model] = field(default_factory=dict)


def load_models(cache_path: str) -> dict[str, Provider]:
    try:
        with open(cache_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        raise ValueError(f"read models cache {cache_path!r}")

    if not isinstance(data, dict):
        raise ValueError(f"parse models cache: expected dict, got {type(data).__name__}")

    providers: dict[str, Provider] = {}
    for pid, raw in data.items():
        if not isinstance(raw, dict):
            continue
        p = Provider(
            id=pid,
            name=raw.get("name", ""),
            env=raw.get("env", []),
        )
        models_raw = raw.get("models", {})
        if isinstance(models_raw, dict):
            for mid, mraw in models_raw.items():
                if not isinstance(mraw, dict):
                    continue
                cost_raw = mraw.get("cost", {}) or {}
                limit_raw = mraw.get("limit", {}) or {}
                p.models[mid] = Model(
                    id=mid,
                    name=mraw.get("name", ""),
                    family=mraw.get("family", ""),
                    tool_call=bool(mraw.get("tool_call", False)),
                    reasoning=bool(mraw.get("reasoning", False)),
                    cost=ModelCost(
                        input=float(cost_raw.get("input", 0)),
                        output=float(cost_raw.get("output", 0)),
                    ),
                    limit=ModelLimit(
                        context=int(limit_raw.get("context", 0)),
                        output=int(limit_raw.get("output", 0)),
                    ),
                )
        providers[pid] = p

    return providers


def load_auth_providers(auth_path: str) -> dict[str, bool]:
    try:
        with open(auth_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}
    return {k: True for k in data if isinstance(k, str)}


def detect_available_providers(providers: dict[str, Provider], auth_path_override: str = "") -> list[str]:
    auth = load_auth_providers(auth_path_override or default_auth_path())

    available: list[str] = []
    for pid, provider in providers.items():
        if not _has_tool_call_model(provider):
            continue
        if auth.get(pid):
            available.append(pid)
            continue
        if pid == "opencode":
            available.append(pid)
            continue
        if provider.env and all(os.getenv(v) for v in provider.env):
            available.append(pid)
            continue

    available.sort()
    return available


def _has_tool_call_model(provider: Provider) -> bool:
    return any(m.tool_call for m in provider.models.values())


def filter_models_for_sdd(provider: Provider) -> list[Model]:
    models = [m for m in provider.models.values() if m.tool_call]
    models.sort(key=lambda m: m.name)
    return models


def sdd_phases() -> list[str]:
    return [
        "sdd-init",
        "sdd-explore",
        "sdd-propose",
        "sdd-spec",
        "sdd-design",
        "sdd-tasks",
        "sdd-apply",
        "sdd-verify",
        "sdd-archive",
    ]
