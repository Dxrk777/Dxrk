# SPDX-License-Identifier: MIT
"""RDU scoring unit tests — retrievability, updates, rd drift, rank order."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest


def _iso_days_ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _meta(s: float = 10.0, n: int = 0, days_idle: float = 0.0, rd: float = 350.0) -> dict[str, object]:
    return {
        "schema_version": 2,
        "S": s,
        "D": 5.0,
        "rd": rd,
        "s_updates": 0,
        "content_sha256": "x",
        "quarantined": False,
        "score_ledger": [],
        "score_ledger_dropped": 0,
        "access_history": [],
        "access_count": n,
        "access_count_total": n,
        "accessed_at": _iso_days_ago(days_idle),
        "filed_at": _iso_days_ago(days_idle + 5),
    }


class TestRetrievability:
    def test_exact_anchor(self) -> None:
        from dxrk.memory.scoring import r_fsrs

        assert r_fsrs(7.0, 7.0) == pytest.approx(0.9, abs=1e-9)

    def test_monotone_in_time_and_stability(self) -> None:
        from dxrk.memory.scoring import r_fsrs

        assert r_fsrs(0.0, 10.0) == 1.0
        assert r_fsrs(5.0, 10.0) > r_fsrs(20.0, 10.0)
        assert r_fsrs(10.0, 60.0) > r_fsrs(10.0, 5.0)

    def test_degenerate_inputs_clamped(self) -> None:
        from dxrk.memory.scoring import r_fsrs

        assert r_fsrs(-3.0, 10.0) == 1.0  # future timestamps never boost
        assert 0.0 < r_fsrs(10.0, 0.0) < 1.0  # zero stability never divides
        assert r_fsrs(10.0, -5.0) == r_fsrs(10.0, 0.0)


class TestSuccessUpdate:
    def test_success_grows_stability_and_shrinks_rd(self) -> None:
        from dxrk.memory.scoring import update_success

        s_new, rd_new = update_success(10.0, 5.0, 200.0, 0.7)
        assert s_new > 10.0
        assert rd_new == pytest.approx(180.0)

    def test_perfect_recall_is_neutral(self) -> None:
        from dxrk.memory.scoring import update_success

        s_new, _rd = update_success(10.0, 5.0, 200.0, 1.0)
        assert s_new == pytest.approx(10.0)

    def test_caps_and_floors(self) -> None:
        from dxrk.memory.scoring import RDU_RD_MIN, RDU_S_MAX, update_success

        s_new, _rd = update_success(360.0, 1.0, 200.0, 0.1)
        assert s_new <= RDU_S_MAX
        _s, rd_new = update_success(10.0, 5.0, 31.0, 0.5)
        assert rd_new >= RDU_RD_MIN


class TestLapseUpdate:
    def test_lapse_dynamics(self) -> None:
        from dxrk.memory.scoring import update_lapse

        s_new, d_new, rd_new = update_lapse(60.0, 5.0, 100.0, 0.9)
        assert s_new < 60.0
        assert d_new > 5.0
        assert d_new <= 10.0
        assert rd_new == pytest.approx(120.0)

    def test_difficulty_mean_reverts(self) -> None:
        from dxrk.memory.scoring import update_lapse

        _s, d_high, _rd = update_lapse(10.0, 9.0, 100.0, 0.9)
        _s2, d_low, _rd2 = update_lapse(10.0, 1.0, 100.0, 0.9)
        assert d_high < 10.0  # capped, pulled toward 5
        assert d_low > 1.0  # pulled up toward 5

    def test_rd_capped(self) -> None:
        from dxrk.memory.scoring import update_lapse

        _s, _d, rd_new = update_lapse(10.0, 5.0, 350.0, 0.5)
        assert rd_new == 350.0


class TestRdDrift:
    def test_drift_grows_with_idleness_and_caps(self) -> None:
        from dxrk.memory.scoring import effective_rd

        assert effective_rd(100.0, 0.0) == pytest.approx(100.0)
        assert effective_rd(100.0, 30.0) > 100.0
        assert effective_rd(349.0, 10000.0) == 350.0  # sqrt would be ~402
        assert effective_rd(350.0, 365.0) == 350.0

    def test_drift_formula(self) -> None:
        from dxrk.memory.scoring import effective_rd

        assert effective_rd(100.0, 25.0) == pytest.approx(math.sqrt(100**2 + 4 * 25))


class TestScoreMetaRank:
    def test_stale_sinks_and_access_lifts(self) -> None:
        from dxrk.memory.scoring import score_meta

        fresh = _meta(s=10.0, n=0, days_idle=0.0)
        stale = _meta(s=10.0, n=0, days_idle=200.0)
        assert score_meta(fresh) > score_meta(stale)
        busy = _meta(s=10.0, n=15, days_idle=0.0)
        quiet = _meta(s=10.0, n=0, days_idle=0.0)
        assert score_meta(busy) > score_meta(quiet)

    def test_frequency_factor_bounds(self) -> None:
        from dxrk.memory.scoring import frequency_factor

        assert frequency_factor(0) == pytest.approx(0.7)
        assert frequency_factor(-5) == pytest.approx(0.7)
        assert 0.7 < frequency_factor(5) < 1.0
        assert frequency_factor(10**9) <= 1.0

    def test_importance_only_tiebreaks(self) -> None:
        from dxrk.memory.scoring import score_meta

        low = dict(_meta())
        low["importance"] = 0.5
        high = dict(_meta())
        high["importance"] = 4.5
        gap = score_meta(high) - score_meta(low)
        assert 0.0 < gap <= 0.011  # tiny static prior, dynamics dominate

    def test_legacy_rank_score_untouched(self) -> None:
        from dxrk.memory.scoring import decay_factor, rank_score

        assert rank_score(0.9) == 0.9
        assert rank_score(0.9, 0, None, None) == 0.9
        assert decay_factor(None) == 1.0
