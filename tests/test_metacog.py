# SPDX-License-Identifier: MIT
"""MetacognitiveMonitor — ECE + bias tracking."""

from __future__ import annotations

from pathlib import Path

from dxrk.memory.metacog import (
    CONFIDENCE_HISTORY_CAP,
    MetacogState,
    adjusted_confidence,
    compute_ece,
    get_bias_category,
    load_metacog_state,
    record_judgment,
    save_metacog_state,
)


class TestMetacognitiveMonitor:
    def test_compute_ece_perfect_calibration(self) -> None:
        """ECE = 0 when predictions match outcomes perfectly."""
        history = [(0.9, 0.9), (0.8, 0.8), (0.5, 0.5)]
        ece = compute_ece(history)
        assert ece == 0.0

    def test_compute_ece_overconfident(self) -> None:
        """ECE > 0 when overconfident (high confidence, low accuracy)."""
        history = [(0.9, 0.5), (0.8, 0.4), (0.7, 0.3)]
        ece = compute_ece(history)
        assert ece > 0.0

    def test_compute_ece_empty_history(self) -> None:
        """ECE = 0 for empty history."""
        ece = compute_ece([])
        assert ece == 0.0

    def test_record_judgment_updates_bias(self) -> None:
        """Recording judgment updates bias direction."""
        state = MetacogState()
        state = record_judgment(state, predicted=0.9, actual=0.5)  # overconfident
        assert state.bias_direction > 0
        assert state.n_judgments == 1

    def test_record_judgment_underconfident(self) -> None:
        """Underconfident judgments produce negative bias."""
        state = MetacogState()
        state = record_judgment(state, predicted=0.3, actual=0.8)
        assert state.bias_direction < 0

    def test_record_judgment_bias_ema(self) -> None:
        """Bias uses exponential moving average."""
        state = MetacogState()
        state = record_judgment(state, predicted=0.9, actual=0.5)  # error = 0.4
        state = record_judgment(state, predicted=0.9, actual=0.5)  # another 0.4
        bias2 = state.bias_direction
        # Should be less than 0.4 (EMA with alpha=0.05)
        assert 0.0 < bias2 < 0.4

    def test_adjusted_confidence_corrects_overconfidence(self) -> None:
        """Adjusted confidence corrects for overconfidence bias."""
        state = MetacogState(bias_direction=0.2)  # overconfident
        adj = adjusted_confidence(state, raw_confidence=0.8)
        assert abs(adj - 0.6) < 1e-10

    def test_adjusted_confidence_corrects_underconfidence(self) -> None:
        """Adjusted confidence corrects for underconfidence bias."""
        state = MetacogState(bias_direction=-0.2)  # underconfident
        adj = adjusted_confidence(state, raw_confidence=0.5)
        assert adj == 0.7  # 0.5 - (-0.2)

    def test_adjusted_confidence_clamped(self) -> None:
        """Adjusted confidence clamped to [0, 1]."""
        state = MetacogState(bias_direction=0.9)
        adj = adjusted_confidence(state, raw_confidence=0.2)
        assert adj == 0.0  # clamped

    def test_get_bias_category(self) -> None:
        """Bias categorization works."""
        assert get_bias_category(MetacogState(bias_direction=0.2)) == "overconfident"
        assert get_bias_category(MetacogState(bias_direction=-0.2)) == "underconfident"
        assert get_bias_category(MetacogState(bias_direction=0.05)) == "well_calibrated"

    def test_history_cap(self) -> None:
        """Confidence history capped at CONFIDENCE_HISTORY_CAP."""
        state = MetacogState()
        for i in range(CONFIDENCE_HISTORY_CAP + 50):
            state = record_judgment(state, 0.5, 0.5)
        assert len(state.confidence_history) == CONFIDENCE_HISTORY_CAP

    def test_persist_load_cycle(self, tmp_path: Path) -> None:
        """Save and load metacog state from JSON sidecar."""
        state = MetacogState(
            calibration_error=0.1,
            bias_direction=0.05,
            confidence_history=[(0.8, 0.7), (0.6, 0.6)],
            n_judgments=2,
            last_update="2024-01-01T00:00:00+00:00",
        )
        save_metacog_state(tmp_path, state)
        loaded = load_metacog_state(tmp_path)
        assert loaded.calibration_error == 0.1
        assert loaded.bias_direction == 0.05
        assert loaded.n_judgments == 2
        # JSON serializes tuples as lists, so compare as lists
        assert [list(p) for p in loaded.confidence_history] == [[0.8, 0.7], [0.6, 0.6]]
        assert loaded.last_update == "2024-01-01T00:00:00+00:00"

    def test_load_missing_returns_defaults(self, tmp_path: Path) -> None:
        """Loading from non-existent path returns defaults."""
        loaded = load_metacog_state(tmp_path)
        assert loaded.calibration_error == 0.0
        assert loaded.bias_direction == 0.0

    def test_load_corrupted_returns_defaults(self, tmp_path: Path) -> None:
        """Loading corrupted JSON returns defaults."""
        (tmp_path / ".metacog_state.json").write_text("not json")
        loaded = load_metacog_state(tmp_path)
        assert loaded.calibration_error == 0.0

    def test_save_creates_0o600(self, tmp_path: Path) -> None:
        """Saved file has 0o600 permissions."""
        state = MetacogState()
        save_metacog_state(tmp_path, state)
        path = tmp_path / ".metacog_state.json"
        assert path.stat().st_mode & 0o777 == 0o600

    def test_ece_with_bins(self) -> None:
        """ECE computed with correct binning."""
        # 10 items in bin 0 (0.0-0.1), perfect calibration
        history = [(0.05, 0.05)] * 10
        ece = compute_ece(history, n_bins=10)
        assert abs(ece) < 1e-10

        # 10 items in bin 9 (0.9-1.0), overconfident
        history = [(0.95, 0.5)] * 10
        ece = compute_ece(history, n_bins=10)
        assert abs(ece - 0.45) < 1e-10
