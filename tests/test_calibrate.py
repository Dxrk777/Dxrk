# SPDX-License-Identifier: MIT
"""Calibrate wing tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from dxrk.memory.calibrate import (
    CalibrationParams,
    load_calibration,
    save_calibration,
    get_calibration_params,
    list_calibrated_wings,
    DEFAULT_PARAMS,
)
from dxrk.memory.qieo import QIEOConfig
from dxrk.memory.thompson import ThompsonConfig


class TestCalibrate:
    def test_default_params(self) -> None:
        """Default params have sensible values."""
        p = DEFAULT_PARAMS
        assert p.a == 1.5
        assert p.b == 0.2
        assert p.c == 1.0
        assert p.pe_lambda == 0.1
        assert p.schema_version == 2

    def test_save_load_calibration(self, tmp_path: Path) -> None:
        """Save and load calibration round-trip."""
        params = CalibrationParams(
            a=2.0, b=0.3, c=1.5, pe_lambda=0.2, score=0.85, method="qieo", calibrated_at="2024-01-01T00:00:00+00:00"
        )
        save_calibration(tmp_path, "test_wing", params)
        loaded = load_calibration(tmp_path, "test_wing")
        assert loaded.a == 2.0
        assert loaded.b == 0.3
        assert loaded.c == 1.5
        assert loaded.pe_lambda == 0.2
        assert loaded.score == 0.85
        assert loaded.method == "qieo"
        assert loaded.calibrated_at == "2024-01-01T00:00:00+00:00"
        assert loaded.schema_version == 2

    def test_load_missing_returns_defaults(self, tmp_path: Path) -> None:
        """Missing file returns defaults."""
        loaded = load_calibration(tmp_path, "nonexistent")
        assert loaded.a == DEFAULT_PARAMS.a
        assert loaded.b == DEFAULT_PARAMS.b

    def test_load_corrupted_returns_defaults(self, tmp_path: Path) -> None:
        """Corrupted JSON returns defaults."""
        cal_dir = tmp_path / ".calibration"
        cal_dir.mkdir()
        (cal_dir / "test_wing.json").write_text("not json")
        loaded = load_calibration(tmp_path, "test_wing")
        assert loaded.a == DEFAULT_PARAMS.a

    def test_save_creates_dir_and_0o600(self, tmp_path: Path) -> None:
        """Save creates .calibration dir and sets 0o600."""
        params = CalibrationParams()
        save_calibration(tmp_path, "wing1", params)
        cal_dir = tmp_path / ".calibration"
        assert cal_dir.exists()
        path = cal_dir / "wing1.json"
        assert path.exists()
        assert path.stat().st_mode & 0o777 == 0o600

    def test_get_calibration_params(self, tmp_path: Path) -> None:
        """get_calibration_params loads from palace path."""
        params = CalibrationParams(a=1.23)
        save_calibration(tmp_path, "wing1", params)
        loaded = get_calibration_params(tmp_path, "wing1")
        assert loaded.a == 1.23

    def test_list_calibrated_wings(self, tmp_path: Path) -> None:
        """List calibrated wings."""
        save_calibration(tmp_path, "wing_a", CalibrationParams())
        save_calibration(tmp_path, "wing_b", CalibrationParams())
        wings = list_calibrated_wings(tmp_path)
        assert "wing_a" in wings
        assert "wing_b" in wings
        assert len(wings) == 2

    def test_list_calibrated_wings_empty(self, tmp_path: Path) -> None:
        """Empty dir returns empty list."""
        wings = list_calibrated_wings(tmp_path)
        assert wings == []

    def test_calibrate_wing_no_candidates(self, tmp_path: Path) -> None:
        """Calibrate returns defaults when no candidates."""
        from dxrk.memory.calibrate import calibrate_wing

        palace = Mock()
        palace.iter_drawers.return_value = []
        palace._path = str(tmp_path)

        result = calibrate_wing(palace, "empty_wing")
        assert result.a == DEFAULT_PARAMS.a

    def test_calibrate_wing_runs(self, tmp_path: Path) -> None:
        """Calibrate runs and saves file (mock palace)."""
        from dxrk.memory.calibrate import calibrate_wing

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
                    "document": f"content {i}",
                }
            )
        palace = Mock()
        palace.iter_drawers.return_value = drawers
        palace._path = str(tmp_path)

        qieo_config = QIEOConfig(pop_size=10, n_iter=5)
        thompson_config = ThompsonConfig()

        result = calibrate_wing(palace, "test", qieo_config, thompson_config)

        # Should have run and saved
        assert result.schema_version == 2
        assert result.method == "qieo"
        assert result.calibrated_at != ""
        assert 0.5 <= result.a <= 3.0
        assert 0.05 <= result.b <= 0.5
        assert 0.5 <= result.c <= 2.0
        assert 0.0 <= result.pe_lambda <= 0.5

        # Check file was saved
        loaded = load_calibration(tmp_path, "test")
        assert loaded.a == result.a
