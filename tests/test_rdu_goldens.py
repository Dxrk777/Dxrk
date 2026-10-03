# SPDX-License-Identifier: MIT
"""RDU golden tests — FSRS-style stability/difficulty/rating-deviation ranking.

Design pins (Fase 0 RDU):
- R_fsrs(t, S) = (1 + (19/81) * t / S) ** -0.5, S in days.
- R(S) == 0.9 exactly; R(2S) > 0.8.
- A fresh drawer (S=1, 7d idle) ranks below a mature one (S=60, n=12).
- A lapse outcome lowers stability S.
- score_ledger hash-chaining detects tampering via verify_chain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def _iso_days_ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _spine_meta(s: float, n: int, days_idle: float) -> dict[str, object]:
    return {
        "schema_version": 2,
        "S": s,
        "D": 5.0,
        "rd": 350.0,
        "s_updates": 0,
        "content_sha256": "abc",
        "quarantined": False,
        "score_ledger": [],
        "score_ledger_dropped": 0,
        "access_history": [],
        "access_count": n,
        "access_count_total": n,
        "accessed_at": _iso_days_ago(days_idle),
        "filed_at": _iso_days_ago(days_idle + 30),
    }


def test_r_at_S_is_point_nine() -> None:
    from dxrk.memory.scoring import r_fsrs

    assert r_fsrs(30.0, 30.0) == pytest.approx(0.9, abs=1e-9)
    assert r_fsrs(1.0, 1.0) == pytest.approx(0.9, abs=1e-9)


def test_r_at_2S_above_point_eight() -> None:
    from dxrk.memory.scoring import r_fsrs

    assert r_fsrs(60.0, 30.0) > 0.8
    assert r_fsrs(2.0, 1.0) > 0.8


def test_new_drawer_ranks_below_mature() -> None:
    from dxrk.memory.scoring import score_meta

    new = _spine_meta(s=1.0, n=0, days_idle=7.0)
    mature = _spine_meta(s=60.0, n=12, days_idle=7.0)
    assert score_meta(mature) > score_meta(new)


def test_lapse_lowers_stability() -> None:
    from dxrk.memory.scoring import r_fsrs, update_lapse

    s, d, rd = 60.0, 5.0, 100.0
    r = r_fsrs(1.0, s)
    s_new, _d_new, _rd_new = update_lapse(s, d, rd, r)
    assert s_new < s


def test_verify_chain_detects_tamper() -> None:
    from dxrk.memory.migrate import ledger_append, verify_chain

    meta: dict[str, object] = {}
    ledger_append(meta, score=0.5, S=1.0, D=5.0, reason="access")
    ledger_append(meta, score=0.6, S=1.5, D=5.0, reason="access")
    ok, _idx = verify_chain(meta)
    assert ok is True
    ledger = meta["score_ledger"]
    assert isinstance(ledger, list)
    second = ledger[1]
    assert isinstance(second, dict)
    second["score"] = 0.99  # tamper
    ok2, break_idx = verify_chain(meta)
    assert ok2 is False
    assert break_idx == 1
