# SPDX-License-Identifier: MIT
"""QIEO — Quantum-Inspired Evolutionary Optimization (arXiv:2609.30938)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Qubit:
    """Qubit representation for a parameter (superposition α|0⟩ + β|1⟩)."""

    alpha: float = 0.7071067811865476  # 1/sqrt(2)
    beta: float = 0.7071067811865476  # 1/sqrt(2)

    def measure(self) -> float:
        """Collapse to [0, 1] based on probability amplitude."""
        p_one = self.beta * self.beta  # P(|1⟩) = |β|²
        return 1.0 if random.random() < p_one else 0.0

    def prob_one(self) -> float:
        """Probability of measuring |1⟩."""
        return self.beta * self.beta

    def rotate(self, target: float, delta: float = 0.05) -> Qubit:
        """
        Rotate qubit toward target value (0..1).

        In QIEO, rotation is based on the difference between current
        probability of |1⟩ and target probability.
        """
        current_prob = self.prob_one()

        # Determine rotation direction
        # If target > current, rotate toward |1⟩ (increase β)
        # If target < current, rotate toward |0⟩ (increase α)
        if target > current_prob:
            theta = delta  # rotate toward |1⟩
        else:
            theta = -delta  # rotate toward |0⟩

        # Rotation matrix
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        new_alpha = self.alpha * cos_t - self.beta * sin_t
        new_beta = self.alpha * sin_t + self.beta * cos_t

        # Normalize (should already be normalized, but ensure)
        norm = math.sqrt(new_alpha * new_alpha + new_beta * new_beta)
        if norm > 0:
            new_alpha /= norm
            new_beta /= norm

        return Qubit(alpha=new_alpha, beta=new_beta)


@dataclass(frozen=True)
class QIEOConfig:
    """Configuration for QIEO optimization."""

    pop_size: int = 30
    n_iter: int = 100
    rotation_delta: float = 0.1
    elite_frac: float = 0.2
    random_frac: float = 0.1


def qieo_optimize(
    objective_fn: Callable[[list[float]], float],
    bounds: list[tuple[float, float]],
    config: QIEOConfig | None = None,
    seed: int | None = None,
) -> tuple[list[float], float]:
    """
    Quantum-Inspired Evolutionary Optimization.

    Args:
        objective_fn: function(params) -> fitness (maximize)
        bounds: list of (min, max) for each parameter
        config: QIEOConfig
        seed: random seed for reproducibility

    Returns:
        (best_params, best_fitness)
    """
    if config is None:
        config = QIEOConfig()
    if seed is not None:
        random.seed(seed)

    n_params = len(bounds)
    elite_size = max(1, int(config.pop_size * config.elite_frac))
    random_size = max(1, int(config.pop_size * config.random_frac))

    # Initialize population of qubits
    population = [[Qubit() for _ in range(n_params)] for _ in range(config.pop_size)]

    best_params = None
    best_fitness = -math.inf

    for iteration in range(config.n_iter):
        # Measure population → concrete solutions
        solutions = []
        for individual in population:
            sol = [q.measure() * (bounds[i][1] - bounds[i][0]) + bounds[i][0] for i, q in enumerate(individual)]
            solutions.append(sol)

        # Evaluate fitness
        fitnesses = [objective_fn(sol) for sol in solutions]

        # Find elite
        sorted_indices = sorted(range(config.pop_size), key=lambda i: fitnesses[i], reverse=True)
        elite_indices = sorted_indices[:elite_size]
        random_indices = sorted_indices[-random_size:] if random_size > 0 else []

        # Update best
        if fitnesses[elite_indices[0]] > best_fitness:
            best_fitness = fitnesses[elite_indices[0]]
            best_params = solutions[elite_indices[0]][:]

        # Compute mean elite as target (in normalized space)
        elite_normed = []
        for idx in elite_indices:
            sol = solutions[idx]
            normed = [(sol[i] - bounds[i][0]) / (bounds[i][1] - bounds[i][0]) for i in range(n_params)]
            elite_normed.append(normed)

        target = [sum(elite_normed[e][i] for e in range(elite_size)) / elite_size for i in range(n_params)]

        # Rotation delta with annealing
        delta = config.rotation_delta * (1.0 - iteration / config.n_iter)

        # Update population
        for i, individual in enumerate(population):
            if i in random_indices:
                # Random restart
                population[i] = [Qubit() for _ in range(n_params)]
            else:
                # Rotate each qubit toward target
                new_individual = []
                for j, qubit in enumerate(individual):
                    new_qubit = qubit.rotate(target[j], delta)
                    new_individual.append(new_qubit)
                population[i] = new_individual

    return best_params, best_fitness
