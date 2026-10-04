# SPDX-License-Identifier: MIT
"""Thompson Sampling for Active Learning (ALMAB-DC, arXiv:2603.21180)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ThompsonConfig:
    """Configuration for Thompson Sampling."""

    alpha_prior: float = 1.0  # Beta(α, β) prior for successes
    beta_prior: float = 1.0  # Beta(α, β) prior for failures
    exploration_bonus: float = 0.5  # weight for uncertainty


def thompson_sample(alpha: float, beta: float) -> float:
    """Sample from Beta(α, β) distribution."""
    return random.betavariate(alpha, beta)


def thompson_select(
    items: list[tuple[str, float, float]],  # (id, alpha, beta)
    n: int,
    exploration_bonus: float = 0.5,
) -> list[str]:
    """
    Select n items using Thompson Sampling with uncertainty bonus.

    Args:
        items: list of (item_id, alpha, beta) where alpha = successes+1, beta = failures+1
        n: number of items to select
        exploration_bonus: weight for variance (uncertainty exploration)

    Returns:
        List of selected item_ids (length n)
    """
    if not items:
        return []

    scored = []
    for item_id, alpha, beta in items:
        # Thompson sample
        theta = random.betavariate(alpha, beta)
        # Uncertainty = variance of Beta(α, β)
        variance = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))
        # Combined score: exploitation + exploration
        score = theta + exploration_bonus * variance
        scored.append((item_id, score))

    # Sort by score descending, take top n
    scored.sort(key=lambda x: -x[1])
    return [item_id for item_id, _ in scored[:n]]


def thompson_select_drawers(
    palace,
    n: int = 10,
    min_visits: int = 0,
) -> list[str]:
    """
    Select drawers for evaluation using Thompson Sampling.

    Prioritizes drawers with high uncertainty (low visits) for exploration,
    while still exploiting known high-value drawers.

    Args:
        palace: DxrkMemory instance
        n: number of drawers to select
        min_visits: minimum access_count_total to consider

    Returns:
        List of drawer_ids
    """
    candidates = []
    for drawer in palace.iter_drawers():
        meta = drawer.get("metadata", {})
        visits = meta.get("access_count_total", meta.get("access_count", 0))
        if visits < min_visits:
            continue
        if meta.get("quarantined"):
            continue
        if meta.get("pinned"):
            continue

        hits = meta.get("irt_hits", 0)
        misses = meta.get("irt_misses", 0)
        alpha = hits + 1.0
        beta = misses + 1.0
        candidates.append((drawer["id"], alpha, beta))

    return thompson_select(candidates, n)


def update_beta_prior(hits: int, misses: int, reward: float) -> tuple[float, float]:
    """
    Update Beta prior with observed reward.

    Args:
        hits: current success count
        misses: current failure count
        reward: 1.0 for success, 0.0 for failure, or fractional

    Returns:
        (new_alpha, new_beta)
    """
    # Fractional update for continuous rewards
    new_alpha = hits + 1.0 + reward
    new_beta = misses + 1.0 + (1.0 - reward)
    return new_alpha, new_beta


def select_evaluation_candidates(
    palace,
    n: int = 10,
    config: ThompsonConfig | None = None,
) -> list[str]:
    """
    Select evaluation candidates using Thompson Sampling + GP-UCB style bonus.

    This implements the ALMAB-DC approach: Thompson Sampling over Beta
    posteriors with uncertainty-driven exploration.
    """
    if config is None:
        config = ThompsonConfig()

    items = []
    for drawer in palace.iter_drawers():
        meta = drawer.get("metadata", {})
        if meta.get("quarantined") or meta.get("pinned"):
            continue

        visits = meta.get("access_count_total", meta.get("access_count", 0))
        hits = meta.get("irt_hits", 0)
        misses = meta.get("irt_misses", 0)

        alpha = hits + config.alpha_prior
        beta = misses + config.beta_prior

        items.append((drawer["id"], alpha, beta))

    return thompson_select(items, n, config.exploration_bonus)
