# SPDX-License-Identifier: MIT
"""NeuromodulatorEngine — four channels DA/NE/5HT/ACh (Dayan & Huys 2009)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class NeuromodState:
    """Global neuromodulator state (one per palace)."""

    da: float = 0.0  # Dopamine: reward prediction error, potentiates LTP
    ne: float = 0.0  # Noradrenaline: arousal/salience, resets consolidation
    sht: float = 0.0  # Serotonin (5HT): patience, modulates intervals
    ach: float = 0.0  # Acetylcholine: gates encoding vs consolidation
    last_update: str = ""


# Decay per cycle (per sleep/consolidation cycle)
NEUROMOD_DECAY = 0.90
# Max values
MAX_LEVEL = 1.0
# Reward magnitudes
REWARD_MAGNITUDE = 0.3
ALERT_MAGNITUDE = 0.4
CONSOLIDATE_SHT = 0.2
CONSOLIDATE_ACH_DECAY = 0.3
ENCODE_ACH = 0.2
ENCODE_ACH_MAX = 0.8


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def reward(state: NeuromodState, magnitude: float = REWARD_MAGNITUDE) -> NeuromodState:
    """DA spike: positive prediction error (judge accepted, recall success)."""
    return replace(state, da=clamp(state.da + magnitude), last_update=_now_iso())


def alert(state: NeuromodState, severity: float = ALERT_MAGNITUDE) -> NeuromodState:
    """NE spike: checksum mismatch, quarantine, unexpected error."""
    return replace(state, ne=clamp(state.ne + severity), last_update=_now_iso())


def consolidate(state: NeuromodState) -> NeuromodState:
    """Sleep consolidation: 5HT up, ACh down."""
    return replace(
        state,
        sht=clamp(state.sht + CONSOLIDATE_SHT),
        ach=max(0.0, state.ach - CONSOLIDATE_ACH_DECAY),
        last_update=_now_iso(),
    )


def encode_mode(state: NeuromodState) -> NeuromodState:
    """Active encoding (reads/writes): ACh up."""
    return replace(state, ach=clamp(state.ach + ENCODE_ACH, hi=ENCODE_ACH_MAX), last_update=_now_iso())


def decay_all(state: NeuromodState) -> NeuromodState:
    """Apply decay to all channels (per cycle)."""
    return replace(
        state,
        da=state.da * NEUROMOD_DECAY,
        ne=state.ne * NEUROMOD_DECAY,
        sht=state.sht * NEUROMOD_DECAY,
        ach=state.ach * NEUROMOD_DECAY,
        last_update=_now_iso(),
    )


def stress_mode(state: NeuromodState) -> NeuromodState:
    """Cooperative masking: high stress → elevated NE baseline."""
    return replace(state, ne=clamp(state.ne + 0.3), last_update=_now_iso())


def load_neuromod_state(palace_path: Path) -> NeuromodState:
    """Load neuromodulator state from sidecar JSON."""
    path = palace_path / ".neuromod_state.json"
    if not path.exists():
        return NeuromodState()
    try:
        data = json.loads(path.read_text())
        return NeuromodState(
            da=data.get("da", 0.0),
            ne=data.get("ne", 0.0),
            sht=data.get("sht", 0.0),
            ach=data.get("ach", 0.0),
            last_update=data.get("last_update", ""),
        )
    except Exception:
        return NeuromodState()


def save_neuromod_state(palace_path: Path, state: NeuromodState) -> None:
    """Persist neuromodulator state to sidecar JSON (0o600)."""
    path = palace_path / ".neuromod_state.json"
    path.write_text(json.dumps(asdict(state), indent=2))
    path.chmod(0o600)


def effective_learning_rate(base_eta: float, state: NeuromodState) -> float:
    """
    Compute effective learning rate modulated by neuromodulators.

    η_eff = η_base * (1 + DA) * (1 + NE) * (1 - 0.5*ACh)
    """
    return base_eta * (1.0 + state.da) * (1.0 + state.ne) * (1.0 - 0.5 * state.ach)
