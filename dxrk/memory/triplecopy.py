# SPDX-License-Identifier: MIT
"""TripleCopyMemory — three divergent decay copies (Schapiro 2017, Kumaran 2016)."""

from __future__ import annotations

from dataclasses import dataclass

# FSRS-4.5 constants (from scoring.py)
_FACTOR = 19.0 / 81.0
_DECAY = -0.5


@dataclass(frozen=True)
class TripleCopy:
    """Three copies of a memory with different stabilities."""

    fast: float  # S_fast = S / 4 (detail, decays fast)
    medium: float  # S_medium = S (main stability)
    deep: float  # S_deep = S * 4 (schema, decays slow)


def create_triple_copy(S: float) -> TripleCopy:
    """Create triple copy from main stability S."""
    return TripleCopy(
        fast=max(0.25, S / 4.0),
        medium=S,
        deep=S * 4.0,
    )


def triple_copy_retrievability(tc: TripleCopy, t_days: float) -> float:
    """
    Total retrievability = max of three copies.

    The fast copy captures recent detail (decays quickly).
    The deep copy captures semantic schema (decays slowly).
    The max captures: "I remember the detail" OR "I remember the gist".
    """
    r_fast = _retrievability(t_days, tc.fast)
    r_medium = _retrievability(t_days, tc.medium)
    r_deep = _retrievability(t_days, tc.deep)
    return max(r_fast, r_medium, r_deep)


def _retrievability(t: float, S: float) -> float:
    """FSRS-4.5 retrievability: R(t,S) = (1 + FACTOR * t/S)^DECAY."""
    if S <= 0:
        return 0.0
    return (1.0 + _FACTOR * t / S) ** _DECAY


def update_triple_copy(tc: TripleCopy, outcome: float, t_days: float, S: float) -> TripleCopy:
    """
    Update triple copy after a recall outcome.

    outcome: 1.0 = success, 0.0 = failure (lapse)
    t_days: time since last access
    S: current main stability (updated by FSRS)
    """
    # Recreate from updated S
    new_tc = create_triple_copy(S)
    return new_tc


def update_fast_only(tc: TripleCopy, outcome: float, t_days: float) -> TripleCopy:
    """
    Fine-grained update: only fast copy changes on each access.
    Medium and deep only update when S changes (less frequently).
    """
    # Fast copy updates with every access (detail level)
    # For simplicity, we just recreate from S which is updated elsewhere
    return tc  # placeholder for more complex logic


def get_copy_ages(tc: TripleCopy) -> tuple[float, float, float]:
    """Get effective ages where each copy hits R=0.9."""
    # At t=S, R=0.9 by definition of FSRS
    return (tc.fast, tc.medium, tc.deep)


def effective_retrievability(
    tc: TripleCopy, t_days: float, weight_fast: float = 0.5, weight_deep: float = 0.2
) -> float:
    """
    Weighted retrievability for scoring.

    Weighted sum emphasizes recent detail (fast) but preserves deep schema.
    """
    r_fast = _retrievability(t_days, tc.fast)
    r_medium = _retrievability(t_days, tc.medium)
    r_deep = _retrievability(t_days, tc.deep)
    return weight_fast * r_fast + (1.0 - weight_fast - weight_deep) * r_medium + weight_deep * r_deep
