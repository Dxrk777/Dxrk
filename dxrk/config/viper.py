# SPDX-License-Identifier: MIT
"""Viper-style config loading via env and files"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

import yaml

from .config import ConfigManager, HierarchicalConfig, WithEnvPrefix

_logger = logging.getLogger("dxrk.config")

ENV_PREFIX = "DXRK"


def _read_file(path: str) -> Dict[str, Any]:
    """Reads a YAML or JSON config file into a nested dict."""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if path.endswith(".json"):
        data = json.loads(content)
    else:
        data = yaml.safe_load(content) or {}
    if not isinstance(data, dict):
        return {}
    return data


def LoadViper(path: str) -> HierarchicalConfig:
    """Loads a HierarchicalConfig from a YAML/JSON file with DXRK_* env overrides."""
    nested: Dict[str, Any] = {}
    if os.path.exists(path):
        try:
            nested = _read_file(path)
        except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
            raise OSError(f"read viper config: {exc}") from exc

    manager = ConfigManager([WithEnvPrefix(ENV_PREFIX)])
    manager.LoadFromViper(nested)
    return manager.Config()
