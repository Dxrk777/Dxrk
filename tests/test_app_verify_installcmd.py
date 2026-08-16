# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from dxrk.app import (
    VERSION,
    SelfUpdateChecker,
    print_help,
    resolve_version,
    run_cli,
)
from dxrk.installcmd import (
    InstallError,
    ProfileResolver,
    git_bash_path,
    new_resolver,
    validate_agent_install_preflight,
    validate_go_for_module_install,
)
from dxrk.models import AgentID, ComponentID
from dxrk.system import PlatformProfile
from dxrk.verify import (
    Check,
    CheckResult,
    CheckStatus,
    PostInstallVerifier,
    Report,
    VerificationScenario,
    build_report,
    render_report,
    run_checks,
)

# ─── app.py ──────────────────────────────────────────────────────────────────


class TestResolveVersion:
    def test_returns_dev_for_dev(self):
        assert resolve_version("dev") == "dev"

    def test_returns_ldflags_version(self):
        assert resolve_version("1.2.3") == "1.2.3"


class TestPrintHelp:
    def test_contains_version(self):
        result = print_help("1.0.0")
        assert "1.0.0" in result
        assert "dxrk" in result

    def test_contains_commands(self):
        result = print_help("dev")
        assert "install" in result
        assert "sync" in result
        assert "uninstall" in result


class TestRunCli:
    def test_version_command(self, capsys):
        rc = run_cli(["version"])
        assert rc == 0
        out = capsys.readouterr().out
        assert VERSION in out

    def test_version_flag(self, capsys):
        rc = run_cli(["--version"])
        assert rc == 0

    def test_version_short(self, capsys):
        rc = run_cli(["-v"])
        assert rc == 0

    def test_help_command(self, capsys):
        rc = run_cli(["help"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "USAGE" in out

    def test_help_flag(self, capsys):
        rc = run_cli(["--help"])
        assert rc == 0

    def test_uninstall_with_unknown_flag(self, capsys):
        rc = run_cli(["uninstall", "--bogus"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "unexpected uninstall argument" in err

    def test_uninstall_all_flag(self, capsys):
        rc = run_cli(["uninstall", "--all"])
        assert rc == 0

    def test_unknown_command(self, capsys):
        rc = run_cli(["zzz_nonexistent_cmd"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "unknown command" in err

    def test_no_args_tui_not_available(self, capsys, monkeypatch):
        class FakeSystem:
            supported = True

            class Profile:
                os = "darwin"

            profile = Profile()

        class FakeDetection:
            system = FakeSystem()

        monkeypatch.setattr("dxrk.app.detect", lambda: FakeDetection())
        monkeypatch.setattr("dxrk.app.ensure_supported_os", lambda _: None)
        rc = run_cli([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "TUI mode not available" in out

    def test_sync_command(self, capsys, monkeypatch):
        class FakeSystem:
            supported = True

            class Profile:
                os = "darwin"

            profile = Profile()

        class FakeDetection:
            system = FakeSystem()

        monkeypatch.setattr("dxrk.app.detect", lambda: FakeDetection())
        monkeypatch.setattr("dxrk.app.ensure_supported_os", lambda _: None)
        monkeypatch.setattr("dxrk.cli.install.parse_sync_flags", lambda a: None)
        rc = run_cli(["sync"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Sync completed" in out

    def test_unsupported_os(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "dxrk.app.ensure_supported_os",
            lambda _: (_ for _ in ()).throw(OSError("bad os")),
        )
        rc = run_cli(["install"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "Error" in err

    def test_detect_failure(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "dxrk.app.detect", lambda: (_ for _ in ()).throw(Exception("boom"))
        )

        class FakeResult:
            system = PlatformProfile(os="darwin", supported=True)

        monkeypatch.setattr("dxrk.app.ensure_supported_os", lambda _: None)
        run_cli(["install"])
        out = capsys.readouterr().err
        assert "detect system" in out


class TestSelfUpdateChecker:
    def test_skip_reason_env_done(self, monkeypatch):
        monkeypatch.setenv("DXRK_SELF_UPDATE_DONE", "1")
        checker = SelfUpdateChecker(version="1.0.0")
        assert checker.skip_reason() is not None
        assert "already updated" in checker.skip_reason()

    def test_skip_reason_env_opt_out(self, monkeypatch):
        monkeypatch.setenv("DXRK_NO_SELF_UPDATE", "1")
        checker = SelfUpdateChecker(version="1.0.0")
        assert checker.skip_reason() is not None
        assert "opt-out" in checker.skip_reason()

    def test_skip_reason_dev_build(self):
        checker = SelfUpdateChecker(version="dev")
        assert checker.skip_reason() is not None
        assert "dev build" in checker.skip_reason()

    def test_skip_reason_none(self):
        checker = SelfUpdateChecker(version="1.0.0")
        assert checker.skip_reason() is None

    def test_check_skips_when_skip_reason(self, monkeypatch):
        monkeypatch.setenv("DXRK_SELF_UPDATE_DONE", "1")
        checker = SelfUpdateChecker(version="1.0.0")
        result = checker.check()
        assert result is None

    def test_disabled_checker(self, monkeypatch):
        monkeypatch.setattr("dxrk.app.check_filtered", lambda *a: [])
        checker = SelfUpdateChecker(version="1.0.0", enabled=False)
        result = checker.check()
        assert result is None


# ─── verify.py ───────────────────────────────────────────────────────────────


class TestCheckStatus:
    def test_values(self):
        assert CheckStatus.PASSED.value == "passed"
        assert CheckStatus.FAILED.value == "failed"
        assert CheckStatus.SKIPPED.value == "skipped"
        assert CheckStatus.WARNING.value == "warning"


class TestCheckDataclass:
    def test_defaults(self):
        c = Check()
        assert c.id == ""
        assert c.description == ""
        assert c.run is None
        assert c.soft is False


class TestRunChecks:
    def test_no_run_implementation(self):
        results = run_checks([Check(id="test")])
        assert len(results) == 1
        assert results[0].status == CheckStatus.SKIPPED
        assert results[0].error == "check not implemented"

    def test_passes_when_run_returns_none(self):
        results = run_checks([Check(id="test", run=lambda: None)])
        assert len(results) == 1
        assert results[0].status == CheckStatus.PASSED

    def test_fails_when_run_returns_error(self):
        results = run_checks([Check(id="test", run=lambda: "error message")])
        assert len(results) == 1
        assert results[0].status == CheckStatus.FAILED
        assert results[0].error == "error message"

    def test_warning_when_soft_check_fails(self):
        results = run_checks([Check(id="test", soft=True, run=lambda: "warning msg")])
        assert len(results) == 1
        assert results[0].status == CheckStatus.WARNING

    def test_multiple_checks(self):
        results = run_checks(
            [
                Check(id="a", run=lambda: None),
                Check(id="b", run=lambda: "fail"),
                Check(id="c"),
            ]
        )
        assert len(results) == 3
        assert results[0].status == CheckStatus.PASSED
        assert results[1].status == CheckStatus.FAILED
        assert results[2].status == CheckStatus.SKIPPED


class TestBuildReport:
    def test_all_pass(self):
        results = [
            CheckResult(id="a", status=CheckStatus.PASSED),
            CheckResult(id="b", status=CheckStatus.PASSED),
        ]
        report = build_report(results)
        assert report.passed == 2
        assert report.failed == 0
        assert report.ready is True
        assert "ready" in report.final_note.lower()

    def test_with_failures(self):
        results = [
            CheckResult(id="a", status=CheckStatus.FAILED),
            CheckResult(id="b", status=CheckStatus.PASSED),
        ]
        report = build_report(results)
        assert report.failed == 1
        assert report.passed == 1
        assert report.ready is False
        assert "verification issues" in report.final_note.lower()

    def test_with_warnings_and_skipped(self):
        results = [
            CheckResult(id="a", status=CheckStatus.WARNING),
            CheckResult(id="b", status=CheckStatus.SKIPPED),
        ]
        report = build_report(results)
        assert report.warnings == 1
        assert report.skipped == 1
        assert report.ready is True


class TestRenderReport:
    def test_output_format(self):
        results = [
            CheckResult(
                id="git", description="Git installed", status=CheckStatus.PASSED
            ),
            CheckResult(id="node", status=CheckStatus.FAILED, error="not found"),
        ]
        report = build_report(results)
        out = render_report(report)
        assert "[ok]" in out
        assert "[!!]" in out
        assert "git" in out
        assert "node" in out
        assert "not found" in out


class TestVerificationScenario:
    def test_run(self):
        checks = [Check(id="a", run=lambda: None)]
        scenario = VerificationScenario(name="test", checks=checks)
        report = scenario.run()
        assert isinstance(report, Report)
        assert report.passed == 1


class TestPostInstallVerifier:
    def test_verify_empty(self):
        verifier = PostInstallVerifier()
        report = verifier.verify_installation()
        assert report.passed == 0

    def test_run_all_with_scenario(self):
        checks = [Check(id="a", run=lambda: None)]
        scenario = VerificationScenario(name="test", checks=checks)
        verifier = PostInstallVerifier(scenarios=[scenario])
        report = verifier.run_all()
        assert report.passed == 1

    def test_add_scenario(self):
        scenario = VerificationScenario(name="test")
        verifier = PostInstallVerifier()
        verifier.add_scenario(scenario)
        assert len(verifier.scenarios) == 1


# ─── installcmd.py ───────────────────────────────────────────────────────────


class TestProfileResolverAgentInstall:
    def test_claude_code_default(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(
            os="darwin", package_manager="brew", npm_writable=True
        )
        cmds = resolver.resolve_agent_install(profile, AgentID.CLAUDE_CODE)
        assert cmds == [
            [
                "npm",
                "install",
                "-g",
                "--ignore-scripts",
                "@anthropic-ai/claude-code@2.1.140",
            ]
        ]

    def test_claude_code_linux_not_writable(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="linux", package_manager="apt", npm_writable=False)
        cmds = resolver.resolve_agent_install(profile, AgentID.CLAUDE_CODE)
        assert cmds == [
            [
                "sudo",
                "npm",
                "install",
                "-g",
                "--ignore-scripts",
                "@anthropic-ai/claude-code@2.1.140",
            ]
        ]

    def test_opencode_brew(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        cmds = resolver.resolve_agent_install(profile, AgentID.OPENCODE)
        assert cmds == [["brew", "install", "opencode"]]

    def test_opencode_apt_writable(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="linux", package_manager="apt", npm_writable=True)
        cmds = resolver.resolve_agent_install(profile, AgentID.OPENCODE)
        assert cmds == [
            ["npm", "install", "-g", "--ignore-scripts", "opencode-ai@1.14.48"]
        ]

    def test_opencode_unsupported_raises(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="linux", package_manager="apk")
        with pytest.raises(InstallError, match="unsupported platform for opencode"):
            resolver.resolve_agent_install(profile, AgentID.OPENCODE)

    def test_kilocode_default(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        cmds = resolver.resolve_agent_install(profile, AgentID.KILOCODE)
        assert cmds == [
            ["npm", "install", "-g", "--ignore-scripts", "@kilocode/cli@7.2.52"]
        ]

    def test_kimi(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="darwin", package_manager="brew", supported=True)
        cmds = resolver.resolve_agent_install(profile, AgentID.KIMI)
        assert cmds == [["uv", "tool", "install", "--python", "3.13", "kimi-cli"]]

    def test_kimi_unsupported(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="linux", supported=False)
        with pytest.raises(InstallError, match="not supported"):
            resolver.resolve_agent_install(profile, AgentID.KIMI)

    def test_unknown_agent_raises(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        with pytest.raises(InstallError, match="install command is not supported"):
            resolver.resolve_agent_install(profile, AgentID.CURSOR)


class TestProfileResolverComponentInstall:
    def test_engram_brew(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        cmds = resolver.resolve_component_install(profile, ComponentID.DXRK_MEMORY)
        assert len(cmds) == 2
        assert ["brew", "tap", "Dxrk777/homebrew-tap"] in cmds
        assert ["brew", "install", "dxrk-memory"] in cmds

    def test_engram_not_brew_raises(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="linux", package_manager="apt")
        with pytest.raises(InstallError, match="dxrk-memory on"):
            resolver.resolve_component_install(profile, ComponentID.DXRK_MEMORY)

    def test_gga_brew(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        cmds = resolver.resolve_component_install(profile, ComponentID.DXRK_GUARDIAN)
        assert ["brew", "reinstall", "dxrk-guardian"] in cmds

    def test_unknown_component_raises(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        with pytest.raises(InstallError, match="install command is not supported"):
            resolver.resolve_component_install(profile, ComponentID.THEME)


class TestProfileResolverDependencyInstall:
    def test_brew(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        cmds = resolver.resolve_dependency_install(profile, "git")
        assert cmds == [["brew", "install", "git"]]

    def test_apt(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="linux", package_manager="apt")
        cmds = resolver.resolve_dependency_install(profile, "curl")
        assert cmds == [["sudo", "apt-get", "install", "-y", "curl"]]

    def test_pacman(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="linux", package_manager="pacman")
        cmds = resolver.resolve_dependency_install(profile, "git")
        assert cmds == [["sudo", "pacman", "-S", "--noconfirm", "git"]]

    def test_dnf(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="linux", package_manager="dnf")
        cmds = resolver.resolve_dependency_install(profile, "git")
        assert cmds == [["sudo", "dnf", "install", "-y", "git"]]

    def test_winget(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="windows", package_manager="winget")
        cmds = resolver.resolve_dependency_install(profile, "Git.Git")
        assert "winget" in cmds[0][0]

    def test_empty_dependency_raises(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        with pytest.raises(InstallError, match="dependency name is required"):
            resolver.resolve_dependency_install(profile, "")

    def test_unsupported_pm_raises(self):
        resolver = ProfileResolver()
        profile = PlatformProfile(os="linux", package_manager="apk")
        with pytest.raises(InstallError, match="unsupported package manager"):
            resolver.resolve_dependency_install(profile, "git")


class TestNewResolver:
    def test_returns_profile_resolver(self):
        resolver = new_resolver()
        assert isinstance(resolver, ProfileResolver)


class TestValidateAgentInstallPreflight:
    def test_kimi_with_uv(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: "/usr/bin/uv")
        profile = PlatformProfile(os="darwin", package_manager="brew", supported=True)
        validate_agent_install_preflight(profile, AgentID.KIMI)

    def test_kimi_without_uv(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: None)
        profile = PlatformProfile(os="darwin", package_manager="brew", supported=True)
        with pytest.raises(InstallError, match="requires Astral uv"):
            validate_agent_install_preflight(profile, AgentID.KIMI)

    def test_non_kimi_skips(self):
        profile = PlatformProfile(os="darwin", package_manager="brew")
        validate_agent_install_preflight(profile, AgentID.CLAUDE_CODE)


class TestValidateGoForModuleInstall:
    def test_go_not_found(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: None)
        profile = PlatformProfile(os="linux", package_manager="apt")
        with pytest.raises(InstallError, match="required to install DxrkMemory"):
            validate_go_for_module_install(profile)

    def test_go_version_ok(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: "/usr/bin/go")
        monkeypatch.setattr(
            "dxrk.installcmd._get_go_version_output",
            lambda: "go version go1.24.0 linux/amd64",
        )
        monkeypatch.setattr("dxrk.installcmd._os_getenv", lambda k: None)
        profile = PlatformProfile(os="linux", package_manager="apt")

        validate_go_for_module_install(profile)

    def test_go_version_too_low(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: "/usr/bin/go")
        monkeypatch.setattr(
            "dxrk.installcmd._get_go_version_output",
            lambda: "go version go1.23.0 linux/amd64",
        )
        monkeypatch.setattr("dxrk.installcmd._os_getenv", lambda k: None)
        profile = PlatformProfile(os="linux", package_manager="apt")
        with pytest.raises(InstallError, match="found go1.23"):
            validate_go_for_module_install(profile)

    def test_go_module_off(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: "/usr/bin/go")
        monkeypatch.setattr(
            "dxrk.installcmd._get_go_version_output",
            lambda: "go version go1.24.0 linux/amd64",
        )
        monkeypatch.setattr("dxrk.installcmd._os_getenv", lambda k: "off")
        profile = PlatformProfile(os="linux", package_manager="apt")
        with pytest.raises(InstallError, match="go modules are disabled"):
            validate_go_for_module_install(profile)


class TestGitBashPath:
    def test_fallback_when_git_not_found(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: None)
        monkeypatch.setattr("dxrk.installcmd._file_exists", lambda _: False)
        path = git_bash_path()
        assert path == "bash"

    def test_uses_candidate_path(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: "/usr/bin/git")
        monkeypatch.setattr(
            "dxrk.installcmd._file_exists",
            lambda p: "/usr/bin/bash.exe" in p or "/usr/bin/bash" in p,
        )
        path = git_bash_path()
        assert path != ""

import sys

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific paths")
