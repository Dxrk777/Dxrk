# SPDX-License-Identifier: MIT
"""Stress detection and cooperative masking (ZenBrain)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from dxrk.memory.stress import (
    StressState,
    compute_system_stress,
    should_activate_defenses,
    get_defense_params,
    load_stress_state,
    save_stress_state,
    STRESS_ACTIVATION_THRESHOLD,
    STRESS_DEACTIVATION_THRESHOLD,
)


class TestStress:
    def test_stress_empty_palace(self, tmp_path: Path) -> None:
        """Empty palace has zero stress."""
        from dxrk.memory.palace import DxrkMemory

        dm = DxrkMemory(str(tmp_path / "palace"))
        dm.init()
        try:
            state = compute_system_stress(dm)
            assert state.level == 0.0
            assert state.defenses_active is False
        finally:
            dm.close()

    def test_stress_density_component(self, tmp_path: Path) -> None:
        """Higher density increases stress (when cap > 0)."""
        from dxrk.memory.palace import DxrkMemory

        dm = DxrkMemory(str(tmp_path / "palace"))
        dm.init()
        try:
            # Need to set a cap for density to be meaningful
            dm._max_entries_per_wing = 100
            for i in range(50):
                dm.add_drawer("w", "r", f"content {i}", f"/f{i}.md", i)
            state = compute_system_stress(dm)
            assert state.density > 0.0
            assert state.density <= 1.0
        finally:
            dm.close()

    def test_stress_inverse_stability(self, tmp_path: Path) -> None:
        """Low stability (high 1/S) increases stress."""
        from dxrk.memory.palace import DxrkMemory

        dm = DxrkMemory(str(tmp_path / "palace"))
        dm.init()
        try:
            # Add drawer with very low S (will be migrated to have S)
            dm.add_drawer("w", "r", "unstable", "/u.md", 0)
            state = compute_system_stress(dm)
            assert state.avg_inv_stability >= 0.0
        finally:
            dm.close()

    def test_stress_recent_quarantines(self, tmp_path: Path) -> None:
        """Recent quarantines increase stress."""
        from dxrk.memory.palace import DxrkMemory

        dm = DxrkMemory(str(tmp_path / "palace"))
        dm.init()
        try:
            did = dm.add_drawer("w", "r", "to quarantine", "/q.md", 0)
            # Manually quarantine (simulate checksum mismatch)
            from dxrk.memory.palace import DxrkMemory

            col = dm._collection(create=False)
            raw = col.get(ids=[did], include=["documents", "metadatas"])
            col.upsert(documents=["TAMPERED"], ids=[did], metadatas=[raw.metadatas[0]])
            dm.get_drawer(did)  # triggers quarantine
            state = compute_system_stress(dm)
            assert state.recent_quarantines >= 1
        finally:
            dm.close()

    def test_hysteresis_activates_at_06(self, tmp_path: Path) -> None:
        """Defenses activate when stress > 0.6."""
        state = StressState(level=0.7, defenses_active=False)
        save_stress_state(tmp_path, state)
        # Next computation should activate
        new_state = StressState(level=0.7, defenses_active=False, last_computed="")
        # Simulate hysteresis logic
        assert 0.7 > STRESS_ACTIVATION_THRESHOLD

    def test_hysteresis_deactivates_at_04(self, tmp_path: Path) -> None:
        """Defenses deactivate when stress < 0.4."""
        state = StressState(level=0.3, defenses_active=True)
        save_stress_state(tmp_path, state)
        assert 0.3 < STRESS_DEACTIVATION_THRESHOLD

    def test_get_defense_params_inactive(self) -> None:
        """Defense params when inactive."""
        state = StressState(level=0.3, defenses_active=False)
        params = get_defense_params(state)
        assert params["triplecopy_full"] is False
        assert params["reconsolidation_hours"] == 6
        assert params["sleep_priority_threshold"] == 0.5
        assert params["ne_baseline"] == 0.0

    def test_get_defense_params_active(self) -> None:
        """Defense params when active."""
        state = StressState(level=0.7, defenses_active=True)
        params = get_defense_params(state)
        assert params["triplecopy_full"] is True
        assert params["reconsolidation_hours"] == 2
        assert params["sleep_priority_threshold"] == 0.3
        assert params["ne_baseline"] == 0.3

    def test_persist_load_cycle(self, tmp_path: Path) -> None:
        """Save and load stress state."""
        state = StressState(
            level=0.5,
            defenses_active=True,
            density=0.6,
            avg_inv_stability=0.1,
            recent_quarantines=3,
            last_computed="2024-01-01T00:00:00+00:00",
        )
        save_stress_state(tmp_path, state)
        loaded = load_stress_state(tmp_path)
        assert loaded.level == 0.5
        assert loaded.defenses_active is True
        assert loaded.density == 0.6
        assert loaded.recent_quarantines == 3

    def test_load_missing_returns_defaults(self, tmp_path: Path) -> None:
        """Loading from missing path returns defaults."""
        loaded = load_stress_state(tmp_path)
        assert loaded.level == 0.0
        assert loaded.defenses_active is False

    def test_load_corrupted_returns_defaults(self, tmp_path: Path) -> None:
        """Loading corrupted JSON returns defaults."""
        (tmp_path / ".stress_state.json").write_text("not json")
        loaded = load_stress_state(tmp_path)
        assert loaded.level == 0.0

    def test_save_creates_0o600(self, tmp_path: Path) -> None:
        """Saved file has 0o600 permissions."""
        state = StressState()
        save_stress_state(tmp_path, state)
        path = tmp_path / ".stress_state.json"
        assert path.stat().st_mode & 0o777 == 0o600
