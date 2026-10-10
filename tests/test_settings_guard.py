# SPDX-License-Identifier: MIT
"""Guard: SettingsManager requires at least one source."""

from __future__ import annotations

import pytest

from dxrk.config.settings import MemorySettingsStore, NewSettingsManager, SettingsManager


def test_settings_manager_empty_list_raises():
    with pytest.raises(ValueError, match="requires at least one source"):
        SettingsManager([])


def test_settings_manager_none_raises():
    with pytest.raises(ValueError, match="requires at least one source"):
        SettingsManager(None)


def test_settings_manager_no_args_raises():
    with pytest.raises(ValueError, match="requires at least one source"):
        NewSettingsManager()


def test_settings_manager_single_store_works():
    mgr = SettingsManager([MemorySettingsStore()])
    mgr.Set("k", "v")
    assert mgr.Get("k") == "v"
