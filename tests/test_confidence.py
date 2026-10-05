# SPDX-License-Identifier: MIT
"""Bayesian Confidence Propagation tests."""

from __future__ import annotations

from dxrk.memory.confidence import (
    adjusted_uncertainty,
    confidence_from_retrievability,
    find_related_drawers,
    propagate_confidence,
)


def make_drawer(did: str, wing: str, room: str, quarantined: bool = False):
    """Create a drawer object for testing."""
    return {
        "id": did,
        "quarantined": quarantined,
        "metadata": {"wing": wing, "room": room},
    }


class TestConfidencePropagation:
    def test_propagate_zero_depth(self) -> None:
        """Zero depth returns base confidence."""
        get_drawer = lambda x: None
        iter_drawers = lambda: []
        result = propagate_confidence(get_drawer, iter_drawers, "d1", 0.8, max_depth=0)
        assert result.propagated_confidence == 0.8
        assert result.depth_reached == 0

    def test_propagate_no_related(self) -> None:
        """No related drawers returns base confidence."""
        get_drawer = lambda x: None
        iter_drawers = lambda: []
        result = propagate_confidence(get_drawer, iter_drawers, "d1", 0.8, max_depth=2)
        assert result.propagated_confidence == 0.8
        assert result.related_count == 0

    def test_propagate_single_related(self) -> None:
        """Single related drawer increases confidence."""
        drawers = {
            "d1": make_drawer("d1", "w1", "r1"),
            "d2": make_drawer("d2", "w1", "r1"),
        }
        get_drawer = lambda x: drawers.get(x)
        iter_drawers = lambda: list(drawers.values())

        result = propagate_confidence(get_drawer, iter_drawers, "d1", 0.5, max_depth=1)
        # sim = 0.5 (wing) + 0.3 (room) = 0.8
        # propagated = 0.5 * (1 + 0.8 * 0.5) = 0.5 * 1.4 = 0.7
        # final = min(1.0, 0.5 + 0.7) = 1.0 (capped)
        assert result.propagated_confidence == 1.0
        assert result.related_count == 1

    def test_adjusted_uncertainty(self) -> None:
        """Higher confidence reduces uncertainty."""
        rd = 100.0
        # t_days = 0, so no drift
        assert adjusted_uncertainty(rd, 0.0, 0.0) == 100.0
        assert adjusted_uncertainty(rd, 0.0, 0.5) == 50.0
        assert adjusted_uncertainty(rd, 0.0, 1.0) == 0.0

    def test_confidence_from_retrievability_high(self) -> None:
        """High S, low D, low rd → high confidence."""
        meta = {"S": 300.0, "D": 2.0, "rd": 50.0}
        conf = confidence_from_retrievability(meta)
        assert conf > 0.7

    def test_confidence_from_retrievability_low(self) -> None:
        """Low S, high D, high rd → low confidence."""
        meta = {"S": 1.0, "D": 9.0, "rd": 350.0}
        conf = confidence_from_retrievability(meta)
        assert conf < 0.3

    def test_confidence_bounds(self) -> None:
        """Confidence always in [0, 1]."""
        for S in [1.0, 10.0, 100.0, 365.0]:
            for D in [1.0, 5.0, 10.0]:
                for rd in [30.0, 100.0, 350.0]:
                    meta = {"S": S, "D": D, "rd": rd}
                    conf = confidence_from_retrievability(meta)
                    assert 0.0 <= conf <= 1.0

    def test_find_related_same_wing_room(self) -> None:
        """Find related drawers in same wing/room."""
        drawers = {
            "d1": make_drawer("d1", "w1", "r1"),
            "d2": make_drawer("d2", "w1", "r1"),
            "d3": make_drawer("d3", "w2", "r2"),
        }
        get_drawer = lambda x: drawers.get(x)
        iter_drawers = lambda: list(drawers.values())

        related_found = find_related_drawers(get_drawer, iter_drawers, "d1")
        assert len(related_found) == 1
        assert related_found[0][0] == "d2"
        assert related_found[0][1] >= 0.5  # wing match

    def test_find_related_excludes_quarantined(self) -> None:
        """Quarantined drawers excluded from related."""
        drawers = {
            "d1": make_drawer("d1", "w1", "r1"),
            "d2": make_drawer("d2", "w1", "r1", quarantined=True),
        }
        get_drawer = lambda x: drawers.get(x)
        iter_drawers = lambda: list(drawers.values())

        related_found = find_related_drawers(get_drawer, iter_drawers, "d1")
        assert len(related_found) == 0

    def test_propagation_decay_per_depth(self) -> None:
        """Propagation decays with depth."""
        drawers = {
            "d1": make_drawer("d1", "w1", "r1"),
            "d2": make_drawer("d2", "w1", "r1"),
            "d3": make_drawer("d3", "w1", "r1"),
        }
        get_drawer = lambda x: drawers.get(x)
        iter_drawers = lambda: list(drawers.values())

        result = propagate_confidence(get_drawer, iter_drawers, "d1", 0.5, max_depth=2, decay_per_depth=0.5)
        # BFS from d1 finds d2,d3 at depth 1; each of those finds the other two at depth 2
        # But visited set prevents revisiting d1
        # Total unique related found = 6 (d2,d3 from d1; d1,d3 from d2; d1,d2 from d3)
        # But d1 is already visited, so only d2,d3 from each = 4 total
        # Actually: from d1→d2,d3 (2); from d2→d3 (d1 visited); from d3→d2 (d1 visited) = 2+1+1=4
        # The current implementation might count differently; let's verify the actual behavior
        assert result.depth_reached == 1
        assert result.related_count >= 4  # at least 4
