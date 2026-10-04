# SPDX-License-Identifier: MIT
"""Bayesian Confidence Propagation (McGaugh 2004)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from dxrk.memory.palace import DxrkMemory
from dxrk.memory.scoring import r_fsrs


@dataclass(frozen=True)
class ConfidencePropagation:
    """Result of confidence propagation."""

    propagated_confidence: float
    depth_reached: int
    related_count: int


def find_related_drawers(
    palace: DxrkMemory,
    drawer_id: str,
    max_related: int = 10,
    min_similarity: float = 0.3,
) -> list[tuple[str, float]]:
    """
    Find related drawers by wing/room and embedding similarity.

    Returns: list of (drawer_id, similarity) sorted by similarity desc.
    """
    # Get the source drawer to find its wing/room
    source = palace.get_drawer(drawer_id)
    if not source or not source.get("metadata"):
        return []

    wing = source.get("metadata", {}).get("wing", "")
    room = source.get("metadata", {}).get("room", "")

    # Find drawers in same wing/room (structural similarity)
    related = []
    for other in palace.iter_drawers():
        if other["id"] == drawer_id:
            continue
        if other.get("quarantined"):
            continue

        other_meta = other.get("metadata", {})
        # Wing match
        sim = 0.0
        if other_meta.get("wing") == wing:
            sim += 0.5
        if other_meta.get("room") == room:
            sim += 0.3

        # Embedding similarity if available
        # Note: would need access to embeddings; simplified here

        if sim >= min_similarity:
            related.append((other["id"], sim))

    # Sort by similarity desc, take top
    related.sort(key=lambda x: -x[1])
    return related[:max_related]


def propagate_confidence(
    palace: DxrkMemory,
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
        palace: DxrkMemory instance
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
        related = find_related_drawers(palace, current_id, min_similarity=min_similarity)
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


def adjusted_uncertainty(rd: float, propagated_confidence: float) -> float:
    """
    Adjust uncertainty (rd) based on propagated confidence.

    Higher confidence → lower uncertainty (more certain).
    rd_effective = rd * (1 - confidence)
    """
    return rd * (1.0 - propagated_confidence)


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
