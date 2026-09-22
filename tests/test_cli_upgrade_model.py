# SPDX-License-Identifier: MIT
"""Tests for `dxrk-py upgrade` and `dxrk-py model` wired to real machinery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dxrk.__main__ import main
from dxrk.model import ModelAssignment, get_model_assignments, set_model_assignment
from dxrk.system import DetectionResult, PlatformProfile, SystemInfo
from dxrk.update import ToolInfo, ToolUpgradeResult, ToolUpgradeStatus, UpdateResult, UpdateStatus, UpgradeReport


def _supported_detection() -> DetectionResult:
    return DetectionResult(
        system=SystemInfo(
            os="linux",
            supported=True,
            profile=PlatformProfile(os="linux", package_manager="apt", supported=True),
        ),
    )


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> list[str]:
    monkeypatch.setattr("sys.argv", argv)
    printed: list[str] = []
    monkeypatch.setattr(
        "builtins.print",
        lambda *a, **kw: printed.append(" ".join(str(x) for x in a)),
    )
    return printed


class TestUpgradeCli:
    def test_up_to_date_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        printed = _run_main(monkeypatch, ["dxrk", "upgrade"])
        monkeypatch.setattr("dxrk.system.detect", lambda: _supported_detection())
        monkeypatch.setattr(
            "dxrk.update.check_filtered",
            lambda version, profile, tools: [UpdateResult(status=UpdateStatus.UP_TO_DATE)],
        )
        main()
        assert any("No hay actualizaciones disponibles" in line for line in printed)

    def test_dry_run_with_updates_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        printed = _run_main(monkeypatch, ["dxrk", "upgrade", "--dry-run"])
        monkeypatch.setattr("dxrk.system.detect", lambda: _supported_detection())
        monkeypatch.setattr(
            "dxrk.update.check_filtered",
            lambda version, profile, tools: [
                UpdateResult(
                    tool=ToolInfo(name="gga"),
                    installed_version="1.0.0",
                    latest_version="2.0.0",
                    status=UpdateStatus.UPDATE_AVAILABLE,
                )
            ],
        )
        main()
        assert any("Actualizaciones disponibles: gga 1.0.0 -> 2.0.0" in line for line in printed)
        assert any("simulación" in line for line in printed)

    def test_tool_filter_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        printed = _run_main(monkeypatch, ["dxrk", "upgrade", "gga", "--dry-run"])
        monkeypatch.setattr("dxrk.system.detect", lambda: _supported_detection())
        seen: dict[str, object] = {}

        def fake_check(version: str, profile: object, tools: list[str] | None) -> list[UpdateResult]:
            seen["tools"] = tools
            return [UpdateResult(status=UpdateStatus.UP_TO_DATE)]

        monkeypatch.setattr("dxrk.update.check_filtered", fake_check)
        main()
        assert seen["tools"] == ["gga"]
        assert any("No hay actualizaciones disponibles" in line for line in printed)

    def test_check_failure_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _run_main(monkeypatch, ["dxrk", "upgrade"])
        monkeypatch.setattr("dxrk.system.detect", lambda: _supported_detection())
        monkeypatch.setattr(
            "dxrk.update.check_filtered",
            lambda version, profile, tools: [
                UpdateResult(tool=ToolInfo(name="gga"), status=UpdateStatus.CHECK_FAILED, err="boom"),
            ],
        )
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    def test_execute_failure_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _run_main(monkeypatch, ["dxrk", "upgrade"])
        monkeypatch.setattr("dxrk.system.detect", lambda: _supported_detection())
        monkeypatch.setattr(
            "dxrk.update.check_filtered",
            lambda version, profile, tools: [
                UpdateResult(
                    tool=ToolInfo(name="gga"),
                    installed_version="1.0.0",
                    latest_version="2.0.0",
                    status=UpdateStatus.UPDATE_AVAILABLE,
                )
            ],
        )
        monkeypatch.setattr(
            "dxrk.update.execute",
            lambda results, profile, home, dry_run=False: UpgradeReport(
                results=[ToolUpgradeResult(tool_name="gga", status=ToolUpgradeStatus.FAILED, err="denied")],
            ),
        )
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    def test_unsupported_system_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _run_main(monkeypatch, ["dxrk", "upgrade"])
        monkeypatch.setattr(
            "dxrk.system.detect",
            lambda: DetectionResult(system=SystemInfo(os="freebsd", supported=False)),
        )
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1


class TestModelCli:
    def test_list_assignments(self, monkeypatch: pytest.MonkeyPatch) -> None:
        printed = _run_main(monkeypatch, ["dxrk", "model"])
        monkeypatch.setattr(
            "dxrk.model.get_model_assignments",
            lambda *a, **k: {"sdd-apply": ModelAssignment(ProviderID="anthropic", ModelID="claude-x")},
        )
        main()
        assert any("sdd-apply: anthropic/claude-x" in line for line in printed)

    def test_set_assignment_confirms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        printed = _run_main(
            monkeypatch, ["dxrk", "model", "sdd-apply", "--provider", "anthropic", "--model", "claude-x"]
        )
        saved: dict[str, str] = {}

        def fake_set(phase: str, provider: str, model: str, home_dir: str = "") -> ModelAssignment:
            saved.update(phase=phase, provider=provider, model=model)
            return ModelAssignment(ProviderID=provider, ModelID=model)

        monkeypatch.setattr("dxrk.model.set_model_assignment", fake_set)
        main()
        assert saved == {"phase": "sdd-apply", "provider": "anthropic", "model": "claude-x"}
        assert any("set to anthropic/claude-x" in line for line in printed)

    def test_show_single_phase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        printed = _run_main(monkeypatch, ["dxrk", "model", "sdd-apply"])
        monkeypatch.setattr(
            "dxrk.model.get_model_assignments",
            lambda *a, **k: {"sdd-apply": ModelAssignment(ProviderID="p", ModelID="m")},
        )
        main()
        assert any("sdd-apply: p/m" in line for line in printed)

    def test_show_missing_phase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        printed = _run_main(monkeypatch, ["dxrk", "model", "sdd-verify"])
        monkeypatch.setattr("dxrk.model.get_model_assignments", lambda *a, **k: {})
        main()
        assert any("No model configured for phase 'sdd-verify'" in line for line in printed)

    def test_half_flags_exit_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _run_main(monkeypatch, ["dxrk", "model", "sdd-apply", "--provider", "anthropic"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2

    def test_set_failure_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _run_main(monkeypatch, ["dxrk", "model", "sdd-apply", "--provider", "p", "--model", "m"])

        def fake_set(phase: str, provider: str, model: str, home_dir: str = "") -> ModelAssignment:
            raise ValueError("boom")

        monkeypatch.setattr("dxrk.model.set_model_assignment", fake_set)
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1


class TestModelPersistence:
    def test_roundtrip(self, tmp_path: Path) -> None:
        home = str(tmp_path)
        saved = set_model_assignment("sdd-apply", "anthropic", "claude-x", home_dir=home)
        assert saved.full_id() == "anthropic/claude-x"
        current = get_model_assignments(home_dir=home)
        assert current["sdd-apply"].full_id() == "anthropic/claude-x"

    def test_set_preserves_other_phases(self, tmp_path: Path) -> None:
        home = str(tmp_path)
        set_model_assignment("sdd-apply", "p1", "m1", home_dir=home)
        set_model_assignment("sdd-verify", "p2", "m2", home_dir=home)
        current = get_model_assignments(home_dir=home)
        assert set(current) == {"sdd-apply", "sdd-verify"}

    def test_get_empty_without_state(self, tmp_path: Path) -> None:
        assert get_model_assignments(home_dir=str(tmp_path / "nope")) == {}

    def test_get_empty_on_corrupt_state(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".dxrk"
        state_dir.mkdir()
        (state_dir / "state.json").write_text("{not json")
        assert get_model_assignments(home_dir=str(tmp_path)) == {}

    def test_set_rejects_empty_fields(self, tmp_path: Path) -> None:
        home = str(tmp_path)
        with pytest.raises(ValueError):
            set_model_assignment("", "p", "m", home_dir=home)
        with pytest.raises(ValueError):
            set_model_assignment("phase", "", "m", home_dir=home)
        with pytest.raises(ValueError):
            set_model_assignment("phase", "p", "", home_dir=home)

    def test_state_file_written(self, tmp_path: Path) -> None:
        home = str(tmp_path)
        set_model_assignment("sdd-apply", "anthropic", "claude-x", home_dir=home)
        raw = json.loads((tmp_path / ".dxrk" / "state.json").read_text())
        assert raw["model_assignments"]["sdd-apply"]["provider_id"] == "anthropic"
