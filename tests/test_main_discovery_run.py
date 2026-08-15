# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import ANY

from dxrk.agents.discovery import (
    discover_installed,
    config_roots_for_backup,
    InstalledAgent,
)
from dxrk.agents.registry import Registry
from dxrk.models import AgentID, ComponentID, Selection, SDDModeID
from dxrk.system import SystemInfo, PlatformProfile, DetectionResult, DependencyReport

import pytest


class FakeAdapter:
    def __init__(self, agent_id, config_dir="", supports_mcp=True):
        self._agent = agent_id
        self._config_dir = config_dir
        self._supports_mcp = supports_mcp

    @property
    def agent(self):
        return self._agent

    @property
    def supports_mcp(self):
        return self._supports_mcp

    def global_config_dir(self, home_dir=""):
        return self._config_dir


def test_discover_installed_empty(tmp_path):
    reg = Registry()
    result = discover_installed(reg, str(tmp_path))
    assert result == []


def test_discover_installed_no_adapter(tmp_path):
    reg = Registry()
    result = discover_installed(reg, "/nonexistent")
    assert isinstance(result, list)


def test_discover_installed_finds_existing(tmp_path):
    (tmp_path / ".config" / "opencode").mkdir(parents=True)
    from dxrk.agents.factory import create_registry

    reg = create_registry()
    result = discover_installed(reg, str(tmp_path))
    opencode_agents = [a for a in result if a.id == AgentID.OPENCODE]
    assert len(opencode_agents) == 1
    assert opencode_agents[0].config_dir.endswith(".config/opencode")


def test_config_roots_for_backup_dedup(tmp_path, monkeypatch):
    from dxrk.agents.factory import create_registry

    reg = create_registry()

    (tmp_path / ".config" / "opencode").mkdir(parents=True)

    roots = config_roots_for_backup(reg, str(tmp_path))
    assert len(roots) >= 1


class TestMainCli:
    def test_main_version(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["dxrk", "--version"])
        printed = []
        monkeypatch.setattr(
            "builtins.print",
            lambda *a, **kw: printed.append(" ".join(str(x) for x in a)),
        )
        from dxrk.__main__ import main

        main()
        assert any("Dxrk" in l for l in printed)

    def test_main_health(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["dxrk", "--health"])
        monkeypatch.setattr(
            "dxrk.system.detect",
            lambda: DetectionResult(
                system=SystemInfo(
                    os="linux",
                    supported=True,
                    profile=PlatformProfile(
                        os="linux", package_manager="apt", supported=True
                    ),
                ),
                dependencies=DependencyReport(all_present=True),
            ),
        )
        lines = []
        monkeypatch.setattr(
            "builtins.print", lambda *a, **kw: lines.append(" ".join(str(x) for x in a))
        )
        from dxrk.__main__ import main

        main()
        assert any("Dependencies" in l for l in lines)

    def test_main_version_command(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["dxrk", "version"])
        printed = []
        monkeypatch.setattr(
            "builtins.print",
            lambda *a, **kw: printed.append(" ".join(str(x) for x in a)),
        )
        from dxrk.__main__ import main

        main()
        assert any("Dxrk" in l for l in printed)

    def test_main_unknown_command(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["dxrk", "nonexistent"])
        lines = []
        monkeypatch.setattr(
            "builtins.print", lambda *a, **kw: lines.append(" ".join(str(x) for x in a))
        )
        from dxrk.__main__ import main

        with pytest.raises(SystemExit):
            main()

    def test_run_install_cli_dry_run(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv", ["dxrk", "install", "--agent", "opencode", "--dry-run"]
        )
        monkeypatch.setattr(
            "dxrk.system.detect",
            lambda: DetectionResult(
                system=SystemInfo(
                    os="linux",
                    supported=True,
                    profile=PlatformProfile(
                        os="linux", package_manager="apt", supported=True
                    ),
                ),
                dependencies=DependencyReport(all_present=True),
            ),
        )
        printed = []
        monkeypatch.setattr(
            "builtins.print",
            lambda *a, **kw: printed.append(" ".join(str(x) for x in a)),
        )
        from dxrk.__main__ import main

        main()
        assert any("Dry Run Review" in l for l in printed)

    def test_run_install_cli_unsupported_os(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["dxrk", "install"])
        monkeypatch.setattr(
            "dxrk.system.detect",
            lambda: DetectionResult(
                system=SystemInfo(
                    os="freebsd", supported=False, profile=PlatformProfile()
                ),
                dependencies=DependencyReport(),
            ),
        )
        from dxrk.__main__ import main

        with pytest.raises(SystemExit):
            main()

    def test_run_sync_cli_dry_run(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv", ["dxrk", "sync", "--dry-run", "--agent", "opencode"]
        )
        printed = []
        monkeypatch.setattr(
            "builtins.print",
            lambda *a, **kw: printed.append(" ".join(str(x) for x in a)),
        )
        monkeypatch.setattr(
            "dxrk.cli.sync.RunSync",
            lambda raw: type(
                "obj",
                (),
                {
                    "dry_run": True,
                    "agents": [AgentID.OPENCODE],
                    "selection": type(
                        "sel", (), {"sdd_mode": "single", "strict_tdd": False}
                    )(),
                },
            )(),
        )
        from dxrk.__main__ import main

        main()
        assert any("Dry Run Sync" in l for l in printed)

    def test_run_backup_cli_no_backups(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["dxrk", "backup"])
        monkeypatch.setattr("dxrk.backup.list_backups", lambda: [])
        printed = []
        monkeypatch.setattr(
            "builtins.print",
            lambda *a, **kw: printed.append(" ".join(str(x) for x in a)),
        )
        from dxrk.__main__ import main

        main()
        assert any("No backups" in l for l in printed)

    def test_run_model_cli_no_args(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["dxrk", "model"])
        printed = []
        monkeypatch.setattr(
            "builtins.print",
            lambda *a, **kw: printed.append(" ".join(str(x) for x in a)),
        )
        from dxrk.__main__ import main

        main()
        assert any("not yet implemented" in l for l in printed)

    def test_run_upgrade(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["dxrk", "upgrade"])
        printed = []
        monkeypatch.setattr(
            "builtins.print",
            lambda *a, **kw: printed.append(" ".join(str(x) for x in a)),
        )
        from dxrk.__main__ import main

        main()
        assert any("not yet implemented" in l for l in printed)


class TestCliRun:
    def test_install_result_defaults(self):
        from dxrk.cli.run import InstallResult

        r = InstallResult()
        assert r.dry_run is False
        assert r.error == ""

    def test_run_install_dry_run(self, monkeypatch):
        from dxrk.cli.run import run_install

        monkeypatch.setattr(
            "dxrk.cli.install.parse_install_flags",
            lambda args: type(
                "f",
                (),
                {
                    "agents": ["opencode"],
                    "components": [],
                    "skills": [],
                    "persona": "dxrk",
                    "preset": "full-dxrk",
                    "dry_run": True,
                    "sdd_mode": "",
                    "agents_raw": [],
                    "strict_tdd": False,
                    "sdd_profile_strategy": "",
                },
            )(),
        )
        monkeypatch.setattr(
            "dxrk.cli.install.normalize_install_flags",
            lambda f, d: type(
                "in",
                (),
                {
                    "selection": Selection(agents=[AgentID.OPENCODE]),
                    "dry_run": True,
                },
            )(),
        )

        class FakeResolver:
            def resolve(self, s):
                return type(
                    "r",
                    (),
                    {
                        "agents": [AgentID.OPENCODE],
                        "ordered_components": [ComponentID.SDD],
                    },
                )()

        monkeypatch.setattr("dxrk.planner.new_resolver", lambda: FakeResolver())
        monkeypatch.setattr("dxrk.planner.build_review_payload", lambda s, r: None)
        monkeypatch.setattr(
            "dxrk.planner.platform_decision_from_profile", lambda p: None
        )
        monkeypatch.setattr(
            "dxrk.cli.install.resolve_install_profile",
            lambda d: PlatformProfile(
                os="linux", package_manager="apt", supported=True
            ),
        )
        monkeypatch.setattr(
            "dxrk.cli.run.resolve_install_profile",
            lambda d: PlatformProfile(
                os="linux", package_manager="apt", supported=True
            ),
        )

        detection = DetectionResult(
            system=SystemInfo(
                os="linux",
                supported=True,
                profile=PlatformProfile(
                    os="linux", package_manager="apt", supported=True
                ),
            ),
            dependencies=DependencyReport(all_present=True),
        )
        result = run_install(["--agent", "opencode", "--dry-run"], detection)
        assert result.dry_run is True
        assert result.resolved is not None

    def test_verify_file_exists_present(self, tmp_path):
        from dxrk.cli.run import _verify_file_exists

        f = tmp_path / "test.txt"
        f.write_text("hello")
        check = _verify_file_exists(str(f))
        assert check() is None

    def test_verify_file_exists_missing(self, tmp_path):
        from dxrk.cli.run import _verify_file_exists

        check = _verify_file_exists(str(tmp_path / "nonexistent.txt"))
        assert check() is not None
        assert "does not exist" in check()

    def test_look_path_found(self, monkeypatch):
        from dxrk.cli.run import _look_path

        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/python3")
        assert _look_path("python3") != ""

    def test_look_path_not_found(self, monkeypatch):
        from dxrk.cli.run import _look_path

        monkeypatch.setattr("shutil.which", lambda _: None)
        assert _look_path("zzz_nonexistent") == ""

    def test_resolve_adapters(self, monkeypatch):
        from dxrk.cli.run import _resolve_adapters

        adapters = _resolve_adapters([AgentID.OPENCODE])
        assert len(adapters) >= 1

    def test_resolve_adapters_unknown(self, monkeypatch):
        from dxrk.cli.run import _resolve_adapters

        adapters = _resolve_adapters(["unknown"])
        assert adapters == []

    def test_has_component_true(self):
        from dxrk.cli.run import has_component

        assert (
            has_component([ComponentID.SDD, ComponentID.DXRK_MEMORY], ComponentID.SDD)
            is True
        )

    def test_has_component_false(self):
        from dxrk.cli.run import has_component

        assert has_component([ComponentID.SDD], ComponentID.DXRK_MEMORY) is False

    def test_resolve_install_profile(self, monkeypatch):
        from dxrk.cli.run import resolve_install_profile

        monkeypatch.setattr(
            "dxrk.cli.install.resolve_install_profile",
            lambda d: PlatformProfile(
                os="darwin", package_manager="brew", supported=True
            ),
        )
        profile = resolve_install_profile(
            DetectionResult(
                system=SystemInfo(
                    os="darwin",
                    profile=PlatformProfile(
                        os="darwin", package_manager="brew", supported=True
                    ),
                ),
            )
        )
        assert profile.os == "darwin"

    def test_build_stage_plan_with_agents(self):
        from dxrk.cli.run import build_stage_plan

        selection = Selection(agents=[AgentID.OPENCODE], components=[ComponentID.SDD])
        resolved = type(
            "r",
            (),
            {"agents": [AgentID.OPENCODE], "ordered_components": [ComponentID.SDD]},
        )()
        plan = build_stage_plan(selection, resolved)
        assert len(plan.prepare) == 2
        assert len(plan.apply) == 2

    def test_build_stage_plan_empty(self):
        from dxrk.cli.run import build_stage_plan

        selection = Selection(agents=[], components=[])
        resolved = type("r", (), {"agents": [], "ordered_components": []})()
        plan = build_stage_plan(selection, resolved)
        assert plan.prepare == []

    def test_engram_health_checks(self, monkeypatch):
        from dxrk.cli.run import _DXRK_MEMORY_health_checks

        monkeypatch.setattr(
            "dxrk.cli.run._look_path",
            lambda name: name == "DXRK_MEMORY" and "/usr/local/bin/DXRK_MEMORY" or "",
        )
        monkeypatch.setattr(
            "subprocess.run", lambda *a, **kw: type("r", (), {"returncode": 0})()
        )
        checks = _DXRK_MEMORY_health_checks()
        assert len(checks) == 2

    def test_antigravity_collision_check_both(self):
        from dxrk.cli.run import _antigravity_collision_check

        checks = _antigravity_collision_check([AgentID.ANTIGRAVITY, AgentID.GEMINI_CLI])
        assert len(checks) == 1
        result = checks[0]()
        assert result is not None

    def test_antigravity_collision_check_one(self):
        from dxrk.cli.run import _antigravity_collision_check

        checks = _antigravity_collision_check([AgentID.ANTIGRAVITY])
        assert checks == []
