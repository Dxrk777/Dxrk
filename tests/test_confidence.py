# SPDX-License-Identifier: MIT
"""Bayesian Confidence Propagation tests."""

from __future__ import annotations

from unittest.mock import Mock

from dxrk.memory.confidence import (
    ConfidencePropagation,
    propagate_confidence,
    find_related_drawers,
    adjusted_uncertainty,
    confidence_from_retrievability,
)


def make_drawer(did: str, wing: str, room: str, quarantined: bool = False):
    """Create a drawer dict (not Mock) for testing."""
    return {
        "id": did,
        "quarantined": quarantined,
        "metadata": {"wing": wing, "room": room},
    }


class TestConfidencePropagation:
    def test_propagate_zero_depth(self) -> None:
        """Zero depth returns base confidence."""
        palace = Mock()
        palace.iter_drawers.return_value = []
        result = propagate_confidence(palace, "d1", 0.8, max_depth=0)
        assert result.propagated_confidence == 0.8
        assert result.depth_reached == 0

    def test_propagate_no_related(self) -> None:
        """No related drawers returns base confidence."""
        palace = Mock()
        palace.iter_drawers.return_value = []
        result = propagate_confidence(palace, "d1", 0.8, max_depth=2)
        assert result.propagated_confidence == 0.8
        assert result.related_count == 0

    def test_propagate_single_related(self) -> None:
        """Single related drawer increases confidence."""
        palace = Mock()
        palace.iter_drawers.return_value = [
            make_drawer("d2", "w1", "r1"),
        ]
        # Mock get_drawer to return source
        palace.get_drawer.return_value = make_drawer("d1", "w1", "r1")

        result = propagate_confidence(palace, "d1", 0.5, max_depth=1)
        # sim = 0.5 (wing) + 0.3 (room) = 0.8
        # propagated = 0.5 * (1 + 0.8 * 0.5) = 0.5 * 1.4 = 0.7
        # final = min(1.0, 0.5 + 0.7) = 1.0 (capped)
        assert result.propagated_confidence == 1.0
        assert result.related_count == 1

    def test_adjusted_uncertainty(self) -> None:
        """Higher confidence reduces uncertainty."""
        rd = 100.0
        assert adjusted_uncertainty(rd, 0.0) == 100.0
        assert adjusted_uncertainty(rd, 0.5) == 50.0
        assert adjusted_uncertainty(rd, 1.0) == 0.0

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
        palace = Mock()
        palace.get_drawer.return_value = make_drawer("d1", "w1", "r1")
        palace.iter_drawers.return_value = [
            make_drawer("d2", "w1", "r1"),
            make_drawer("d3", "w2", "r2"),
        ]

        related_found = find_related_drawers(palace, "d1")
        assert len(related_found) == 1
        assert related_found[0][0] == "d2"
        assert related_found[0][1] >= 0.5  # wing match

    def test_find_related_excludes_quarantined(self) -> None:
        """Quarantined drawers excluded from related."""
        palace = Mock()
        palace.get_drawer.return_value = make_drawer("d1", "w1", "r1")
        palace.iter_drawers.return_value = [
            make_drawer("d2", "w1", "r1", quarantined=True),
        ]

        related_found = find_related_drawers(palace, "d1")
        assert len(related_found) == 0

    def test_propagation_decay_per_depth(self) -> None:
        """Propagation decays with depth."""
        palace = Mock()
        palace.get_drawer.return_value = make_drawer("d1", "w1", "r1")
        palace.iter_drawers.return_value = [
            make_drawer("d2", "w1", "r1"),
            make_drawer("d3", "w1", "r1"),
        ]

        result = propagate_confidence(palace, "d1", 0.5, max_depth=2, decay_per_depth=0.5)
        # Both d2 and d3 found at depth 1 from d1; each also finds the other
        assert result.depth_reached == 1
        assert result.related_count == 4
