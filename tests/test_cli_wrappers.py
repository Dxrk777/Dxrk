# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path

from dxrk.cli.sync import ParseSyncFlags, RunSync, SyncResult, SyncFlags
from dxrk.cli.restore import ParseRestoreFlags, RunRestore
from dxrk.cli.uninstall import (
    ParseUninstallFlags,
    RunUninstall,
    UninstallFlags,
    UninstallResult,
)
from dxrk.cli.dryrun import DryRunMode, build_dryrun_report
from dxrk.cli.run import (
    InstallResult,
    run_install,
    build_stage_plan,
    resolve_install_profile,
    has_component,
    add_post_install_notes,
    _verify_file_exists,
    _look_path,
    _resolve_adapters,
)
from dxrk.models import AgentID, ComponentID, Selection
from dxrk.system import DetectionResult, SystemInfo
from dxrk.pipeline import StagePlan

import pytest


class TestSyncWrapper:
    def test_parse_sync_flags(self, monkeypatch):
        called = None

        def fake_parse(args):
            nonlocal called
            called = args
            return {"agents": ["opencode"]}

        monkeypatch.setattr("dxrk.cli.install.parse_sync_flags", fake_parse)
        result = ParseSyncFlags(["--dry-run"])
        assert called == ["--dry-run"]
        assert result == {"agents": ["opencode"]}

    def test_run_sync(self, monkeypatch):
        called = None

        def fake_run(args):
            nonlocal called
            called = args
            return {"dry_run": True}

        monkeypatch.setattr("dxrk.cli.install.run_sync", fake_run)
        result = RunSync(["--dry-run"])
        assert called == ["--dry-run"]
        assert result == {"dry_run": True}

    def test_sync_result_defaults(self):
        r = SyncResult()
        assert r.agents == []
        assert r.dry_run is False
        assert r.no_op is False
        assert r.files_changed == 0

    def test_sync_result_custom(self):
        r = SyncResult(
            agents=[AgentID.OPENCODE], dry_run=True, no_op=True, files_changed=3
        )
        assert r.agents == [AgentID.OPENCODE]
        assert r.dry_run is True
        assert r.no_op is True
        assert r.files_changed == 3

    def test_sync_flags_defaults(self):
        f = SyncFlags()
        assert f.agents == []
        assert f.skills == []
        assert f.dry_run is False
        assert f.strict_tdd is False

    def test_sync_flags_custom(self):
        f = SyncFlags(agents=["opencode"], dry_run=True, strict_tdd=True)
        assert f.agents == ["opencode"]
        assert f.dry_run is True
        assert f.strict_tdd is True


class TestRestoreWrapper:
    def test_parse_restore_flags_list(self):
        result = ParseRestoreFlags(["--list"])
        assert result["list"] is True
        assert result["yes"] is False
        assert result["target"] is None

    def test_parse_restore_flags_yes(self):
        result = ParseRestoreFlags(["--yes"])
        assert result["list"] is False
        assert result["yes"] is True

    def test_parse_restore_flags_short_yes(self):
        result = ParseRestoreFlags(["-y"])
        assert result["yes"] is True

    def test_parse_restore_flags_target(self):
        result = ParseRestoreFlags(["latest"])
        assert result["target"] == "latest"

    def test_parse_restore_flags_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown flag"):
            ParseRestoreFlags(["--bogus"])

    def test_run_restore(self, monkeypatch):
        called = None

        def fake_run(args, stdout):
            nonlocal called
            called = (args, stdout)
            return "restore complete"

        monkeypatch.setattr("dxrk.cli.install.run_restore", fake_run)
        result = RunRestore(["latest"])
        assert called[0] == ["latest"]
        assert result == "restore complete"


class TestUninstallWrapper:
    def test_parse_uninstall_flags(self, monkeypatch):
        called = None

        def fake_parse(args):
            nonlocal called
            called = args
            return UninstallFlags(agents=["opencode"], all=False, yes=True)

        monkeypatch.setattr("dxrk.cli.install.parse_uninstall_flags", fake_parse)
        result = ParseUninstallFlags(["--yes"])
        assert called == ["--yes"]
        assert result.yes is True
        assert result.agents == ["opencode"]

    def test_uninstall_flags_defaults(self):
        f = UninstallFlags()
        assert f.agents == []
        assert f.all is False
        assert f.yes is False

    def test_uninstall_result_defaults(self):
        r = UninstallResult()
        assert r.agents_removed_from_state == []
        assert r.removed_files == []

    def test_run_uninstall(self, monkeypatch):
        called = None

        def fake_run(args, stdout):
            nonlocal called
            called = (args, stdout)
            return {}

        monkeypatch.setattr("dxrk.cli.install.run_uninstall", fake_run)
        result = RunUninstall(["--all"])
        assert called[0] == ["--all"]
        assert result == {}


class TestDryRunWrapper:
    def test_dry_run_mode_defaults(self):
        d = DryRunMode()
        assert d.agents == []
        assert d.components == []
        assert d.prepare_steps == 0
        assert d.apply_steps == 0

    def test_build_dryrun_report(self, monkeypatch):
        called = None

        def fake_render(result):
            nonlocal called
            called = result
            return "DRY RUN report"

        monkeypatch.setattr("dxrk.cli.install.render_dry_run", fake_render)
        result = build_dryrun_report({"dry_run": True})
        assert called == {"dry_run": True}
        assert result == "DRY RUN report"


class TestRunInstall:
    def test_run_install_dry_run(self, monkeypatch):
        detection = DetectionResult(system=SystemInfo(os="linux"))

        def fake_parse(args):
            from dxrk.cli.install import InstallFlags

            return InstallFlags(dry_run=True)

        def fake_normalize(flags, detection):
            from dxrk.cli.install import InstallInput

            return InstallInput(selection=Selection(), dry_run=True)

        monkeypatch.setattr("dxrk.cli.install.parse_install_flags", fake_parse)
        monkeypatch.setattr("dxrk.cli.install.normalize_install_flags", fake_normalize)
        monkeypatch.setattr(
            "dxrk.planner.new_resolver",
            lambda: type(
                "R",
                (),
                {
                    "resolve": lambda self, s: type(
                        "R", (), {"agents": [], "ordered_components": []}
                    )()
                },
            )(),
        )
        monkeypatch.setattr("dxrk.planner.build_review_payload", lambda s, r: {})
        monkeypatch.setattr("dxrk.planner.platform_decision_from_profile", lambda p: {})

        result = run_install(["--dry-run"], detection)
        assert result.dry_run is True
        assert result.error == ""

    def test_run_install_dry_run_minimal(self, monkeypatch):
        detection = DetectionResult(system=SystemInfo(os="linux"))

        def fake_parse(args):
            from dxrk.cli.install import InstallFlags

            return InstallFlags(dry_run=True, preset="minimal")

        def fake_normalize(flags, detection):
            from dxrk.cli.install import InstallInput

            return InstallInput(
                selection=Selection(agents=[AgentID.OPENCODE]), dry_run=True
            )

        monkeypatch.setattr("dxrk.cli.install.parse_install_flags", fake_parse)
        monkeypatch.setattr("dxrk.cli.install.normalize_install_flags", fake_normalize)
        monkeypatch.setattr(
            "dxrk.planner.new_resolver",
            lambda: type(
                "R",
                (),
                {
                    "resolve": lambda self, s: type(
                        "R",
                        (),
                        {
                            "agents": [AgentID.OPENCODE],
                            "ordered_components": [ComponentID.DXRK_MEMORY],
                        },
                    )()
                },
            )(),
        )
        monkeypatch.setattr("dxrk.planner.build_review_payload", lambda s, r: {})
        monkeypatch.setattr("dxrk.planner.platform_decision_from_profile", lambda p: {})

        result = run_install(["--dry-run", "--preset", "minimal"], detection)
        assert result.dry_run is True
        assert result.error == ""

    def test_build_stage_plan_with_agents(self):
        selection = Selection(agents=[AgentID.OPENCODE])
        resolved = type(
            "R",
            (),
            {
                "agents": [AgentID.OPENCODE],
                "ordered_components": [ComponentID.DXRK_MEMORY],
            },
        )()
        plan = build_stage_plan(selection, resolved)
        assert isinstance(plan, StagePlan)
        assert len(plan.prepare) == 2
        assert len(plan.apply) == 2  # agent:opencode + component:engram

    def test_build_stage_plan_empty(self):
        selection = Selection(agents=[], components=[])
        resolved = type("R", (), {"agents": [], "ordered_components": []})()
        plan = build_stage_plan(selection, resolved)
        assert len(plan.prepare) == 0
        assert len(plan.apply) == 0

    def test_resolve_install_profile(self):
        detection = DetectionResult(system=SystemInfo(os="darwin"))
        profile = resolve_install_profile(detection)
        assert profile.os == "darwin"

    def test_has_component(self):
        assert (
            has_component(
                [ComponentID.DXRK_MEMORY, ComponentID.SDD], ComponentID.DXRK_MEMORY
            )
            is True
        )
        assert has_component([ComponentID.SDD], ComponentID.DXRK_MEMORY) is False

    def test_add_post_install_notes(self):
        report = type("R", (), {"ready": True, "final_note": ""})()
        resolved = type("R", (), {"ordered_components": [ComponentID.DXRK_GUARDIAN]})()
        add_post_install_notes(report, resolved)
        assert "DXRK_GUARDIAN" in report.final_note

    def test_verify_file_exists_missing(self, tmp_path):
        check = _verify_file_exists(str(tmp_path / "nonexistent"))
        result = check()
        assert result is not None
        assert "does not exist" in result

    def test_verify_file_exists_present(self, tmp_path):
        f = tmp_path / "present.txt"
        f.write_text("ok")
        check = _verify_file_exists(str(f))
        result = check()
        assert result is None

    def test_look_path(self):
        result = _look_path("python3")
        assert result != ""

    def test_look_path_missing(self):
        result = _look_path("zzz_nonexistent_tool_xyz")
        assert result == ""

    def test_resolve_adapters_empty(self):
        result = _resolve_adapters([])
        assert result == []

    def test_resolve_adapters_with_agent(self, monkeypatch):
        fake_adapter = type("A", (), {"agent": AgentID.OPENCODE})()
        fake_reg = type(
            "R",
            (),
            {
                "get": lambda self, aid: (
                    fake_adapter if aid == AgentID.OPENCODE else None
                )
            },
        )()
        monkeypatch.setattr("dxrk.agents.registry.Registry", lambda: fake_reg)
        adapters = _resolve_adapters([AgentID.OPENCODE])
        assert len(adapters) == 1
