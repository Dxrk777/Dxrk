# SPDX-License-Identifier: MIT
"""Stress detection and cooperative masking (ZenBrain finding)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from dxrk.memory.palace import DxrkMemory


@dataclass(frozen=True)
class StressState:
    """Global stress state of the palace."""

    level: float = 0.0  # [0, 1] current stress
    last_computed: str = ""  # ISO timestamp
    defenses_active: bool = False  # whether cooperative masking is active
    density: float = 0.0  # drawer density (count/cap)
    avg_inv_stability: float = 0.0  # mean 1/S
    recent_quarantines: int = 0  # quarantines in last 7 days


STRESS_ACTIVATION_THRESHOLD = 0.6
STRESS_DEACTIVATION_THRESHOLD = 0.4
QUARANTINE_WINDOW_DAYS = 7
QUARANTINE_NORMALIZER = 10.0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def compute_system_stress(palace: DxrkMemory) -> StressState:
    """
    Compute system stress level (ZenBrain cooperative masking).

    Stress = 0.4 * density + 0.4 * avg_inv_stability + 0.2 * quarantine_rate

    High stress → activate defensive mechanisms (TripleCopy full, shorter reconsolidation, etc.)
    """
    wings = palace.list_wings()
    total_drawers = 0
    total_cap = 0
    inv_stabilities = []
    recent_q = 0
    cutoff = datetime.now(UTC)

    col = palace._collection(create=False)
    for wing in wings:
        usage = palace.wing_usage(wing)
        total_drawers += int(cast(Any, usage.get("count", 0)))
        total_cap += int(cast(Any, usage.get("budget", 0)))
        # Query drawers in this wing
        got = col.get(
            where={"wing": {"$in": [wing]}},
            include=["metadatas"],
            limit=2000,
        )
        for meta in got.metadatas:
            if not isinstance(meta, dict):
                continue
            # Inverse stability
            s = meta.get("S", 1.0)
            if isinstance(s, (int, float)) and s > 0:
                inv_stabilities.append(1.0 / s)
            # Recent quarantines
            q_reason = meta.get("quarantine_reason", "")
            q_at = meta.get("quarantined_at", "")
            if q_reason and q_at:
                try:
                    q_dt = datetime.fromisoformat(str(q_at).replace("Z", "+00:00"))
                    if q_dt.tzinfo is None:
                        q_dt = q_dt.replace(tzinfo=UTC)
                    if (cutoff - q_dt).days <= QUARANTINE_WINDOW_DAYS:
                        recent_q += 1
                except Exception:
                    pass

    density = total_drawers / total_cap if total_cap > 0 else 0.0
    avg_inv_s = sum(inv_stabilities) / len(inv_stabilities) if inv_stabilities else 0.0
    quarantine_rate = min(recent_q / QUARANTINE_NORMALIZER, 1.0)

    stress_level = 0.4 * density + 0.4 * clamp(avg_inv_s) + 0.2 * quarantine_rate

    # Load previous state to check hysteresis
    prev = load_stress_state(Path(palace.palace_path))

    # Hysteresis: activate at 0.6, deactivate at 0.4
    if prev.defenses_active:
        defenses_active = stress_level > STRESS_DEACTIVATION_THRESHOLD
    else:
        defenses_active = stress_level > STRESS_ACTIVATION_THRESHOLD

    state = StressState(
        level=clamp(stress_level),
        last_computed=_now_iso(),
        defenses_active=defenses_active,
        density=clamp(density),
        avg_inv_stability=clamp(avg_inv_s),
        recent_quarantines=recent_q,
    )

    save_stress_state(Path(palace.palace_path), state)
    return state


def should_activate_defenses(stress_state: StressState) -> bool:
    """Check if defensive mechanisms should be active."""
    return stress_state.defenses_active


def get_defense_params(stress_state: StressState) -> dict:
    """
    Return defense parameters based on stress level.

    When defenses active:
    - TripleCopy full (not just lazy)
    - Reconsolidation window: 6h → 2h
    - Sleep threshold: lower (consolidate more)
    - NE baseline: elevated
    """
    if not stress_state.defenses_active:
        return {
            "triplecopy_full": False,
            "reconsolidation_hours": 6,
            "sleep_priority_threshold": 0.5,
            "ne_baseline": 0.0,
        }
    return {
        "triplecopy_full": True,
        "reconsolidation_hours": 2,
        "sleep_priority_threshold": 0.3,
        "ne_baseline": 0.3,
    }


def load_stress_state(palace_path: Path) -> StressState:
    """Load stress state from sidecar JSON."""
    path = palace_path / ".stress_state.json"
    if not path.exists():
        return StressState()
    try:
        import json

        data = json.loads(path.read_text())
        return StressState(
            level=data.get("level", 0.0),
            last_computed=data.get("last_computed", ""),
            defenses_active=data.get("defenses_active", False),
            density=data.get("density", 0.0),
            avg_inv_stability=data.get("avg_inv_stability", 0.0),
            recent_quarantines=data.get("recent_quarantines", 0),
        )
    except Exception:
        return StressState()


def save_stress_state(palace_path: Path, state: StressState) -> None:
    """Persist stress state to sidecar JSON."""
    import json

    path = palace_path / ".stress_state.json"
    path.write_text(
        json.dumps(
            {
                "level": state.level,
                "last_computed": state.last_computed,
                "defenses_active": state.defenses_active,
                "density": state.density,
                "avg_inv_stability": state.avg_inv_stability,
                "recent_quarantines": state.recent_quarantines,
            },
            indent=2,
        )
    )
    path.chmod(0o600)
