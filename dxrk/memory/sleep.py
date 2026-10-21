# SPDX-License-Identifier: MIT
"""Sleep consolidation — Simulation-Selection loop (Lee & Jung 2025, CA3/CA1 replay)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .scoring import r_fsrs


@dataclass(frozen=True)
class SleepCandidate:
    """A fragmento selected for sleep consolidation."""

    fragmento_id: str
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


def is_protected(fragmento: dict) -> bool:
    """Check if fragmento is protected from sleep consolidation."""
    meta = fragmento.get("metadata", {})
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


def avg_prediction_error(fragmento: dict) -> float:
    """Compute average prediction error from ledger."""
    ledger = fragmento.get("metadata", {}).get("score_ledger", [])
    if not ledger:
        return 0.0
    pes: list[float] = [float(entry.get("pe", 0.0)) for entry in ledger if "pe" in entry]
    if not pes:
        return 0.0
    return float(sum(abs(pe) for pe in pes) / len(pes))


def count_supersedes(fragmento: dict) -> int:
    """Count superseded relations."""
    # Simple heuristic: superseded count in metadata
    return int(fragmento.get("metadata", {}).get("superseded_count", 0))


def select_sleep_candidates(
    malla,
    limit: int = 50,
    stress_active: bool = False,
) -> list[SleepCandidate]:
    """
    Selection à la CA3 replay: prioritize prediction error, not recency.

    Args:
        malla: DxrkMemory instance
        limit: max candidates to return
        stress_active: if True, lower threshold (cooperative masking)

    Returns:
        List of SleepCandidate sorted by priority desc.
    """
    threshold = 0.1 if stress_active else 0.3
    candidates = []

    for fragmento in malla.iter_fragmentos():
        if is_protected(fragmento):
            continue

        pe_avg = avg_prediction_error(fragmento)
        staleness = age_days(fragmento.get("metadata", {}).get("filed_at"))
        contradiction = count_supersedes(fragmento)

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
                    fragmento_id=fragmento["id"],
                    priority=priority,
                    reason=reason,
                )
            )

    return sorted(candidates, key=lambda c: -c.priority)[:limit]


def classify_reason(pe_avg: float, staleness: float, contradiction: int) -> str:
    """Classify why this fragmento was selected."""
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


def consolidate_candidate(malla, candidate: SleepCandidate) -> dict:
    """
    Consolidation CA3→CA1:
    1. Replay: re-evaluate the fragmento against corpus
    2. Integrate: update S/D with PE
    3. Prune: if near-duplicate, merge
    """
    fragmento = malla.get_fragmento(candidate.fragmento_id)
    if not fragmento or "document" not in fragmento:
        return {"status": "not_found"}

    meta = fragmento.get("metadata", {})
    if is_protected(fragmento):
        return {"status": "protected"}

    # NREM phase: replay (re-evaluate)
    pe = avg_prediction_error(fragmento)

    # Apply consolidation based on reason
    if candidate.reason == "near_dup":
        # REM phase: merge near-duplicates (handled in reorganize)
        return {"status": "deferred_rem"}

    # Update stability with PE coupling
    from .scoring import update_success

    # Simulate a "success" replay with predicted_r from retrievability
    predicted_r = r_fsrs(age_days(meta.get("accessed_at") or meta.get("filed_at")), meta.get("S", 1.0))

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
    malla.update_fragmento(candidate.fragmento_id, metadata=new_meta)

    return {"status": "consolidated", "pe": pe, "S": s_new, "D": d_new}


def reorganize_candidate(malla, candidate: SleepCandidate) -> dict:
    """
    REM phase: reorganize representations.
    Merge near-duplicates (>0.85 similarity).
    """
    fragmento = malla.get_fragmento(candidate.fragmento_id)
    if not fragmento or "document" not in fragmento:
        return {"status": "not_found"}

    meta = fragmento.get("metadata", {})
    if is_protected(fragmento):
        return {"status": "protected"}

    # Find near-duplicates in same nodo
    nodo = meta.get("nodo", "")
    celda = meta.get("celda", "")
    doc = fragmento["document"]

    # Simple text similarity (could use embeddings in future)
    # For now, merge if same nodo/celda and very similar content
    for other in malla.iter_fragmentos():
        if other["id"] == candidate.fragmento_id:
            continue
        if is_protected(other):
            continue
        if other.get("metadata", {}).get("nodo") != nodo:
            continue
        if other.get("metadata", {}).get("celda") != celda:
            continue

        other_doc = other.get("document", "")
        if not other_doc:
            continue

        # Simple Jaccard-like similarity on words
        sim = jaccard_similarity(doc, other_doc)
        if sim > 0.85:
            # Merge: keep higher S, combine content
            winner = candidate.fragmento_id if meta.get("S", 1.0) >= other["metadata"].get("S", 1.0) else other["id"]
            loser = other["id"] if winner == candidate.fragmento_id else candidate.fragmento_id

            # Mark loser as superseded
            malla.supersede_fragmento(loser, winner)
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


def load_sleep_state(malla_path: Path) -> SleepState:
    """Load sleep state from sidecar JSON."""
    path = malla_path / SLEEP_SIDECAR
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


def save_sleep_state(malla_path: Path, state: SleepState) -> None:
    """Persist sleep state to sidecar JSON (0o600)."""
    import json

    path = malla_path / SLEEP_SIDECAR
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
    malla,
    limit: int = 50,
    nrem_ratio: float = 0.7,
    stress_active: bool = False,
) -> dict:
    """
    Full sleep cycle: NREM consolidation + REM reorganization.

    Args:
        malla: DxrkMemory instance
        limit: max candidates per cycle
        nrem_ratio: fraction for NREM (0.7)
        stress_active: if True, lower threshold

    Returns:
        Dict with stats.
    """
    candidates = select_sleep_candidates(malla, limit, stress_active)

    nrem_count = int(limit * nrem_ratio)
    rem_count = limit - nrem_count

    nrem_results = []
    rem_results = []

    # NREM: consolidation
    for c in candidates[:nrem_count]:
        result = consolidate_candidate(malla, c)
        if result.get("status") == "consolidated":
            nrem_results.append(result)

    # REM: reorganization
    for c in candidates[nrem_count : nrem_count + rem_count]:
        result = reorganize_candidate(malla, c)
        if result.get("status") == "merged":
            rem_results.append(result)

    # Update sleep state
    state = load_sleep_state(Path(malla._path))
    state = SleepState(
        last_sleep=_now_iso(),
        last_candidates=len(candidates),
        total_consolidated=state.total_consolidated + len(nrem_results) + len(rem_results),
    )
    save_sleep_state(Path(malla._path), state)

    return {
        "candidates": len(candidates),
        "nrem_consolidated": len(nrem_results),
        "rem_merged": len(rem_results),
        "total": len(nrem_results) + len(rem_results),
    }


def reconsolidate_labile(malla) -> int:
    """
    Reconsolidate fragmentos in labile state (accessed within 6h but not reconsolidated).
    """
    count = 0
    for fragmento in malla.iter_fragmentos():
        if is_protected(fragmento):
            continue
        meta = fragmento.get("metadata", {})
        labile_until = meta.get("labile_until")
        if not labile_until:
            continue
        try:
            lu = datetime.fromisoformat(labile_until.replace("Z", "+00:00"))
            if datetime.now(UTC) > lu:
                # Labile window expired without reconsolidation → soft decay
                new_meta = dict(meta)
                new_meta["S"] = meta.get("S", 1.0) * 0.9
                malla.update_fragmento(fragmento["id"], metadata=new_meta)
                count += 1
        except Exception:
            pass
    return count
