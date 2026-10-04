# SPDX-License-Identifier: MIT
"""ReconsolidationEngine — labile window on recall."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dxrk.memory.reconsolidation import (
    ReconsolidationState,
    is_labile,
    mark_labile,
    reconsolidate,
    reconsolidate_with_fsrs,
    get_labile_remaining,
    LABILE_WINDOW_HOURS,
)


class TestReconsolidationEngine:
    def test_mark_labile_sets_future_timestamp(self) -> None:
        """mark_labile sets labile_until to ~6 hours in future."""
        state = ReconsolidationState()
        new_state = mark_labile(state)
        assert new_state.labile_until != ""
        # Should be approximately 6 hours from now
        labile_until = datetime.fromisoformat(new_state.labile_until.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff_hours = (labile_until - now).total_seconds() / 3600.0
        assert 5.9 < diff_hours < 6.1

    def test_is_labile_after_mark(self) -> None:
        """Drawer is labile immediately after mark_labile."""
        state = ReconsolidationState()
        state = mark_labile(state)
        assert is_labile(state) is True

    def test_is_labile_false_when_empty(self) -> None:
        """Drawer not labile when labile_until is empty."""
        state = ReconsolidationState()
        assert is_labile(state) is False

    def test_is_labile_false_after_window(self) -> None:
        """Drawer not labile after window expires."""
        state = ReconsolidationState()
        # Set to 7 hours ago
        past = datetime.now(timezone.utc) - timedelta(hours=7)
        state = ReconsolidationState(labile_until=past.isoformat())
        assert is_labile(state) is False

    def test_reconsolidate_good_outcome_strengthens(self) -> None:
        """Good outcome (>=0.7) strengthens stability."""
        state = mark_labile(ReconsolidationState())
        new_state, s, d, rd = reconsolidate(state, stability=10.0, difficulty=5.0, rd=100.0, outcome=0.8)
        assert s > 10.0  # strengthened
        assert new_state.labile_until == ""  # window closed
        assert new_state.reconsolidation_count == 1

    def test_reconsolidate_poor_outcome_weakens(self) -> None:
        """Poor outcome (<=0.3) weakens stability."""
        state = mark_labile(ReconsolidationState())
        new_state, s, d, rd = reconsolidate(state, stability=10.0, difficulty=5.0, rd=100.0, outcome=0.2)
        assert s < 10.0  # weakened
        assert new_state.labile_until == ""
        assert new_state.reconsolidation_count == 1

    def test_reconsolidate_neutral_no_change(self) -> None:
        """Neutral outcome (0.3-0.7) keeps stability."""
        state = mark_labile(ReconsolidationState())
        new_state, s, d, rd = reconsolidate(state, stability=10.0, difficulty=5.0, rd=100.0, outcome=0.5)
        assert s == 10.0
        assert new_state.labile_until == ""
        assert new_state.reconsolidation_count == 1

    def test_reconsolidate_expired_window_decays(self) -> None:
        """Expired window without reconsolidation decays stability."""
        state = ReconsolidationState()
        # Set to 7 hours ago (expired)
        past = datetime.now(timezone.utc) - timedelta(hours=7)
        state = ReconsolidationState(labile_until=past.isoformat())
        new_state, s, d, rd = reconsolidate(state, stability=10.0, difficulty=5.0, rd=100.0, outcome=0.8)
        assert s < 10.0  # decayed
        assert s == 9.0  # 10.0 * 0.9
        assert new_state.labile_until == ""
        assert new_state.reconsolidation_count == 0  # not incremented

    def test_reconsolidate_not_labile_no_change(self) -> None:
        """Non-labile drawer returns unchanged."""
        state = ReconsolidationState()
        new_state, s, d, rd = reconsolidate(state, stability=10.0, difficulty=5.0, rd=100.0, outcome=0.8)
        assert s == 10.0
        assert new_state is state  # same object (no change)

    def test_reconsolidate_fsrs_success(self) -> None:
        """FSRS-based reconsolidation on success."""
        state = mark_labile(ReconsolidationState())
        new_state, s, d, rd = reconsolidate_with_fsrs(
            state, stability=10.0, difficulty=5.0, rd=100.0, retrievability=0.9, outcome=1.0
        )
        assert s > 10.0  # S should grow on success
        assert rd < 100.0  # rd should shrink
        assert new_state.reconsolidation_count == 1

    def test_reconsolidate_fsrs_lapse(self) -> None:
        """FSRS-based reconsolidation on lapse."""
        state = mark_labile(ReconsolidationState())
        new_state, s, d, rd = reconsolidate_with_fsrs(
            state, stability=10.0, difficulty=5.0, rd=100.0, retrievability=0.9, outcome=0.0
        )
        assert s < 10.0  # S should collapse on lapse
        assert d > 5.0  # D should rise
        assert rd > 100.0  # rd should bump
        assert new_state.reconsolidation_count == 1

    def test_get_labile_remaining(self) -> None:
        """Get remaining labile window in hours."""
        state = mark_labile(ReconsolidationState())
        remaining = get_labile_remaining(state)
        assert 5.9 < remaining < 6.1

    def test_get_labile_remaining_negative_when_closed(self) -> None:
        """Negative remaining when window closed."""
        state = ReconsolidationState()
        remaining = get_labile_remaining(state)
        assert remaining == -1.0

    def test_reconsolidation_count_increments(self) -> None:
        """Reconsolidation count increments on each reconsolidation."""
        state = mark_labile(ReconsolidationState())
        state, _, _, _ = reconsolidate(state, 10.0, 5.0, 100.0, 0.8)
        assert state.reconsolidation_count == 1
        # Second reconsolidation
        state = mark_labile(state)
        state, _, _, _ = reconsolidate(state, 10.0, 5.0, 100.0, 0.8)
        assert state.reconsolidation_count == 2
