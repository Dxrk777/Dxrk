# SPDX-License-Identifier: MIT
"""MetacognitiveMonitor — ECE + bias tracking (Fleming & Dolan 2012)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Expected Calibration Error bins
DEFAULT_BINS = 10
CONFIDENCE_HISTORY_CAP = 100


@dataclass
class MetacogState:
    """Global metacognitive state (one per palace)."""

    calibration_error: float = 0.0  # Current ECE
    bias_direction: float = 0.0  # >0 over-confident, <0 under-confident
    confidence_history: list[tuple[float, float]] = field(default_factory=list)  # (predicted, actual)
    n_judgments: int = 0
    last_update: str = ""


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def compute_ece(history: list[tuple[float, float]], n_bins: int = DEFAULT_BINS) -> float:
    """
    Expected Calibration Error (ECE).

    Bins predictions into n_bins, computes weighted average of
    |avg_confidence - avg_accuracy| per bin.
    """
    if not history:
        return 0.0

    bins = defaultdict(list)
    for p, a in history:
        bin_idx = min(int(p * n_bins), n_bins - 1)
        bins[bin_idx].append((p, a))

    ece = 0.0
    total = len(history)
    for bin_idx, items in bins.items():
        if not items:
            continue
        avg_conf = sum(p for p, _ in items) / len(items)
        avg_acc = sum(a for _, a in items) / len(items)
        ece += (len(items) / total) * abs(avg_conf - avg_acc)

    return ece


def record_judgment(state: MetacogState, predicted: float, actual: float) -> MetacogState:
    """
    Record a metacognitive judgment.

    Args:
        state: current MetacogState
        predicted: system's predicted confidence (0..1)
        actual: actual outcome (0 or 1, or confidence if graded)
    """
    predicted = clamp(predicted)
    actual = clamp(actual)

    # Update bias with exponential moving average
    error = predicted - actual
    state.bias_direction = state.bias_direction * 0.95 + error * 0.05

    # Add to history (capped)
    state.confidence_history.append((predicted, actual))
    if len(state.confidence_history) > CONFIDENCE_HISTORY_CAP:
        state.confidence_history.pop(0)

    state.n_judgments += 1
    state.calibration_error = compute_ece(state.confidence_history)
    state.last_update = _now_iso()

    return state


def adjusted_confidence(state: MetacogState, raw_confidence: float) -> float:
    """
    Correct raw confidence with learned bias.

    If system tends to over-confide (bias > 0), subtract bias.
    If system tends to under-confide (bias < 0), add |bias|.
    """
    return clamp(raw_confidence - state.bias_direction)


def get_bias_category(state: MetacogState) -> str:
    """Categorize bias direction."""
    if state.bias_direction > 0.1:
        return "overconfident"
    elif state.bias_direction < -0.1:
        return "underconfident"
    return "well_calibrated"


def load_metacog_state(palace_path: Path) -> MetacogState:
    """Load metacognitive state from sidecar JSON."""
    path = palace_path / ".metacog_state.json"
    if not path.exists():
        return MetacogState()
    try:
        data = json.loads(path.read_text())
        return MetacogState(
            calibration_error=data.get("calibration_error", 0.0),
            bias_direction=data.get("bias_direction", 0.0),
            confidence_history=data.get("confidence_history", []),
            n_judgments=data.get("n_judgments", 0),
            last_update=data.get("last_update", ""),
        )
    except Exception:
        return MetacogState()


def save_metacog_state(palace_path: Path, state: MetacogState) -> None:
    """Persist metacognitive state to sidecar JSON (0o600)."""
    path = palace_path / ".metacog_state.json"
    # Convert tuple list to list of lists for JSON
    data = asdict(state)
    data["confidence_history"] = [list(pair) for pair in state.confidence_history]
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)


def confidence_from_outcome(hit: bool, base_confidence: float = 0.5) -> float:
    """
    Convert hit/miss to confidence signal for metacog tracking.

    In a full implementation, this would come from the model's
    predicted probability. For now, use base confidence.
    """
    return base_confidence
