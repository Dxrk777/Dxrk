# SPDX-License-Identifier: MIT
"""Tests for dxrk.config (mirrors internal/config)."""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from dxrk.config import (
    APIValidator,
    ConfigManager,
    ConflictLocalWins,
    ConflictManual,
    ConflictRemoteWins,
    Default,
    FeatureFlag,
    FeatureFlagManager,
    FilterErrors,
    FormatErrors,
    HasErrors,
    HierarchicalConfig,
    Load,
    LoadViper,
    MemorySettingsStore,
    ModelValidator,
    NewDefaultSettingsManager,
    NewFileSettingsStore,
    NewSettingsSyncer,
    PathValidator,
    PortValidator,
    ProviderByName,
    Save,
    SettingChange,
    SyncConfig,
    ValidateConfig,
    expand_path,
)

# ---- Legacy Config (config_test.go) ----


def test_default_is_complete():
    cfg = Default()
    assert cfg is not None
    assert len(cfg.providers) > 0
    assert cfg.sandbox is not None
    assert cfg.autonomy is not None


def test_load_save_roundtrip(tmp_path):
    cfg = Default()
    path = str(tmp_path / "config.yaml")
    Save(path, cfg)
    loaded = Load(path)
    assert loaded.project.name == "my-project"
    assert len(loaded.providers) == 4


def test_load_nonexistent_creates_default(tmp_path):
    path = str(tmp_path / "nested" / "config.yaml")
    loaded = Load(path)
    assert loaded.project.name == "my-project"
    assert os.path.exists(path)


def test_provider_by_name():
    cfg = Default()
    assert cfg.providers[0].name == "claude"
    provider = ProviderByName(cfg, "claude")
    assert provider is not None
    assert provider.model == "claude-sonnet-4-20250514"
    assert ProviderByName(cfg, "nope") is None


def test_sandbox_defaults():
    cfg = Default()
    assert cfg.sandbox.default_image == "ubuntu:22.04"
    assert cfg.sandbox.timeout_sec == 120


def test_autonomy_defaults():
    cfg = Default()
    assert cfg.autonomy.self_update is True
    assert cfg.autonomy.self_verify is True
    assert cfg.autonomy.self_learn is True
    assert cfg.autonomy.interval_sec == 300


# ---- ConfigManager ----


def test_config_manager_defaults():
    mgr = ConfigManager()
    assert mgr.Get("model.provider") == "claude"
    assert mgr.Get("model.model_name") == "claude-sonnet-4-20250514"
    assert mgr.Get("api.timeout") == 30
    assert mgr.Get("tools.max_concurrent") == 5
    assert mgr.Get("bogus.key") is None
    assert mgr.Get("bogus") is None


def test_config_manager_set_get_watch():
    mgr = ConfigManager()
    seen = []
    mgr.Watch("model.provider", lambda path, value: seen.append((path, value)))
    mgr.Set("model.provider", "openai")
    assert mgr.Get("model.provider") == "openai"
    assert seen == [("model.provider", "openai")]


def test_config_manager_set_invalid_path():
    mgr = ConfigManager()
    with pytest.raises(ValueError):
        mgr.Set("model", "x")
    with pytest.raises(ValueError):
        mgr.Set("nope.key", "x")


def test_config_manager_merge_and_reset():
    mgr = ConfigManager()
    mgr.merge({"model": {"provider": "gemini"}, "api": {"timeout": 60}})
    assert mgr.Get("model.provider") == "gemini"
    assert mgr.Get("api.timeout") == 60
    mgr.Reset("model")
    assert mgr.Get("model.provider") == "claude"
    with pytest.raises(ValueError):
        mgr.Reset("bogus")


def test_config_manager_env_overrides(monkeypatch):
    mgr = ConfigManager()
    monkeypatch.setenv("DXRK_MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("DXRK_API_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("DXRK_MODEL_TEMPERATURE", "1.5")
    monkeypatch.setenv("DXRK_ADVANCED_DEBUG", "true")
    monkeypatch.setenv("DXRK_UI_COMPACT_MODE", "1")
    mgr.Load()
    assert mgr.Get("model.provider") == "ollama"
    assert mgr.Get("api.base_url") == "http://localhost:11434"
    assert mgr.Get("model.temperature") == 1.5
    assert mgr.Get("advanced.debug") is True
    assert mgr.Get("ui.compact_mode") is True


def test_config_manager_save(tmp_path):
    mgr = ConfigManager([__import__("dxrk.config", fromlist=["WithUserPath"]).WithUserPath(str(tmp_path / "c.json"))])
    mgr.Set("model.provider", "openai")
    mgr.Save()
    saved = json.loads((tmp_path / "c.json").read_text())
    assert saved["model"]["provider"] == "openai"


def test_config_manager_load_from_viper():
    mgr = ConfigManager()
    mgr.LoadFromViper(
        {
            "model": {"provider": "gemini", "max_tokens": 16384},
            "api": {"base_url": "https://api.example.com"},
            "auth": {"scopes": ["read"]},
        }
    )
    assert mgr.Get("model.provider") == "gemini"
    assert mgr.Get("model.max_tokens") == 16384
    assert mgr.Get("auth.scopes") == ["read"]


def test_load_viper_file(tmp_path):
    path = tmp_path / "viper.yaml"
    path.write_text("model:\n  provider: ollama\n  temperature: 0.3\napi:\n  base_url: http://localhost:11434\n")
    cfg = LoadViper(str(path))
    assert cfg.model.provider == "ollama"
    assert cfg.model.temperature == 0.3
    assert cfg.api.base_url == "http://localhost:11434"


# ---- Settings ----


def test_settings_manager_priority_and_merge():
    mgr = NewDefaultSettingsManager()
    project = mgr._stores[0]
    file_store = mgr._stores[1]
    assert project.Priority() == 200
    assert file_store.Priority() == 100
    project.Set("theme", "dark")
    file_store.Set("theme", "light")
    file_store.Set("other", "file-only")
    assert mgr.Get("theme") == "dark"
    assert mgr.Get("other") == "file-only"
    assert mgr.Keys() == ["other", "theme"]
    assert mgr.Has("theme")
    assert not mgr.Has("missing")
    assert mgr.GetWithDefault("missing", "fallback") == "fallback"
    assert mgr.KeysByPrefix("th") == ["theme"]


def test_settings_memory_store():
    store = MemorySettingsStore(priority=50)
    store.Set("k", 1)
    assert store.Get("k") == (1, True)
    assert store.Get("nope") == (None, False)
    store.Delete("k")
    assert store.Get("k") == (None, False)
    store.Save()
    store.Load()


def test_settings_file_store_roundtrip(tmp_path):
    store = NewFileSettingsStore()
    store._path = str(tmp_path / "settings.json")
    store.Set("key", {"nested": True})
    store.Save()
    other = NewFileSettingsStore()
    other._path = str(tmp_path / "settings.json")
    other.Load()
    assert other.Get("key") == ({"nested": True}, True)


def test_settings_export_import():
    mgr = NewDefaultSettingsManager()
    mgr.Set("a", 1)
    mgr.Set("b", "two")
    data = mgr.Export()
    other = NewDefaultSettingsManager()
    other.Import(data)
    assert other.Get("a") == 1
    assert other.Get("b") == "two"
    with pytest.raises(ValueError):
        other.Import(b"not json")


# ---- Sync ----


def _change(key, value, ts, operation="set"):
    return SettingChange(key=key, value=value, timestamp=ts, device_id="dev", operation=operation)


def test_sync_resolve_last_write_wins():
    s = NewSettingsSyncer(SyncConfig(device_id="dev"), MemorySettingsStore())
    earlier_local = _change("k", "local", datetime(2025, 1, 1, tzinfo=UTC))
    later_remote = _change("k", "remote", datetime(2025, 1, 2, tzinfo=UTC))
    assert s.ResolveConflicts([earlier_local], [later_remote])[0].value == "remote"
    assert s.ResolveConflicts([later_remote], [earlier_local])[0].value == "remote"


def test_sync_resolve_strategies():
    local = _change("k", "local", datetime(2025, 1, 2, tzinfo=UTC))
    remote = _change("k", "remote", datetime(2025, 1, 1, tzinfo=UTC))
    s = NewSettingsSyncer(SyncConfig(device_id="dev"), MemorySettingsStore())
    s.SetResolver(ConflictLocalWins)
    assert s.ResolveConflicts([local], [remote])[0].value == "local"
    s.SetResolver(ConflictRemoteWins)
    assert s.ResolveConflicts([local], [remote])[0].value == "remote"
    s.SetResolver(ConflictManual)
    merged = s.ResolveConflicts([local], [remote])
    assert len(merged) == 2
    assert {c.value for c in merged} == {"local", "remote"}


def test_sync_local_only_and_ordering():
    s = NewSettingsSyncer(SyncConfig(device_id="dev"), MemorySettingsStore())
    local = _change("a", 1, datetime(2025, 1, 2, tzinfo=UTC))
    remote = _change("b", 2, datetime(2025, 1, 1, tzinfo=UTC))
    merged = s.ResolveConflicts([local], [remote])
    assert [c.key for c in merged] == ["b", "a"]


def test_sync_push_requires_endpoint():
    s = NewSettingsSyncer(SyncConfig(device_id="dev"), MemorySettingsStore())
    with pytest.raises(ValueError):
        s.Push([_change("k", 1, datetime(2025, 1, 1, tzinfo=UTC))])


def test_sync_queue_and_flush(tmp_path):
    store = MemorySettingsStore()
    server = _FakeSyncServer(tmp_path)
    server.start()
    try:
        s = NewSettingsSyncer(
            SyncConfig(endpoint=f"http://127.0.0.1:{server.port}", device_id="dev"),
            store,
        )
        s.QueueChange("a", 1)
        s.QueueChange("b", 2)
        assert s.GetSyncStatus().pending_push == 2
        s.FlushQueue()
        assert s.GetSyncStatus().pending_push == 0
        assert server.pushed == 1
    finally:
        server.stop()


def test_sync_full_cycle(tmp_path):
    store = MemorySettingsStore()
    store.Set("theme", "dark")
    server = _FakeSyncServer(
        tmp_path,
        remote_changes=[
            {
                "key": "remote_key",
                "value": "from-server",
                "timestamp": "2025-01-01T10:00:00Z",
                "device_id": "other",
                "operation": "set",
            },
        ],
    )
    server.start()
    try:
        s = NewSettingsSyncer(
            SyncConfig(endpoint=f"http://127.0.0.1:{server.port}", device_id="dev"),
            store,
        )
        s.Sync()
        assert s.GetSyncStatus().connected is True
        assert store.Get("remote_key") == ("from-server", True)
        assert server.pushed == 1
    finally:
        server.stop()


def test_sync_apply_conflict_marker_skipped():
    store = MemorySettingsStore()
    s = NewSettingsSyncer(SyncConfig(device_id="dev"), store)
    changes = [
        _change("__conflict__k", "local", datetime(2025, 1, 1, tzinfo=UTC)),
        _change("k", "remote", datetime(2025, 1, 2, tzinfo=UTC)),
        _change("del", None, datetime(2025, 1, 3, tzinfo=UTC), operation="delete"),
    ]
    store.Set("del", "old")
    s._apply_changes(changes)
    assert store.Get("k") == ("remote", True)
    assert store.Get("__conflict__k") == (None, False)
    assert store.Get("del") == (None, False)


# ---- Validators ----


def test_model_validator_messages():
    cfg = HierarchicalConfig()
    cfg.model.provider = ""
    cfg.model.model_name = ""
    cfg.model.max_tokens = -5
    cfg.model.temperature = 3.0
    cfg.model.top_p = 1.5
    errs = ModelValidator().Validate(cfg)
    paths = {e.path: e for e in errs}
    assert paths["model.provider"].severity == "error"
    assert "must not be empty" in paths["model.provider"].message
    assert paths["model.model_name"].severity == "error"
    assert paths["model.max_tokens"].message == "max_tokens must be non-negative, got -5"
    assert paths["model.temperature"].message == "temperature must be 0.0-2.0, got 3.00"
    assert paths["model.top_p"].message == "top_p must be 0.0-1.0, got 1.50"


def test_model_validator_warning():
    cfg = HierarchicalConfig()
    cfg.model.max_tokens = 2000000
    errs = ModelValidator().Validate(cfg)
    assert any(e.path == "model.max_tokens" and e.severity == "warning" for e in errs)


def test_api_validator_messages():
    cfg = HierarchicalConfig()
    cfg.api.base_url = ""
    cfg.api.timeout = -1
    cfg.api.retries = -2
    cfg.api.rate_limit = -3
    errs = APIValidator().Validate(cfg)
    paths = {e.path: e for e in errs}
    assert paths["api.base_url"].severity == "error"
    assert paths["api.timeout"].message == "timeout must be non-negative, got -1"
    assert paths["api.retries"].message == "retries must be non-negative, got -2"
    assert paths["api.rate_limit"].message == "rate_limit must be non-negative, got -3"


def test_api_validator_invalid_url_and_warnings():
    cfg = HierarchicalConfig()
    cfg.api.base_url = "not a url"
    cfg.api.timeout = 9999
    cfg.api.retries = 50
    errs = APIValidator().Validate(cfg)
    paths = {e.path: e for e in errs}
    assert paths["api.base_url"].severity == "error"
    assert "invalid URL format" in paths["api.base_url"].message
    assert paths["api.timeout"].severity == "warning"
    assert paths["api.retries"].severity == "warning"


def test_path_validator_missing_path():
    cfg = HierarchicalConfig()
    cfg.auth.token_path = str(Path("/nonexistent/dxrk/xyz/tokens"))
    errs = PathValidator().Validate(cfg)
    assert len(errs) == 1
    assert errs[0].severity == "warning"
    assert "path does not exist" in errs[0].message


def test_port_validator():
    cfg = HierarchicalConfig()
    cfg.session.max_history = -1
    cfg.session.archive_after = -1
    cfg.tools.max_concurrent = -1
    errs = PortValidator().Validate(cfg)
    assert len(errs) == 3
    cfg2 = HierarchicalConfig()
    cfg2.tools.max_concurrent = 500
    errs2 = PortValidator().Validate(cfg2)
    assert errs2[0].severity == "warning"
    assert "exceeds safe limit" in errs2[0].message


def test_validate_config_helpers():
    cfg = HierarchicalConfig()
    cfg.model.provider = ""
    cfg.model.model_name = ""
    cfg.api.base_url = ""
    errs = ValidateConfig(cfg)
    assert HasErrors(errs)
    errors_only = FilterErrors(errs, "error")
    assert all(e.severity == "error" for e in errors_only)
    formatted = FormatErrors(errs)
    assert formatted.endswith("\n")
    assert "[ERROR]" in formatted
    assert "(hint:" in formatted
    assert FormatErrors([]) == "configuration is valid"
    assert not HasErrors([])


def test_expand_path(monkeypatch):
    assert expand_path("/abs/path") == "/abs/path"
    expanded = expand_path("~/x")
    assert expanded.endswith("/x")


# ---- Feature Flags ----


def test_feature_flag_defaults():
    ffm = FeatureFlagManager()
    assert ffm.IsEnabled("auto_compact") is True
    assert ffm.IsEnabled("yolo_mode") is False
    assert ffm.IsEnabled("unknown") is False


def test_feature_flag_enable_disable():
    ffm = FeatureFlagManager()
    ffm.Enable("yolo_mode")
    assert ffm.IsEnabled("yolo_mode") is True
    flag, ok = ffm.Get("yolo_mode")
    assert ok and flag.rollout_percent == 100
    ffm.Disable("yolo_mode")
    assert ffm.IsEnabled("yolo_mode") is False
    with pytest.raises(ValueError):
        ffm.Enable("bogus")
    with pytest.raises(ValueError):
        ffm.Disable("bogus")


def test_feature_flag_rollout():
    ffm = FeatureFlagManager()
    with pytest.raises(ValueError):
        ffm.SetRollout("auto_compact", 150)
    with pytest.raises(ValueError):
        ffm.SetRollout("bogus", 10)
    ffm.SetRollout("auto_compact", 0)
    assert ffm.IsEnabled("auto_compact") is False
    ffm.SetRollout("auto_compact", 100)
    assert ffm.IsEnabled("auto_compact") is True


def test_feature_flag_register_remove():
    ffm = FeatureFlagManager()
    ffm.Register(FeatureFlag(name="custom", enabled=True, rollout_percent=50))
    assert ffm.IsEnabled("custom") is True
    assert "custom" in ffm.EnabledFlags()
    ffm.Remove("custom")
    assert not ffm.IsEnabled("custom")
    with pytest.raises(ValueError):
        ffm.Remove("custom")


def test_feature_flag_user_rollout():
    ffm = FeatureFlagManager()
    ffm.SetRollout("experimental_tools", 0)
    assert ffm.IsEnabledForUser("experimental_tools", "anyone") is False
    ffm.SetRollout("experimental_tools", 100)
    assert ffm.IsEnabledForUser("experimental_tools", "anyone") is True
    ffm.Disable("experimental_tools")
    flag = FeatureFlag(name="beta", enabled=True, rollout_percent=50)
    flag.allowed_users = ["admin"]
    ffm.Register(flag)
    assert ffm.IsEnabledForUser("beta", "admin") is True
    results = [ffm.IsEnabledForUser("beta", f"user{i}") for i in range(100)]
    assert any(results)
    assert not all(results)
    assert ffm.IsEnabledForUser("bogus", "x") is False


class _FakeSyncServer:
    """Minimal HTTP server that records pushes and serves canned pulls."""

    def __init__(self, tmp_path, remote_changes=None):
        self.remote_changes = remote_changes or []
        self.pushed = 0
        self._server = None
        self._thread = None
        self.port = 0

    def start(self):
        handler = self._make_handler()
        self._server = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    def _make_handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args) -> None:  # noqa: A002
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                owner.pushed += 1
                self.send_response(200)
                self.end_headers()

            def do_GET(self):
                body = json.dumps(owner.remote_changes).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


def test_section_fields_introspected_match_dataclasses():
    """ADR-004: _SECTION_FIELDS derives from HierarchicalConfig (no curated copy)."""
    from dataclasses import fields as _dc_fields

    from dxrk.config.config import HierarchicalConfig
    from dxrk.config.unified import _SECTION_FIELDS

    expected = {
        s.name: [f.name for f in _dc_fields(getattr(HierarchicalConfig(), s.name))]
        for s in _dc_fields(HierarchicalConfig)
    }
    assert _SECTION_FIELDS == expected
    assert set(_SECTION_FIELDS) == {"model", "api", "auth", "session", "tools", "ui", "advanced"}


def test_config_settings_store_list_flattens_section():
    """ConfigSettingsStore.List flattens a known section via introspected fields."""
    from dxrk.config.config import ConfigManager
    from dxrk.config.unified import ConfigSettingsStore

    mgr = ConfigManager()
    store = ConfigSettingsStore(mgr, prefix="ui")
    listed = store.List()
    assert listed["theme"] == mgr.Get("ui.theme")
    assert set(listed) >= {"theme", "font_size"}


def _write_yaml(path, data):
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _isolated_manager(tmp_path, monkeypatch, files):
    """Build ConfigManager with all file layers pointed at tmp files."""
    from dxrk.config.config import ConfigManager, WithGlobalPath, WithProjectPath, WithTenantPath, WithUserPath

    paths = {}
    for layer in ("global", "user", "tenant", "project"):
        p = tmp_path / f"{layer}.yaml"
        if layer in files:
            _write_yaml(p, files[layer])
        paths[layer] = str(p)
    mgr = ConfigManager(
        [
            WithGlobalPath(paths["global"]),
            WithUserPath(paths["user"]),
            WithTenantPath(paths["tenant"]),
            WithProjectPath(paths["project"]),
        ]
    )
    mgr.Load()
    return mgr


def test_config_manager_layer_order_global_user_tenant_project(tmp_path, monkeypatch):
    """Later layers win: global < user < tenant < project."""
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_UI_THEME", raising=False)
    mgr = _isolated_manager(
        tmp_path,
        monkeypatch,
        {
            "global": {"ui": {"theme": "global"}},
            "user": {"ui": {"theme": "user"}},
            "tenant": {"ui": {"theme": "tenant"}},
            "project": {"ui": {"theme": "project"}},
        },
    )
    assert mgr.Get("ui.theme") == "project"


def test_config_manager_tenant_beats_user(tmp_path, monkeypatch):
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_UI_THEME", raising=False)
    mgr = _isolated_manager(
        tmp_path, monkeypatch, {"user": {"ui": {"theme": "user"}}, "tenant": {"ui": {"theme": "tenant"}}}
    )
    assert mgr.Get("ui.theme") == "tenant"


def test_config_manager_tenant_env_fallback(tmp_path, monkeypatch):
    """DXRK_TENANT resolves ~/.dxrk/tenants/<tid>/config.yaml (HOME isolated)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DXRK_TENANT", "acme")
    monkeypatch.delenv("DXRK_UI_THEME", raising=False)
    from dxrk.tenant.migration import ensure_tenant

    ensure_tenant("acme")
    _write_yaml(home / ".dxrk" / "tenants" / "acme" / "config.yaml", {"ui": {"theme": "acme-tenant"}})
    from dxrk.config.config import ConfigManager, WithGlobalPath, WithProjectPath, WithUserPath

    missing = str(tmp_path / "missing.yaml")
    mgr = ConfigManager([WithGlobalPath(missing), WithUserPath(missing), WithProjectPath(missing)])
    mgr.Load()
    assert mgr.Get("ui.theme") == "acme-tenant"


def test_config_manager_env_beats_files(tmp_path, monkeypatch):
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.setenv("DXRK_UI_THEME", "from-env")
    mgr = _isolated_manager(tmp_path, monkeypatch, {"project": {"ui": {"theme": "project"}}})
    assert mgr.Get("ui.theme") == "from-env"


def test_unified_runtime_overrides_win(tmp_path, monkeypatch):
    """Level-1 overrides beat env, settings and files."""
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.setenv("DXRK_UI_THEME", "from-env")
    from dxrk.config.config import ConfigManager, WithGlobalPath, WithProjectPath, WithTenantPath, WithUserPath
    from dxrk.config.unified import UnifiedConfig

    missing = str(tmp_path / "missing.yaml")
    mgr = ConfigManager(
        [WithGlobalPath(missing), WithUserPath(missing), WithTenantPath(missing), WithProjectPath(missing)]
    )
    uni = UnifiedConfig(config=mgr)
    uni.load()
    assert uni.get_typed("ui.theme") == "from-env"
    uni.override("ui.theme", "flag-value")
    assert uni.get_typed("ui.theme") == "flag-value"
    uni.clear_overrides()
    assert uni.get_typed("ui.theme") == "from-env"


def test_unified_precedence_matrix_settings_vs_config(tmp_path, monkeypatch):
    """Settings layers (project > tenant > file) beat config YAML layers."""
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_UI_THEME", raising=False)
    from dxrk.config.config import ConfigManager, WithGlobalPath, WithProjectPath, WithTenantPath, WithUserPath
    from dxrk.config.settings import FileSettingsStore, MemorySettingsStore, ProjectSettingsStore, SettingsManager
    from dxrk.config.unified import ConfigSettingsStore, UnifiedConfig

    missing = str(tmp_path / "missing.yaml")
    _write_yaml(tmp_path / "project.yaml", {"ui": {"theme": "yaml-project"}})
    mgr = ConfigManager(
        [
            WithGlobalPath(missing),
            WithUserPath(missing),
            WithTenantPath(missing),
            WithProjectPath(str(tmp_path / "project.yaml")),
        ]
    )
    file_store = FileSettingsStore(path=str(tmp_path / "user.json"))
    project_store = ProjectSettingsStore(path=str(tmp_path / "proj.json"))
    tenant_store = ConfigSettingsStore(mgr, priority=150)
    settings = SettingsManager([project_store, tenant_store, file_store, MemorySettingsStore(priority=10)])
    uni = UnifiedConfig(config=mgr, settings=settings)
    uni.load()
    # config project yaml visible through tenant store fallback chain
    assert uni.get_typed("ui.theme") == "yaml-project"
    # flat settings layers: project > file
    file_store.Set("k", "file")
    project_store.Set("k", "project")
    assert uni.get_raw("k") == "project"
    # overrides win over everything
    uni.override("k", "flag")
    assert uni.get_raw("k") == "flag"
    uni.set_raw("k2", "v2")
    assert uni.get_raw("k2") == "v2"


def test_unified_camelcase_aliases_deprecated():
    """CamelCase aliases warn but behave identically (ADR-004)."""
    import warnings

    from dxrk.config.unified import UnifiedConfig

    uni = UnifiedConfig()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        uni.SetTyped("ui.theme", "dark")
        assert uni.GetTyped("ui.theme") == "dark"
        uni.SetRaw("dk", "dv")
        assert uni.GetRaw("dk") == "dv"
        uni.Load()
        uni.Save()
        assert isinstance(uni.Validate(), list)
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def _run_config_cli(argv, tmp_path, monkeypatch, tenant=""):
    """Runs dxrk config subcommands with isolated HOME+cwd."""
    import io

    from dxrk.commands import register_all

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_USER", raising=False)
    monkeypatch.delenv("DXRK_UI_THEME", raising=False)
    if tenant:
        monkeypatch.setenv("DXRK_TENANT", tenant)
    monkeypatch.chdir(proj)
    reg = register_all()
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(argv, out=out, err=err, cwd=str(proj))
    return code, out.getvalue(), err.getvalue(), home, proj


def test_config_get_reads_user_yaml(tmp_path, monkeypatch):
    import yaml

    code, out, err, home, proj = _run_config_cli(["config", "get", "ui.theme"], tmp_path, monkeypatch)
    assert code == 0  # defaults resolve even with no files
    user_cfg = home / ".dxrk" / "config.yaml"
    user_cfg.parent.mkdir(parents=True, exist_ok=True)
    user_cfg.write_text(yaml.safe_dump({"ui": {"theme": "user-theme"}}), encoding="utf-8")
    code, out, err, home, proj = _run_config_cli(["config", "get", "ui.theme"], tmp_path, monkeypatch)
    assert code == 0
    assert "user-theme" in out


def test_config_get_missing_value(tmp_path, monkeypatch):
    code, out, err, home, proj = _run_config_cli(["config", "get", "ui.nonexistent"], tmp_path, monkeypatch)
    assert code == 0
    assert "sin valor" in out


def test_config_set_persists_and_get_reads_back(tmp_path, monkeypatch):
    code, out, err, home, proj = _run_config_cli(["config", "set", "ui.theme", "cli-dark"], tmp_path, monkeypatch)
    assert code == 0
    code, out, err, home, proj = _run_config_cli(["config", "get", "ui.theme"], tmp_path, monkeypatch)
    assert code == 0
    assert "cli-dark" in out


def test_config_set_invalid_path_rejected(tmp_path, monkeypatch):
    code, out, err, home, proj = _run_config_cli(["config", "set", "nope", "x"], tmp_path, monkeypatch)
    assert code == 1


def test_config_layers_marks_winner(tmp_path, monkeypatch):
    import yaml

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    (home / ".dxrk").mkdir(parents=True, exist_ok=True)
    (home / ".dxrk" / "config.yaml").write_text(yaml.safe_dump({"ui": {"theme": "user"}}), encoding="utf-8")
    (proj / ".dxrk").mkdir(parents=True, exist_ok=True)
    (proj / ".dxrk" / "config.yaml").write_text(yaml.safe_dump({"ui": {"theme": "project"}}), encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_USER", raising=False)
    monkeypatch.delenv("DXRK_UI_THEME", raising=False)
    monkeypatch.chdir(proj)
    import io

    from dxrk.commands import register_all

    reg = register_all()
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(["config", "layers", "ui.theme"], out=out, err=err, cwd=str(proj))
    assert code == 0
    text = out.getvalue()
    assert "ui.theme = 'project'" in text
    assert "gana" in text


def test_config_set_tenant_writes_tenant_yaml(tmp_path, monkeypatch):
    from dxrk.tenant.migration import ensure_tenant

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DXRK_TENANT", "acme")
    monkeypatch.delenv("DXRK_USER", raising=False)
    monkeypatch.delenv("DXRK_UI_THEME", raising=False)
    monkeypatch.chdir(proj)
    ensure_tenant("acme")
    import io
    import stat

    from dxrk.commands import register_all

    reg = register_all()
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(["config", "set", "ui.theme", "acme-theme"], out=out, err=err, cwd=str(proj))
    assert code == 0
    target = home / ".dxrk" / "tenants" / "acme" / "config.yaml"
    assert target.exists()
    if sys.platform != "win32":  # POSIX-only file permissions
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(["config", "get", "ui.theme"], out=out, err=err, cwd=str(proj))
    assert code == 0
    assert "acme-theme" in out.getvalue()


def test_config_set_denied_for_readonly(tmp_path, monkeypatch):
    from dxrk.security.rbac import TenantRoleResolver
    from dxrk.tenant.migration import ensure_tenant

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DXRK_TENANT", "acme")
    monkeypatch.setenv("DXRK_USER", "ro")
    monkeypatch.delenv("DXRK_UI_THEME", raising=False)
    monkeypatch.chdir(proj)
    ensure_tenant("acme")
    TenantRoleResolver("acme").save({"ro": "readonly"}, "readonly")
    import io

    from dxrk.commands import register_all

    reg = register_all()
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(["config", "set", "ui.theme", "x"], out=out, err=err, cwd=str(proj))
    assert code == 1
    assert "RBAC_DENIED" in err.getvalue()
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(["config", "get", "ui.theme"], out=out, err=err, cwd=str(proj))
    assert code == 0


def test_config_settings_section_roundtrip(tmp_path):
    """Schemaless settings.* survives Load/Save/Get; Set stays rejected (ADR-004)."""
    import pytest

    from dxrk.config.config import ConfigManager, WithGlobalPath, WithProjectPath, WithTenantPath, WithUserPath

    missing = str(tmp_path / "missing.yaml")
    target = tmp_path / "user.yaml"
    target.write_text("settings:\n  theme: dark\n", encoding="utf-8")
    mgr = ConfigManager(
        [WithGlobalPath(missing), WithUserPath(str(target)), WithTenantPath(missing), WithProjectPath(missing)]
    )
    mgr.Load()
    assert mgr.Get("settings.theme") == "dark"
    # Set is read-only by design (keeps ConfigSettingsStore fallback coherent)
    with pytest.raises(ValueError):
        mgr.Set("settings.theme", "light")
    mgr.Save()
    mgr2 = ConfigManager(
        [WithGlobalPath(missing), WithUserPath(str(target)), WithTenantPath(missing), WithProjectPath(missing)]
    )
    mgr2.Load()
    assert mgr2.Get("settings.theme") == "dark"
    # unknown paths still rejected / empty
    assert mgr2.Get("settings") is None
    assert mgr2.Get("nope") is None


def test_config_settings_section_merge_layers(tmp_path, monkeypatch):
    """settings.* merges across user/project layers; project wins."""
    import yaml

    from dxrk.config.config import ConfigManager, WithGlobalPath, WithProjectPath, WithTenantPath, WithUserPath

    monkeypatch.delenv("DXRK_TENANT", raising=False)
    (tmp_path / "user.yaml").write_text(yaml.safe_dump({"settings": {"a": 1, "b": 1}}), encoding="utf-8")
    (tmp_path / "project.yaml").write_text(yaml.safe_dump({"settings": {"b": 2}}), encoding="utf-8")
    missing = str(tmp_path / "missing.yaml")
    mgr = ConfigManager(
        [
            WithGlobalPath(missing),
            WithUserPath(str(tmp_path / "user.yaml")),
            WithTenantPath(missing),
            WithProjectPath(str(tmp_path / "project.yaml")),
        ]
    )
    mgr.Load()
    assert mgr.Get("settings.a") == 1
    assert mgr.Get("settings.b") == 2


def _iso_cfg_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_USER", raising=False)
    monkeypatch.chdir(proj)
    return home, proj


def test_migrate_moves_keys_and_is_idempotent(tmp_path, monkeypatch):
    import json

    from dxrk.config.migration import migrate_settings_to_yaml

    home, proj = _iso_cfg_home(tmp_path, monkeypatch)
    (home / ".dxrk").mkdir(parents=True, exist_ok=True)
    (home / ".dxrk" / "settings.json").write_text(json.dumps({"theme": "dark", "k": 1}), encoding="utf-8")
    (proj / ".dxrk").mkdir(parents=True, exist_ok=True)
    (proj / ".dxrk" / "settings.json").write_text(json.dumps({"theme": "proj"}), encoding="utf-8")

    res = migrate_settings_to_yaml(dry_run=False)
    assert len(res["copied"]) == 3  # user theme/k + project theme
    # values land in YAML settings sections
    import yaml

    user_doc = yaml.safe_load((home / ".dxrk" / "config.yaml").read_text(encoding="utf-8"))
    assert user_doc["settings"]["theme"] == "dark"
    assert user_doc["settings"]["k"] == 1
    # second run: everything skipped (idempotent)
    res2 = migrate_settings_to_yaml(dry_run=False)
    assert res2["copied"] == []
    assert any("already present" in s for s in res2["skipped"])


def test_migrate_dry_run_writes_nothing(tmp_path, monkeypatch):
    import json

    from dxrk.config.migration import migrate_settings_to_yaml

    home, proj = _iso_cfg_home(tmp_path, monkeypatch)
    (home / ".dxrk").mkdir(parents=True, exist_ok=True)
    (home / ".dxrk" / "settings.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    res = migrate_settings_to_yaml(dry_run=True)
    assert len(res["copied"]) == 1
    assert not (home / ".dxrk" / "config.yaml").exists()


def test_migrate_tenant_scope(tmp_path, monkeypatch):
    import json

    import yaml

    from dxrk.config.migration import migrate_settings_to_yaml
    from dxrk.tenant.migration import ensure_tenant

    home, proj = _iso_cfg_home(tmp_path, monkeypatch)
    (home / ".dxrk").mkdir(parents=True, exist_ok=True)
    (home / ".dxrk" / "settings.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    ensure_tenant("acme")
    res = migrate_settings_to_yaml(dry_run=False, tenant="acme")
    tenant_doc = yaml.safe_load((home / ".dxrk" / "tenants" / "acme" / "config.yaml").read_text(encoding="utf-8"))
    assert tenant_doc["settings"]["theme"] == "dark"
    assert any(s.startswith("tenant:") for s in res["copied"])


def test_config_migrate_cli(tmp_path, monkeypatch):
    import io
    import json

    from dxrk.commands import register_all

    home, proj = _iso_cfg_home(tmp_path, monkeypatch)
    (home / ".dxrk").mkdir(parents=True, exist_ok=True)
    (home / ".dxrk" / "settings.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    reg = register_all()
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(["config", "migrate"], out=out, err=err, cwd=str(proj))
    assert code == 0
    assert "migradas" in out.getvalue()
    # get reads migrated value through the ladder
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(["config", "get", "settings.theme"], out=out, err=err, cwd=str(proj))
    assert code == 0
    assert "dark" in out.getvalue()


def test_migrate_preserves_existing_yaml_and_backs_up(tmp_path, monkeypatch):
    import json

    import yaml

    from dxrk.config.migration import migrate_settings_to_yaml

    home, proj = _iso_cfg_home(tmp_path, monkeypatch)
    (home / ".dxrk").mkdir(parents=True, exist_ok=True)
    (home / ".dxrk" / "settings.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    existing = {"ui": {"theme": "user"}, "settings": {"keep": True}}
    (home / ".dxrk" / "config.yaml").write_text(yaml.safe_dump(existing), encoding="utf-8")
    res = migrate_settings_to_yaml(dry_run=False)
    assert len(res["copied"]) == 1
    bak = home / ".dxrk" / "config.yaml.bak"
    assert bak.exists()
    assert yaml.safe_load(bak.read_text(encoding="utf-8")) == existing
    doc = yaml.safe_load((home / ".dxrk" / "config.yaml").read_text(encoding="utf-8"))
    assert doc["ui"]["theme"] == "user"  # untouched
    assert doc["settings"] == {"keep": True, "theme": "dark"}  # merged


def test_config_set_unknown_tenant_rejected(tmp_path, monkeypatch):
    import io

    from dxrk.commands import register_all

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DXRK_TENANT", "noexiste")
    monkeypatch.delenv("DXRK_USER", raising=False)
    monkeypatch.chdir(proj)
    reg = register_all()
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(["config", "set", "ui.theme", "x"], out=out, err=err, cwd=str(proj))
    assert code == 1
    assert "no encontrado" in err.getvalue()
    assert not (home / ".dxrk" / "tenants" / "noexiste").exists()


def test_config_migrate_unknown_tenant_rejected(tmp_path, monkeypatch):
    import io

    from dxrk.commands import register_all

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DXRK_TENANT", "noexiste")
    monkeypatch.delenv("DXRK_USER", raising=False)
    monkeypatch.chdir(proj)
    reg = register_all()
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(["config", "migrate"], out=out, err=err, cwd=str(proj))
    assert code == 1
    assert "no encontrado" in err.getvalue()
