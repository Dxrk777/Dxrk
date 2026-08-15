# SPDX-License-Identifier: MIT
"""Comprehensive hierarchical configuration system for Dxrk

Configuration is loaded from multiple sources with the following priority
(highest to lowest):

  1. CLI flags (runtime overrides)
  2. Environment variables (DXRK_* prefix)
  3. Project config (.dxrk/config.yaml)
  4. User config (~/.dxrk/config.yaml)
  5. Global config (/etc/dxrk/config.yaml)
  6. Built-in defaults

The package provides:

  - ConfigManager: hierarchical config with dot-notation access, validation, and watch
  - SettingsStore: pluggable key-value persistence (file, project, memory)
  - SettingsManager: multi-store settings with export/import
  - SettingsSyncer: bidirectional sync across devices
  - FeatureFlagManager: feature flags with rollout percentages
  - Validators: composable config validation pipeline

File formats: YAML (primary), JSON (fallback).
"""

from .config import (
    APIConfig,
    AdvancedConfig,
    AuthConfig,
    AutonomyConfig,
    CacheConfig,
    Config,
    ConfigManager,
    Default,
    DEFAULT_ENV_PREFIX,
    DEFAULT_GLOBAL_PATH,
    DEFAULT_PROJECT_PATH,
    DEFAULT_USER_PATH,
    GitConfig,
    HierarchicalConfig,
    ModelConfig,
    NewConfigManager,
    ProjectConfig,
    ProviderByName,
    ProviderConfig,
    RAGConfig,
    SandboxConfig,
    SessionConfig,
    TUIOpts,
    ToolsConfig,
    UIConfig,
    VaultConfig,
    Watcher,
    WebUIConfig,
    WithEnvPrefix,
    WithGlobalPath,
    WithProjectPath,
    WithUserPath,
    default_hierarchical_config,
)
from .featureflags import FeatureFlag, FeatureFlagManager, NewFeatureFlagManager
from .load import Load, Save
from .settings import (
    FileSettingsStore,
    MemorySettingsStore,
    NewDefaultSettingsManager,
    NewFileSettingsStore,
    NewMemorySettingsStore,
    NewProjectSettingsStore,
    NewSettingsManager,
    ProjectSettingsStore,
    SettingsManager,
    SettingsStore,
)
from .sync import (
    ConflictLastWriteWins,
    ConflictLocalWins,
    ConflictManual,
    ConflictRemoteWins,
    ConflictResolution,
    NewSettingsSyncer,
    SettingChange,
    SettingsSyncer,
    SyncConfig,
    SyncStatus,
)
from .validation import (
    APIValidator,
    CompositeValidator,
    ConfigError,
    FilterErrors,
    FormatErrors,
    HasErrors,
    ModelValidator,
    NewCompositeValidator,
    PathValidator,
    PortValidator,
    SeverityError,
    SeverityInfo,
    SeverityWarning,
    ValidateConfig,
    ValidateConfigWith,
    Validator,
    expand_path,
)
from .viper import LoadViper

__all__ = [
    "APIConfig",
    "APIValidator",
    "AdvancedConfig",
    "AuthConfig",
    "AutonomyConfig",
    "CacheConfig",
    "CompositeValidator",
    "Config",
    "ConfigError",
    "ConfigManager",
    "ConflictLastWriteWins",
    "ConflictLocalWins",
    "ConflictManual",
    "ConflictRemoteWins",
    "ConflictResolution",
    "Default",
    "DEFAULT_ENV_PREFIX",
    "DEFAULT_GLOBAL_PATH",
    "DEFAULT_PROJECT_PATH",
    "DEFAULT_USER_PATH",
    "FeatureFlag",
    "FeatureFlagManager",
    "FileSettingsStore",
    "FilterErrors",
    "FormatErrors",
    "GitConfig",
    "HasErrors",
    "HierarchicalConfig",
    "Load",
    "LoadViper",
    "MemorySettingsStore",
    "ModelConfig",
    "ModelValidator",
    "NewCompositeValidator",
    "NewConfigManager",
    "NewDefaultSettingsManager",
    "NewFeatureFlagManager",
    "NewFileSettingsStore",
    "NewMemorySettingsStore",
    "NewProjectSettingsStore",
    "NewSettingsManager",
    "NewSettingsSyncer",
    "PathValidator",
    "PortValidator",
    "ProjectConfig",
    "ProjectSettingsStore",
    "ProviderByName",
    "ProviderConfig",
    "RAGConfig",
    "Save",
    "SandboxConfig",
    "SessionConfig",
    "SettingChange",
    "SettingsManager",
    "SettingsStore",
    "SettingsSyncer",
    "SeverityError",
    "SeverityInfo",
    "SeverityWarning",
    "SyncConfig",
    "SyncStatus",
    "TUIOpts",
    "ToolsConfig",
    "UIConfig",
    "ValidateConfig",
    "ValidateConfigWith",
    "Validator",
    "VaultConfig",
    "Watcher",
    "WebUIConfig",
    "WithEnvPrefix",
    "WithGlobalPath",
    "WithProjectPath",
    "WithUserPath",
    "default_hierarchical_config",
    "expand_path",
]
