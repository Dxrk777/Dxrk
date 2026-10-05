# SPDX-License-Identifier: MIT
"""Prediction-Error coupling (vmPFC-FSRS, Zou 2025)."""

from __future__ import annotations

from dxrk.memory.scoring import PE_CLAMP, apply_success_with_pe


class TestPredictionError:
    def test_pe_positive_when_underpredicted(self) -> None:
        """PE > 0 when recall better than predicted (r < 1.0)."""
        meta = {"S": 10.0, "D": 5.0, "rd": 100.0}
        s_new, rd_new, pe = apply_success_with_pe(meta, predicted_r=0.7)
        assert pe > 0  # 1.0 - 0.7 = 0.3
        assert abs(pe - 0.3) < 1e-10

    def test_pe_negative_when_overpredicted(self) -> None:
        """With outcome=1, PE = 1 - r is always >= 0. Test clamp behavior."""
        meta = {"S": 10.0, "D": 5.0, "rd": 100.0}
        s_new, rd_new, pe = apply_success_with_pe(meta, predicted_r=0.0)
        # PE = 1.0 - 0.0 = 1.0, clamped to 0.5
        assert pe == 0.5  # PE_CLAMP

    def test_pe_clamped(self) -> None:
        """PE clamped to [-0.5, 0.5]."""
        meta = {"S": 10.0, "D": 5.0, "rd": 100.0}
        s_new, rd_new, pe = apply_success_with_pe(meta, predicted_r=0.0)
        assert pe == PE_CLAMP  # 1.0 clamped to 0.5

    def test_pe_modulates_stability(self) -> None:
        """PE modulates stability growth."""
        meta = {"S": 10.0, "D": 5.0, "rd": 100.0}
        # Low predicted_r → high PE → more growth
        s_low_r, _, _ = apply_success_with_pe(meta, predicted_r=0.3)
        # High predicted_r → low PE → less growth
        s_high_r, _, _ = apply_success_with_pe(meta, predicted_r=0.9)
        assert s_low_r > s_high_r

    def test_pe_lambda_small(self) -> None:
        """PE coupling is small (PE_LAMBDA=0.1) relative to base growth."""
        meta = {"S": 10.0, "D": 5.0, "rd": 100.0}
        s_low_r, _, pe_low = apply_success_with_pe(meta, predicted_r=0.3)  # PE=0.7→clamped 0.5
        s_high_r, _, pe_high = apply_success_with_pe(meta, predicted_r=0.9)  # PE=0.1
        # Low r gives higher PE, should give more growth
        assert pe_low > pe_high
        assert s_low_r >= s_high_r  # PE boosts growth

    def test_rd_still_shrinks(self) -> None:
        """RD still shrinks on success regardless of PE."""
        meta = {"S": 10.0, "D": 5.0, "rd": 100.0}
        _, rd_new, _ = apply_success_with_pe(meta, predicted_r=0.5)
        assert rd_new < 100.0
        assert rd_new == 90.0  # 100 * 0.9

    def test_uses_meta_defaults(self) -> None:
        """Uses migrated defaults for missing keys."""
        meta = {}  # empty, will get defaults
        s_new, rd_new, pe = apply_success_with_pe(meta, predicted_r=0.5)
        assert s_new > 0
        assert rd_new > 0
        assert 0.0 <= pe <= PE_CLAMP

    def test_pe_zero_when_perfect_prediction(self) -> None:
        """PE = 0 when predicted_r = 1.0 (perfect prediction)."""
        meta = {"S": 10.0, "D": 5.0, "rd": 100.0}
        s_new, rd_new, pe = apply_success_with_pe(meta, predicted_r=1.0)
        assert pe == 0.0
        # With r=1.0, base FSRS growth = 0 (e^(1-1)-1 = 0)
        # So S stays same
        assert s_new == 10.0
