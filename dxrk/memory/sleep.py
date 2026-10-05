# SPDX-License-Identifier: MIT
"""Sleep consolidation — Simulation-Selection loop (Lee & Jung 2025, CA3/CA1 replay)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .scoring import r_fsrs


@dataclass(frozen=True)
class SleepCandidate:
    """A drawer selected for sleep consolidation."""

    drawer_id: str
    priority: float
    reason: str  # "pe_high" | "stale" | "contradiction" | "near_dup"


@dataclass(frozen=True)
class SleepState:
    """Sleep engine state (sidecar)."""

    last_sleep: str = ""
    last_candidates: int = 0
    total_consolidated: int = 0


Labile_WINDOW_HOURS = 6
SLEEP_SIDECAR = ".sleep_state.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def is_protected(drawer: dict) -> bool:
    """Check if drawer is protected from sleep consolidation."""
    meta = drawer.get("metadata", {})
    if meta.get("pinned"):
        return True
    if meta.get("quarantined"):
        return True
    # Recent valid_to (not superseded)
    vt = meta.get("valid_to")
    if vt:
        try:
            vt_dt = datetime.fromisoformat(vt.replace("Z", "+00:00"))
            if (datetime.now(UTC) - vt_dt) < timedelta(days=7):
                return True
        except Exception:
            pass
    return False


def avg_prediction_error(drawer: dict) -> float:
    """Compute average prediction error from ledger."""
    ledger = drawer.get("metadata", {}).get("score_ledger", [])
    if not ledger:
        return 0.0
    pes = [entry.get("pe", 0.0) for entry in ledger if "pe" in entry]
    if not pes:
        return 0.0
    return sum(abs(pe) for pe in pes) / len(pes)


def count_supersedes(drawer: dict) -> int:
    """Count superseded relations."""
    # Simple heuristic: superseded count in metadata
    return drawer.get("metadata", {}).get("superseded_count", 0)


def select_sleep_candidates(
    palace,
    limit: int = 50,
    stress_active: bool = False,
) -> list[SleepCandidate]:
    """
    Selection à la CA3 replay: prioritize prediction error, not recency.

    Args:
        palace: DxrkMemory instance
        limit: max candidates to return
        stress_active: if True, lower threshold (cooperative masking)

    Returns:
        List of SleepCandidate sorted by priority desc.
    """
    threshold = 0.1 if stress_active else 0.3
    candidates = []

    for drawer in palace.iter_drawers():
        if is_protected(drawer):
            continue

        pe_avg = avg_prediction_error(drawer)
        staleness = age_days(drawer.get("metadata", {}).get("filed_at"))
        contradiction = count_supersedes(drawer)

        # Simulation-Selection priority (Lee & Jung 2025)
        priority = (
            2.0 * pe_avg  # prediction error dominant
            + 0.5 * max(0.0, staleness - 30)  # only stale > 30 days
            + 1.5 * contradiction
        )

        if priority > threshold:
            reason = classify_reason(pe_avg, staleness, contradiction)
            candidates.append(
                SleepCandidate(
                    drawer_id=drawer["id"],
                    priority=priority,
                    reason=reason,
                )
            )

    return sorted(candidates, key=lambda c: -c.priority)[:limit]


def classify_reason(pe_avg: float, staleness: float, contradiction: int) -> str:
    """Classify why this drawer was selected."""
    if contradiction > 0:
        return "contradiction"
    if pe_avg > 0.2:
        return "pe_high"
    if staleness > 90:
        return "stale"
    return "near_dup"


def age_days(filed_at: str | None) -> float:
    """Days since filed_at."""
    if not filed_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(filed_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return (datetime.now(UTC) - dt).total_seconds() / 86400.0
    except Exception:
        return 0.0


def consolidate_candidate(palace, candidate: SleepCandidate) -> dict:
    """
    Consolidation CA3→CA1:
    1. Replay: re-evaluate the drawer against corpus
    2. Integrate: update S/D with PE
    3. Prune: if near-duplicate, merge
    """
    drawer = palace.get_drawer(candidate.drawer_id)
    if not drawer or "document" not in drawer:
        return {"status": "not_found"}

    meta = drawer.get("metadata", {})
    if is_protected(drawer):
        return {"status": "protected"}

    # NREM phase: replay (re-evaluate)
    pe = avg_prediction_error(drawer)

    # Apply consolidation based on reason
    if candidate.reason == "near_dup":
        # REM phase: merge near-duplicates (handled in reorganize)
        return {"status": "deferred_rem"}

    # Update stability with PE coupling
    from .scoring import update_lapse, update_success

    # Simulate a "success" replay with predicted_r from retrievability
    predicted_r = r_fsrs(age_days(meta.get("accessed_at") or meta.get("filed_at")), meta.get("S", 1.0))

    if candidate.reason == "pe_high" and pe < -0.1:
        # Negative PE = recall was worse than predicted → lapse
        s_new, d_new, rd_new = update_lapse(meta.get("S", 1.0), meta.get("D", 5.0), meta.get("rd", 350.0), predicted_r)
    else:
        # Positive or neutral PE → success
        s_new, rd_new = update_success(meta.get("S", 1.0), meta.get("D", 5.0), meta.get("rd", 350.0), predicted_r)
        d_new = meta.get("D", 5.0)

    # Update metadata
    new_meta = dict(meta)
    new_meta["S"] = s_new
    new_meta["D"] = d_new
    new_meta["rd"] = rd_new
    new_meta["last_sleep_consolidation"] = _now_iso()

    # Append ledger entry
    from .migrate import ledger_append

    new_meta = ledger_append(
        new_meta,
        score=0.0,
        S=s_new,
        D=d_new,
        reason="sleep_consolidation",
        ts=_now_iso(),
    )

    # Persist
    palace.update_drawer(candidate.drawer_id, metadata=new_meta)

    return {"status": "consolidated", "pe": pe, "S": s_new, "D": d_new}


def reorganize_candidate(palace, candidate: SleepCandidate) -> dict:
    """
    REM phase: reorganize representations.
    Merge near-duplicates (>0.85 similarity).
    """
    drawer = palace.get_drawer(candidate.drawer_id)
    if not drawer or "document" not in drawer:
        return {"status": "not_found"}

    meta = drawer.get("metadata", {})
    if is_protected(drawer):
        return {"status": "protected"}

    # Find near-duplicates in same wing
    wing = meta.get("wing", "")
    room = meta.get("room", "")
    doc = drawer["document"]

    # Simple text similarity (could use embeddings in future)
    # For now, merge if same wing/room and very similar content
    for other in palace.iter_drawers():
        if other["id"] == candidate.drawer_id:
            continue
        if is_protected(other):
            continue
        if other.get("metadata", {}).get("wing") != wing:
            continue
        if other.get("metadata", {}).get("room") != room:
            continue

        other_doc = other.get("document", "")
        if not other_doc:
            continue

        # Simple Jaccard-like similarity on words
        sim = jaccard_similarity(doc, other_doc)
        if sim > 0.85:
            # Merge: keep higher S, combine content
            winner = candidate.drawer_id if meta.get("S", 1.0) >= other["metadata"].get("S", 1.0) else other["id"]
            loser = other["id"] if winner == candidate.drawer_id else candidate.drawer_id

            # Mark loser as superseded
            palace.supersede_drawer(loser, winner)
            return {"status": "merged", "winner": winner, "loser": loser, "sim": sim}

    return {"status": "no_merge"}


def jaccard_similarity(a: str, b: str) -> float:
    """Simple word-level Jaccard similarity."""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def load_sleep_state(palace_path: Path) -> SleepState:
    """Load sleep state from sidecar JSON."""
    path = palace_path / SLEEP_SIDECAR
    if not path.exists():
        return SleepState()
    try:
        import json

        data = json.loads(path.read_text())
        return SleepState(
            last_sleep=data.get("last_sleep", ""),
            last_candidates=data.get("last_candidates", 0),
            total_consolidated=data.get("total_consolidated", 0),
        )
    except Exception:
        return SleepState()


def save_sleep_state(palace_path: Path, state: SleepState) -> None:
    """Persist sleep state to sidecar JSON (0o600)."""
    import json

    path = palace_path / SLEEP_SIDECAR
    path.write_text(
        json.dumps(
            {
                "last_sleep": state.last_sleep,
                "last_candidates": state.last_candidates,
                "total_consolidated": state.total_consolidated,
            },
            indent=2,
        )
    )
    path.chmod(0o600)


def sleep_cycle(
    palace,
    limit: int = 50,
    nrem_ratio: float = 0.7,
    stress_active: bool = False,
) -> dict:
    """
    Full sleep cycle: NREM consolidation + REM reorganization.

    Args:
        palace: DxrkMemory instance
        limit: max candidates per cycle
        nrem_ratio: fraction for NREM (0.7)
        stress_active: if True, lower threshold

    Returns:
        Dict with stats.
    """
    candidates = select_sleep_candidates(palace, limit, stress_active)

    nrem_count = int(limit * nrem_ratio)
    rem_count = limit - nrem_count

    nrem_results = []
    rem_results = []

    # NREM: consolidation
    for c in candidates[:nrem_count]:
        result = consolidate_candidate(palace, c)
        if result.get("status") == "consolidated":
            nrem_results.append(result)

    # REM: reorganization
    for c in candidates[nrem_count : nrem_count + rem_count]:
        result = reorganize_candidate(palace, c)
        if result.get("status") == "merged":
            rem_results.append(result)

    # Update sleep state
    state = load_sleep_state(Path(palace._path))
    state = SleepState(
        last_sleep=_now_iso(),
        last_candidates=len(candidates),
        total_consolidated=state.total_consolidated + len(nrem_results) + len(rem_results),
    )
    save_sleep_state(Path(palace._path), state)

    return {
        "candidates": len(candidates),
        "nrem_consolidated": len(nrem_results),
        "rem_merged": len(rem_results),
        "total": len(nrem_results) + len(rem_results),
    }


def reconsolidate_labile(palace) -> int:
    """
    Reconsolidate drawers in labile state (accessed within 6h but not reconsolidated).
    """
    count = 0
    for drawer in palace.iter_drawers():
        if is_protected(drawer):
            continue
        meta = drawer.get("metadata", {})
        labile_until = meta.get("labile_until")
        if not labile_until:
            continue
        try:
            lu = datetime.fromisoformat(labile_until.replace("Z", "+00:00"))
            if datetime.now(UTC) > lu:
                # Labile window expired without reconsolidation → soft decay
                new_meta = dict(meta)
                new_meta["S"] = meta.get("S", 1.0) * 0.9
                palace.update_drawer(drawer["id"], metadata=new_meta)
                count += 1
        except Exception:
            pass
    return count
