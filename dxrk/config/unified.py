# SPDX-License-Identifier: MIT
"""Unified configuration facade and ConfigManager-backed SettingsStore adapter"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import ConfigManager, default_hierarchical_config
from .settings import FileSettingsStore, ProjectSettingsStore, SettingsManager, SettingsStore
from .storage import save_json_atomic
from .validation import ConfigError

# Known hierarchical sections and their fields for flattening in List()
_SECTION_FIELDS: dict[str, list[str]] = {
    "model": ["provider", "model_name", "max_tokens", "temperature", "top_p", "system_prompt"],
    "api": ["base_url", "api_key", "timeout", "retries", "rate_limit"],
    "auth": ["provider", "client_id", "scopes", "token_path"],
    "session": ["max_history", "auto_save", "archive_after", "restore_last"],
    "tools": ["enabled", "disabled", "timeout", "max_concurrent"],
    "ui": ["theme", "font_size", "show_tokens", "show_cost", "compact_mode"],
    "advanced": ["debug", "log_level", "telemetry", "auto_update", "yolo_mode"],
}


class ConfigSettingsStore(SettingsStore):
    """Adapter that wraps a :class:`ConfigManager` as a :class:`SettingsStore`.

    Maps flat settings keys to hierarchical dot-notation paths via an optional
    prefix. Example: ``Get("theme")`` delegates to ``mgr.Get("ui.theme")``
    when ``prefix="ui"``; otherwise it tries ``mgr.Get("settings.<key>")``
    and falls back to an in-memory dict for arbitrary keys. This allows
    tenant-scoped settings (priority 150) to reuse the hierarchical config's
    persistence while still supporting free-form keys.

    Priority is configurable, default ``150`` places the tenant store between
    project (``200``) and file (``100``) stores.
    """

    def __init__(
        self,
        manager: ConfigManager,
        prefix: str | None = None,
        priority: int = 150,
        path: str | Path | None = None,
    ) -> None:
        self._mgr = manager
        self._prefix = prefix
        self._priority = priority
        self._path = Path(path) if path is not None else None
        self._mu = threading.RLock()
        self._fallback: dict[str, Any] = {}

    def _resolve_path(self, key: str) -> str:
        if self._prefix:
            if key.startswith(self._prefix + "."):
                return key
            return f"{self._prefix}.{key}"
        # No prefix → try settings.<key> namespace
        if key.startswith("settings."):
            return key
        return f"settings.{key}"

    def Get(self, key: str) -> tuple[Any, bool]:
        with self._mu:
            # 1. Try prefixed path via ConfigManager
            path = self._resolve_path(key)
            val = self._mgr.Get(path)
            if val is not None:
                return val, True
            # 2. If key itself is a dot-path, try directly
            if "." in key and key != path:
                direct = self._mgr.Get(key)
                if direct is not None:
                    return direct, True
            # 3. Fallback dict
            if key in self._fallback:
                return self._fallback[key], True
            return None, False

    def Set(self, key: str, value: Any) -> None:
        with self._mu:
            # Try to delegate to ConfigManager if path is valid
            path = self._resolve_path(key)
            try:
                self._mgr.Set(path, value)
                return
            except ValueError:
                pass
            # Try direct dot-path if key contains dot
            if "." in key and key != path:
                try:
                    self._mgr.Set(key, value)
                    return
                except ValueError:
                    pass
            # Fallback to in-memory dict for free-form keys
            self._fallback[key] = value

    def Delete(self, key: str) -> None:
        with self._mu:
            # Remove from fallback
            self._fallback.pop(key, None)
            # Attempt to reset hierarchical value to default if it exists
            path = self._resolve_path(key)
            current = self._mgr.Get(path)
            if current is not None:
                try:
                    defaults = asdict(default_hierarchical_config())
                    parts = path.split(".")
                    node: Any = defaults
                    for part in parts:
                        if isinstance(node, dict) and part in node:
                            node = node[part]
                        else:
                            node = None
                            break
                    if node is not None:
                        try:
                            self._mgr.Set(path, node)
                        except ValueError:
                            pass
                except Exception:
                    pass
            # Also handle direct dot-path keys
            if "." in key and key != path:
                cur2 = self._mgr.Get(key)
                if cur2 is not None:
                    try:
                        defaults2 = asdict(default_hierarchical_config())
                        parts2 = key.split(".")
                        node2: Any = defaults2
                        for part in parts2:
                            if isinstance(node2, dict) and part in node2:
                                node2 = node2[part]
                            else:
                                node2 = None
                                break
                        if node2 is not None:
                            try:
                                self._mgr.Set(key, node2)
                            except ValueError:
                                pass
                    except Exception:
                        pass

    def List(self) -> dict[str, Any]:
        with self._mu:
            result: dict[str, Any] = {}
            # If prefix is a known section, flatten that section
            if self._prefix and self._prefix in _SECTION_FIELDS:
                for field in _SECTION_FIELDS[self._prefix]:
                    val = self._mgr.Get(f"{self._prefix}.{field}")
                    if val is not None:
                        result[field] = val
            elif self._prefix:
                # Unknown prefix: try to get each field via Get, include fallback
                pass
            else:
                # No prefix: check for settings section (unlikely) otherwise fallback only
                pass
            # Merge fallback (fallback wins for overlapping keys)
            result.update(self._fallback)
            return result

    def Save(self) -> None:
        # Persist hierarchical config via manager and fallback dict if path is set
        if self._path is not None:
            with self._mu:
                data = dict(self._fallback)
            save_json_atomic(self._path, data)
        self._mgr.Save()

    def Load(self) -> None:
        self._mgr.Load()
        if self._path is not None:
            try:
                with open(self._path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    with self._mu:
                        self._fallback = data
            except FileNotFoundError:
                with self._mu:
                    self._fallback = {}
            except (OSError, json.JSONDecodeError) as exc:
                raise OSError(f"read tenant settings: {exc}") from exc

    def Priority(self) -> int:
        return self._priority


class UnifiedConfig:
    """Facade unifying :class:`ConfigManager` (typed, hierarchical) and
    :class:`SettingsManager` (flat, pluggable stores).

    Final priority (highest to lowest):

    1. CLI flags (runtime overrides)
    2. Env vars ``DXRK_*`` (via ConfigManager)
    3. Settings project (``.dxrk/settings.json``, priority 200)
    4. Settings tenant (``ConfigSettingsStore``, priority 150)
    5. Settings file (``~/.dxrk/settings.json``, priority 100)
    6. Config project (``.dxrk/config.yaml``)
    7. Config user (``~/.dxrk/config.yaml``)
    8. Config global (``/etc/dxrk/config.yaml``)
    9. Built-in defaults (``HierarchicalConfig``)

    ``load()`` calls ``config.Load()`` then ``settings.Load()`` in that
    order so that settings can override config where needed. ``save()``
    persists both layers. ``validate()`` delegates to ``config.Validate()``.
    """

    def __init__(
        self,
        config: ConfigManager | None = None,
        settings: SettingsManager | None = None,
    ) -> None:
        self.config: ConfigManager = config if config is not None else ConfigManager()
        if settings is not None:
            self.settings: SettingsManager = settings
        else:
            # Build default settings stack with tenant store (priority 150)
            # wrapping the same config instance for reuse.
            tenant_store = ConfigSettingsStore(self.config, priority=150)
            self.settings = SettingsManager([ProjectSettingsStore(), tenant_store, FileSettingsStore()])

    def get_typed(self, path: str) -> Any | None:
        """Returns a typed hierarchical value via ``ConfigManager.Get``."""
        return self.config.Get(path)

    def get_raw(self, key: str) -> Any:
        """Returns a flat setting via ``SettingsManager.Get`` (raises ``KeyError`` if missing)."""
        return self.settings.Get(key)

    def set_typed(self, path: str, value: Any) -> None:
        """Sets a typed hierarchical value via ``ConfigManager.Set``."""
        self.config.Set(path, value)

    def set_raw(self, key: str, value: Any) -> None:
        """Sets a flat setting via ``SettingsManager.Set`` (writes to highest-priority store)."""
        self.settings.Set(key, value)

    def load(self) -> None:
        """Loads both layers: hierarchical config then flat settings."""
        self.config.Load()
        self.settings.Load()

    def save(self) -> None:
        """Persists both layers: hierarchical config then flat settings."""
        self.config.Save()
        self.settings.Save()

    def validate(self) -> list[ConfigError]:
        """Validates the hierarchical config and returns any errors."""
        return self.config.Validate()

    # Compatibility aliases (CamelCase) for existing call sites if needed
    def Load(self) -> None:  # noqa: N802
        self.load()

    def Save(self) -> None:  # noqa: N802
        self.save()

    def Validate(self) -> list[ConfigError]:  # noqa: N802
        return self.validate()

    def GetTyped(self, path: str) -> Any | None:  # noqa: N802
        return self.get_typed(path)

    def GetRaw(self, key: str) -> Any:  # noqa: N802
        return self.get_raw(key)

    def SetTyped(self, path: str, value: Any) -> None:  # noqa: N802
        self.set_typed(path, value)

    def SetRaw(self, key: str, value: Any) -> None:  # noqa: N802
        self.set_raw(key, value)
