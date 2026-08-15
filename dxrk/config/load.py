# SPDX-License-Identifier: MIT
"""Load and save legacy YAML configs"""

from __future__ import annotations

import logging
import os
from typing import Any

import yaml

from .config import Config, Default, ProviderByName, ProviderConfig  # noqa: F401

_logger = logging.getLogger("dxrk.config")


def _load_config_dict(data: dict[str, Any]) -> Config:
    """Builds a Config from a parsed dict, keeping defaults for missing sections."""
    cfg = Default()

    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    if isinstance(project, dict):
        if project.get("name"):
            cfg.project.name = str(project["name"])
        if project.get("root"):
            cfg.project.root = str(project["root"])
        if project.get("default_provider"):
            cfg.project.default_provider = str(project["default_provider"])

    providers = data.get("providers")
    if isinstance(providers, list) and providers:
        cfg.providers = []
        for p in providers:
            if not isinstance(p, dict):
                continue
            cfg.providers.append(
                ProviderConfig(
                    name=str(p.get("name", "")),
                    model=str(p.get("model", "")),
                    api_key_env=str(p.get("api_key_env", "")),
                    base_url=str(p.get("base_url", "")),
                )
            )

    sandbox = data.get("sandbox")
    if isinstance(sandbox, dict) and cfg.sandbox is not None:
        for key in (
            "default_image",
            "memory_limit",
            "cpu_limit",
            "timeout_sec",
            "max_containers",
        ):
            if sandbox.get(key) is not None:
                setattr(cfg.sandbox, key, sandbox[key])

    git = data.get("git")
    if isinstance(git, dict) and cfg.git is not None:
        for key in ("auto_commit", "auto_push", "require_pr"):
            if git.get(key) is not None:
                setattr(cfg.git, key, git[key])

    tui = data.get("tui")
    if isinstance(tui, dict) and cfg.tui is not None:
        for key in ("enabled", "show_filenames"):
            if tui.get(key) is not None:
                setattr(cfg.tui, key, tui[key])

    webui = data.get("webui")
    if isinstance(webui, dict) and cfg.webui is not None:
        for key in ("enabled", "port", "host", "theme", "log_level", "auto_update"):
            if webui.get(key) is not None:
                setattr(cfg.webui, key, webui[key])

    rag = data.get("rag")
    if isinstance(rag, dict) and cfg.rag is not None:
        for key in (
            "enabled",
            "embedding_model",
            "chunk_size",
            "chunk_overlap",
            "max_results",
        ):
            if rag.get(key) is not None:
                setattr(cfg.rag, key, rag[key])

    autonomy = data.get("autonomy")
    if isinstance(autonomy, dict) and cfg.autonomy is not None:
        for key in (
            "enabled",
            "interval_sec",
            "self_update",
            "self_verify",
            "self_learn",
            "auto_fix",
            "evolution",
            "learn_dir",
            "memories_file",
            "max_memory_items",
            "iq_metrics_file",
            "iq_report_every",
            "capabilities",
            "ask_before",
        ):
            if autonomy.get(key) is not None:
                setattr(cfg.autonomy, key, autonomy[key])

    vault = data.get("vault")
    if isinstance(vault, dict) and cfg.vault is not None:
        for key in ("enabled", "path", "master_key_env"):
            if vault.get(key) is not None:
                setattr(cfg.vault, key, vault[key])

    cache = data.get("cache")
    if isinstance(cache, dict) and cfg.cache is not None:
        for key in (
            "enabled",
            "max_size",
            "ttl_seconds",
            "semantic_enabled",
            "semantic_threshold",
        ):
            if cache.get(key) is not None:
                setattr(cfg.cache, key, cache[key])

    return cfg


def _config_to_dict(cfg: Config) -> dict[str, Any]:
    """Serializes a Config to a dict for YAML output."""
    data: dict[str, Any] = {}
    data["project"] = {
        "name": cfg.project.name,
        "root": cfg.project.root,
        "default_provider": cfg.project.default_provider,
    }
    data["providers"] = [
        {
            "name": p.name,
            "model": p.model,
            "api_key_env": p.api_key_env,
            **({"base_url": p.base_url} if p.base_url else {}),
        }
        for p in cfg.providers
    ]
    if cfg.sandbox is not None:
        data["sandbox"] = {
            "default_image": cfg.sandbox.default_image,
            "memory_limit": cfg.sandbox.memory_limit,
            "cpu_limit": cfg.sandbox.cpu_limit,
            "timeout_sec": cfg.sandbox.timeout_sec,
            "max_containers": cfg.sandbox.max_containers,
        }
    if cfg.git is not None:
        data["git"] = {
            "auto_commit": cfg.git.auto_commit,
            "auto_push": cfg.git.auto_push,
            "require_pr": cfg.git.require_pr,
        }
    if cfg.tui is not None:
        data["tui"] = {
            "enabled": cfg.tui.enabled,
            "show_filenames": cfg.tui.show_filenames,
        }
    if cfg.webui is not None:
        data["webui"] = {
            "enabled": cfg.webui.enabled,
            "port": cfg.webui.port,
            "host": cfg.webui.host,
            "theme": cfg.webui.theme,
            "log_level": cfg.webui.log_level,
            "auto_update": cfg.webui.auto_update,
        }
    if cfg.rag is not None:
        data["rag"] = {
            "enabled": cfg.rag.enabled,
            "embedding_model": cfg.rag.embedding_model,
            "chunk_size": cfg.rag.chunk_size,
            "chunk_overlap": cfg.rag.chunk_overlap,
            "max_results": cfg.rag.max_results,
        }
    if cfg.autonomy is not None:
        data["autonomy"] = {
            "enabled": cfg.autonomy.enabled,
            "interval_sec": cfg.autonomy.interval_sec,
            "self_update": cfg.autonomy.self_update,
            "self_verify": cfg.autonomy.self_verify,
            "self_learn": cfg.autonomy.self_learn,
            "auto_fix": cfg.autonomy.auto_fix,
            "evolution": cfg.autonomy.evolution,
            "learn_dir": cfg.autonomy.learn_dir,
            "memories_file": cfg.autonomy.memories_file,
            "max_memory_items": cfg.autonomy.max_memory_items,
            "iq_metrics_file": cfg.autonomy.iq_metrics_file,
            "iq_report_every": cfg.autonomy.iq_report_every,
            "capabilities": cfg.autonomy.capabilities,
            "ask_before": cfg.autonomy.ask_before,
        }
    if cfg.vault is not None:
        data["vault"] = {
            "enabled": cfg.vault.enabled,
            "path": cfg.vault.path,
            "master_key_env": cfg.vault.master_key_env,
        }
    if cfg.cache is not None:
        data["cache"] = {
            "enabled": cfg.cache.enabled,
            "max_size": cfg.cache.max_size,
            "ttl_seconds": cfg.cache.ttl_seconds,
            "semantic_enabled": cfg.cache.semantic_enabled,
            "semantic_threshold": cfg.cache.semantic_threshold,
        }
    return data


def Load(path: str) -> Config:
    """Loads a config from path, creating and saving defaults if it does not exist."""
    if not os.path.exists(path):
        cfg = Default()
        Save(path, cfg)
        return cfg
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        raise OSError(f"read config: {exc}") from exc
    if data is None:
        return Default()
    if not isinstance(data, dict):
        raise OSError("parse config: expected a mapping")
    return _load_config_dict(data)


def Save(path: str, cfg: Config) -> None:
    """Saves a config to path as YAML with restrictive permissions."""
    try:
        payload = yaml.safe_dump(_config_to_dict(cfg), sort_keys=False)
    except yaml.YAMLError as exc:
        raise OSError(f"parse config: {exc}") from exc
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, mode=0o750, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)
    os.chmod(path, 0o600)
