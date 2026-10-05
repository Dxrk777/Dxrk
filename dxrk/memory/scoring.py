# SPDX-License-Identifier: MIT
"""Decay-aware memory scoring — Phase 2 lifecycle, stdlib only.

Single ranking signal combining three decay-aware inputs:

- explicit ``importance`` (caller-stamped; 0.0 when unknown),
- ``access_count`` recency (``log1p``-compressed frequency + ``accessed_at``
  half-life so a burst of old reads does not outrank fresh signals forever),
- ``filed_at`` half-life (exponential decay so stale drawers sink).

Deterministic, dependency-free. ``rank_score`` is the uniform entry point
used by ``top_by_importance`` (both ``types`` and ``__init__`` copies),
``Layer1`` and the sqlite fused ranker — one formula everywhere.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, cast

from .confidence import adjusted_uncertainty
from .migrate import ensure_spine_defaults
from .triplecopy import create_triple_copy, triple_copy_retrievability

# Half-life for filed_at decay: ~6 months. Matches the sqlite backend's
# pre-existing recency prior (exp decay, half-life ~125-180d) so the fused
# ranker and this scorer agree on what "stale" means.
HALF_LIFE_DAYS = 180.0
# Accessed-at decays faster: a drawer read a month ago keeps half its
# access boost; after ~4 months the boost is ~1/16.
ACCESSED_HALF_LIFE_DAYS = 30.0
# Weight of the log-compressed access frequency against raw importance.
ACCESS_WEIGHT = 0.5


def parse_dt(value: object) -> datetime | None:
    """Parse an ISO date/datetime to aware UTC, or None when missing/garbled."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def decay_factor(
    filed_at: object,
    half_life_days: float = HALF_LIFE_DAYS,
    now: datetime | None = None,
) -> float:
    """Exponential half-life decay in (0, 1]; 1.0 when the timestamp is missing.

    Future timestamps clamp to 1.0 (never boost above fresh).
    """
    dt = parse_dt(filed_at)
    if dt is None or half_life_days <= 0:
        return 1.0
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    age_days = (current - dt).total_seconds() / 86400.0
    if age_days <= 0:
        return 1.0
    return float(0.5 ** (age_days / half_life_days))


def rank_score(
    importance: object = 0.0,
    access_count: object = 0,
    filed_at: object = None,
    accessed_at: object = None,
    now: datetime | None = None,
) -> float:
    """Uniform memory rank: ``(importance + w*log1p(access)) * filed_decay * access_decay``.

    Missing signals are neutral (decay 1.0, access 0), so entries carrying
    only ``importance`` score exactly ``importance`` — legacy order preserved.
    """
    try:
        imp = float(cast(Any, importance)) if importance is not None else 0.0
    except (TypeError, ValueError):
        imp = 0.0
    try:
        accesses = int(cast(Any, access_count)) if access_count is not None else 0
    except (TypeError, ValueError):
        accesses = 0
    if accesses < 0:
        accesses = 0
    base = imp + ACCESS_WEIGHT * math.log1p(accesses)
    filed_decay = decay_factor(filed_at, HALF_LIFE_DAYS, now)
    accessed_decay = decay_factor(accessed_at, ACCESSED_HALF_LIFE_DAYS, now)
    return base * filed_decay * (0.5 + 0.5 * accessed_decay)


# ---------------------------------------------------------------------------
# RDU model (Fase 0) — FSRS-style stability/difficulty + rating deviation.
# ---------------------------------------------------------------------------
# rank = R_fsrs(t, S) * (0.7 + 0.3*log1p(n)/log1p(20)) + 0.05*(rd/350)
# R_fsrs(t, S) = (1 + (19/81)*t/S)^(-0.5), S in days, t idle days,
# n = access_count_total, rd init 350. Time alone only drops R; S/D are
# time-invariant and move only on outcomes (success / lapse). S caps at 365.
RDU_S_MAX = 365.0
RDU_RD_INIT = 350.0
RDU_RD_MIN = 30.0
RDU_RD_DRIFT_RATE = 2.0
RDU_RD_LAPSE_BUMP = 20.0
RDU_FREQ_BASE = 0.7
RDU_FREQ_GAIN = 0.3
RDU_FREQ_NORM_N = 20
RDU_RD_BOOST_W = 0.05
RDU_TIEBREAK_W = 0.01
RDU_IMP_SAT = 5.0
SPINE_S_FALLBACK = 1.0
_S_FLOOR = 0.05

# Prediction-error coupling (Zou 2025 - vmPFC-FSRS)
PE_LAMBDA = 0.1  # coupling strength, small for Fase 1
PE_CLAMP = 0.5  # clamp PE to [-0.5, 0.5]


def _clamp_float(value: object, default: float, low: float | None = None, high: float | None = None) -> float:
    try:
        result = float(cast(Any, value))
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    if low is not None and result < low:
        return low
    if high is not None and result > high:
        return high
    return result


def r_fsrs(t_days: object, stability_days: object) -> float:
    """Retrievability ``(1 + (19/81) * t / S) ** -0.5``; ``R(S) == 0.9``.

    Non-positive stability clamps to a small floor (never divides by zero);
    negative idle time clamps to 0 (future timestamps never boost).
    """
    t = _clamp_float(t_days, 0.0, low=0.0)
    s = _clamp_float(stability_days, SPINE_S_FALLBACK, low=_S_FLOOR)
    return float((1.0 + (19.0 / 81.0) * t / s) ** -0.5)


def frequency_factor(n: object) -> float:
    """Access-frequency multiplier in [0.7, 1.0]: ``0.7 + 0.3*log1p(n)/log1p(20)``.

    Saturates at 1.0 past n=20 reads (the ``/log1p(20)`` normalization
    point) — without the clamp, huge access counts would push the factor
    past 1.0 and let frequency dominate retrievability.
    """
    try:
        count = int(cast(Any, n))
    except (TypeError, ValueError):
        count = 0
    if count < 0:
        count = 0
    return min(1.0, RDU_FREQ_BASE + RDU_FREQ_GAIN * math.log1p(count) / math.log1p(RDU_FREQ_NORM_N))


def effective_rd(rd: object, t_days: object) -> float:
    """Inactivity-drifted rating deviation for the read-path boost.

    ``RD(t) = min(350, sqrt(rd^2 + 2.0^2 * t))`` — applied in reads only,
    never persisted (persistence happens on outcomes via the update rules).
    """
    base = _clamp_float(rd, RDU_RD_INIT, low=0.0)
    t = _clamp_float(t_days, 0.0, low=0.0)
    return min(RDU_RD_INIT, math.sqrt(base * base + (RDU_RD_DRIFT_RATE**2) * t))


def update_success(stability: object, difficulty: object, rd: object, retrievability: object) -> tuple[float, float]:
    """Success outcome (drawer read / search-hit used): stability grows, rd shrinks.

    ``S' = S * (1 + e^1.5 * (11-D) * S^-0.2 * (e^(1-R) - 1))`` capped at 365;
    ``rd' = max(30, rd * 0.9)``. Returns ``(S', rd')`` — difficulty is
    untouched by success.
    """
    s = _clamp_float(stability, SPINE_S_FALLBACK, low=_S_FLOOR)
    d = _clamp_float(difficulty, 5.0, low=1.0, high=10.0)
    base_rd = _clamp_float(rd, RDU_RD_INIT, low=0.0)
    r = _clamp_float(retrievability, 1.0, low=0.0, high=1.0)
    growth = math.exp(1.5) * (11.0 - d) * (s**-0.2) * (math.exp(1.0 * (1.0 - r)) - 1.0)
    s_new = min(RDU_S_MAX, max(_S_FLOOR, s * (1.0 + growth)))
    return s_new, max(RDU_RD_MIN, base_rd * 0.9)


def apply_success_with_pe(
    meta: dict[str, object],
    predicted_r: float,
    now: datetime | None = None,
) -> tuple[float, float, float]:
    """
    Success outcome with prediction-error coupling (vmPFC-FSRS, Zou 2025).

    PE = outcome - predicted_r
    S' = S_fsrs * (1 + PE_LAMBDA * PE)  — clamp PE to [-0.5, 0.5]

    Returns: (new_S, new_rd, PE)
    """
    m = ensure_spine_defaults(dict(meta)) if isinstance(meta, dict) else ensure_spine_defaults({})
    stability = _clamp_float(m.get("S"), SPINE_S_FALLBACK, low=_S_FLOOR)
    difficulty = _clamp_float(m.get("D"), 5.0, low=1.0, high=10.0)
    rd = _clamp_float(m.get("rd"), RDU_RD_INIT, low=0.0)
    r = _clamp_float(predicted_r, 1.0, low=0.0, high=1.0)

    # Standard FSRS success update
    growth = math.exp(1.5) * (11.0 - difficulty) * (stability**-0.2) * (math.exp(1.0 * (1.0 - r)) - 1.0)
    s_new = min(RDU_S_MAX, max(_S_FLOOR, stability * (1.0 + growth)))
    rd_new = max(RDU_RD_MIN, rd * 0.9)

    # Prediction error coupling
    pe = 1.0 - r  # outcome=1 (success) - predicted_r
    pe = max(-PE_CLAMP, min(PE_CLAMP, pe))
    s_new = min(RDU_S_MAX, max(_S_FLOOR, s_new * (1.0 + PE_LAMBDA * pe)))

    return s_new, rd_new, pe


def update_lapse(
    stability: object, difficulty: object, rd: object, retrievability: object
) -> tuple[float, float, float]:
    """Lapse outcome (contradiction / supersede / forget / quarantine).

    ``S' = 2 * D^-0.2 * ((S+1)^0.2 - 1) * e^(1-R)`` (stability collapses);
    ``D' = min(10, D + 0.5*(10-D)/9 + 0.03*(5.0-D))`` (difficulty rises with
    mean-reversion toward 5.0); ``rd' = min(350, rd + 20)``. Returns
    ``(S', D', rd')``.
    """
    s = _clamp_float(stability, SPINE_S_FALLBACK, low=0.0)
    d = _clamp_float(difficulty, 5.0, low=1.0, high=10.0)
    base_rd = _clamp_float(rd, RDU_RD_INIT, low=0.0)
    r = _clamp_float(retrievability, 1.0, low=0.0, high=1.0)
    s_new = min(RDU_S_MAX, max(_S_FLOOR, 2.0 * (d**-0.2) * ((s + 1.0) ** 0.2 - 1.0) * math.exp(1.0 * (1.0 - r))))
    d_new = min(10.0, d + 0.5 * (10.0 - d) / 9.0 + 0.03 * (5.0 - d))
    return s_new, d_new, min(RDU_RD_INIT, base_rd + RDU_RD_LAPSE_BUMP)


def _days_since_access(meta: dict[str, object], current: datetime) -> float:
    """Idle days since last access (``accessed_at`` else ``filed_at`` else 0)."""
    raw: object = meta.get("accessed_at") or meta.get("filed_at")
    dt = parse_dt(raw)
    if dt is None:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    age = (current - dt).total_seconds() / 86400.0
    return max(0.0, age)


def score_meta(
    meta: dict[str, object],
    default_importance: float = 1.0,
    now: datetime | None = None,
) -> float:
    """Rank a drawer metadata dict with the enhanced RDU model (Fase 1).

    ``rank = R_triple(t, S) * freq(n) + 0.05 * (rd_eff / 350) + 0.15 * (synapse_w - 0.5) + tiebreak`` with

    - ``R_triple(t, S) = max(R_fast, R_medium, R_deep)`` — TripleCopy retrievability
      (Schapiro 2017, Kumaran 2016): three copies with divergent decay.
    - ``t`` = days since last access (``accessed_at`` else ``filed_at``),
    - ``freq(n) = 0.7 + 0.3 * log1p(n) / log1p(20)``,
      ``n = access_count_total``,
    - ``rd_eff`` = confidence-adjusted uncertainty (``min(350, sqrt(rd^2 + 4*t)) * (1 - confidence)``),
    - ``synapse_w`` = synaptic weight from Two-Factor STDP (0..1, centered at 0.5),
    - ``tiebreak = 0.01 * clamp(importance / 5)`` — a deliberately tiny
      static prior so Phase 2 invariants survive.

    Spine keys are read through :func:`migrate.ensure_spine_defaults` on a
    copy, so legacy rows score with their migrated priors without mutating
    the caller's dict.
    """
    m = ensure_spine_defaults(dict(meta)) if isinstance(meta, dict) else ensure_spine_defaults({})
    stability = _clamp_float(m.get("S"), SPINE_S_FALLBACK, low=_S_FLOOR)
    difficulty = _clamp_float(m.get("D"), 5.0, low=1.0, high=10.0)
    _ = difficulty  # difficulty shapes updates, not the rank itself
    rd = _clamp_float(m.get("rd"), RDU_RD_INIT, low=0.0)
    try:
        n = int(cast(Any, m.get("access_count_total", m.get("access_count", 0))))
    except (TypeError, ValueError):
        n = 0
    if n < 0:
        n = 0
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    t_days = _days_since_access(m, current)

    # TripleCopy retrievability (replaces single r_fsrs)
    tc = create_triple_copy(stability)
    retrievability = triple_copy_retrievability(tc, t_days)

    # Confidence-adjusted uncertainty
    confidence = _clamp_float(m.get("confidence", 0.5), 0.5, low=0.0, high=1.0)
    rd_eff = adjusted_uncertainty(rd, t_days, confidence)

    # Synapse weight boost (0..1, centered at 0.5)
    synapse_weight = _clamp_float(m.get("synapse_weight", 0.5), 0.5, low=0.0, high=1.0)
    synapse_boost = 0.15 * (synapse_weight - 0.5)

    imp: object = default_importance
    for key in ("importance", "emotional_weight", "weight"):
        val = m.get(key)
        if val is not None:
            imp = val
            break
    try:
        imp_f = float(cast(Any, imp))
    except (TypeError, ValueError):
        imp_f = default_importance if isinstance(default_importance, (int, float)) else 1.0
    tiebreak = RDU_TIEBREAK_W * min(1.0, max(0.0, imp_f / RDU_IMP_SAT))
    return retrievability * frequency_factor(n) + RDU_RD_BOOST_W * (rd_eff / RDU_RD_INIT) + synapse_boost + tiebreak
