# SPDX-License-Identifier: MIT
"""Bayesian Confidence Propagation (McGaugh 2004) — no malla dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class RecallLike(Protocol):
    """Minimal recall protocol for confidence propagation."""

    id: str
    metadata: dict
    quarantined: bool


class RecallIterator(Protocol):
    """Protocol for iterating recalls."""

    def __call__(self) -> list[RecallLike]: ...


class RecallGetter(Protocol):
    """Protocol for getting a single recall by ID."""

    def __call__(self, recall_id: str) -> RecallLike | None: ...


@dataclass(frozen=True)
class ConfidencePropagation:
    """Result of confidence propagation."""

    propagated_confidence: float
    depth_reached: int
    related_count: int


def find_related_recalls(
    get_recall: RecallGetter,
    iter_recalls: RecallIterator,
    recall_id: str,
    max_related: int = 10,
    min_similarity: float = 0.3,
) -> list[tuple[str, float]]:
    """
    Find related recalls by partition/subgroup and embedding similarity.

    Returns: list of (recall_id, similarity) sorted by similarity desc.
    """
    # Get the source recall to find its partition/subgroup
    source = get_recall(recall_id)
    if not source:
        return []

    def _get(d, key, default=None):
        if hasattr(d, key):
            return getattr(d, key)
        return d.get(key, default)

    source_meta = _get(source, "metadata", {})
    partition = source_meta.get("partition", "")
    subgroup = source_meta.get("subgroup", "")

    # Find recalls in same partition/subgroup (structural similarity)
    related = []
    for other in iter_recalls():
        if _get(other, "id") == recall_id:
            continue
        if _get(other, "quarantined"):
            continue

        other_meta = _get(other, "metadata", {})
        # Partition match
        sim = 0.0
        if other_meta.get("partition") == partition:
            sim += 0.5
        if other_meta.get("subgroup") == subgroup:
            sim += 0.3

        # Embedding similarity if available (would need embeddings access)

        if sim >= min_similarity:
            related.append((_get(other, "id"), sim))

    # Sort by similarity desc, take top
    related.sort(key=lambda x: -x[1])
    return related[:max_related]


def propagate_confidence(
    get_recall: RecallGetter,
    iter_recalls: RecallIterator,
    recall_id: str,
    base_confidence: float,
    max_depth: int = 2,
    decay_per_depth: float = 0.5,
    min_similarity: float = 0.3,
) -> ConfidencePropagation:
    """
    Propagate confidence from a recall to related recalls (Bayesian propagation).

    Confidence propagates through the graph:
    confidence(d) = base_conf(d) * Π(1 + sim * related_conf * decay) for depth levels

    Args:
        get_recall: callable(recall_id) -> recall or None
        iter_recalls: callable() -> list of recalls
        recall_id: starting recall
        base_confidence: confidence of source recall
        max_depth: max propagation depth
        decay_per_depth: multiplicative decay per depth level
        min_similarity: minimum similarity to propagate

    Returns:
        ConfidencePropagation with propagated confidence, depth reached, related count
    """
    if max_depth <= 0:
        return ConfidencePropagation(base_confidence, 0, 0)

    # BFS propagation
    visited = {recall_id}
    queue = [(recall_id, base_confidence, 0)]
    total_propagated = 0.0
    related_count = 0
    max_depth_reached = 0

    while queue:
        current_id, current_conf, depth = queue.pop(0)

        if depth >= max_depth:
            continue

        # Find related recalls
        related = find_related_recalls(get_recall, iter_recalls, current_id, min_similarity=min_similarity)
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
    rd_eff = float(min(350.0, (rd * rd + 4.0 * t_days) ** 0.5))
    # Confidence adjustment
    return float(rd_eff * (1.0 - confidence))


def confidence_from_retrievability(meta: dict) -> float:
    """Estimate confidence from recall's retrievability and stability."""
    S = float(meta.get("S", 1.0))
    D = float(meta.get("D", 5.0))
    rd = float(meta.get("rd", 350.0))

    # Higher stability + lower difficulty + lower rd = higher confidence
    stability_factor = min(1.0, S / 365.0)  # S max 365
    difficulty_factor = 1.0 - (D - 1.0) / 9.0  # D in [1,10] → [1,0]
    uncertainty_factor = 1.0 - min(1.0, rd / 350.0)

    return stability_factor * 0.5 + difficulty_factor * 0.3 + uncertainty_factor * 0.2
