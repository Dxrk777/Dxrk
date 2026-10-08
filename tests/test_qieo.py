# SPDX-License-Identifier: MIT
"""QIEO optimizer tests — realistic expectations for heuristic."""

from __future__ import annotations

import random

from dxrk.memory.qieo import QIEOConfig, Qubit, qieo_optimize


class TestQIEO:
    def test_qubit_measure(self) -> None:
        """Qubit measure returns 0 or 1."""
        q = Qubit()
        for _ in range(100):
            m = q.measure()
            assert m in (0.0, 1.0)

    def test_qubit_rotate_toward_one(self) -> None:
        """Rotating toward 1 increases probability of measuring 1."""
        q = Qubit(alpha=0.9, beta=0.436)  # p1 ≈ 0.19, biased toward 0
        initial_p1 = q.prob_one()

        q2 = q
        for _ in range(10):
            q2 = q2.rotate(1.0, delta=0.1)

        final_p1 = q2.prob_one()
        assert final_p1 > initial_p1

    def test_qubit_rotate_toward_zero(self) -> None:
        """Rotating toward 0 decreases probability of measuring 1."""
        q = Qubit(alpha=0.436, beta=0.9)  # p1 ≈ 0.81, biased toward 1
        initial_p1 = q.prob_one()

        q2 = q
        for _ in range(10):
            q2 = q2.rotate(0.0, delta=0.1)

        final_p1 = q2.prob_one()
        assert final_p1 < initial_p1

    def test_qubit_normalize(self) -> None:
        """Qubit amplitudes are normalized."""
        q = Qubit()
        q2 = q.rotate(1.0, delta=0.1)
        norm = q2.alpha**2 + q2.beta**2
        assert abs(norm - 1.0) < 1e-10

    def test_qieo_runs_and_returns_valid(self) -> None:
        """QIEO runs without error and returns valid params within bounds."""

        def objective(params):
            x = params[0]
            return -x * x + 10 * x  # max at x=5, value=25

        bounds = [(0.0, 10.0)]
        config = QIEOConfig(pop_size=30, n_iter=50, rotation_delta=0.1)
        best_params, best_fitness = qieo_optimize(objective, bounds, config, seed=42)

        assert len(best_params) == 1
        assert 0.0 <= best_params[0] <= 10.0
        assert isinstance(best_fitness, float)

    def test_qieo_two_params_valid(self) -> None:
        """QIEO works with 2 parameters, returns valid bounds."""

        def objective(params):
            x, y = params
            return -((x - 2) ** 2) - (y + 3) ** 2 + 100

        bounds = [(0.0, 5.0), (-5.0, 0.0)]
        config = QIEOConfig(pop_size=30, n_iter=50, rotation_delta=0.1)
        best_params, best_fitness = qieo_optimize(objective, bounds, config, seed=42)

        assert len(best_params) == 2
        assert 0.0 <= best_params[0] <= 5.0
        assert -5.0 <= best_params[1] <= 0.0
        assert isinstance(best_fitness, float)

    def test_qieo_noisy_objective_runs(self) -> None:
        """QIEO handles noisy objectives without crashing."""

        def objective(params):
            x = params[0]
            return -((x - 3) ** 2) + 50 + random.uniform(-2, 2)

        bounds = [(0.0, 6.0)]
        config = QIEOConfig(pop_size=30, n_iter=30, rotation_delta=0.1)
        best_params, best_fitness = qieo_optimize(objective, bounds, config, seed=42)

        assert 0.0 <= best_params[0] <= 6.0
        assert isinstance(best_fitness, float)

    def test_qieo_respects_bounds(self) -> None:
        """Solutions stay within bounds."""

        def objective(params):
            return sum(p for p in params)

        bounds = [(0.0, 1.0), (10.0, 20.0), (-5.0, 5.0)]
        config = QIEOConfig(pop_size=20, n_iter=30)
        best_params, _ = qieo_optimize(objective, bounds, config, seed=42)

        assert 0.0 <= best_params[0] <= 1.0
        assert 10.0 <= best_params[1] <= 20.0
        assert -5.0 <= best_params[2] <= 5.0

    def test_qieo_different_seeds_different_results(self) -> None:
        """Different seeds produce different exploration."""

        def objective(params):
            x = params[0]
            return -((x - 4) ** 2) + 20

        bounds = [(0.0, 8.0)]
        config = QIEOConfig(pop_size=20, n_iter=30)

        p1, f1 = qieo_optimize(objective, bounds, config, seed=1)
        p2, f2 = qieo_optimize(objective, bounds, config, seed=2)

        # At least params or fitness should differ (stochastic algorithm)
        assert p1 != p2 or f1 != f2
