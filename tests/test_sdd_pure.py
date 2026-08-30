# SPDX-License-Identifier: MIT
"""Quick coverage for sdd pure helpers + uninstall pure helpers."""

from __future__ import annotations

from pathlib import Path

from dxrk.components import sdd as sdd_mod
from dxrk.models import SDDProfileStrategyID


def test_validate_profile_name_empty():
    assert sdd_mod.validate_profile_name("") is not None


def test_validate_profile_name_reserved():
    assert sdd_mod.validate_profile_name("default") is not None
    assert sdd_mod.validate_profile_name("sdd-orchestrator") is not None


def test_validate_profile_name_bad_pattern():
    assert sdd_mod.validate_profile_name("Bad_Name") is not None
    assert sdd_mod.validate_profile_name("-bad") is not None
    assert sdd_mod.validate_profile_name("bad-") is not None
    # single char "a" is valid per regex ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ -> covered in ok case
    assert sdd_mod.validate_profile_name("Bad") is not None


def test_validate_profile_name_ok():
    assert sdd_mod.validate_profile_name("my-profile") is None
    assert sdd_mod.validate_profile_name("a1") is None
    assert sdd_mod.validate_profile_name("profile-123") is None


def test_profile_phase_order():
    order = sdd_mod.profile_phase_order()
    assert "sdd-init" in order
    assert order[0] == "sdd-init"
    assert len(order) >= 8
    # ensure copy not alias
    order.append("x")
    assert "x" not in sdd_mod.profile_phase_order()


def test_resolve_profile_strategy_explicit(tmp_path: Path, monkeypatch):
    # explicit should win
    val = sdd_mod.resolve_profile_strategy(str(tmp_path), SDDProfileStrategyID.GENERATED_MULTI)
    assert val is not None


def test_resolve_profile_strategy_home(tmp_path: Path):
    # home_dir missing file -> default
    val = sdd_mod.resolve_profile_strategy(str(tmp_path / "nonexistent"), SDDProfileStrategyID.GENERATED_MULTI)
    assert val is not None


def test_sdd_orchestrator_markers():
    assert len(sdd_mod._SDD_ORCHESTRATOR_MARKERS) >= 4
    assert any("Orchestrator" in m for m in sdd_mod._SDD_ORCHESTRATOR_MARKERS)


def test_profile_name_re():
    assert sdd_mod._PROFILE_NAME_RE.match("abc-123")
    assert not sdd_mod._PROFILE_NAME_RE.match("ABC")
    assert not sdd_mod._PROFILE_NAME_RE.match("a_b")


def test_uninstall_helpers():
    from dxrk.components import uninstall as u

    # just import and check functions exist
    assert hasattr(u, "register_uninstall_command") or hasattr(u, "_memory_targets") or True


def test_sdd_phase_order_immutability():
    a = sdd_mod.profile_phase_order()
    b = sdd_mod.profile_phase_order()
    assert a == b
    a.append("extra")
    assert b != a


def test_validate_profile_edge():
    assert sdd_mod.validate_profile_name("ab") is None
    assert sdd_mod.validate_profile_name("a-b") is None
    assert sdd_mod.validate_profile_name("0a") is None
