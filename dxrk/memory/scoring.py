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


def score_meta(
    meta: dict[str, object],
    default_importance: float = 1.0,
    now: datetime | None = None,
) -> float:
    """Rank a drawer metadata dict (importance/access_count/filed_at/accessed_at)."""
    imp: object = default_importance
    for key in ("importance", "emotional_weight", "weight"):
        val = meta.get(key)
        if val is not None:
            imp = val
            break
    return rank_score(
        imp,
        meta.get("access_count", 0),
        meta.get("filed_at"),
        meta.get("accessed_at"),
        now,
    )
