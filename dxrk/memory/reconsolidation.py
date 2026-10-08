# SPDX-License-Identifier: MIT
"""ReconsolidationEngine — labile window on recall (Nader 2000, Nader & Hardt 2009)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from dxrk.memory.scoring import update_lapse, update_success


@dataclass(frozen=True)
class ReconsolidationState:
    """Per-drawer reconsolidation state."""

    labile_until: str = ""  # ISO timestamp when labile window closes
    reconsolidation_count: int = 0  # number of reconsolidation events


# Labile window: 6 hours after recall
LABILE_WINDOW_HOURS = 6


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(ts: str) -> datetime:
    """Parse ISO timestamp to aware UTC."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def is_labile(state: ReconsolidationState) -> bool:
    """Check if drawer is in labile window."""
    if not state.labile_until:
        return False
    return datetime.now(UTC) < _parse_iso(state.labile_until)


def mark_labile(state: ReconsolidationState) -> ReconsolidationState:
    """Mark drawer as labile for LABILE_WINDOW_HOURS (called on recall)."""
    labile_until = datetime.now(UTC) + timedelta(hours=LABILE_WINDOW_HOURS)
    return replace(state, labile_until=labile_until.isoformat())


def reconsolidate(
    state: ReconsolidationState,
    stability: float,
    difficulty: float,
    rd: float,
    outcome: float,  # 0..1, quality of recall
) -> tuple[ReconsolidationState, float, float, float]:
    """
    Reconsolidate drawer based on recall outcome.

    If within labile window:
      - outcome >= 0.7: strengthen (S * 1.1)
      - outcome < 0.3: weaken (S * 0.85)
      - else: no change
    If outside labile window: S * 0.9 (passive decay)

    Returns: (new_state, new_S, new_D, new_rd)
    """
    now = datetime.now(UTC)

    if not state.labile_until:
        # Not in labile state, nothing to do
        return state, stability, difficulty, rd

    labile_until = _parse_iso(state.labile_until)

    if now > labile_until:
        # Window closed without reconsolidation → passive decay
        new_stability = max(0.05, stability * 0.9)
        new_state = replace(state, labile_until="")
        return new_state, new_stability, difficulty, rd

    # Within labile window: active reconsolidation
    if outcome >= 0.7:
        # Good recall: strengthen
        new_stability = min(365.0, stability * 1.1)
    elif outcome <= 0.3:
        # Poor recall: weaken
        new_stability = max(0.05, stability * 0.85)
    else:
        # Neutral: no change
        new_stability = stability

    new_state = replace(
        state,
        labile_until="",
        reconsolidation_count=state.reconsolidation_count + 1,
    )
    return new_state, new_stability, difficulty, rd


def reconsolidate_with_fsrs(
    state: ReconsolidationState,
    stability: float,
    difficulty: float,
    rd: float,
    retrievability: float,
    outcome: float,  # 1.0 = success, 0.0 = lapse
) -> tuple[ReconsolidationState, float, float, float]:
    """
    Reconsolidate using FSRS update rules.

    Uses the existing update_success/update_lapse from scoring.py.
    """
    now = datetime.now(UTC)

    if not state.labile_until:
        return state, stability, difficulty, rd

    labile_until = _parse_iso(state.labile_until)

    if now > labile_until:
        # Window closed without reconsolidation → passive decay
        new_stability = max(0.05, stability * 0.9)
        new_state = replace(state, labile_until="")
        return new_state, new_stability, difficulty, rd

    # Within labile window: apply FSRS update
    if outcome >= 0.7:
        new_s, new_rd = update_success(stability, difficulty, rd, retrievability)
        new_d = difficulty
    else:
        new_s, new_d, new_rd = update_lapse(stability, difficulty, rd, retrievability)

    new_state = replace(
        state,
        labile_until="",
        reconsolidation_count=state.reconsolidation_count + 1,
    )
    return new_state, new_s, new_d, new_rd


def get_labile_remaining(state: ReconsolidationState) -> float:
    """Get remaining labile window in hours (negative if closed)."""
    if not state.labile_until:
        return -1.0
    labile_until = _parse_iso(state.labile_until)
    delta = labile_until - datetime.now(UTC)
    return delta.total_seconds() / 3600.0
