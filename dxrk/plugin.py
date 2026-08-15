# SPDX-License-Identifier: MIT
"""Plugin manager"""

from __future__ import annotations

import copy
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Callable

from dxrk.strconst import StrEnabled, StrError, StrUnknown
from dxrk.tools import Registry

# --- Lifecycle (mirrors lifecycle.go) ---


HookPoint = str

# Pre/post pairs for core operations.
HookBeforeLoad: HookPoint = "before_load"
HookAfterLoad: HookPoint = "after_load"
HookBeforeUnload: HookPoint = "before_unload"
HookAfterUnload: HookPoint = "after_unload"
HookBeforeEnable: HookPoint = "before_enable"
HookAfterEnable: HookPoint = "after_enable"
HookBeforeDisable: HookPoint = "before_disable"
HookAfterDisable: HookPoint = "after_disable"
HookBeforeUpdate: HookPoint = "before_update"
HookAfterUpdate: HookPoint = "after_update"
HookBeforeRegister: HookPoint = "before_register"
HookAfterRegister: HookPoint = "after_register"
HookBeforeDeregister: HookPoint = "before_deregister"
HookAfterDeregister: HookPoint = "after_deregister"
HookBeforeSettings: HookPoint = "before_settings"
HookAfterSettings: HookPoint = "after_settings"

# Pre/post pairs for tool operations.
HookBeforeToolExec: HookPoint = "before_tool_exec"
HookAfterToolExec: HookPoint = "after_tool_exec"
HookBeforeToolReg: HookPoint = "before_tool_register"
HookAfterToolReg: HookPoint = "after_tool_register"
HookBeforeToolDereg: HookPoint = "before_tool_deregister"
HookAfterToolDereg: HookPoint = "after_tool_deregister"

# Pre/post pairs for MCP operations.
HookBeforeMCPStart: HookPoint = "before_mcp_start"
HookAfterMCPStart: HookPoint = "after_mcp_start"
HookBeforeMCPStop: HookPoint = "before_mcp_stop"
HookAfterMCPStop: HookPoint = "after_mcp_stop"
HookBeforeMCPConfig: HookPoint = "before_mcp_config"
HookAfterMCPConfig: HookPoint = "after_mcp_config"

# Pre/post pairs for skill operations.
HookBeforeSkillLoad: HookPoint = "before_skill_load"
HookAfterSkillLoad: HookPoint = "after_skill_load"
HookBeforeSkillExec: HookPoint = "before_skill_exec"
HookAfterSkillExec: HookPoint = "after_skill_exec"

# Pre/post pairs for hook operations.
HookBeforeHookExec: HookPoint = "before_hook_exec"
HookAfterHookExec: HookPoint = "after_hook_exec"


@dataclass
class HookEvent:
    """Metadata about a hook invocation."""

    point: HookPoint = ""
    plugin_id: str = ""
    time: datetime = field(default_factory=datetime.now)
    data: dict[str, object] = field(default_factory=dict)


HookFunc = Callable[[HookEvent], str | None]


@dataclass
class HookRegistration:
    id: str = ""
    point: HookPoint = ""
    priority: int = 0  # Lower = runs first
    fn: HookFunc | None = None


class HookManager:
    """Manages lifecycle hooks for plugins."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._hooks: dict[HookPoint, list[HookRegistration]] = {}
        self._next_id = 0

    def register(self, point: HookPoint, priority: int, fn: HookFunc) -> str:
        """Add a hook callback for a given hook point, sorted by priority."""
        with self._lock:
            self._next_id += 1
            hook_id = f"hook-{self._next_id}"
            registration = HookRegistration(
                id=hook_id, point=point, priority=priority, fn=fn
            )
            hooks = list(self._hooks.get(point, []))
            insert_at = len(hooks)
            for index, existing in enumerate(hooks):
                if priority < existing.priority:
                    insert_at = index
                    break
            hooks.insert(insert_at, registration)
            self._hooks[point] = hooks
            return hook_id

    def remove(self, hook_id: str) -> None:
        """Remove a hook by its ID."""
        with self._lock:
            for point, hooks in list(self._hooks.items()):
                for index, registration in enumerate(hooks):
                    if registration.id == hook_id:
                        remaining = hooks[:index] + hooks[index + 1 :]
                        if remaining:
                            self._hooks[point] = remaining
                        else:
                            del self._hooks[point]
                        return

    def execute(
        self,
        point: HookPoint,
        plugin_id: str,
        data: dict[str, object] | None = None,
    ) -> str | None:
        """Run all hooks for a point in priority order; return the first error."""
        with self._lock:
            hooks = list(self._hooks.get(point, []))
        event = HookEvent(point=point, plugin_id=plugin_id, data=data or {})
        for registration in hooks:
            if registration.fn is None:
                continue
            err = registration.fn(event)
            if err is not None:
                return f"hook {point} ({registration.id}) failed: {err}"
        return None

    def clear(self) -> None:
        """Remove all hooks."""
        with self._lock:
            self._hooks = {}

    def hook_count(self, point: HookPoint) -> int:
        """Number of hooks registered for a point."""
        with self._lock:
            return len(self._hooks.get(point, []))

    def total_hooks(self) -> int:
        """Total number of registered hooks."""
        with self._lock:
            return sum(len(hooks) for hooks in self._hooks.values())


def new_hook_manager() -> HookManager:
    return HookManager()


# --- Manager (mirrors manager.go) ---


RegisterFn = Callable[[Registry], str | None]


@dataclass
class Plugin:
    """An external tool provider."""

    name: str = ""
    description: str = ""
    version: str = ""
    register: RegisterFn | None = None


@dataclass
class Manifest:
    name: str = ""
    description: str = ""
    version: str = ""
    entry: str = ""


class Manager:
    """Discovers and loads tool plugins."""

    def __init__(self, registry: Registry, plugins_dir: str | Path) -> None:
        self._registry = registry
        self._plugins_dir = Path(plugins_dir)
        self._plugins: list[Plugin] = []

    def register(self, plugin: Plugin) -> str | None:
        """Add a plugin to the manager."""
        if not plugin.name:
            return "plugin name is required"
        if plugin.register is None:
            return f'plugin "{plugin.name}": Register function is required'
        self._plugins.append(plugin)
        return None

    def load_all(self) -> tuple[int, str | None]:
        """Load all registered plugins."""
        loaded = 0
        for plugin in self._plugins:
            if plugin.register is None:
                return (
                    loaded,
                    f'load plugin "{plugin.name}": Register function is required',
                )
            err = plugin.register(self._registry)
            if err is not None:
                return loaded, f'load plugin "{plugin.name}": {err}'
            loaded += 1
        return loaded, None

    def discover(self) -> tuple[list[Manifest], str | None]:
        """Scan the plugins directory; manifests are discovered but not loaded."""
        try:
            entries = list(self._plugins_dir.iterdir())
        except FileNotFoundError:
            return [], None
        except OSError as exc:
            return [], f'read plugins dir "{self._plugins_dir}": {exc}'
        for entry in entries:
            if not entry.is_dir():
                continue
            manifest_path = entry / "plugin.json"
            if not manifest_path.exists():
                continue
            # Found a manifest (actual loading deferred to LoadAll).
        return [], None

    def plugins(self) -> list[Plugin]:
        """List of registered plugins."""
        return list(self._plugins)


def new_manager(registry: Registry, plugins_dir: str | Path) -> Manager:
    return Manager(registry, plugins_dir)


# --- Marketplace (mirrors marketplace.go) ---


class PluginStatus(IntEnum):
    StatusInstalled = 0
    StatusEnabled = 1
    StatusDisabled = 2
    StatusUpdating = 3
    StatusError = 4

    def __str__(self) -> str:
        match self:
            case PluginStatus.StatusInstalled:
                return "installed"
            case PluginStatus.StatusEnabled:
                return StrEnabled
            case PluginStatus.StatusDisabled:
                return "disabled"
            case PluginStatus.StatusUpdating:
                return "updating"
            case PluginStatus.StatusError:
                return StrError
            case _:
                return StrUnknown


@dataclass
class PluginSkill:
    name: str = ""
    path: str = ""
    description: str = ""


@dataclass
class PluginHook:
    name: str = ""
    point: HookPoint = ""
    priority: int = 0


@dataclass
class PluginMCP:
    name: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class PluginTool:
    name: str = ""
    description: str = ""


@dataclass
class PluginComponents:
    skills: list[PluginSkill] = field(default_factory=list)
    hooks: list[PluginHook] = field(default_factory=list)
    mcps: list[PluginMCP] = field(default_factory=list)
    tools: list[PluginTool] = field(default_factory=list)


@dataclass
class PluginSettings:
    requires_approval: bool = False
    max_instances: int = 0
    timeout: float = 0.0  # seconds
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class PluginMetadata:
    id: str = ""
    name: str = ""
    version: str = ""
    description: str = ""
    author: str = ""
    license: str = ""
    tags: list[str] = field(default_factory=list)
    homepage: str = ""
    repository: str = ""
    components: PluginComponents = field(default_factory=PluginComponents)
    settings: PluginSettings = field(default_factory=PluginSettings)
    status: PluginStatus = PluginStatus.StatusInstalled
    installed_at: datetime | None = None
    updated_at: datetime | None = None
    enabled: bool = False

    def to_json(self) -> str:
        return json.dumps(_serialize_metadata(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> PluginMetadata:
        return _deserialize_metadata(json.loads(text))


@dataclass
class MarketplaceEvent:
    """Describes a marketplace change."""

    type: str = ""  # "installed", "updated", "removed", "enabled", "disabled"
    plugin_id: str = ""
    time: datetime = field(default_factory=datetime.now)


OnChangeFn = Callable[[MarketplaceEvent], None]


class Marketplace:
    """Manages plugin discovery, installation, and updates."""

    def __init__(self, plugins_dir: str | Path) -> None:
        self._lock = threading.RLock()
        self._registry: dict[str, PluginMetadata] = {}
        self._plugins_dir = Path(plugins_dir)
        self._on_change: OnChangeFn | None = None

    def set_on_change(self, fn: OnChangeFn | None) -> None:
        """Set a callback for marketplace events."""
        with self._lock:
            self._on_change = fn

    def _emit_event(self, event_type: str, plugin_id: str) -> None:
        with self._lock:
            fn = self._on_change
        if fn is not None:
            fn(MarketplaceEvent(type=event_type, plugin_id=plugin_id))

    def scan(self) -> str | None:
        """Scan the plugins directory for installed plugins."""
        with self._lock:
            try:
                entries = list(self._plugins_dir.iterdir())
            except FileNotFoundError:
                return None
            except OSError as exc:
                return f"read plugins dir: {exc}"
            for entry in entries:
                if not entry.is_dir():
                    continue
                manifest_path = entry / "plugin.json"
                try:
                    text = manifest_path.read_text()
                except OSError:
                    continue
                try:
                    meta = PluginMetadata.from_json(text)
                except (ValueError, TypeError):
                    continue
                meta.status = PluginStatus.StatusInstalled
                self._registry[meta.id] = meta
            return None

    def install(self, meta: PluginMetadata) -> str | None:
        """Install a plugin from a manifest."""
        with self._lock:
            if meta.id in self._registry:
                return f"plugin {meta.id} already installed"
            stored = copy.copy(meta)
            stored.status = PluginStatus.StatusEnabled
            stored.enabled = True
            stored.installed_at = datetime.now()
            self._registry[stored.id] = stored
            self._emit_event("installed", stored.id)
            return None

    def uninstall(self, plugin_id: str) -> str | None:
        """Remove a plugin from the marketplace."""
        with self._lock:
            if plugin_id not in self._registry:
                return f"plugin {plugin_id} not found"
            del self._registry[plugin_id]
            self._emit_event("removed", plugin_id)
            return None

    def enable(self, plugin_id: str) -> str | None:
        """Enable a plugin."""
        with self._lock:
            meta = self._registry.get(plugin_id)
            if meta is None:
                return f"plugin {plugin_id} not found"
            meta.enabled = True
            meta.status = PluginStatus.StatusEnabled
            self._emit_event(StrEnabled, plugin_id)
            return None

    def disable(self, plugin_id: str) -> str | None:
        """Disable a plugin."""
        with self._lock:
            meta = self._registry.get(plugin_id)
            if meta is None:
                return f"plugin {plugin_id} not found"
            meta.enabled = False
            meta.status = PluginStatus.StatusDisabled
            self._emit_event("disabled", plugin_id)
            return None

    def get(self, plugin_id: str) -> PluginMetadata | None:
        """Metadata for a plugin."""
        with self._lock:
            return self._registry.get(plugin_id)

    def list_plugins(self) -> list[PluginMetadata]:
        """All registered plugins, sorted by name."""
        with self._lock:
            return sorted(self._registry.values(), key=lambda m: m.name)

    def enabled_plugins(self) -> list[PluginMetadata]:
        """Enabled plugins, sorted by name."""
        with self._lock:
            return sorted(
                (m for m in self._registry.values() if m.enabled),
                key=lambda m: m.name,
            )

    def update_available(self, plugin_id: str, latest_version: str) -> bool:
        """Check if an update is available for a plugin."""
        with self._lock:
            meta = self._registry.get(plugin_id)
            if meta is None:
                return False
            return meta.version != latest_version


def new_marketplace(plugins_dir: str | Path) -> Marketplace:
    return Marketplace(plugins_dir)


# --- Policy (mirrors policy.go) ---


class PolicyLevel(IntEnum):
    PolicyAdvisory = 0  # Log but allow
    PolicyEnforce = 1  # Block if policy violated

    def __str__(self) -> str:
        match self:
            case PolicyLevel.PolicyAdvisory:
                return "advisory"
            case PolicyLevel.PolicyEnforce:
                return "enforce"
            case _:
                return StrUnknown


@dataclass
class PluginApprovalConfig:
    """Controls when plugin actions require approval."""

    install: bool = False
    enable: bool = False
    disable: bool = False
    update: bool = False
    hook_exec: bool = False


@dataclass
class PluginTimeoutPolicy:
    """Timeout limits in seconds."""

    max_load_time: float = 0.0
    max_hook_time: float = 0.0
    max_mcp_start_time: float = 0.0


@dataclass
class EnterprisePolicy:
    """Organizational rules for plugin usage."""

    level: PolicyLevel = PolicyLevel.PolicyAdvisory
    allowed_plugins: list[str] = field(default_factory=list)  # Allowlist of plugin IDs
    blocked_plugins: list[str] = field(default_factory=list)  # Blocklist of plugin IDs
    allowed_authors: list[str] = field(
        default_factory=list
    )  # Only plugins from these authors
    max_plugin_version: str = ""  # Max semver allowed
    required_tags: list[str] = field(
        default_factory=list
    )  # Plugins must have these tags
    blocked_tags: list[str] = field(
        default_factory=list
    )  # Plugins with these tags are blocked
    restricted_hooks: list[HookPoint] = field(
        default_factory=list
    )  # Hooks that require approval
    approval_required: PluginApprovalConfig = field(
        default_factory=PluginApprovalConfig
    )
    audit_log: bool = False  # Log all plugin operations
    max_plugins: int = 0  # Max concurrent plugins (0 = unlimited)
    timeout_policy: PluginTimeoutPolicy = field(default_factory=PluginTimeoutPolicy)

    def to_json(self) -> str:
        return json.dumps(_serialize_policy(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> EnterprisePolicy:
        return _deserialize_policy(json.loads(text))


@dataclass
class AuditEntry:
    """Records a plugin operation for auditing."""

    timestamp: datetime = field(default_factory=datetime.now)
    action: str = ""
    plugin_id: str = ""
    user: str = ""
    allowed: bool = False
    reason: str = ""
    details: dict[str, str] = field(default_factory=dict)


class PolicyManager:
    """Enforces enterprise plugin policies."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._policy = EnterprisePolicy(
            level=PolicyLevel.PolicyAdvisory,
            max_plugins=0,
            audit_log=False,
            timeout_policy=PluginTimeoutPolicy(
                max_load_time=10.0,
                max_hook_time=30.0,
                max_mcp_start_time=15.0,
            ),
        )
        self._audit_log: list[AuditEntry] = []
        self._max_audit = 1000

    def load_policy(self, path: str | Path) -> str | None:
        """Load a policy from a JSON file."""
        policy_path = Path(path)
        try:
            text = policy_path.read_text()
        except OSError as exc:
            return f"read policy file: {exc}"
        try:
            policy = EnterprisePolicy.from_json(text)
        except (ValueError, TypeError) as exc:
            return f"parse policy: {exc}"
        with self._lock:
            self._policy = policy
        return None

    def save_policy(self, path: str | Path) -> str | None:
        """Save the current policy to a JSON file."""
        policy_path = Path(path)
        try:
            policy_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            policy_path.write_text(self._policy.to_json() + "\n")
            policy_path.chmod(0o600)
        except OSError as exc:
            return str(exc)
        return None

    def get_policy(self) -> EnterprisePolicy:
        """A copy of the current policy."""
        with self._lock:
            return copy.copy(self._policy)

    def check_install(self, meta: PluginMetadata) -> tuple[bool, str]:
        """Check if a plugin can be installed per policy."""
        with self._lock:
            policy = self._policy

        for blocked in policy.blocked_plugins:
            if blocked == meta.id:
                self._audit("install", meta.id, False, "plugin is blocked")
                return False, "plugin is in the blocked list"

        if policy.allowed_plugins:
            if meta.id not in policy.allowed_plugins:
                self._audit("install", meta.id, False, "plugin not in allowlist")
                return False, "plugin is not in the allowed list"

        if policy.allowed_authors:
            if meta.author not in policy.allowed_authors:
                self._audit("install", meta.id, False, "author not allowed")
                return False, "plugin author is not in the allowed authors list"

        for blocked_tag in policy.blocked_tags:
            for tag in meta.tags:
                if tag == blocked_tag:
                    self._audit("install", meta.id, False, f"blocked tag: {tag}")
                    return False, f"plugin has blocked tag: {tag}"

        if policy.max_plugins > 0:
            self._audit("install", meta.id, True, "within plugin limit")

        self._audit("install", meta.id, True, "policy check passed")
        return True, ""

    def check_hook_exec(self, plugin_id: str, point: HookPoint) -> tuple[bool, str]:
        """Check if a hook can be executed per policy."""
        with self._lock:
            restricted = list(self._policy.restricted_hooks)

        if point in restricted:
            self._audit("hook_exec", plugin_id, False, f"restricted hook: {point}")
            return False, f"hook {point} requires approval"

        self._audit("hook_exec", plugin_id, True, "policy check passed")
        return True, ""

    def is_plugin_allowed(self, plugin_id: str) -> bool:
        """Check if a plugin is generally allowed."""
        with self._lock:
            policy = self._policy

        for blocked in policy.blocked_plugins:
            if blocked == plugin_id:
                return False

        if policy.allowed_plugins:
            return plugin_id in policy.allowed_plugins

        return True

    def _audit(self, action: str, plugin_id: str, allowed: bool, reason: str) -> None:
        with self._lock:
            audit_enabled = self._policy.audit_log
        if not audit_enabled:
            return
        entry = AuditEntry(
            timestamp=datetime.now(),
            action=action,
            plugin_id=plugin_id,
            allowed=allowed,
            reason=reason,
        )
        with self._lock:
            self._audit_log.append(entry)
            if len(self._audit_log) > self._max_audit:
                if self._max_audit <= 0:
                    self._audit_log = []
                else:
                    self._audit_log = self._audit_log[-self._max_audit :]

    def get_audit_log(self) -> list[AuditEntry]:
        """A copy of the audit log."""
        with self._lock:
            return list(self._audit_log)


def new_policy_manager() -> PolicyManager:
    return PolicyManager()


# --- JSON helpers ---


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class _JsonReader:
    """Strict-typed accessor over a JSON object (mirrors encoding/json)."""

    def __init__(self, raw: object) -> None:
        if not isinstance(raw, dict):
            raise TypeError("expected a JSON object")
        self._raw = raw

    def get_str(self, key: str) -> str:
        value = self._raw.get(key, "")
        if value is None:
            return ""
        if not isinstance(value, str):
            raise TypeError(f"field {key!r} must be a string")
        return value

    def get_int(self, key: str) -> int:
        value = self._raw.get(key, 0)
        if value is None:
            return 0
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"field {key!r} must be an integer")
        return value

    def get_float(self, key: str) -> float:
        value = self._raw.get(key, 0.0)
        if value is None:
            return 0.0
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"field {key!r} must be a number")
        return float(value)

    def get_bool(self, key: str) -> bool:
        value = self._raw.get(key, False)
        if value is None:
            return False
        if not isinstance(value, bool):
            raise TypeError(f"field {key!r} must be a boolean")
        return value

    def get_str_list(self, key: str) -> list[str]:
        value = self._raw.get(key, [])
        if value is None:
            return []
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise TypeError(f"field {key!r} must be a list of strings")
        return list(value)

    def get_str_map(self, key: str) -> dict[str, str]:
        value = self._raw.get(key, {})
        if value is None:
            return {}
        if not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        ):
            raise TypeError(f"field {key!r} must be a map of strings")
        return dict(value)

    def get_obj(self, key: str) -> _JsonReader:
        value = self._raw.get(key, {})
        if value is None:
            return _JsonReader({})
        if not isinstance(value, dict):
            raise TypeError(f"field {key!r} must be an object")
        return _JsonReader(value)

    def get_obj_list(self, key: str) -> list[_JsonReader]:
        value = self._raw.get(key, [])
        if value is None:
            return []
        if not isinstance(value, list) or not all(
            isinstance(item, dict) for item in value
        ):
            raise TypeError(f"field {key!r} must be a list of objects")
        return [_JsonReader(item) for item in value]


def _serialize_metadata(meta: PluginMetadata) -> dict[str, object]:
    components = meta.components
    settings = meta.settings
    return {
        "id": meta.id,
        "name": meta.name,
        "version": meta.version,
        "description": meta.description,
        "author": meta.author,
        "license": meta.license,
        "tags": list(meta.tags),
        "homepage": meta.homepage,
        "repository": meta.repository,
        "components": {
            "skills": [
                {"name": s.name, "path": s.path, "description": s.description}
                for s in components.skills
            ],
            "hooks": [
                {"name": h.name, "point": h.point, "priority": h.priority}
                for h in components.hooks
            ],
            "mcps": [
                {
                    "name": m.name,
                    "command": m.command,
                    "args": list(m.args),
                    "env": dict(m.env),
                }
                for m in components.mcps
            ],
            "tools": [
                {"name": t.name, "description": t.description} for t in components.tools
            ],
        },
        "settings": {
            "requires_approval": settings.requires_approval,
            "max_instances": settings.max_instances,
            "timeout": settings.timeout,
            "env": dict(settings.env),
        },
        "status": int(meta.status),
        "installed_at": _iso(meta.installed_at),
        "updated_at": _iso(meta.updated_at),
        "enabled": meta.enabled,
    }


def _deserialize_metadata(raw: object) -> PluginMetadata:
    r = _JsonReader(raw)
    components = r.get_obj("components")
    settings = r.get_obj("settings")
    return PluginMetadata(
        id=r.get_str("id"),
        name=r.get_str("name"),
        version=r.get_str("version"),
        description=r.get_str("description"),
        author=r.get_str("author"),
        license=r.get_str("license"),
        tags=r.get_str_list("tags"),
        homepage=r.get_str("homepage"),
        repository=r.get_str("repository"),
        components=PluginComponents(
            skills=[
                PluginSkill(
                    name=s.get_str("name"),
                    path=s.get_str("path"),
                    description=s.get_str("description"),
                )
                for s in components.get_obj_list("skills")
            ],
            hooks=[
                PluginHook(
                    name=h.get_str("name"),
                    point=h.get_str("point"),
                    priority=h.get_int("priority"),
                )
                for h in components.get_obj_list("hooks")
            ],
            mcps=[
                PluginMCP(
                    name=m.get_str("name"),
                    command=m.get_str("command"),
                    args=m.get_str_list("args"),
                    env=m.get_str_map("env"),
                )
                for m in components.get_obj_list("mcps")
            ],
            tools=[
                PluginTool(name=t.get_str("name"), description=t.get_str("description"))
                for t in components.get_obj_list("tools")
            ],
        ),
        settings=PluginSettings(
            requires_approval=settings.get_bool("requires_approval"),
            max_instances=settings.get_int("max_instances"),
            timeout=settings.get_float("timeout"),
            env=settings.get_str_map("env"),
        ),
        status=PluginStatus(r.get_int("status")),
        installed_at=_parse_time(r.get_str("installed_at")),
        updated_at=_parse_time(r.get_str("updated_at")),
        enabled=r.get_bool("enabled"),
    )


def _serialize_policy(policy: EnterprisePolicy) -> dict[str, object]:
    approval = policy.approval_required
    timeout = policy.timeout_policy
    return {
        "level": int(policy.level),
        "allowed_plugins": list(policy.allowed_plugins),
        "blocked_plugins": list(policy.blocked_plugins),
        "allowed_authors": list(policy.allowed_authors),
        "max_plugin_version": policy.max_plugin_version,
        "required_tags": list(policy.required_tags),
        "blocked_tags": list(policy.blocked_tags),
        "restricted_hooks": list(policy.restricted_hooks),
        "approval_required": {
            "install": approval.install,
            "enable": approval.enable,
            "disable": approval.disable,
            "update": approval.update,
            "hook_exec": approval.hook_exec,
        },
        "audit_log": policy.audit_log,
        "max_plugins": policy.max_plugins,
        "timeout_policy": {
            "max_load_time": timeout.max_load_time,
            "max_hook_time": timeout.max_hook_time,
            "max_mcp_start_time": timeout.max_mcp_start_time,
        },
    }


def _deserialize_policy(raw: object) -> EnterprisePolicy:
    r = _JsonReader(raw)
    approval = r.get_obj("approval_required")
    timeout = r.get_obj("timeout_policy")
    return EnterprisePolicy(
        level=PolicyLevel(r.get_int("level")),
        allowed_plugins=r.get_str_list("allowed_plugins"),
        blocked_plugins=r.get_str_list("blocked_plugins"),
        allowed_authors=r.get_str_list("allowed_authors"),
        max_plugin_version=r.get_str("max_plugin_version"),
        required_tags=r.get_str_list("required_tags"),
        blocked_tags=r.get_str_list("blocked_tags"),
        restricted_hooks=r.get_str_list("restricted_hooks"),
        approval_required=PluginApprovalConfig(
            install=approval.get_bool("install"),
            enable=approval.get_bool("enable"),
            disable=approval.get_bool("disable"),
            update=approval.get_bool("update"),
            hook_exec=approval.get_bool("hook_exec"),
        ),
        audit_log=r.get_bool("audit_log"),
        max_plugins=r.get_int("max_plugins"),
        timeout_policy=PluginTimeoutPolicy(
            max_load_time=timeout.get_float("max_load_time"),
            max_hook_time=timeout.get_float("max_hook_time"),
            max_mcp_start_time=timeout.get_float("max_mcp_start_time"),
        ),
    )
