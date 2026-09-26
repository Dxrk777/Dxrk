# SPDX-License-Identifier: MIT
"""Hook configuration file load/save/validate/merge/filter."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Any

from dxrk.utils.hooks_model_codec import _file_dump, _file_load
from dxrk.utils.hooks_model_errors import ErrConfigNotFound, ErrConfigParse, ErrInvalidConfig, HookError
from dxrk.utils.hooks_model_events import HookConfig, HookConfigFile
from dxrk.utils.hooks_model_types import HookType, ParseHookType, _hook_type_name


def DefaultConfig() -> HookConfigFile:
    """Return a default hook configuration. Mirrors hooks.DefaultConfig."""
    return HookConfigFile(version="1.0", hooks=[])


def LoadConfig(path: str) -> tuple[HookConfigFile | None, Any]:
    """Load hook configuration from a file. Mirrors hooks.LoadConfig.

    A missing file yields the default config; unreadable or unparseable
    files yield ``ErrConfigNotFound`` / ``ErrConfigParse``.
    """
    try:
        with open(os.path.abspath(path), encoding="utf-8") as f:
            data = f.read()
    except FileNotFoundError:
        return DefaultConfig(), None
    except OSError:
        return None, ErrConfigNotFound

    try:
        raw = json.loads(data)
        cfg = _file_load(raw)
    except (ValueError, TypeError):
        return None, ErrConfigParse

    if cfg.version == "":
        cfg.version = "1.0"
    for hook in cfg.hooks:
        if hook.timeout == timedelta(0):
            hook.timeout = timedelta(seconds=30)
        if hook.max_retries < 0:
            hook.max_retries = 0
        if hook.retry_delay == timedelta(0):
            hook.retry_delay = timedelta(seconds=1)
    return cfg, None


def SaveConfig(path: str, cfg: HookConfigFile) -> Any:
    """Save hook configuration to a file. Mirrors hooks.SaveConfig."""
    try:
        data = json.dumps(_file_dump(cfg), indent=2)
    except (ValueError, TypeError):
        return ErrConfigParse

    dirname = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(dirname, exist_ok=True, mode=0o700)
    except OSError as e:
        return HookError(str(e))
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        os.chmod(path, 0o600)
    except OSError as e:
        return HookError(str(e))
    return None


def ValidateConfig(cfg: HookConfigFile | None) -> Any:
    """Validate a hook configuration. Mirrors hooks.ValidateConfig."""
    if cfg is None:
        return ErrConfigParse

    ids: set[str] = set()
    for hook in cfg.hooks:
        if hook.id == "":
            return ErrConfigParse
        if hook.id in ids:
            return ErrInvalidConfig
        ids.add(hook.id)

        if hook.command == "":
            return ErrConfigParse

        if not ParseHookType(_hook_type_name(hook.type))[1]:
            return ErrConfigParse

        if hook.timeout < timedelta(0):
            return ErrConfigParse
        if hook.max_retries < 0:
            return ErrConfigParse
        if hook.retry_delay < timedelta(0):
            return ErrConfigParse
    return None


def MergeConfigs(*configs: HookConfigFile | None) -> HookConfigFile:
    """Merge multiple hook configurations. Mirrors hooks.MergeConfigs.

    The first configuration that defines a hook ID wins.
    """
    merged = DefaultConfig()
    ids: set[str] = set()
    for cfg in configs:
        if cfg is None:
            continue
        for hook in cfg.hooks:
            if hook.id not in ids:
                merged.hooks.append(hook)
                ids.add(hook.id)
    return merged


def FilterByType(cfg: HookConfigFile, ht: HookType) -> list[HookConfig]:
    """Return hooks of a specific type. Mirrors hooks.FilterByType."""
    return [hook for hook in cfg.hooks if hook.type == ht]


def FilterEnabled(cfg: HookConfigFile) -> list[HookConfig]:
    """Return only enabled hooks. Mirrors hooks.FilterEnabled."""
    return [hook for hook in cfg.hooks if hook.enabled]
