# SPDX-License-Identifier: MIT
"""Thompson Sampling for Active Learning tests."""

from __future__ import annotations

from dxrk.memory.thompson import (
    ThompsonConfig,
    select_evaluation_candidates,
    thompson_sample,
    thompson_select,
    thompson_select_drawers,
    update_beta_prior,
)


class TestThompsonSampling:
    def test_thompson_sample_bounds(self) -> None:
        """Sample from Beta is in [0, 1]."""
        for _ in range(100):
            s = thompson_sample(2.0, 3.0)
            assert 0.0 <= s <= 1.0

    def test_thompson_sample_distribution(self) -> None:
        """Beta(1,1) = uniform; Beta(10,1) biased toward 1."""
        samples_uniform = [thompson_sample(1.0, 1.0) for _ in range(10000)]
        samples_biased = [thompson_sample(10.0, 1.0) for _ in range(10000)]
        mean_uniform = sum(samples_uniform) / len(samples_uniform)
        mean_biased = sum(samples_biased) / len(samples_biased)
        assert abs(mean_uniform - 0.5) < 0.05
        assert mean_biased > 0.8

    def test_thompson_select_returns_n(self) -> None:
        """Select returns exactly n items."""
        items = [("a", 2.0, 2.0), ("b", 3.0, 1.0), ("c", 1.0, 3.0), ("d", 4.0, 4.0)]
        selected = thompson_select(items, n=2)
        assert len(selected) == 2
        assert all(s in ["a", "b", "c", "d"] for s in selected)

    def test_thompson_select_empty(self) -> None:
        """Empty list returns empty."""
        assert thompson_select([], n=3) == []

    def test_thompson_select_exploitation(self) -> None:
        """High alpha/(alpha+beta) items more likely selected."""
        items = [
            ("low", 1.0, 10.0),  # mean ~0.09
            ("high", 10.0, 1.0),  # mean ~0.91
        ]
        counts = {"low": 0, "high": 0}
        for _ in range(1000):
            sel = thompson_select(items, n=1)
            counts[sel[0]] += 1
        assert counts["high"] > counts["low"] * 5  # strongly prefer high

    def test_thompson_select_exploration_bonus(self) -> None:
        """Uncertain items (high variance) get exploration bonus."""
        items = [
            ("certain", 50.0, 50.0),  # low variance, mean=0.5
            ("uncertain", 1.0, 1.0),  # high variance, mean=0.5
        ]
        # With exploration bonus, uncertain should be selected more often
        counts = {"certain": 0, "uncertain": 0}
        for _ in range(1000):
            sel = thompson_select(items, n=1, exploration_bonus=1.0)
            counts[sel[0]] += 1
        # Uncertain gets bonus, so should appear more
        assert counts["uncertain"] >= counts["certain"]

    def test_update_beta_prior(self) -> None:
        """Beta prior updates with reward."""
        alpha, beta = update_beta_prior(5, 3, 1.0)  # success
        assert alpha == 7.0  # 5+1+1
        assert beta == 4.0  # 3+1+0

        alpha, beta = update_beta_prior(5, 3, 0.0)  # failure
        assert alpha == 6.0  # 5+1+0
        assert beta == 5.0  # 3+1+1

        # Fractional reward
        alpha, beta = update_beta_prior(5, 3, 0.7)
        assert alpha == 6.7
        assert beta == 4.3

    def test_thompson_select_drawers(self) -> None:
        """Integration test with mock palace."""
        from unittest.mock import Mock

        drawers = [
            {"id": "d1", "metadata": {"access_count_total": 10, "irt_hits": 8, "irt_misses": 2}},
            {"id": "d2", "metadata": {"access_count_total": 5, "irt_hits": 1, "irt_misses": 4}},
            {"id": "d3", "metadata": {"access_count_total": 0, "irt_hits": 0, "irt_misses": 0, "quarantined": True}},
        ]
        palace = Mock()
        palace.iter_drawers.return_value = drawers

        selected = thompson_select_drawers(palace, n=2)
        assert len(selected) == 2
        assert "d3" not in selected  # quarantined excluded

    def test_select_evaluation_candidates(self) -> None:
        """Select evaluation candidates with config."""
        from unittest.mock import Mock

        drawers = [
            {"id": "d1", "metadata": {"access_count_total": 10, "irt_hits": 8, "irt_misses": 2}},
            {"id": "d2", "metadata": {"access_count_total": 5, "irt_hits": 1, "irt_misses": 4}},
            {"id": "d3", "metadata": {"access_count_total": 0, "irt_hits": 0, "irt_misses": 0}},
        ]
        palace = Mock()
        palace.iter_drawers.return_value = drawers

        config = ThompsonConfig(alpha_prior=1.0, beta_prior=1.0, exploration_bonus=0.5)
        selected = select_evaluation_candidates(palace, n=2, config=config)
        assert len(selected) == 2

    def test_thompson_config_defaults(self) -> None:
        """Config has sensible defaults."""
        config = ThompsonConfig()
        assert config.alpha_prior == 1.0
        assert config.beta_prior == 1.0
        assert config.exploration_bonus == 0.5
