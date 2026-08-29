# SPDX-License-Identifier: MIT
"""Hierarchical configuration types and ConfigManager"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .storage import save_json_atomic
from .validation import ConfigError, ValidateConfig

_logger = logging.getLogger("dxrk.config")

DEFAULT_GLOBAL_PATH = "/etc/dxrk/config.yaml"
DEFAULT_USER_PATH = str(Path.home() / ".dxrk" / "config.yaml")
DEFAULT_PROJECT_PATH = ".dxrk/config.yaml"
DEFAULT_ENV_PREFIX = "DXRK"

Watcher = Callable[[str, Any], None]


@dataclass
class ModelConfig:
    provider: str = "claude"
    model_name: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    temperature: float = 0.7
    top_p: float = 0.9
    system_prompt: str = ""


@dataclass
class APIConfig:
    base_url: str = "https://api.anthropic.com"
    api_key: str = ""
    timeout: int = 30
    retries: int = 3
    rate_limit: int = 60


@dataclass
class AuthConfig:
    provider: str = "oauth"
    client_id: str = ""
    scopes: list[str] = field(default_factory=lambda: ["read", "write"])
    token_path: str = "~/.dxrk/tokens"


@dataclass
class SessionConfig:
    max_history: int = 100
    auto_save: bool = True
    archive_after: int = 24
    restore_last: bool = True


@dataclass
class ToolsConfig:
    enabled: list[str] = field(default_factory=list)
    disabled: list[str] = field(default_factory=list)
    timeout: int = 30
    max_concurrent: int = 5


@dataclass
class UIConfig:
    theme: str = "dark"
    font_size: int = 14
    show_tokens: bool = True
    show_cost: bool = True
    compact_mode: bool = False


@dataclass
class AdvancedConfig:
    debug: bool = False
    log_level: str = "info"
    telemetry: bool = True
    auto_update: bool = True
    yolo_mode: bool = False


@dataclass
class HierarchicalConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    api: APIConfig = field(default_factory=APIConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)


def default_hierarchical_config() -> HierarchicalConfig:
    """Returns the built-in default hierarchical configuration."""
    return HierarchicalConfig()


def _config_to_dict(cfg: HierarchicalConfig) -> dict[str, Any]:
    """Serializes a HierarchicalConfig to a nested dict."""
    return {
        "model": {
            "provider": cfg.model.provider,
            "model_name": cfg.model.model_name,
            "max_tokens": cfg.model.max_tokens,
            "temperature": cfg.model.temperature,
            "top_p": cfg.model.top_p,
            "system_prompt": cfg.model.system_prompt,
        },
        "api": {
            "base_url": cfg.api.base_url,
            "api_key": cfg.api.api_key,
            "timeout": cfg.api.timeout,
            "retries": cfg.api.retries,
            "rate_limit": cfg.api.rate_limit,
        },
        "auth": {
            "provider": cfg.auth.provider,
            "client_id": cfg.auth.client_id,
            "scopes": cfg.auth.scopes,
            "token_path": cfg.auth.token_path,
        },
        "session": {
            "max_history": cfg.session.max_history,
            "auto_save": cfg.session.auto_save,
            "archive_after": cfg.session.archive_after,
            "restore_last": cfg.session.restore_last,
        },
        "tools": {
            "enabled": cfg.tools.enabled,
            "disabled": cfg.tools.disabled,
            "timeout": cfg.tools.timeout,
            "max_concurrent": cfg.tools.max_concurrent,
        },
        "ui": {
            "theme": cfg.ui.theme,
            "font_size": cfg.ui.font_size,
            "show_tokens": cfg.ui.show_tokens,
            "show_cost": cfg.ui.show_cost,
            "compact_mode": cfg.ui.compact_mode,
        },
        "advanced": {
            "debug": cfg.advanced.debug,
            "log_level": cfg.advanced.log_level,
            "telemetry": cfg.advanced.telemetry,
            "auto_update": cfg.advanced.auto_update,
            "yolo_mode": cfg.advanced.yolo_mode,
        },
    }


def _dict_to_config(data: dict[str, Any]) -> HierarchicalConfig:
    """Deserializes a nested dict back into a HierarchicalConfig."""
    model = data.get("model", {})
    api = data.get("api", {})
    auth = data.get("auth", {})
    session = data.get("session", {})
    tools = data.get("tools", {})
    ui = data.get("ui", {})
    advanced = data.get("advanced", {})
    return HierarchicalConfig(
        model=ModelConfig(
            provider=str(model.get("provider", "")),
            model_name=str(model.get("model_name", "")),
            max_tokens=int(model.get("max_tokens", 0)),
            temperature=float(model.get("temperature", 0.0)),
            top_p=float(model.get("top_p", 0.0)),
            system_prompt=str(model.get("system_prompt", "")),
        ),
        api=APIConfig(
            base_url=str(api.get("base_url", "")),
            api_key=str(api.get("api_key", "")),
            timeout=int(api.get("timeout", 0)),
            retries=int(api.get("retries", 0)),
            rate_limit=int(api.get("rate_limit", 0)),
        ),
        auth=AuthConfig(
            provider=str(auth.get("provider", "")),
            client_id=str(auth.get("client_id", "")),
            scopes=list(auth.get("scopes", [])),
            token_path=str(auth.get("token_path", "")),
        ),
        session=SessionConfig(
            max_history=int(session.get("max_history", 0)),
            auto_save=bool(session.get("auto_save", False)),
            archive_after=int(session.get("archive_after", 0)),
            restore_last=bool(session.get("restore_last", False)),
        ),
        tools=ToolsConfig(
            enabled=list(tools.get("enabled", [])),
            disabled=list(tools.get("disabled", [])),
            timeout=int(tools.get("timeout", 0)),
            max_concurrent=int(tools.get("max_concurrent", 0)),
        ),
        ui=UIConfig(
            theme=str(ui.get("theme", "")),
            font_size=int(ui.get("font_size", 0)),
            show_tokens=bool(ui.get("show_tokens", False)),
            show_cost=bool(ui.get("show_cost", False)),
            compact_mode=bool(ui.get("compact_mode", False)),
        ),
        advanced=AdvancedConfig(
            debug=bool(advanced.get("debug", False)),
            log_level=str(advanced.get("log_level", "")),
            telemetry=bool(advanced.get("telemetry", False)),
            auto_update=bool(advanced.get("auto_update", False)),
            yolo_mode=bool(advanced.get("yolo_mode", False)),
        ),
    )


@dataclass
class _Option:
    """Internal option holder for ConfigManager construction."""

    global_path: str | None = None
    user_path: str | None = None
    project_path: str | None = None
    env_prefix: str | None = None


def WithGlobalPath(path: str) -> _Option:
    return _Option(global_path=path)


def WithUserPath(path: str) -> _Option:
    return _Option(user_path=path)


def WithProjectPath(path: str) -> _Option:
    return _Option(project_path=path)


def WithEnvPrefix(prefix: str) -> _Option:
    return _Option(env_prefix=prefix)


class ConfigManager:
    """Manages hierarchical configuration with dot-notation access, validation and watch."""

    def __init__(self, options: list[_Option] | None = None):
        self._mu = threading.RLock()
        self._defaults: HierarchicalConfig = default_hierarchical_config()
        self._config: HierarchicalConfig = default_hierarchical_config()
        self._global_path: str = DEFAULT_GLOBAL_PATH
        self._user_path: str = DEFAULT_USER_PATH
        self._project_path: str = DEFAULT_PROJECT_PATH
        self._env_prefix: str = DEFAULT_ENV_PREFIX
        if options:
            for opt in options:
                if opt.global_path is not None:
                    self._global_path = opt.global_path
                if opt.user_path is not None:
                    self._user_path = opt.user_path
                if opt.project_path is not None:
                    self._project_path = opt.project_path
                if opt.env_prefix is not None:
                    self._env_prefix = opt.env_prefix
        self._watchers: dict[str, list[Watcher]] = {}

    def Load(self) -> None:
        """Loads configuration from file sources and environment variables."""
        with self._mu:
            self._config = default_hierarchical_config()
            self._load_file(self._global_path)
            self._load_file(self._user_path)
            self._load_file(self._project_path)
            self._load_from_env()

    def _load_file(self, path: str) -> None:
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError as exc:
            _logger.warning("load %s: %s", path, exc)
            return
        if not content.strip():
            return
        data: Any = None
        if path.endswith(".json"):
            try:
                data = json.loads(content)
            except json.JSONDecodeError as exc:
                _logger.warning("parse json %s: %s", path, exc)
                return
        else:
            try:
                data = yaml.safe_load(content)
            except yaml.YAMLError as exc:
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    _logger.warning("parse %s: %s", path, exc)
                    return
        if not isinstance(data, dict):
            return
        with self._mu:
            self._merge(data)

    def merge(self, overlay: dict[str, Any]) -> None:
        """Merges a dict overlay into the current config (non-zero values win)."""
        with self._mu:
            self._merge(overlay)

    def _merge(self, overlay: dict[str, Any]) -> None:
        cfg = self._config
        model = overlay.get("model")
        if isinstance(model, dict):
            if model.get("provider"):
                cfg.model.provider = str(model["provider"])
            if model.get("model_name"):
                cfg.model.model_name = str(model["model_name"])
            if model.get("system_prompt"):
                cfg.model.system_prompt = str(model["system_prompt"])
            if model.get("max_tokens"):
                cfg.model.max_tokens = int(model["max_tokens"])
            if model.get("temperature"):
                cfg.model.temperature = float(model["temperature"])
            if model.get("top_p"):
                cfg.model.top_p = float(model["top_p"])
        api = overlay.get("api")
        if isinstance(api, dict):
            if api.get("base_url"):
                cfg.api.base_url = str(api["base_url"])
            if api.get("api_key"):
                cfg.api.api_key = str(api["api_key"])
            if api.get("timeout"):
                cfg.api.timeout = int(api["timeout"])
            if api.get("retries"):
                cfg.api.retries = int(api["retries"])
            if api.get("rate_limit"):
                cfg.api.rate_limit = int(api["rate_limit"])
        auth = overlay.get("auth")
        if isinstance(auth, dict):
            if auth.get("provider"):
                cfg.auth.provider = str(auth["provider"])
            if auth.get("client_id"):
                cfg.auth.client_id = str(auth["client_id"])
            if auth.get("token_path"):
                cfg.auth.token_path = str(auth["token_path"])
            if auth.get("scopes"):
                cfg.auth.scopes = list(auth["scopes"])
        session = overlay.get("session")
        if isinstance(session, dict):
            if session.get("max_history"):
                cfg.session.max_history = int(session["max_history"])
        tools = overlay.get("tools")
        if isinstance(tools, dict):
            if tools.get("timeout"):
                cfg.tools.timeout = int(tools["timeout"])
            if tools.get("max_concurrent"):
                cfg.tools.max_concurrent = int(tools["max_concurrent"])
            if tools.get("enabled"):
                cfg.tools.enabled = list(tools["enabled"])
            if tools.get("disabled"):
                cfg.tools.disabled = list(tools["disabled"])
        ui = overlay.get("ui")
        if isinstance(ui, dict):
            if ui.get("theme"):
                cfg.ui.theme = str(ui["theme"])
            if ui.get("font_size"):
                cfg.ui.font_size = int(ui["font_size"])
        advanced = overlay.get("advanced")
        if isinstance(advanced, dict):
            if advanced.get("log_level"):
                cfg.advanced.log_level = str(advanced["log_level"])

    def _load_from_env(self) -> None:
        prefix = self._env_prefix + "_"
        env = os.environ
        cfg = self._config

        def get_env(key: str) -> str | None:
            val = env.get(prefix + key)
            return val if val is not None else None

        val = get_env("MODEL_PROVIDER")
        if val:
            cfg.model.provider = val
        val = get_env("MODEL_NAME")
        if val:
            cfg.model.model_name = val
        val = get_env("API_BASE_URL")
        if val:
            cfg.api.base_url = val
        val = get_env("API_KEY")
        if val:
            cfg.api.api_key = val
        val = get_env("AUTH_PROVIDER")
        if val:
            cfg.auth.provider = val
        val = get_env("AUTH_CLIENT_ID")
        if val:
            cfg.auth.client_id = val
        val = get_env("AUTH_TOKEN_PATH")
        if val:
            cfg.auth.token_path = val
        val = get_env("UI_THEME")
        if val:
            cfg.ui.theme = val
        val = get_env("LOG_LEVEL")
        if val:
            cfg.advanced.log_level = val

        for env_key, setter in (
            ("MODEL_MAX_TOKENS", lambda v: setattr(cfg.model, "max_tokens", v)),
            ("API_TIMEOUT", lambda v: setattr(cfg.api, "timeout", v)),
            ("API_RETRIES", lambda v: setattr(cfg.api, "retries", v)),
            ("API_RATE_LIMIT", lambda v: setattr(cfg.api, "rate_limit", v)),
            ("SESSION_MAX_HISTORY", lambda v: setattr(cfg.session, "max_history", v)),
            ("TOOLS_TIMEOUT", lambda v: setattr(cfg.tools, "timeout", v)),
            ("TOOLS_MAX_CONCURRENT", lambda v: setattr(cfg.tools, "max_concurrent", v)),
            ("UI_FONT_SIZE", lambda v: setattr(cfg.ui, "font_size", v)),
        ):
            val = get_env(env_key)
            if val is not None:
                try:
                    setter(int(val))
                except ValueError:
                    pass

        for env_key, setter in (
            ("MODEL_TEMPERATURE", lambda v: setattr(cfg.model, "temperature", v)),
            ("MODEL_TOP_P", lambda v: setattr(cfg.model, "top_p", v)),
        ):
            val = get_env(env_key)
            if val is not None:
                try:
                    setter(float(val))
                except ValueError:
                    pass

        for env_key, setter in (
            ("SESSION_AUTO_SAVE", lambda v: setattr(cfg.session, "auto_save", v)),
            ("SESSION_RESTORE_LAST", lambda v: setattr(cfg.session, "restore_last", v)),
            ("UI_SHOW_TOKENS", lambda v: setattr(cfg.ui, "show_tokens", v)),
            ("UI_SHOW_COST", lambda v: setattr(cfg.ui, "show_cost", v)),
            ("UI_COMPACT_MODE", lambda v: setattr(cfg.ui, "compact_mode", v)),
            ("ADVANCED_DEBUG", lambda v: setattr(cfg.advanced, "debug", v)),
            ("ADVANCED_TELEMETRY", lambda v: setattr(cfg.advanced, "telemetry", v)),
            ("ADVANCED_AUTO_UPDATE", lambda v: setattr(cfg.advanced, "auto_update", v)),
            ("ADVANCED_YOLO_MODE", lambda v: setattr(cfg.advanced, "yolo_mode", v)),
        ):
            val = get_env(env_key)
            if val is not None:
                lowered = val.strip().lower()
                if lowered == "true" or lowered == "1":
                    setter(True)
                elif lowered == "false" or lowered == "0":
                    setter(False)

    def Get(self, path: str) -> Any | None:
        """Returns the value at a dot-notation path, or None."""
        with self._mu:
            parts = path.split(".")
            if len(parts) < 2:
                return None
            data = _config_to_dict(self._config)
            node: Any = data
            for part in parts:
                if not isinstance(node, dict) or part not in node:
                    return None
                node = node[part]
            return node

    def Set(self, path: str, value: Any) -> None:
        """Sets a value at a dot-notation path and notifies watchers."""
        with self._mu:
            parts = path.split(".")
            if len(parts) < 2:
                raise ValueError(f"invalid config path: {path}")
            data = _config_to_dict(self._config)
            node: Any = data
            for part in parts[:-1]:
                if not isinstance(node, dict) or part not in node:
                    raise ValueError(f"invalid config path: {path}")
                node = node[part]
            if not isinstance(node, dict):
                raise ValueError(f"invalid config path: {path}")
            node[parts[-1]] = value
            try:
                self._config = _dict_to_config(data)
            except (TypeError, ValueError) as exc:
                raise ValueError("unmarshal config") from exc
            self._notify_watchers(path, value)

    def Save(self) -> None:
        """Saves the config as JSON to the user config path."""
        with self._mu:
            path = self._user_path
            data = _config_to_dict(self._config)
        save_json_atomic(path, data)

    def Reset(self, path: str) -> None:
        """Resets a section of the config to defaults."""
        with self._mu:
            defaults = _config_to_dict(default_hierarchical_config())
            section = path.split(".")[0]
            if section not in defaults:
                raise ValueError(f"unknown config section: {section}")
            current = _config_to_dict(self._config)
            current[section] = defaults[section]
            self._config = _dict_to_config(current)
            self._notify_watchers(path, None)

    def Merge(self, other: HierarchicalConfig | None) -> None:
        """Merges another config into this one."""
        if other is None:
            return
        with self._mu:
            overlay = _config_to_dict(other)
            self._merge(overlay)

    def Validate(self) -> list[ConfigError]:
        """Runs the default validation pipeline on the current config."""
        with self._mu:
            return ValidateConfig(self._config)

    def Watch(self, path: str, callback: Watcher) -> None:
        """Registers a callback invoked when config under path changes."""
        with self._mu:
            self._watchers.setdefault(path, []).append(callback)

    def _notify_watchers(self, path: str, value: Any) -> None:
        for pattern, callbacks in list(self._watchers.items()):
            if pattern == "*" or path.startswith(pattern):
                for cb in callbacks:
                    try:
                        cb(path, value)
                    except Exception:
                        _logger.exception("config watcher failed for %s", pattern)

    def Config(self) -> HierarchicalConfig:
        """Returns a snapshot copy of the current config."""
        with self._mu:
            return _dict_to_config(_config_to_dict(self._config))

    def LoadFromViper(self, v: dict[str, Any]) -> None:
        """Applies values from a viper-style config dict (mirrors LoadFromViper)."""
        with self._mu:
            overlay: dict[str, Any] = {}

            def put(section: str, key: str, value: Any) -> None:
                if value is not None:
                    overlay.setdefault(section, {})[key] = value

            model = v.get("model", {})
            put("model", "provider", model.get("provider"))
            put("model", "model_name", model.get("model_name"))
            put("model", "max_tokens", model.get("max_tokens"))
            put("model", "temperature", model.get("temperature"))
            put("model", "top_p", model.get("top_p"))
            put("model", "system_prompt", model.get("system_prompt"))
            api = v.get("api", {})
            put("api", "base_url", api.get("base_url"))
            put("api", "api_key", api.get("api_key"))
            put("api", "timeout", api.get("timeout"))
            put("api", "retries", api.get("retries"))
            put("api", "rate_limit", api.get("rate_limit"))
            auth = v.get("auth", {})
            put("auth", "provider", auth.get("provider"))
            put("auth", "client_id", auth.get("client_id"))
            put("auth", "scopes", auth.get("scopes"))
            put("auth", "token_path", auth.get("token_path"))
            session = v.get("session", {})
            put("session", "max_history", session.get("max_history"))
            put("session", "archive_after", session.get("archive_after"))
            tools = v.get("tools", {})
            put("tools", "timeout", tools.get("timeout"))
            put("tools", "max_concurrent", tools.get("max_concurrent"))
            ui = v.get("ui", {})
            put("ui", "theme", ui.get("theme"))
            put("ui", "font_size", ui.get("font_size"))
            advanced = v.get("advanced", {})
            put("advanced", "log_level", advanced.get("log_level"))
            self._merge(overlay)


def NewConfigManager(options: list[_Option] | None = None) -> ConfigManager:
    """Creates a ConfigManager with the given options applied."""
    return ConfigManager(options)


# ---- Legacy Config Types ----


@dataclass
class ProjectConfig:
    name: str = "my-project"
    root: str = "."
    default_provider: str = "claude"


@dataclass
class ProviderConfig:
    name: str = ""
    model: str = ""
    api_key_env: str = ""
    base_url: str = ""


@dataclass
class SandboxConfig:
    default_image: str = "ubuntu:22.04"
    memory_limit: str = "4g"
    cpu_limit: str = "2"
    timeout_sec: int = 120
    max_containers: int = 5


@dataclass
class GitConfig:
    auto_commit: bool = True
    auto_push: bool = False
    require_pr: bool = True


@dataclass
class TUIOpts:
    enabled: bool = True
    show_filenames: bool = True


@dataclass
class WebUIConfig:
    enabled: bool = False
    port: int = 8080
    host: str = "127.0.0.1"
    theme: str = "dark"
    log_level: str = "info"
    auto_update: bool = True


@dataclass
class RAGConfig:
    enabled: bool = False
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = 512
    chunk_overlap: int = 64
    max_results: int = 5


@dataclass
class AutonomyConfig:
    enabled: bool = True
    interval_sec: int = 300
    self_update: bool = True
    self_verify: bool = True
    self_learn: bool = True
    auto_fix: bool = True
    evolution: bool = False
    learn_dir: str = ".dxrk/learn"
    memories_file: str = ".dxrk/memories.json"
    max_memory_items: int = 1000
    iq_metrics_file: str = ".dxrk/iq.json"
    iq_report_every: int = 10
    capabilities: list[str] = field(default_factory=lambda: ["fs.read", "fs.write", "git", "net.http"])
    ask_before: list[str] = field(default_factory=lambda: ["fs.write", "sudo", "pkg.install", "docker"])


@dataclass
class VaultConfig:
    enabled: bool = False
    path: str = ".dxrk/vault.enc"
    master_key_env: str = "DXRK_VAULT_KEY"


@dataclass
class CacheConfig:
    enabled: bool = False
    max_size: int = 1000
    ttl_seconds: int = 300
    semantic_enabled: bool = False
    semantic_threshold: float = 0.95


@dataclass
class Config:
    """Legacy flat configuration (mirrors the original Config type)."""

    project: ProjectConfig = field(default_factory=ProjectConfig)
    providers: list[ProviderConfig] = field(default_factory=list)
    sandbox: SandboxConfig | None = None
    git: GitConfig | None = None
    tui: TUIOpts | None = None
    webui: WebUIConfig | None = None
    rag: RAGConfig | None = None
    autonomy: AutonomyConfig | None = None
    vault: VaultConfig | None = None
    cache: CacheConfig | None = None


def Default() -> Config:
    """Returns the built-in default configuration."""
    return Config(
        project=ProjectConfig(),
        providers=[
            ProviderConfig(
                name="claude",
                model="claude-sonnet-4-20250514",
                api_key_env="ANTHROPIC_API_KEY",
            ),
            ProviderConfig(name="openai", model="gpt-4o", api_key_env="OPENAI_API_KEY"),
            ProviderConfig(name="gemini", model="gemini-2.0-flash", api_key_env="GEMINI_API_KEY"),
            ProviderConfig(name="ollama", model="llama3.1:8b", base_url="http://localhost:11434"),
        ],
        sandbox=SandboxConfig(),
        git=GitConfig(),
        tui=TUIOpts(),
        webui=WebUIConfig(),
        rag=RAGConfig(),
        autonomy=AutonomyConfig(),
        vault=VaultConfig(),
        cache=CacheConfig(),
    )


def ProviderByName(cfg: Config, name: str) -> ProviderConfig | None:
    """Returns the provider with the given name, or None."""
    for p in cfg.providers:
        if p.name == name:
            return p
    return None
