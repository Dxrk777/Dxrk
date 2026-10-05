# SPDX-License-Identifier: MIT
"""Multi-Tenant Calibration tests — tenant isolation, transfer learning, fallback chain."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from dxrk.memory.calibrate_v2 import (
    CALIBRATION_DIR,
    DEFAULT_PARAMS,
    CalibrationParams,
    get_calibration_chain,
    get_calibration_params,
    list_calibrated_wings,
    load_calibration,
    merge_calibrations,
    save_calibration,
)
from dxrk.memory.qieo import QIEOConfig


class TestCalibrateV2:
    def test_default_params(self) -> None:
        """Default params have sensible values."""
        p = DEFAULT_PARAMS
        assert p.a == 1.5
        assert p.b == 0.2
        assert p.c == 1.0
        assert p.pe_lambda == 0.1
        assert p.schema_version == 3
        assert p.tenant == ""
        assert p.wing == ""

    def test_save_load_calibration(self, tmp_path: Path) -> None:
        """Save and load calibration round-trip."""
        params = CalibrationParams(
            a=2.0,
            b=0.3,
            c=1.5,
            pe_lambda=0.2,
            score=0.85,
            method="qieo",
            calibrated_at="2024-01-01T00:00:00+00:00",
            tenant="tenant1",
            wing="wing1",
            n_queries=100,
        )
        save_calibration(tmp_path, params)
        loaded = load_calibration(tmp_path, "tenant1", "wing1")
        assert loaded.a == 2.0
        assert loaded.b == 0.3
        assert loaded.c == 1.5
        assert loaded.pe_lambda == 0.2
        assert loaded.score == 0.85
        assert loaded.method == "qieo"
        assert loaded.calibrated_at == "2024-01-01T00:00:00+00:00"
        assert loaded.tenant == "tenant1"
        assert loaded.wing == "wing1"
        assert loaded.n_queries == 100

    def test_load_missing_returns_defaults(self, tmp_path: Path) -> None:
        """Missing file returns defaults."""
        loaded = load_calibration(tmp_path, "tenant1", "wing1")
        assert loaded.a == DEFAULT_PARAMS.a

    def test_load_corrupted_returns_defaults(self, tmp_path: Path) -> None:
        """Corrupted JSON returns defaults."""
        cal_dir = tmp_path / ".calibration"
        cal_dir.mkdir()
        (cal_dir / "tenant1_wing1.json").write_text("not json")
        loaded = load_calibration(tmp_path, "tenant1", "wing1")
        assert loaded.a == DEFAULT_PARAMS.a

    def test_save_creates_dir_and_0o600(self, tmp_path: Path) -> None:
        """Save creates .calibration dir and sets 0o600."""
        params = CalibrationParams(tenant="", wing="wing1")
        save_calibration(tmp_path, params)
        cal_dir = tmp_path / CALIBRATION_DIR
        assert cal_dir.exists()
        # Global wing file is named "global_wing1.json" (tenant="" uses global naming)
        path = cal_dir / "global_wing1.json"
        assert path.exists()
        assert path.stat().st_mode & 0o777 == 0o600

    def test_tenant_specific_overrides_global(self, tmp_path: Path) -> None:
        """Tenant-specific calibration overrides global."""
        # Save global
        global_params = CalibrationParams(a=1.0, b=0.1, wing="wing1")
        save_calibration(tmp_path, global_params)

        # Save tenant-specific
        tenant_params = CalibrationParams(a=2.0, b=0.3, tenant="tenant1", wing="wing1")
        save_calibration(tmp_path, tenant_params)

        # Load should return tenant-specific
        loaded = load_calibration(tmp_path, "tenant1", "wing1")
        assert loaded.a == 2.0
        assert loaded.b == 0.3
        assert loaded.tenant == "tenant1"

        # Global still accessible
        loaded_global = load_calibration(tmp_path, "", "wing1")
        assert loaded_global.a == 1.0

    def test_fallback_chain(self, tmp_path: Path) -> None:
        """Fallback chain returns tenant > global > default."""
        # Save only global
        global_params = CalibrationParams(a=1.5, wing="wing1")
        save_calibration(tmp_path, global_params)

        # Load with tenant should fallback to global
        loaded = load_calibration(tmp_path, "tenant1", "wing1")
        assert loaded.a == 1.5
        assert loaded.tenant == ""  # came from global

        # Load without tenant returns global
        loaded_global = load_calibration(tmp_path, "", "wing1")
        assert loaded_global.a == 1.5

    def test_get_calibration_params(self, tmp_path: Path) -> None:
        """get_calibration_params loads from palace path."""
        params = CalibrationParams(a=1.23, tenant="tenant1", wing="wing1")
        save_calibration(tmp_path, params)
        loaded = get_calibration_params(tmp_path, "tenant1", "wing1")
        assert loaded.a == 1.23

    def test_list_calibrated_wings(self, tmp_path: Path) -> None:
        """List calibrated wings."""
        save_calibration(tmp_path, CalibrationParams(tenant="t1", wing="w1", a=1.0))
        save_calibration(tmp_path, CalibrationParams(tenant="t1", wing="w2", a=2.0))
        save_calibration(tmp_path, CalibrationParams(tenant="", wing="w3", a=3.0))
        wings = list_calibrated_wings(tmp_path)
        assert "t1_w1" in wings
        assert "t1_w2" in wings
        assert "global_w3" in wings
        assert len(wings) == 3

    def test_list_calibrated_wings_empty(self, tmp_path: Path) -> None:
        """Empty dir returns empty list."""
        wings = list_calibrated_wings(tmp_path)
        assert wings == []

    def test_get_calibration_chain(self, tmp_path: Path) -> None:
        """Get full fallback chain."""
        # Save tenant-specific
        save_calibration(tmp_path, CalibrationParams(tenant="t1", wing="w1", a=1.0))
        # Save global
        save_calibration(tmp_path, CalibrationParams(tenant="", wing="w1", a=2.0))

        chain = get_calibration_chain(tmp_path, "t1", "w1")
        assert len(chain) == 3
        assert chain[0].a == 1.0  # tenant-specific
        assert chain[1].a == 2.0  # global
        assert chain[2].a == DEFAULT_PARAMS.a  # default

    def test_get_calibration_chain_no_tenant(self, tmp_path: Path) -> None:
        """Chain for no tenant starts at global."""
        save_calibration(tmp_path, CalibrationParams(tenant="", wing="w1", a=2.0))
        chain = get_calibration_chain(tmp_path, "", "w1")
        assert len(chain) == 2
        assert chain[0].a == 2.0
        assert chain[1].a == DEFAULT_PARAMS.a

    def test_merge_calibrations(self) -> None:
        """Merge calibration chain with weighted averaging."""
        chain = [
            CalibrationParams(a=1.0, b=0.1, c=1.0, pe_lambda=0.0, tenant="t1", wing="w1"),
            CalibrationParams(a=2.0, b=0.3, c=2.0, pe_lambda=0.2, tenant="", wing="w1"),
            DEFAULT_PARAMS,
        ]

        merged = merge_calibrations(chain, alpha=0.7)

        # Weighted: 0.7 * 1.0 + 0.15 * 2.0 + 0.15 * 1.5 = 0.7 + 0.3 + 0.225 = 1.225
        assert abs(merged.a - 1.225) < 0.01
        assert merged.tenant == "t1"  # inherits from most specific
        assert merged.wing == "w1"

    def test_merge_calibrations_single(self) -> None:
        """Single item chain returns that item."""
        chain = [CalibrationParams(a=3.0, tenant="t1", wing="w1")]
        merged = merge_calibrations(chain)
        assert merged.a == 3.0
        assert merged.tenant == "t1"

    def test_merge_calibrations_empty(self) -> None:
        """Empty chain returns defaults."""
        merged = merge_calibrations([])
        assert merged.a == DEFAULT_PARAMS.a

    def test_merge_calibrations_alpha_zero(self) -> None:
        """Alpha=0 gives equal weight to all."""
        chain = [
            CalibrationParams(a=1.0),
            CalibrationParams(a=3.0),
        ]
        merged = merge_calibrations(chain, alpha=0.0)
        assert merged.a == 2.0  # equal average

    def test_merge_calibrations_alpha_one(self) -> None:
        """Alpha=1 gives full weight to first."""
        chain = [
            CalibrationParams(a=1.0),
            CalibrationParams(a=3.0),
        ]
        merged = merge_calibrations(chain, alpha=1.0)
        assert merged.a == 1.0


class TestCalibrateIntegration:
    def test_calibrate_wing_no_candidates(self, tmp_path: Path) -> None:
        """Calibrate returns defaults when no candidates."""
        from dxrk.memory.calibrate_v2 import calibrate_wing

        palace = Mock()
        palace.iter_drawers.return_value = []
        palace._path = str(tmp_path)

        result = calibrate_wing(palace, "empty_wing")
        assert result.a == DEFAULT_PARAMS.a

    def test_calibrate_wing_runs_and_saves(self, tmp_path: Path) -> None:
        """Calibrate runs and saves file (mock palace)."""
        from dxrk.memory.calibrate_v2 import calibrate_wing

        # Create drawers with enough data
        drawers = []
        for i in range(10):
            drawers.append(
                {
                    "id": f"d{i}",
                    "metadata": {
                        "wing": "test",
                        "access_count_total": i * 2,
                        "irt_hits": i,
                        "irt_misses": max(0, 5 - i),
                        "S": 10.0 + i,
                        "D": 5.0,
                        "rd": 100.0,
                    },
                    "document": f"completely unique content {i} distinct words",
                }
            )
        palace = Mock()
        palace.iter_drawers.return_value = drawers
        palace._path = str(tmp_path)

        QIEOConfig(pop_size=10, n_iter=5)

        # Use a simple ThompsonConfig-like object
        class ThompsonConfig:
            alpha_prior = 1.0
            beta_prior = 1.0
            exploration_bonus = 0.5

        ThompsonConfig()

        result = calibrate_wing(
            palace, "test", qieo_config=QIEOConfig(pop_size=10, n_iter=5), thompson_config=ThompsonConfig()
        )

        # Should have run and saved
        assert result.schema_version == 3
        assert result.method == "qieo"
        assert result.calibrated_at != ""
        assert 0.5 <= result.a <= 3.0
        assert 0.05 <= result.b <= 0.5
        assert 0.5 <= result.c <= 2.0
        assert 0.0 <= result.pe_lambda <= 0.5

        # Check file was saved
        loaded = load_calibration(tmp_path, "", "test")
        assert loaded.a == result.a
