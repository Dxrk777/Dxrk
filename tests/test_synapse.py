# SPDX-License-Identifier: MIT
"""Synapse core — Two-Factor STDP with neuromodulation."""

from __future__ import annotations

from dxrk.memory.synapse import (
    ETA_BASE,
    NEUROMOD_DECAY,
    TAU_MINUS,
    TAU_PLUS,
    SynapseState,
    apply_reward,
    effective_learning_rate,
    stdp_update,
)


class TestSynapseCore:
    def test_ltp_pre_before_post_increases_weight(self) -> None:
        """LTP: pre before post (dt < 0) increases weight."""
        state = SynapseState(weight=0.5)
        new_state = stdp_update(state, pre=1.0, post=1.0, dt=-1.0)
        assert new_state.weight > 0.5

    def test_ltd_post_before_pre_decreases_weight(self) -> None:
        """LTD: post before pre (dt > 0) decreases weight."""
        state = SynapseState(weight=0.5)
        new_state = stdp_update(state, pre=1.0, post=1.0, dt=1.0)
        assert new_state.weight < 0.5

    def test_zero_activity_no_change(self) -> None:
        """Zero pre or post activity produces no weight change."""
        state = SynapseState(weight=0.5)
        # pre=0
        new_state = stdp_update(state, pre=0.0, post=1.0, dt=-1.0)
        assert new_state.weight == 0.5
        # post=0
        new_state = stdp_update(state, pre=1.0, post=0.0, dt=-1.0)
        assert new_state.weight == 0.5

    def test_neuromod_enhances_ltp(self) -> None:
        """Neuromodulator amplifies LTP."""
        state = SynapseState(weight=0.5, neuromod=0.5)
        new_state = stdp_update(state, pre=1.0, post=1.0, dt=-1.0, neuromod=0.5)
        state_no_mod = SynapseState(weight=0.5)
        new_state_no_mod = stdp_update(state_no_mod, pre=1.0, post=1.0, dt=-1.0, neuromod=0.0)
        # With neuromod, delta should be larger (weight higher)
        assert new_state.weight > new_state_no_mod.weight

    def test_neuromod_enhances_ltd_magnitude(self) -> None:
        """Neuromodulator amplifies LTD magnitude (more negative)."""
        state = SynapseState(weight=0.5, neuromod=0.5)
        new_state = stdp_update(state, pre=1.0, post=1.0, dt=1.0, neuromod=0.5)
        state_no_mod = SynapseState(weight=0.5)
        new_state_no_mod = stdp_update(state_no_mod, pre=1.0, post=1.0, dt=1.0, neuromod=0.0)
        # With neuromod, weight should be lower (stronger LTD)
        assert new_state.weight < new_state_no_mod.weight

    def test_weight_clamped_to_bounds(self) -> None:
        """Weight stays within [0, 1] bounds."""
        state = SynapseState(weight=0.99)
        # Strong LTP
        for _ in range(100):
            state = stdp_update(state, pre=1.0, post=1.0, dt=-1.0, neuromod=1.0)
        assert state.weight == 1.0

        state = SynapseState(weight=0.01)
        # Strong LTD
        for _ in range(100):
            state = stdp_update(state, pre=1.0, post=1.0, dt=1.0, neuromod=1.0)
        assert state.weight == 0.0

    def test_neuromod_decays_per_access(self) -> None:
        """Neuromodulator decays with each access."""
        state = SynapseState(weight=0.5, neuromod=1.0)
        new_state = stdp_update(state, pre=1.0, post=1.0, dt=-1.0)
        assert new_state.neuromod < 1.0
        assert new_state.neuromod == 1.0 * NEUROMOD_DECAY

    def test_last_stdp_updated(self) -> None:
        """last_stdp timestamp is updated on each call."""
        state = SynapseState(weight=0.5, last_stdp="")
        new_state = stdp_update(state, pre=1.0, post=1.0, dt=-1.0)
        assert new_state.last_stdp != ""
        assert "T" in new_state.last_stdp  # ISO format

    def test_apply_reward_increases_neuromod(self) -> None:
        """Reward increases neuromodulator level."""
        state = SynapseState(weight=0.5, neuromod=0.0)
        new_state = apply_reward(state, magnitude=0.3)
        assert new_state.neuromod == 0.3
        # Clamped at 1.0
        state2 = SynapseState(weight=0.5, neuromod=0.9)
        new_state2 = apply_reward(state2, magnitude=0.3)
        assert new_state2.neuromod == 1.0

    def test_effective_learning_rate_modulated(self) -> None:
        """Effective learning rate incorporates neuromodulators."""
        state = SynapseState(weight=0.5, neuromod=0.5)
        eta = effective_learning_rate(state, ach=0.0)
        assert eta > ETA_BASE  # DA enhances

        # ACh gates: higher ACh reduces effective rate
        eta_high_ach = effective_learning_rate(state, ach=0.8)
        assert eta_high_ach < eta

    def test_stdp_window_asymmetry(self) -> None:
        """LTP window (TAU_PLUS) is narrower than LTD (TAU_MINUS) → LTP decays faster."""
        assert TAU_PLUS < TAU_MINUS
        state = SynapseState(weight=0.5)
        # Same absolute dt, LTP decays faster (narrower window)
        ltp = stdp_update(state, pre=1.0, post=1.0, dt=-5.0).weight
        ltd = stdp_update(state, pre=1.0, post=1.0, dt=5.0).weight
        # LTD delta should be larger in magnitude (wider window)
        assert (0.5 - ltd) > (ltp - 0.5)

    def test_partial_activity_scales_change(self) -> None:
        """Partial pre/post scales the weight change."""
        state = SynapseState(weight=0.5)
        full = stdp_update(state, pre=1.0, post=1.0, dt=-1.0)
        half = stdp_update(state, pre=0.5, post=1.0, dt=-1.0)
        # Half pre should produce half the delta
        assert abs((half.weight - 0.5) - 0.5 * (full.weight - 0.5)) < 1e-6
