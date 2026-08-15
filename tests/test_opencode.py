# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dxrk.opencode import (
    Model,
    Provider,
    default_auth_path,
    default_cache_path,
    default_settings_path,
    detect_available_providers,
    filter_models_for_sdd,
    load_models,
    sdd_phases,
)


def test_default_settings_path():
    p = default_settings_path()
    assert p.endswith("/.config/opencode/opencode.json")


def test_default_cache_path():
    p = default_cache_path()
    assert p.endswith("/.cache/opencode/models.json")


def test_default_auth_path():
    p = default_auth_path()
    assert p.endswith("/.local/share/opencode/auth.json")


def test_sdd_phases():
    phases = sdd_phases()
    assert len(phases) == 9
    assert phases[0] == "sdd-init"
    assert phases[-1] == "sdd-archive"


def test_load_models_invalid_path():
    with pytest.raises(ValueError, match="read models cache"):
        load_models("/nonexistent/path/models.json")


def test_load_models_invalid_json(temp_dir: Path):
    p = temp_dir / "bad.json"
    p.write_text("not json")
    with pytest.raises(ValueError, match="read models cache"):
        load_models(str(p))


def test_load_models_empty_object(temp_dir: Path):
    p = temp_dir / "empty.json"
    p.write_text("{}")
    result = load_models(str(p))
    assert result == {}


def test_load_models_single_provider(temp_dir: Path):
    data = {
        "opencode": {
            "name": "OpenCode",
            "models": {
                "sonnet": {
                    "name": "Sonnet",
                    "family": "claude",
                    "tool_call": True,
                    "cost": {"input": 3.0, "output": 15.0},
                    "limit": {"context": 200000, "output": 8192},
                }
            },
        }
    }
    p = temp_dir / "models.json"
    p.write_text(json.dumps(data))

    result = load_models(str(p))
    assert "opencode" in result
    provider = result["opencode"]
    assert provider.name == "OpenCode"
    assert "sonnet" in provider.models
    model = provider.models["sonnet"]
    assert model.tool_call is True
    assert model.cost.input == 3.0
    assert model.limit.context == 200000


def test_load_models_provider_with_env(temp_dir: Path):
    data = {
        "anthropic": {
            "name": "Anthropic",
            "env": ["ANTHROPIC_API_KEY"],
            "models": {
                "claude-opus-4": {
                    "name": "Claude Opus 4",
                    "tool_call": True,
                    "cost": {"input": 15.0, "output": 75.0},
                }
            },
        }
    }
    p = temp_dir / "models.json"
    p.write_text(json.dumps(data))
    result = load_models(str(p))
    assert result["anthropic"].env == ["ANTHROPIC_API_KEY"]


def test_filter_models_for_sdd(temp_dir: Path):
    data = {
        "opencode": {
            "models": {
                "free": {"name": "Free", "tool_call": False},
                "pro": {"name": "Pro", "tool_call": True},
                "ultra": {"name": "Ultra", "tool_call": True},
            }
        }
    }
    p = temp_dir / "models.json"
    p.write_text(json.dumps(data))
    providers = load_models(str(p))
    filtered = filter_models_for_sdd(providers["opencode"])
    assert len(filtered) == 2
    assert all(m.tool_call for m in filtered)


def test_detect_available_providers_no_auth(temp_dir: Path):
    providers = {
        "opencode": Provider(
            id="opencode", name="OpenCode",
            models={"sonnet": Model(id="sonnet", name="Sonnet", tool_call=True)},
        ),
        "anthropic": Provider(
            id="anthropic", name="Anthropic",
            env=["ANTHROPIC_API_KEY"],
            models={"opus": Model(id="opus", name="Opus", tool_call=True)},
        ),
    }

    available = detect_available_providers(providers, str(temp_dir / "auth.json"))
    assert "opencode" in available
    assert "anthropic" not in available


def test_provider_defaults():
    p = Provider()
    assert p.id == ""
    assert p.env == []
    assert p.models == {}


def test_model_defaults():
    m = Model()
    assert m.id == ""
    assert m.tool_call is False
    assert m.reasoning is False
    assert m.cost.input == 0.0
    assert m.limit.context == 0
