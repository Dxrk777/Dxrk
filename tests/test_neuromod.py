# SPDX-License-Identifier: MIT
"""NeuromodulatorEngine — four channels DA/NE/5HT/ACh."""

from __future__ import annotations

import json
from pathlib import Path

from dxrk.memory.neuromod import (
    NeuromodState,
    reward,
    alert,
    consolidate,
    encode_mode,
    decay_all,
    stress_mode,
    load_neuromod_state,
    save_neuromod_state,
    effective_learning_rate,
    NEUROMOD_DECAY,
    REWARD_MAGNITUDE,
    ALERT_MAGNITUDE,
    MAX_LEVEL,
)


class TestNeuromodEngine:
    def test_reward_increases_da(self) -> None:
        """Reward increases dopamine."""
        state = NeuromodState()
        new_state = reward(state)
        assert new_state.da == REWARD_MAGNITUDE
        assert new_state.last_update != ""

    def test_reward_clamped_at_max(self) -> None:
        """DA clamped at 1.0."""
        state = NeuromodState(da=0.9)
        new_state = reward(state, magnitude=0.5)
        assert new_state.da == MAX_LEVEL

    def test_alert_increases_ne(self) -> None:
        """Alert increases noradrenaline."""
        state = NeuromodState()
        new_state = alert(state)
        assert new_state.ne == ALERT_MAGNITUDE

    def test_consolidate_up_sht_down_ach(self) -> None:
        """Consolidation: 5HT up, ACh down."""
        state = NeuromodState(sht=0.0, ach=0.5)
        new_state = consolidate(state)
        assert new_state.sht == 0.2  # CONSOLIDATE_SHT
        assert new_state.ach == 0.2  # 0.5 - CONSOLIDATE_ACH_DECAY

    def test_encode_mode_up_ach(self) -> None:
        """Encode mode increases ACh up to max."""
        state = NeuromodState(ach=0.0)
        new_state = encode_mode(state)
        assert new_state.ach == 0.2  # ENCODE_ACH

        # Multiple encodes saturate at ENCODE_ACH_MAX
        for _ in range(10):
            state = encode_mode(state)
        assert state.ach == 0.8  # ENCODE_ACH_MAX

    def test_decay_all_channels(self) -> None:
        """All channels decay by NEUROMOD_DECAY."""
        state = NeuromodState(da=1.0, ne=1.0, sht=1.0, ach=1.0)
        new_state = decay_all(state)
        assert new_state.da == NEUROMOD_DECAY
        assert new_state.ne == NEUROMOD_DECAY
        assert new_state.sht == NEUROMOD_DECAY
        assert new_state.ach == NEUROMOD_DECAY

    def test_stress_mode_elevates_ne(self) -> None:
        """Stress mode elevates NE baseline."""
        state = NeuromodState(ne=0.0)
        new_state = stress_mode(state)
        assert new_state.ne == 0.3

    def test_effective_learning_rate(self) -> None:
        """Effective learning rate modulated by neuromodulators."""
        base_eta = 0.01
        state = NeuromodState(da=0.5, ne=0.0, ach=0.0)
        eta = effective_learning_rate(base_eta, state)
        assert eta == base_eta * 1.5  # (1 + DA)

        # NE also enhances
        state2 = NeuromodState(da=0.0, ne=0.5, ach=0.0)
        eta2 = effective_learning_rate(base_eta, state2)
        assert eta2 == base_eta * 1.5

        # ACh gates (reduces)
        state3 = NeuromodState(da=0.0, ne=0.0, ach=0.5)
        eta3 = effective_learning_rate(base_eta, state3)
        assert eta3 == base_eta * 0.75  # (1 - 0.5*ACh)

        # Combined
        state4 = NeuromodState(da=1.0, ne=1.0, ach=0.5)
        eta4 = effective_learning_rate(base_eta, state4)
        # (1+1) * (1+1) * (1-0.25) = 2 * 2 * 0.75 = 3.0
        assert eta4 == base_eta * 3.0

    def test_persist_load_cycle(self, tmp_path: Path) -> None:
        """Save and load neuromod state from JSON sidecar."""
        state = NeuromodState(da=0.3, ne=0.4, sht=0.5, ach=0.6, last_update="2024-01-01T00:00:00+00:00")
        save_neuromod_state(tmp_path, state)
        loaded = load_neuromod_state(tmp_path)
        assert loaded.da == 0.3
        assert loaded.ne == 0.4
        assert loaded.sht == 0.5
        assert loaded.ach == 0.6
        assert loaded.last_update == "2024-01-01T00:00:00+00:00"

    def test_load_missing_returns_defaults(self, tmp_path: Path) -> None:
        """Loading from non-existent path returns default state."""
        loaded = load_neuromod_state(tmp_path)
        assert loaded.da == 0.0
        assert loaded.ne == 0.0
        assert loaded.sht == 0.0
        assert loaded.ach == 0.0

    def test_load_corrupted_returns_defaults(self, tmp_path: Path) -> None:
        """Loading corrupted JSON returns defaults (resilient)."""
        (tmp_path / ".neuromod_state.json").write_text("not json")
        loaded = load_neuromod_state(tmp_path)
        assert loaded.da == 0.0

    def test_save_creates_0o600(self, tmp_path: Path) -> None:
        """Saved file has 0o600 permissions."""
        state = NeuromodState()
        save_neuromod_state(tmp_path, state)
        path = tmp_path / ".neuromod_state.json"
        assert path.stat().st_mode & 0o777 == 0o600
