# SPDX-License-Identifier: MIT
"""Autonomy audit espejo (Fase 0 tanda 2, tarea 11).

VIVE: dxrk/autonomy/permissions.py (con memory.maintain, sin
PermissionLevel muerto) y el verifier aislado como juez externo en
dxrk/judge/ (auto-fix solo detras de flag explicito default-off).
MUERE: autonomy, learner, metrics, swarm, updater, evolution.
"""

from __future__ import annotations

import importlib

import pytest

DEAD_MODULES = [
    "dxrk.autonomy.autonomy",
    "dxrk.autonomy.learner",
    "dxrk.autonomy.metrics",
    "dxrk.autonomy.swarm",
    "dxrk.autonomy.updater",
    "dxrk.autonomy.evolution",
]


class TestDeadModulesGone:
    @pytest.mark.parametrize("mod", DEAD_MODULES)
    def test_old_imports_fail(self, mod: str) -> None:
        with pytest.raises(ImportError):
            importlib.import_module(mod)

    @pytest.mark.parametrize("mod", DEAD_MODULES)
    def test_no_stale_reexport(self, mod: str) -> None:
        short = mod.split(".")[-1]
        pkg = importlib.import_module("dxrk.autonomy")
        assert not hasattr(pkg, short) or getattr(pkg, short) is None


class TestPermissionsSurvive:
    def test_capabilities_include_maintain(self) -> None:
        from dxrk.autonomy import permissions as perms

        assert perms.CapMemoryMaintain == "memory.maintain"
        assert "memory.maintain" in perms.CAPABILITIES

    def test_permission_level_dead(self) -> None:
        import dxrk.autonomy

        assert not hasattr(dxrk.autonomy, "PermissionLevel")
        from dxrk.autonomy import permissions as perms

        assert not hasattr(perms, "PermissionLevel")

    def test_store_still_functional(self) -> None:
        from dxrk.autonomy.permissions import NewPermissionStore

        store = NewPermissionStore(["memory.maintain"], [])
        assert store.check("memory.maintain", "policy") is None
        assert store.check("sudo", "policy") is not None


class TestJudgeIsolation:
    def test_judge_verifier_exists(self) -> None:
        from dxrk.judge import verifier as judge

        assert hasattr(judge, "Verifier")
        assert hasattr(judge, "VerifyResult")

    def test_autofix_defaults_off(self) -> None:
        from dxrk.judge.verifier import Verifier

        assert Verifier.auto_fix_default() is False

    def test_judge_has_no_autonomy_imports(self) -> None:
        import re
        from pathlib import Path

        src = Path("dxrk/judge/verifier.py").read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+[\w.]*autonomy", src, re.MULTILINE)
        assert "Learner" not in src
        assert "from .learner" not in src and "from .metrics" not in src

    def test_verify_passes_clean_project(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from dxrk.judge.verifier import Verifier

        proj = tmp_path / "proj"
        proj.mkdir()
        result = Verifier(str(proj)).verify()
        assert result.pass_ is True

    def test_failing_command_marks_failure(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from dxrk.judge.verifier import Verifier

        proj = tmp_path / "proj"
        proj.mkdir()
        result = Verifier(str(proj), commands=(("false",),)).verify()
        assert result.pass_ is False
        assert result.failures == 1

    def test_autofix_without_fix_fn_does_nothing(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from dxrk.judge.verifier import Verifier

        proj = tmp_path / "proj"
        proj.mkdir()
        result = Verifier(str(proj), auto_fix=True, commands=(("false",),)).verify()
        assert result.pass_ is False  # no silent fix attempted, still failing

    def test_autofix_with_explicit_fix_fn_retries(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from dxrk.judge.verifier import Verifier

        proj = tmp_path / "proj"
        proj.mkdir()
        marker = proj / "fixed.txt"
        calls: list[tuple[str, ...]] = []

        def fix(cmd: tuple[str, ...]) -> None:
            calls.append(cmd)
            marker.write_text("fixed", encoding="utf-8")

        result = Verifier(str(proj), auto_fix=True, fix_fn=fix, commands=(("false",),)).verify()
        assert result.pass_ is False
        assert len(calls) == 1
        assert marker.is_file()
