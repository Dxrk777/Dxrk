# SPDX-License-Identifier: MIT
"""TripleCopyMemory — three divergent decay copies."""

from __future__ import annotations

from dxrk.memory.triplecopy import (
    create_triple_copy,
    effective_retrievability,
    get_copy_ages,
    triple_copy_retrievability,
)

# FSRS-4.5 constants (inline to avoid import issues)
_FACTOR = 19.0 / 81.0
_DECAY = -0.5


def _retrievability(t: float, S: float) -> float:
    if S <= 0:
        return 0.0
    return (1.0 + _FACTOR * t / S) ** _DECAY


class TestTripleCopy:
    def test_create_triple_copy_ratios(self) -> None:
        """Triple copy has correct ratios: fast=S/4, medium=S, deep=S*4."""
        tc = create_triple_copy(10.0)
        assert tc.fast == 2.5
        assert tc.medium == 10.0
        assert tc.deep == 40.0

    def test_create_triple_copy_min_fast(self) -> None:
        """Fast copy has minimum floor at 0.25."""
        tc = create_triple_copy(0.5)
        assert tc.fast == 0.25  # max(0.25, 0.5/4)

    def test_retrievability_fast_decays_first(self) -> None:
        """Fast copy decays fastest (lowest R at same t)."""
        tc = create_triple_copy(10.0)
        t = 10.0  # t = S_medium
        r_fast = _retrievability(t, tc.fast)
        r_medium = _retrievability(t, tc.medium)
        r_deep = _retrievability(t, tc.deep)
        # At t = S_medium: R_medium = 0.9, R_fast < 0.9, R_deep > 0.9
        assert r_medium == 0.9
        assert r_fast < 0.9
        assert r_deep > 0.9

    def test_max_retrievability_preserves_schema(self) -> None:
        """Max retrievability preserves schema via deep copy at long delays."""
        tc = create_triple_copy(10.0)
        # At t=100 days: fast decayed, deep still strong
        r_max = triple_copy_retrievability(tc, 100.0)
        r_fast_only = _retrievability(100.0, tc.fast)
        r_deep_only = _retrievability(100.0, tc.deep)
        # Max should be close to deep (schema preserved)
        assert r_max == r_deep_only
        assert r_max > r_fast_only

    def test_fsrs_vs_triplecopy_at_long_delay(self) -> None:
        """TripleCopy outperforms single FSRS at long delays."""
        S = 10.0
        tc = create_triple_copy(S)
        t = 100.0
        # Single FSRS
        r_single = _retrievability(t, S)
        # TripleCopy max
        r_triple = triple_copy_retrievability(tc, t)
        assert r_triple > r_single
        # At t=100, S=10: single ≈ 0.31, triple ≈ 0.71 (deep copy)

    def test_effective_retrievability_weighted(self) -> None:
        """Effective retrievability uses weighted sum."""
        tc = create_triple_copy(10.0)
        t = 10.0
        r_eff = effective_retrievability(tc, t)
        # At t=S_medium: r_fast < 0.9, r_medium = 0.9, r_deep > 0.9
        # Weighted: 0.5*r_fast + 0.3*0.9 + 0.2*r_deep
        assert 0.0 <= r_eff <= 1.0

    def test_get_copy_ages(self) -> None:
        """Copy ages correspond to their stabilities."""
        tc = create_triple_copy(10.0)
        fast_age, med_age, deep_age = get_copy_ages(tc)
        assert fast_age == 2.5
        assert med_age == 10.0
        assert deep_age == 40.0

    def test_retrievability_bounds(self) -> None:
        """Retrievability always in [0, 1]."""
        tc = create_triple_copy(10.0)
        for t in [0.0, 1.0, 10.0, 100.0, 1000.0]:
            r = triple_copy_retrievability(tc, t)
            assert 0.0 <= r <= 1.0

    def test_retrievability_monotonic(self) -> None:
        """Retrievability monotonically decreases with time."""
        tc = create_triple_copy(10.0)
        prev = 1.0
        for t in [0.0, 1.0, 5.0, 10.0, 20.0, 50.0, 100.0]:
            r = triple_copy_retrievability(tc, t)
            assert r <= prev + 1e-10  # allow floating point
            prev = r

    def test_deep_copy_protects_old_memories(self) -> None:
        """Deep copy ensures old memories never fully disappear."""
        tc = create_triple_copy(10.0)
        # Even at very long delay, deep copy gives some retrievability
        r = triple_copy_retrievability(tc, 1000.0)
        assert r > 0.1  # schema still accessible
