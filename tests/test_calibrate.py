# SPDX-License-Identifier: MIT
"""Calibrate nodo tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from dxrk.memory.calibrate import (
    DEFAULT_PARAMS,
    CalibrationParams,
    get_calibration_params,
    list_calibrated_nodos,
    load_calibration,
    save_calibration,
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
        save_calibration(tmp_path, "test_nodo", params)
        loaded = load_calibration(tmp_path, "test_nodo")
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
        (cal_dir / "test_nodo.json").write_text("not json")
        loaded = load_calibration(tmp_path, "test_nodo")
        assert loaded.a == DEFAULT_PARAMS.a

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only file permissions")
    def test_save_creates_dir_and_0o600(self, tmp_path: Path) -> None:
        """Save creates .calibration dir and sets 0o600."""
        params = CalibrationParams()
        save_calibration(tmp_path, "nodo1", params)
        cal_dir = tmp_path / ".calibration"
        assert cal_dir.exists()
        path = cal_dir / "nodo1.json"
        assert path.exists()
        assert path.stat().st_mode & 0o777 == 0o600

    def test_get_calibration_params(self, tmp_path: Path) -> None:
        """get_calibration_params loads from malla path."""
        params = CalibrationParams(a=1.23)
        save_calibration(tmp_path, "nodo1", params)
        loaded = get_calibration_params(tmp_path, "nodo1")
        assert loaded.a == 1.23

    def test_list_calibrated_nodos(self, tmp_path: Path) -> None:
        """List calibrated nodos."""
        save_calibration(tmp_path, "nodo_a", CalibrationParams())
        save_calibration(tmp_path, "nodo_b", CalibrationParams())
        nodos = list_calibrated_nodos(tmp_path)
        assert "nodo_a" in nodos
        assert "nodo_b" in nodos
        assert len(nodos) == 2

    def test_list_calibrated_nodos_empty(self, tmp_path: Path) -> None:
        """Empty dir returns empty list."""
        nodos = list_calibrated_nodos(tmp_path)
        assert nodos == []

    def test_calibrate_nodo_no_candidates(self, tmp_path: Path) -> None:
        """Calibrate returns defaults when no candidates."""
        from dxrk.memory.calibrate import calibrate_nodo

        malla = Mock()
        malla.iter_fragmentos.return_value = []
        malla._path = str(tmp_path)

        result = calibrate_nodo(malla, "empty_nodo")
        assert result.a == DEFAULT_PARAMS.a

    def test_calibrate_nodo_runs(self, tmp_path: Path) -> None:
        """Calibrate runs and saves file (mock malla)."""
        from dxrk.memory.calibrate import calibrate_nodo

        # Create fragmentos with enough data
        fragmentos = []
        for i in range(10):
            fragmentos.append(
                {
                    "id": f"d{i}",
                    "metadata": {
                        "nodo": "test",
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
        malla = Mock()
        malla.iter_fragmentos.return_value = fragmentos
        malla._path = str(tmp_path)

        qieo_config = QIEOConfig(pop_size=10, n_iter=5)
        thompson_config = ThompsonConfig()

        result = calibrate_nodo(malla, "test", qieo_config, thompson_config)

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
