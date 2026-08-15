# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path

from dxrk.cli.install import run_sync, build_sync_selection, SyncRuntime, SyncResult
from dxrk.cli.install import parse_sync_flags
from dxrk.models import AgentID, ComponentID, Selection, SDDModeID, SDDProfileStrategyID
from dxrk.pipeline import StagePlan

import pytest


def test_dry_run_no_agents(tmp_path, monkeypatch):
    monkeypatch.setattr("dxrk.cli.install.discover_agents", lambda _: [])
    monkeypatch.setattr("dxrk.cli.install.os.path.expanduser", lambda _: str(tmp_path))

    result = run_sync(["--dry-run"])

    assert result.dry_run is True
    assert result.no_op is True
    assert result.agents == []


def test_dry_run_with_agents(tmp_path, monkeypatch):
    monkeypatch.setattr("dxrk.cli.install.discover_agents", lambda _: [])
    monkeypatch.setattr("dxrk.cli.install.os.path.expanduser", lambda _: str(tmp_path))

    result = run_sync(["--dry-run", "--agents", "opencode"])

    assert result.dry_run is True
    assert result.agents == [AgentID.OPENCODE]
    assert result.plan is not None
    assert isinstance(result.plan, StagePlan)


def test_dry_run_multiple_agents(tmp_path, monkeypatch):
    monkeypatch.setattr("dxrk.cli.install.discover_agents", lambda _: [])
    monkeypatch.setattr("dxrk.cli.install.os.path.expanduser", lambda _: str(tmp_path))

    result = run_sync(["--dry-run", "--agents", "opencode,claude-code"])

    assert result.dry_run is True
    assert result.agents == [AgentID.OPENCODE, AgentID.CLAUDE_CODE]


def test_dry_run_strict_tdd(tmp_path, monkeypatch):
    monkeypatch.setattr("dxrk.cli.install.discover_agents", lambda _: [])
    monkeypatch.setattr("dxrk.cli.install.os.path.expanduser", lambda _: str(tmp_path))

    result = run_sync(["--dry-run", "--agents", "opencode", "--strict-tdd"])

    assert result.selection.strict_tdd is True


def test_dry_run_include_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr("dxrk.cli.install.discover_agents", lambda _: [])
    monkeypatch.setattr("dxrk.cli.install.os.path.expanduser", lambda _: str(tmp_path))

    result = run_sync(["--dry-run", "--agents", "opencode", "--include-permissions"])

    assert ComponentID.PERMISSIONS in result.selection.components


def test_dry_run_include_theme(tmp_path, monkeypatch):
    monkeypatch.setattr("dxrk.cli.install.discover_agents", lambda _: [])
    monkeypatch.setattr("dxrk.cli.install.os.path.expanduser", lambda _: str(tmp_path))

    result = run_sync(["--dry-run", "--agents", "opencode", "--include-theme"])

    assert ComponentID.THEME in result.selection.components


def test_dry_run_profile_strategy(tmp_path, monkeypatch):
    monkeypatch.setattr("dxrk.cli.install.discover_agents", lambda _: [])
    monkeypatch.setattr("dxrk.cli.install.os.path.expanduser", lambda _: str(tmp_path))

    result = run_sync(["--dry-run", "--agents", "opencode", "--sdd-profile-strategy", "external-single-active"])

    assert result.selection.sdd_profile_strategy == SDDProfileStrategyID.EXTERNAL_SINGLE_ACTIVE


def test_dry_run_unknown_flag_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("dxrk.cli.install.os.path.expanduser", lambda _: str(tmp_path))

    with pytest.raises(ValueError, match="unexpected sync argument"):
        run_sync(["--dry-run", "--agents", "opencode", "--bogus-flag"])


class TestParseSyncFlags:
    def test_defaults(self):
        flags = parse_sync_flags(["--dry-run"])
        assert flags.dry_run is True
        assert flags.agents == []
        assert flags.strict_tdd is False
        assert flags.include_permissions is False
        assert flags.include_theme is False

    def test_with_agents(self):
        flags = parse_sync_flags(["--dry-run", "--agents", "opencode,claude"])
        assert flags.agents == ["opencode", "claude"]

    def test_strict_tdd(self):
        flags = parse_sync_flags(["--dry-run", "--strict-tdd"])
        assert flags.strict_tdd is True

    def test_include_permissions(self):
        flags = parse_sync_flags(["--dry-run", "--include-permissions"])
        assert flags.include_permissions is True

    def test_include_theme(self):
        flags = parse_sync_flags(["--dry-run", "--include-theme"])
        assert flags.include_theme is True

    def test_sdd_mode(self):
        flags = parse_sync_flags(["--dry-run", "--sdd-mode", "multi"])
        assert flags.sdd_mode == "multi"

    def test_profile_strategy(self):
        flags = parse_sync_flags(["--dry-run", "--sdd-profile-strategy", "external-single-active"])
        assert flags.sdd_profile_strategy == "external-single-active"


class TestBuildSyncSelection:
    def test_default_components(self):
        selection = build_sync_selection(
            parse_sync_flags(["--dry-run"]),
            [AgentID.OPENCODE],
        )
        assert AgentID.OPENCODE in selection.agents
        assert ComponentID.SDD in selection.components
        assert ComponentID.DXRK_MEMORY in selection.components
        assert ComponentID.PERMISSIONS not in selection.components
        assert ComponentID.THEME not in selection.components

    def test_with_permissions(self):
        selection = build_sync_selection(
            parse_sync_flags(["--dry-run", "--include-permissions"]),
            [AgentID.OPENCODE],
        )
        assert ComponentID.PERMISSIONS in selection.components

    def test_with_theme(self):
        selection = build_sync_selection(
            parse_sync_flags(["--dry-run", "--include-theme"]),
            [AgentID.OPENCODE],
        )
        assert ComponentID.THEME in selection.components

    def test_default_sdd_mode(self):
        selection = build_sync_selection(
            parse_sync_flags(["--dry-run"]),
            [AgentID.OPENCODE],
        )
        assert selection.sdd_mode == SDDModeID.SINGLE

    def test_default_profile_strategy(self):
        selection = build_sync_selection(
            parse_sync_flags(["--dry-run"]),
            [AgentID.OPENCODE],
        )
        assert selection.sdd_profile_strategy == SDDProfileStrategyID.GENERATED_MULTI


class TestSyncRuntimeStagePlan:
    def test_returns_stage_plan(self, tmp_path, monkeypatch):
        selection = Selection(
            agents=[AgentID.OPENCODE],
            components=[ComponentID.SDD, ComponentID.DXRK_MEMORY],
        )

        monkeypatch.setattr("dxrk.cli.install._resolve_adapters", lambda agents: [])
        monkeypatch.setattr("dxrk.cli.install._sync_backup_targets", lambda *a: [])

        rt = SyncRuntime(str(tmp_path), str(tmp_path), selection)
        plan = rt.stage_plan()

        assert isinstance(plan, StagePlan)
        assert len(plan.prepare) == 1
        assert len(plan.apply) == 3  # rollback-restore + SDD + ENGRAM
        assert plan.prepare[0].id() == "prepare:backup-snapshot"
        assert plan.apply[0].id() == "apply:rollback-restore"

    def test_empty_selection_returns_plan(self, tmp_path, monkeypatch):
        selection = Selection(agents=[], components=[])

        monkeypatch.setattr("dxrk.cli.install._resolve_adapters", lambda agents: [])
        monkeypatch.setattr("dxrk.cli.install._sync_backup_targets", lambda *a: [])

        rt = SyncRuntime(str(tmp_path), str(tmp_path), selection)
        plan = rt.stage_plan()

        assert isinstance(plan, StagePlan)
        assert len(plan.apply) == 1  # just rollback-restore, no component steps
