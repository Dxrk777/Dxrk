# SPDX-License-Identifier: MIT
"""Bayesian Confidence Propagation (McGaugh 2004) — no palace dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class DrawerLike(Protocol):
    """Minimal drawer protocol for confidence propagation."""

    id: str
    metadata: dict
    quarantined: bool


class DrawerIterator(Protocol):
    """Protocol for iterating drawers."""

    def __call__(self) -> list[DrawerLike]: ...


class DrawerGetter(Protocol):
    """Protocol for getting a single drawer by ID."""

    def __call__(self, drawer_id: str) -> DrawerLike | None: ...


@dataclass(frozen=True)
class ConfidencePropagation:
    """Result of confidence propagation."""

    propagated_confidence: float
    depth_reached: int
    related_count: int


def find_related_drawers(
    get_drawer: DrawerGetter,
    iter_drawers: DrawerIterator,
    drawer_id: str,
    max_related: int = 10,
    min_similarity: float = 0.3,
) -> list[tuple[str, float]]:
    """
    Find related drawers by wing/room and embedding similarity.

    Returns: list of (drawer_id, similarity) sorted by similarity desc.
    """
    # Get the source drawer to find its wing/room
    source = get_drawer(drawer_id)
    if not source:
        return []

    def _get(d, key, default=None):
        if hasattr(d, key):
            return getattr(d, key)
        return d.get(key, default)

    source_meta = _get(source, "metadata", {})
    wing = source_meta.get("wing", "")
    room = source_meta.get("room", "")

    # Find drawers in same wing/room (structural similarity)
    related = []
    for other in iter_drawers():
        if _get(other, "id") == drawer_id:
            continue
        if _get(other, "quarantined"):
            continue

        other_meta = _get(other, "metadata", {})
        # Wing match
        sim = 0.0
        if other_meta.get("wing") == wing:
            sim += 0.5
        if other_meta.get("room") == room:
            sim += 0.3

        # Embedding similarity if available (would need embeddings access)

        if sim >= min_similarity:
            related.append((_get(other, "id"), sim))

    # Sort by similarity desc, take top
    related.sort(key=lambda x: -x[1])
    return related[:max_related]


def propagate_confidence(
    get_drawer: DrawerGetter,
    iter_drawers: DrawerIterator,
    drawer_id: str,
    base_confidence: float,
    max_depth: int = 2,
    decay_per_depth: float = 0.5,
    min_similarity: float = 0.3,
) -> ConfidencePropagation:
    """
    Propagate confidence from a drawer to related drawers (Bayesian propagation).

    Confidence propagates through the graph:
    confidence(d) = base_conf(d) * Π(1 + sim * related_conf * decay) for depth levels

    Args:
        get_drawer: callable(drawer_id) -> drawer or None
        iter_drawers: callable() -> list of drawers
        drawer_id: starting drawer
        base_confidence: confidence of source drawer
        max_depth: max propagation depth
        decay_per_depth: multiplicative decay per depth level
        min_similarity: minimum similarity to propagate

    Returns:
        ConfidencePropagation with propagated confidence, depth reached, related count
    """
    if max_depth <= 0:
        return ConfidencePropagation(base_confidence, 0, 0)

    # BFS propagation
    visited = {drawer_id}
    queue = [(drawer_id, base_confidence, 0)]
    total_propagated = 0.0
    related_count = 0
    max_depth_reached = 0

    while queue:
        current_id, current_conf, depth = queue.pop(0)

        if depth >= max_depth:
            continue

        # Find related drawers
        related = find_related_drawers(get_drawer, iter_drawers, current_id, min_similarity=min_similarity)
        related_count += len(related)

        for rel_id, sim in related:
            if rel_id in visited:
                continue
            visited.add(rel_id)

            # Propagated confidence
            propagated = current_conf * (1.0 + sim * decay_per_depth)
            total_propagated += propagated

            queue.append((rel_id, propagated, depth + 1))
            max_depth_reached = max(max_depth_reached, depth + 1)

    # Combined confidence = base + propagated (capped at 1.0)
    final_confidence = min(1.0, base_confidence + total_propagated)

    return ConfidencePropagation(
        propagated_confidence=final_confidence,
        depth_reached=max_depth_reached,
        related_count=related_count,
    )


def adjusted_uncertainty(rd: float, t_days: float, confidence: float) -> float:
    """
    Adjust uncertainty (rd) based on time and propagated confidence.

    Higher confidence → lower uncertainty (more certain).
    Time drift: rd_eff = min(350, sqrt(rd^2 + 4*t))
    Then: rd_effective = rd_eff * (1 - confidence)
    """
    # Time drift
    rd_eff = min(350.0, (rd * rd + 4.0 * t_days) ** 0.5)
    # Confidence adjustment
    return rd_eff * (1.0 - confidence)


def confidence_from_retrievability(meta: dict) -> float:
    """Estimate confidence from drawer's retrievability and stability."""
    S = meta.get("S", 1.0)
    D = meta.get("D", 5.0)
    rd = meta.get("rd", 350.0)

    # Higher stability + lower difficulty + lower rd = higher confidence
    stability_factor = min(1.0, S / 365.0)  # S max 365
    difficulty_factor = 1.0 - (D - 1.0) / 9.0  # D in [1,10] → [1,0]
    uncertainty_factor = 1.0 - min(1.0, rd / 350.0)

    return stability_factor * 0.5 + difficulty_factor * 0.3 + uncertainty_factor * 0.2
