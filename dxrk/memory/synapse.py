# SPDX-License-Identifier: MIT
"""Synapse core — Two-Factor STDP with neuromodulation."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class SynapseState:
    """State of a synaptic connection (one drawer's synaptic weight)."""

    weight: float = 0.5  # [0, 1], initial neutral
    last_stdp: str = ""  # ISO timestamp of last STDP event
    neuromod: float = 0.0  # [0, 1], accumulated neuromodulator (dopamine-like)


# Time constants (in days, scaled from ms for our domain)
TAU_PLUS = 20.0  # LTP window ~20 days equivalent
TAU_MINUS = 40.0  # LTD window ~40 days equivalent
NEUROMOD_DECAY = 0.95  # per access
ETA_BASE = 0.01  # base learning rate


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def stdp_update(
    state: SynapseState,
    pre: float,
    post: float,
    dt: float,
    eta: float = ETA_BASE,
    neuromod: float = 0.0,
) -> SynapseState:
    """
    Spike-Timing-Dependent Plasticity with neuromodulation (Two-Factor model).

    Args:
        state: current SynapseState
        pre: pre-synaptic activity (query relevance, 0..1)
        post: post-synaptic activity (hit=1.0, miss=0.0, partial in between)
        dt: time difference (pre - post) in days; negative = pre before post (LTP)
        eta: base learning rate
        neuromod: neuromodulator level (0..1, DA-like)

    Returns:
        New SynapseState with updated weight, timestamp, and decayed neuromod.
    """
    # STDP kernel
    if dt < 0:
        # pre before post → LTP (potentiation)
        delta = eta * pre * post * math.exp(dt / TAU_PLUS)
    else:
        # post before pre → LTD (depression)
        delta = -eta * pre * post * math.exp(-dt / TAU_MINUS)

    # Two-factor: neuromodulation scales the change
    delta *= 1.0 + neuromod

    new_weight = clamp(state.weight + delta)

    # Neuromodulator decays with each access
    new_neuromod = state.neuromod * NEUROMOD_DECAY

    return replace(
        state,
        weight=new_weight,
        last_stdp=_now_iso(),
        neuromod=new_neuromod,
    )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def apply_reward(state: SynapseState, magnitude: float = 0.3) -> SynapseState:
    """Apply a reward signal (dopamine spike)."""
    return replace(state, neuromod=clamp(state.neuromod + magnitude))


def effective_learning_rate(state: SynapseState, ach: float = 0.0) -> float:
    """
    Effective learning rate modulated by neuromodulators.

    DA and NE enhance; ACh gates encoding vs consolidation.
    """
    da = state.neuromod  # using neuromod as DA proxy
    ne = 0.0  # NE tracked separately in NeuromodState
    # η_eff = η_base * (1 + DA) * (1 + NE) * (1 - 0.5*ACh)
    return ETA_BASE * (1.0 + da) * (1.0 + ne) * (1.0 - 0.5 * ach)
