# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from dxrk.update import (
    InstallMethod,
    ManualFallbackError,
    ToolInfo,
    ToolUpgradeResult,
    ToolUpgradeStatus,
    UpdateResult,
    UpdateStatus,
    UpgradeReport,
)
from dxrk.update import (
    _detect_command_hint,
    _detect_npm_package_version,
    _DXRK_MEMORY_hint,
    _execute_one,
    _dxrk_hint,
    _DXRK_GUARDIAN_hint,
    _go_arch,
    _install_script_url,
    _look_path,
    _opencode_manual_hint,
    _opencode_pm_from_metadata,
    _opencode_plugin_registered_or_materialized,
    _parse_version_parts,
    _resolve_asset_url,
    _select_opencode_package_manager,
    _status_icon,
    as_manual_fallback,
    check_failures,
    compare_versions,
    detect_installed_version,
    effective_method,
    enumerate_files_in_dir,
    has_check_failures,
    has_updates,
    is_semver,
    normalize_version,
    parse_version_from_output,
    render_cli,
    render_upgrade_report,
    update_hint,
    update_summary_line,
    upgrade_icon,
)


class TestDataclasses:
    def test_tool_info_defaults(self):
        t = ToolInfo()
        assert t.name == ""

    def test_update_result_defaults(self):
        r = UpdateResult()
        assert r.status == UpdateStatus.UP_TO_DATE
        assert r.installed_version == ""

    def test_tool_upgrade_result_defaults(self):
        r = ToolUpgradeResult()
        assert r.status == ToolUpgradeStatus.SKIPPED

    def test_upgrade_report_defaults(self):
        r = UpgradeReport()
        assert r.dry_run is False
        assert r.results == []

    def test_manual_fallback_error(self):
        e = ManualFallbackError("some hint")
        assert e.hint == "some hint"
        assert str(e) == "some hint"


class TestParseVersionParts:
    def test_full(self):
        assert _parse_version_parts("1.2.3") == [1, 2, 3]

    def test_two_parts(self):
        assert _parse_version_parts("1.2") == [1, 2, 0]

    def test_one_part(self):
        assert _parse_version_parts("5") == [5, 0, 0]

    def test_non_numeric(self):
        assert _parse_version_parts("a.b.c") == [0, 0, 0]

    def test_mixed(self):
        assert _parse_version_parts("1.x.3") == [1, 0, 3]


class TestNormalizeVersion:
    def test_strips_v_prefix(self):
        assert normalize_version("v1.2.3") == "1.2.3"

    def test_strips_whitespace(self):
        assert normalize_version("  1.2.3  ") == "1.2.3"

    def test_extracts_semver_from_string(self):
        assert normalize_version("dxrk version 0.1.55") == "0.1.55"

    def test_dev_returns_raw(self):
        assert normalize_version("dev") == "dev"

    def test_dev_with_v(self):
        assert normalize_version("vdev") == "dev"

    def test_empty_returns_empty(self):
        assert normalize_version("") == ""


class TestIsSemver:
    def test_valid(self):
        assert is_semver("1.2.3") is True
        assert is_semver("0.0.1") is True

    def test_invalid(self):
        assert is_semver("dev") is False
        assert is_semver("abc") is False
        assert is_semver("") is False


class TestCompareVersions:
    def test_local_newer(self):
        assert compare_versions("2.0.0", "1.0.0") == UpdateStatus.UP_TO_DATE

    def test_remote_newer(self):
        assert compare_versions("1.0.0", "2.0.0") == UpdateStatus.UPDATE_AVAILABLE

    def test_equal(self):
        assert compare_versions("1.2.3", "1.2.3") == UpdateStatus.UP_TO_DATE

    def test_patch_ahead(self):
        assert compare_versions("1.2.4", "1.2.3") == UpdateStatus.UP_TO_DATE

    def test_patch_behind(self):
        assert compare_versions("1.2.3", "1.2.4") == UpdateStatus.UPDATE_AVAILABLE

    def test_minor_behind(self):
        assert compare_versions("1.1.0", "1.2.0") == UpdateStatus.UPDATE_AVAILABLE

    def test_major_ahead(self):
        assert compare_versions("3.0.0", "2.9.9") == UpdateStatus.UP_TO_DATE


class TestParseVersionFromOutput:
    def test_empty(self):
        assert parse_version_from_output("") == ""

    def test_dev_output(self):
        assert parse_version_from_output("dxrk dev (abc123)") == "dev"

    def test_dev_only(self):
        assert parse_version_from_output("dev") == "dev"

    def test_semver(self):
        assert parse_version_from_output("dxrk v0.1.55") == "0.1.55"

    def test_no_match(self):
        assert parse_version_from_output("not a version") == ""


class TestAsManualFallback:
    def test_with_manual_fallback(self):
        err = ManualFallbackError("do it manually")
        hint, ok = as_manual_fallback(err)
        assert hint == "do it manually"
        assert ok is True

    def test_with_other_exception(self):
        err = RuntimeError("something else")
        hint, ok = as_manual_fallback(err)
        assert hint == ""
        assert ok is False


class TestLookPath:
    @patch("dxrk.update.shutil.which", return_value="/usr/bin/python3")
    def test_finds(self, mock_which):
        assert _look_path("python3") == "/usr/bin/python3"

    @patch("dxrk.update.shutil.which", return_value=None)
    def test_not_found(self, mock_which):
        assert _look_path("nonexistent") is None


class TestDetectNpmPackageVersion:
    def test_returns_version_from_package_json(self, tmp_path):
        home = str(tmp_path)
        pkg_dir = tmp_path / ".config" / "opencode" / "node_modules" / "test-pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.json").write_text(json.dumps({"version": "2.1.0"}))

        with patch("dxrk.update.os.path.expanduser", return_value=home):
            assert _detect_npm_package_version("test-pkg") == "2.1.0"

    def test_returns_empty_when_no_package_json(self, tmp_path):
        home = str(tmp_path)
        with patch("dxrk.update.os.path.expanduser", return_value=home):
            assert _detect_npm_package_version("nonexistent") == ""

    def test_returns_empty_on_invalid_json(self, tmp_path):
        home = str(tmp_path)
        pkg_dir = tmp_path / ".config" / "opencode" / "node_modules" / "bad"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.json").write_text("not json")

        with patch("dxrk.update.os.path.expanduser", return_value=home):
            assert _detect_npm_package_version("bad") == ""

    def test_returns_empty_when_home_not_resolved(self):
        with patch("dxrk.update.os.path.expanduser", return_value="~"):
            assert _detect_npm_package_version("pkg") == ""


class TestStatusIcon:
    def test_all_statuses(self):
        assert _status_icon(UpdateStatus.UP_TO_DATE) == "[ok]"
        assert _status_icon(UpdateStatus.UPDATE_AVAILABLE) == "[UP]"
        assert _status_icon(UpdateStatus.NOT_INSTALLED) == "[--]"
        assert _status_icon(UpdateStatus.VERSION_UNKNOWN) == "[??]"
        assert _status_icon(UpdateStatus.CHECK_FAILED) == "[!!]"
        assert _status_icon(UpdateStatus.DEV_BUILD) == "[dev]"

    def test_unknown_status(self):
        assert _status_icon("unknown") == "[  ]"


class TestUpgradeIcon:
    def test_all_statuses(self):
        assert upgrade_icon(ToolUpgradeStatus.SUCCEEDED) == "[ok]"
        assert upgrade_icon(ToolUpgradeStatus.FAILED) == "[!!]"
        assert upgrade_icon(ToolUpgradeStatus.SKIPPED) == "[--]"

    def test_unknown(self):
        assert upgrade_icon("unknown") == "[  ]"


class TestDxrkHint:
    def test_darwin(self):
        p = MagicMock()
        p.os = "darwin"
        assert _dxrk_hint(p) == "brew upgrade dxrk"

    def test_linux(self):
        p = MagicMock()
        p.os = "linux"
        assert "curl -fsSL" in _dxrk_hint(p)

    def test_windows(self):
        p = MagicMock()
        p.os = "windows"
        assert "irm" in _dxrk_hint(p)

    def test_unknown_os(self):
        p = MagicMock()
        p.os = "freebsd"
        assert _dxrk_hint(p) == ""


class TestEngramHint:
    def test_brew(self):
        p = MagicMock()
        p.package_manager = "brew"
        assert _DXRK_MEMORY_hint(p) == "brew upgrade DXRK_MEMORY"

    def test_not_brew(self):
        p = MagicMock()
        p.package_manager = "apt"
        assert "dxrk upgrade" in _DXRK_MEMORY_hint(p)


class TestGgaHint:
    def test_brew(self):
        p = MagicMock()
        p.package_manager = "brew"
        assert _DXRK_GUARDIAN_hint(p) == "brew upgrade DXRK_GUARDIAN"

    def test_not_brew(self):
        p = MagicMock()
        p.package_manager = "apt"
        assert "github.com" in _DXRK_GUARDIAN_hint(p)


class TestUpdateHint:
    def test_dxrk_hint(self):
        p = MagicMock()
        p.os = "darwin"
        p.package_manager = "brew"
        t = ToolInfo(name="dxrk")
        assert "brew upgrade dxrk" in update_hint(t, p)

    def test_engram(self):
        p = MagicMock()
        p.package_manager = "brew"
        t = ToolInfo(name="DXRK_MEMORY")
        assert update_hint(t, p) == "brew upgrade DXRK_MEMORY"

    def test_opencode_plugin(self):
        p = MagicMock()
        t = ToolInfo(name="opencode-subagent-statusline")
        assert "Restart/reload" in update_hint(t, p)

    def test_unknown_tool(self):
        p = MagicMock()
        t = ToolInfo(name="unknown-tool")
        assert update_hint(t, p) == ""


class TestEffectiveMethod:
    def test_opencode_plugin(self):
        p = MagicMock()
        t = ToolInfo(name="x", install_method=InstallMethod.OPENCODE_PLUGIN)
        assert effective_method(t, p) == InstallMethod.OPENCODE_PLUGIN

    def test_brew_pm(self):
        p = MagicMock()
        p.package_manager = "brew"
        t = ToolInfo(name="x", install_method=InstallMethod.BINARY)
        assert effective_method(t, p) == InstallMethod.BREW

    def test_uses_tool_default(self):
        p = MagicMock()
        p.package_manager = "apt"
        t = ToolInfo(name="x", install_method=InstallMethod.GO_INSTALL)
        assert effective_method(t, p) == InstallMethod.GO_INSTALL


class TestGoArch:
    def test_amd64(self):
        with patch("os.uname") as m:
            m.return_value.machine = "x86_64"
            assert _go_arch() == "amd64"

    def test_arm64(self):
        with patch("os.uname") as m:
            m.return_value.machine = "aarch64"
            assert _go_arch() == "arm64"

    def test_passthrough(self):
        with patch("os.uname") as m:
            m.return_value.machine = "riscv64"
            assert _go_arch() == "riscv64"


class TestInstallScriptUrl:
    def test_returns_raw_github_url(self):
        url = _install_script_url("owner", "repo")
        assert url == "https://raw.githubusercontent.com/owner/repo/main/install.sh"


class TestResolveAssetUrl:
    def test_linux_amd64(self):
        with patch("dxrk.update._go_arch", return_value="amd64"):
            url = _resolve_asset_url("o", "r", "1.0.0", "linux")
        assert "o/r/releases/download/v1.0.0/r_1.0.0_linux_amd64.tar.gz" in url


class TestDetectCommandHint:
    def test_no_detect_cmd(self):
        t = ToolInfo(name="my-tool")
        assert _detect_command_hint(t) == "my-tool"

    def test_with_cmd(self):
        t = ToolInfo(name="x", detect_cmd=["engram", "version"])
        assert _detect_command_hint(t) == "engram version"


class TestOpencodeManualHint:
    def test_uses_update_hint_when_set(self):
        r = UpdateResult()
        r.update_hint = "custom hint"
        assert _opencode_manual_hint(r) == "custom hint"

    def test_with_npm_package(self):
        r = UpdateResult()
        r.tool.npm_package = "my-plugin"
        r.update_hint = ""
        assert "my-plugin" in _opencode_manual_hint(r)

    def test_fallback(self):
        r = UpdateResult()
        r.tool.npm_package = ""
        r.update_hint = ""
        assert "tui.json" in _opencode_manual_hint(r)


class TestHasUpdates:
    def test_true_when_available(self):
        r = UpdateResult(status=UpdateStatus.UPDATE_AVAILABLE)
        assert has_updates([r]) is True

    def test_false_when_none(self):
        r = UpdateResult(status=UpdateStatus.UP_TO_DATE)
        assert has_updates([r]) is False

    def test_empty_list(self):
        assert has_updates([]) is False


class TestCheckFailures:
    def test_returns_failed_names(self):
        r1 = UpdateResult(tool=ToolInfo(name="a"), status=UpdateStatus.CHECK_FAILED)
        r2 = UpdateResult(tool=ToolInfo(name="b"), status=UpdateStatus.UP_TO_DATE)
        assert check_failures([r1, r2]) == ["a"]

    def test_empty(self):
        assert check_failures([]) == []


class TestHasCheckFailures:
    def test_true(self):
        r = UpdateResult(status=UpdateStatus.CHECK_FAILED)
        assert has_check_failures([r]) is True

    def test_false(self):
        r = UpdateResult(status=UpdateStatus.UP_TO_DATE)
        assert has_check_failures([r]) is False


class TestUpdateSummaryLine:
    def test_with_updates(self):
        r = UpdateResult(
            tool=ToolInfo(name="DXRK_MEMORY"),
            installed_version="1.0.0",
            latest_version="2.0.0",
            status=UpdateStatus.UPDATE_AVAILABLE,
        )
        result = update_summary_line([r])
        assert "DXRK_MEMORY" in result
        assert "1.0.0 -> 2.0.0" in result

    def test_no_updates(self):
        r = UpdateResult(status=UpdateStatus.UP_TO_DATE)
        assert update_summary_line([r]) == ""

    def test_mixed(self):
        r1 = UpdateResult(
            tool=ToolInfo(name="a"),
            installed_version="1",
            latest_version="2",
            status=UpdateStatus.UPDATE_AVAILABLE,
        )
        r2 = UpdateResult(tool=ToolInfo(name="b"), status=UpdateStatus.UP_TO_DATE)
        result = update_summary_line([r1, r2])
        assert "a" in result
        assert "b" not in result


class TestRenderCli:
    def test_all_up_to_date(self):
        r = UpdateResult(
            tool=ToolInfo(name="DXRK_MEMORY"), status=UpdateStatus.UP_TO_DATE
        )
        output = render_cli([r])
        assert "All tools are up to date!" in output
        assert "[ok]" in output

    def test_with_updates(self):
        r = UpdateResult(
            tool=ToolInfo(name="DXRK_MEMORY"),
            installed_version="1",
            latest_version="2",
            status=UpdateStatus.UPDATE_AVAILABLE,
            update_hint="brew upgrade engram",
        )
        output = render_cli([r])
        assert "update(s) available" in output
        assert "[UP]" in output
        assert "brew upgrade engram" in output

    def test_with_check_failures(self):
        r = UpdateResult(
            tool=ToolInfo(name="DXRK_MEMORY"),
            status=UpdateStatus.CHECK_FAILED,
        )
        output = render_cli([r])
        assert "check failed" in output
        assert "[!!]" in output

    def test_with_not_installed(self):
        r = UpdateResult(tool=ToolInfo(name="gga"), status=UpdateStatus.NOT_INSTALLED)
        output = render_cli([r])
        assert "[--]" in output

    def test_dev_build(self):
        r = UpdateResult(
            tool=ToolInfo(name="DXRK_MEMORY"), status=UpdateStatus.DEV_BUILD
        )
        output = render_cli([r])
        assert "[dev]" in output

    def test_empty_results(self):
        output = render_cli([])
        assert "All tools are up to date!" in output

    def test_mixed_status_summary(self):
        r1 = UpdateResult(
            tool=ToolInfo(name="a"),
            installed_version="1",
            latest_version="2",
            status=UpdateStatus.UPDATE_AVAILABLE,
            update_hint="hint",
        )
        r2 = UpdateResult(tool=ToolInfo(name="b"), status=UpdateStatus.CHECK_FAILED)
        output = render_cli([r1, r2])
        assert "update(s) available" in output
        assert "check(s) failed" in output


class TestRenderUpgradeReport:
    def test_dry_run_header(self):
        r = UpgradeReport(dry_run=True)
        assert "dry-run" in render_upgrade_report(r)

    def test_live_header(self):
        r = UpgradeReport(dry_run=False)
        assert "Upgrade" in render_upgrade_report(r)
        assert "dry-run" not in render_upgrade_report(r)

    def test_no_results(self):
        r = UpgradeReport()
        output = render_upgrade_report(r)
        assert "No upgrades available" in output

    def test_succeeded(self):
        r = UpgradeReport(
            results=[
                ToolUpgradeResult(
                    tool_name="DXRK_MEMORY",
                    old_version="1",
                    new_version="2",
                    status=ToolUpgradeStatus.SUCCEEDED,
                ),
            ]
        )
        output = render_upgrade_report(r)
        assert "succeeded" in output
        assert "1 → 2" in output

    def test_failed(self):
        r = UpgradeReport(
            results=[
                ToolUpgradeResult(
                    tool_name="DXRK_MEMORY",
                    status=ToolUpgradeStatus.FAILED,
                    err="permission denied",
                ),
            ]
        )
        output = render_upgrade_report(r)
        assert "FAILED" in output
        assert "permission denied" in output

    def test_skipped_manual_hint(self):
        r = UpgradeReport(
            results=[
                ToolUpgradeResult(
                    tool_name="DXRK_MEMORY",
                    status=ToolUpgradeStatus.SKIPPED,
                    manual_hint="download manually",
                ),
            ]
        )
        output = render_upgrade_report(r)
        assert "manual" in output
        assert "download manually" in output

    def test_skipped_dry_run(self):
        r = UpgradeReport(
            dry_run=True,
            results=[
                ToolUpgradeResult(
                    tool_name="DXRK_MEMORY",
                    old_version="1",
                    new_version="2",
                    status=ToolUpgradeStatus.SKIPPED,
                ),
            ],
        )
        output = render_upgrade_report(r)
        assert "dry-run" in output

    def test_backup_id(self):
        r = UpgradeReport(
            backup_id="backup-123",
            results=[
                ToolUpgradeResult(tool_name="x", status=ToolUpgradeStatus.SUCCEEDED),
            ],
        )
        output = render_upgrade_report(r)
        assert "backup-123" in output

    def test_backup_warning(self):
        r = UpgradeReport(
            backup_warning="no space",
            results=[
                ToolUpgradeResult(tool_name="x", status=ToolUpgradeStatus.SUCCEEDED),
            ],
        )
        output = render_upgrade_report(r)
        assert "WARNING" in output
        assert "no space" in output

    def test_actionable_count(self):
        r = UpgradeReport(
            dry_run=True,
            results=[
                ToolUpgradeResult(
                    tool_name="a",
                    old_version="1",
                    new_version="2",
                    status=ToolUpgradeStatus.SKIPPED,
                ),
            ],
        )
        output = render_upgrade_report(r)
        assert "pending" in output

    def test_no_actionable(self):
        r = UpgradeReport(
            dry_run=True,
            results=[
                ToolUpgradeResult(
                    tool_name="a",
                    status=ToolUpgradeStatus.SKIPPED,
                    manual_hint="do it yourself",
                ),
            ],
        )
        output = render_upgrade_report(r)
        assert "manual" in output

    def test_summary_line_live(self):
        r = UpgradeReport(
            results=[
                ToolUpgradeResult(tool_name="a", status=ToolUpgradeStatus.SUCCEEDED),
            ]
        )
        output = render_upgrade_report(r)
        assert "succeeded" in output


class TestOpencodePmFromMetadata:
    def test_package_json_bun(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"packageManager": "bun@1.2.0"}))
        assert _opencode_pm_from_metadata(str(tmp_path)) == "bun"

    def test_package_json_npm(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"packageManager": "npm@10.0.0"}))
        assert _opencode_pm_from_metadata(str(tmp_path)) == "npm"

    def test_bun_lock(self, tmp_path):
        (tmp_path / "bun.lockb").touch()
        assert _opencode_pm_from_metadata(str(tmp_path)) == "bun"

    def test_npm_lock(self, tmp_path):
        (tmp_path / "package-lock.json").touch()
        assert _opencode_pm_from_metadata(str(tmp_path)) == "npm"

    def test_no_metadata(self, tmp_path):
        assert _opencode_pm_from_metadata(str(tmp_path)) is None

    def test_no_dir(self, tmp_path):
        assert _opencode_pm_from_metadata(str(tmp_path / "nonexistent")) is None

    def test_bun_literal(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"packageManager": "bun"}))
        assert _opencode_pm_from_metadata(str(tmp_path)) == "bun"

    def test_npm_shrinkwrap(self, tmp_path):
        (tmp_path / "npm-shrinkwrap.json").touch()
        assert _opencode_pm_from_metadata(str(tmp_path)) == "npm"


class TestSelectOpencodePackageManager:
    @patch("dxrk.update._look_path", return_value=None)
    @patch("dxrk.update._opencode_pm_from_metadata", return_value=None)
    def test_none_available(self, mock_meta, mock_look):
        assert _select_opencode_package_manager("/x") is None

    @patch(
        "dxrk.update._look_path",
        side_effect=lambda p: f"/usr/bin/{p}" if p == "bun" else None,
    )
    @patch("dxrk.update._opencode_pm_from_metadata", return_value=None)
    def test_bun_found(self, mock_meta, mock_look):
        assert _select_opencode_package_manager("/x") == "bun"

    @patch(
        "dxrk.update._look_path",
        side_effect=lambda p: f"/usr/bin/{p}" if p == "npm" else None,
    )
    @patch("dxrk.update._opencode_pm_from_metadata", return_value=None)
    def test_npm_found(self, mock_meta, mock_look):
        assert _select_opencode_package_manager("/x") == "npm"

    @patch("dxrk.update._look_path", return_value="/usr/bin/bun")
    @patch("dxrk.update._opencode_pm_from_metadata", return_value="bun")
    def test_prefers_metadata(self, mock_meta, mock_look):
        assert _select_opencode_package_manager("/x") == "bun"


class TestOpencodePluginRegisteredOrMaterialized:
    def test_node_modules_exists(self, tmp_path):
        (tmp_path / "node_modules" / "my-pkg").mkdir(parents=True)
        assert (
            _opencode_plugin_registered_or_materialized(str(tmp_path), "my-pkg") is True
        )

    def test_registered_in_tui_json(self, tmp_path):
        tui = tmp_path / "tui.json"
        tui.write_text(json.dumps({"plugin": ["my-pkg"]}))
        assert (
            _opencode_plugin_registered_or_materialized(str(tmp_path), "my-pkg") is True
        )

    def test_not_found(self, tmp_path):
        assert (
            _opencode_plugin_registered_or_materialized(str(tmp_path), "no-pkg")
            is False
        )

    def test_invalid_tui_json(self, tmp_path):
        (tmp_path / "tui.json").write_text("bad json")
        assert (
            _opencode_plugin_registered_or_materialized(str(tmp_path), "pkg") is False
        )


class TestEnumerateFilesInDir:
    def test_returns_files(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("b")
        files = enumerate_files_in_dir(str(tmp_path), exclude_names=set())
        assert len(files) == 2

    def test_excludes_dirs(self, tmp_path):
        (tmp_path / "file.txt").write_text("")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "backups").mkdir()
        (sub / "backups" / "x.txt").write_text("")
        files = enumerate_files_in_dir(str(tmp_path))
        names = {os.path.basename(f) for f in files}
        assert "file.txt" in names
        assert "x.txt" not in names

    def test_skips_symlinks_to_dirs(self, tmp_path):
        target = tmp_path / "target"
        target.mkdir()
        link = tmp_path / "link"
        link.symlink_to(target, target_is_directory=True)
        files = enumerate_files_in_dir(str(tmp_path), exclude_names=set())
        assert len(files) == 0


class TestExecuteOne:
    def test_dry_run_skips(self):
        p = MagicMock()
        r = UpdateResult(
            tool=ToolInfo(name="test"),
            installed_version="1",
            latest_version="2",
            status=UpdateStatus.UPDATE_AVAILABLE,
        )
        result = _execute_one(r, p, dry_run=True)
        assert result.status == ToolUpgradeStatus.SKIPPED
        assert result.old_version == "1"
        assert result.new_version == "2"

    @patch("dxrk.update._run_strategy")
    def test_success(self, mock_strategy):
        p = MagicMock()
        r = UpdateResult(
            tool=ToolInfo(name="test", install_method=InstallMethod.BREW),
            installed_version="1",
            latest_version="2",
            status=UpdateStatus.UPDATE_AVAILABLE,
        )
        result = _execute_one(r, p, dry_run=False)
        assert result.status == ToolUpgradeStatus.SUCCEEDED

    @patch("dxrk.update._run_strategy", side_effect=RuntimeError("boom"))
    def test_failure(self, mock_strategy):
        p = MagicMock()
        r = UpdateResult(
            tool=ToolInfo(name="test"),
            installed_version="1",
            latest_version="2",
            status=UpdateStatus.UPDATE_AVAILABLE,
        )
        result = _execute_one(r, p, dry_run=False)
        assert result.status == ToolUpgradeStatus.FAILED
        assert "boom" in result.err

    @patch("dxrk.update._run_strategy", side_effect=ManualFallbackError("do it"))
    def test_manual_fallback(self, mock_strategy):
        p = MagicMock()
        r = UpdateResult(
            tool=ToolInfo(name="test"),
            installed_version="1",
            latest_version="2",
            status=UpdateStatus.UPDATE_AVAILABLE,
        )
        result = _execute_one(r, p, dry_run=False)
        assert result.status == ToolUpgradeStatus.SKIPPED
        assert result.manual_hint == "do it"


class TestEffectiveMethodEdgeCases:
    def test_opencode_plugin_preserved(self):
        p = MagicMock()
        p.package_manager = "brew"
        t = ToolInfo(name="x", install_method=InstallMethod.OPENCODE_PLUGIN)
        assert effective_method(t, p) == InstallMethod.OPENCODE_PLUGIN

    def test_script_not_overridden(self):
        p = MagicMock()
        p.package_manager = "brew"
        t = ToolInfo(name="gga", install_method=InstallMethod.SCRIPT)
        assert effective_method(t, p) == InstallMethod.BREW

    def test_binary_not_brew(self):
        p = MagicMock()
        p.package_manager = "apt"
        t = ToolInfo(name="x", install_method=InstallMethod.BINARY)
        assert effective_method(t, p) == InstallMethod.BINARY


class TestDetectInstalledVersion:
    @patch("dxrk.update._look_path", return_value=None)
    def test_returns_empty_when_binary_not_found(self, mock_look):
        t = ToolInfo(name="gga", detect_cmd=["gga", "--version"])
        assert detect_installed_version(t, "dev") == ""

    @patch("dxrk.update._look_path", return_value="/usr/bin/gga")
    @patch("dxrk.update.subprocess.run")
    def test_returns_version_from_subprocess(self, mock_run, mock_look):
        mock_run.return_value = MagicMock(returncode=0, stdout="gga v1.2.3\n")
        t = ToolInfo(name="gga", detect_cmd=["gga", "--version"])
        assert detect_installed_version(t, "dev") == "1.2.3"

    @patch("dxrk.update._look_path", return_value="/usr/bin/gga")
    @patch("dxrk.update.subprocess.run")
    def test_returns_empty_on_nonzero_returncode(self, mock_run, mock_look):
        mock_run.return_value = MagicMock(returncode=1, stdout="error\n")
        t = ToolInfo(name="gga", detect_cmd=["gga", "--version"])
        assert detect_installed_version(t, "dev") == ""

    @patch("dxrk.update._look_path", return_value="/usr/bin/gga")
    @patch("dxrk.update.subprocess.run", side_effect=FileNotFoundError)
    def test_handles_file_not_found(self, mock_run, mock_look):
        t = ToolInfo(name="gga", detect_cmd=["gga", "--version"])
        assert detect_installed_version(t, "dev") == ""

    @patch("dxrk.update._look_path", return_value="/usr/bin/gga")
    @patch(
        "dxrk.update.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 10)
    )
    def test_handles_timeout(self, mock_run, mock_look):
        t = ToolInfo(name="gga", detect_cmd=["gga", "--version"])
        assert detect_installed_version(t, "dev") == ""

    def test_returns_build_version_when_detect_cmd_none(self):
        t = ToolInfo(name="dxrk", detect_cmd=None)
        assert detect_installed_version(t, "0.1.55") == "0.1.55"

    def test_returns_empty_when_detect_cmd_empty(self):
        t = ToolInfo(name="test", detect_cmd=[])
        assert detect_installed_version(t, "dev") == ""

    def test_npm_package(self, tmp_path):
        home = str(tmp_path)
        pkg_dir = tmp_path / ".config" / "opencode" / "node_modules" / "plugin"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.json").write_text(json.dumps({"version": "3.0.0"}))

        with patch("dxrk.update.os.path.expanduser", return_value=home):
            t = ToolInfo(name="plugin", npm_package="plugin")
            assert detect_installed_version(t, "dev") == "3.0.0"

    def test_detect_version_from_output_returns_empty_on_failed_run(self, tmp_path):
        # detect_cmd is not None and not empty, but subprocess raises FileNotFoundError
        t = ToolInfo(name="gga", detect_cmd=["gga", "--version"])
        with patch("dxrk.update._look_path", side_effect=[None]):
            assert detect_installed_version(t, "dev") == ""


class TestResolveGithubToken:
    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghs_xxxx"}, clear=True)
    def test_uses_github_token_env(self):
        from dxrk.update import _resolve_github_token

        assert _resolve_github_token() == "ghs_xxxx"

    @patch.dict(os.environ, {"GH_TOKEN": "gho_yyyy"}, clear=True)
    def test_uses_gh_token_env(self):
        from dxrk.update import _resolve_github_token

        assert _resolve_github_token() == "gho_yyyy"

    @patch.dict(os.environ, {}, clear=True)
    @patch("dxrk.update._look_path", return_value="/usr/bin/gh")
    @patch("dxrk.update.subprocess.run")
    def test_uses_gh_auth_token(self, mock_run, mock_look):
        mock_run.return_value = MagicMock(returncode=0, stdout="ghs_zzzz\n")
        from dxrk.update import _resolve_github_token

        assert _resolve_github_token() == "ghs_zzzz"

    @patch.dict(os.environ, {}, clear=True)
    @patch("dxrk.update._look_path", return_value=None)
    def test_returns_empty_when_no_source(self, mock_look):
        from dxrk.update import _resolve_github_token

        assert _resolve_github_token() == ""


class TestFetchLatestRelease:
    @patch("dxrk.update.urllib.request.urlopen")
    @patch("dxrk.update._resolve_github_token", return_value="")
    def test_returns_release(self, mock_token, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {
                "tag_name": "v1.2.3",
                "html_url": "https://github.com/o/r/releases/tag/v1.2.3",
            }
        ).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        from dxrk.update import fetch_latest_release

        rel = fetch_latest_release("o", "r")
        assert rel.tag_name == "v1.2.3"
        assert rel.html_url == "https://github.com/o/r/releases/tag/v1.2.3"

    @patch(
        "dxrk.update.urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            "/url",
            403,
            "Forbidden",
            {},
            None,
        ),
    )
    @patch("dxrk.update._resolve_github_token", return_value="")
    def test_http_403_raises_rate_limit(self, mock_token, mock_urlopen):
        import urllib.error
        from dxrk.update import fetch_latest_release

        with pytest.raises(RuntimeError, match="rate limit"):
            fetch_latest_release("o", "r")

    @patch(
        "dxrk.update.urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            "/url",
            404,
            "Not Found",
            {},
            None,
        ),
    )
    @patch("dxrk.update._resolve_github_token", return_value="")
    def test_http_404_raises_no_releases(self, mock_token, mock_urlopen):
        import urllib.error
        from dxrk.update import fetch_latest_release

        with pytest.raises(RuntimeError, match="No releases"):
            fetch_latest_release("o", "r")

    @patch(
        "dxrk.update.urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            "/url",
            500,
            "Server Error",
            {},
            None,
        ),
    )
    @patch("dxrk.update._resolve_github_token", return_value="")
    def test_http_other_raises(self, mock_token, mock_urlopen):
        import urllib.error
        from dxrk.update import fetch_latest_release

        with pytest.raises(RuntimeError, match="HTTP 500"):
            fetch_latest_release("o", "r")


class TestCheckSingleTool:
    @patch("dxrk.update.detect_installed_version", return_value="1.0.0")
    @patch("dxrk.update.fetch_latest_release")
    def test_up_to_date(self, mock_fetch, mock_detect):
        mock_fetch.return_value = MagicMock(tag_name="v1.0.0", html_url="")
        p = MagicMock()
        t = ToolInfo(name="DXRK_MEMORY", detect_cmd=["engram", "version"])
        from dxrk.update import _check_single_tool

        result = _check_single_tool(t, "dev", p)
        assert result.status == UpdateStatus.UP_TO_DATE

    @patch("dxrk.update.detect_installed_version", return_value="1.0.0")
    @patch("dxrk.update.fetch_latest_release")
    def test_update_available(self, mock_fetch, mock_detect):
        mock_fetch.return_value = MagicMock(tag_name="v2.0.0", html_url="")
        p = MagicMock()
        t = ToolInfo(name="DXRK_MEMORY", detect_cmd=["engram", "version"])
        from dxrk.update import _check_single_tool

        result = _check_single_tool(t, "dev", p)
        assert result.status == UpdateStatus.UPDATE_AVAILABLE

    @patch("dxrk.update.detect_installed_version", return_value="dev")
    @patch("dxrk.update.fetch_latest_release")
    def test_dev_build(self, mock_fetch, mock_detect):
        mock_fetch.return_value = MagicMock(tag_name="v2.0.0", html_url="")
        p = MagicMock()
        t = ToolInfo(name="DXRK_MEMORY", detect_cmd=["engram", "version"])
        from dxrk.update import _check_single_tool

        result = _check_single_tool(t, "dev", p)
        assert result.status == UpdateStatus.DEV_BUILD

    @patch("dxrk.update.detect_installed_version", return_value="")
    @patch("dxrk.update.fetch_latest_release")
    @patch("dxrk.update._look_path", return_value=None)
    def test_not_installed(self, mock_look, mock_fetch, mock_detect):
        mock_fetch.return_value = MagicMock(tag_name="v2.0.0", html_url="")
        p = MagicMock()
        t = ToolInfo(name="DXRK_MEMORY", detect_cmd=["engram", "version"])
        from dxrk.update import _check_single_tool

        result = _check_single_tool(t, "dev", p)
        assert result.status == UpdateStatus.NOT_INSTALLED

    @patch("dxrk.update.detect_installed_version", return_value="")
    @patch("dxrk.update.fetch_latest_release")
    def test_version_unknown_when_detect_cmd_none(self, mock_fetch, mock_detect):
        mock_fetch.return_value = MagicMock(tag_name="v2.0.0", html_url="")
        p = MagicMock()
        t = ToolInfo(name="dxrk", detect_cmd=None)
        from dxrk.update import _check_single_tool

        result = _check_single_tool(t, "dev", p)
        assert result.status == UpdateStatus.VERSION_UNKNOWN

    @patch("dxrk.update.detect_installed_version", return_value="")
    @patch("dxrk.update.fetch_latest_release")
    def test_version_unknown_when_binary_not_found(self, mock_fetch, mock_detect):
        mock_fetch.return_value = MagicMock(tag_name="v2.0.0", html_url="")
        p = MagicMock()
        t = ToolInfo(name="DXRK_MEMORY", detect_cmd=["engram", "version"])
        from dxrk.update import _check_single_tool

        with patch("dxrk.update._look_path", return_value="/usr/bin/engram"):
            result = _check_single_tool(t, "dev", p)
            assert result.status == UpdateStatus.VERSION_UNKNOWN

    @patch("dxrk.update.detect_installed_version", return_value="abc")
    @patch("dxrk.update.fetch_latest_release")
    def test_version_unknown_when_not_semver(self, mock_fetch, mock_detect):
        mock_fetch.return_value = MagicMock(tag_name="v2.0.0", html_url="")
        p = MagicMock()
        t = ToolInfo(name="DXRK_MEMORY", detect_cmd=["engram", "version"])
        from dxrk.update import _check_single_tool

        result = _check_single_tool(t, "dev", p)
        assert result.status == UpdateStatus.VERSION_UNKNOWN

    @patch("dxrk.update.detect_installed_version", return_value="1.0.0")
    @patch(
        "dxrk.update.fetch_latest_release", side_effect=RuntimeError("GitHub API error")
    )
    def test_check_failed_on_fetch_error(self, mock_fetch, mock_detect):
        p = MagicMock()
        t = ToolInfo(name="DXRK_MEMORY", detect_cmd=["engram", "version"])
        from dxrk.update import _check_single_tool

        result = _check_single_tool(t, "dev", p)
        assert result.status == UpdateStatus.CHECK_FAILED
        assert "GitHub API error" in result.err

    @patch("dxrk.update.detect_installed_version", return_value="")
    @patch("dxrk.update.fetch_latest_release")
    def test_npm_tool_not_installed(self, mock_fetch, mock_detect):
        mock_fetch.return_value = MagicMock(tag_name="v2.0.0", html_url="")
        p = MagicMock()
        t = ToolInfo(name="plugin", npm_package="my-plugin", detect_cmd=None)
        from dxrk.update import _check_single_tool

        result = _check_single_tool(t, "dev", p)
        assert result.status == UpdateStatus.NOT_INSTALLED


class TestDetectInstalledVersionWithNpm:
    def test_npm_detection(self, tmp_path):
        home = str(tmp_path)
        pkg_dir = tmp_path / ".config" / "opencode" / "node_modules" / "test-pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}))

        with patch("dxrk.update.os.path.expanduser", return_value=home):
            t = ToolInfo(name="plugin", npm_package="test-pkg")
            from dxrk.update import detect_installed_version

            assert detect_installed_version(t, "dev") == "1.2.3"


class TestDetectInstalledVersionSubprocessError:
    @patch("dxrk.update._look_path", return_value="/usr/bin/engram")
    @patch(
        "dxrk.update.subprocess.run",
        side_effect=subprocess.TimeoutExpired("engram version", 10),
    )
    def test_timeout_returns_empty(self, mock_run, mock_look):
        t = ToolInfo(name="DXRK_MEMORY", detect_cmd=["engram", "version"])
        from dxrk.update import detect_installed_version

        assert detect_installed_version(t, "dev") == ""


class TestResolveGithubTokenGHEnvFallback:
    @patch.dict(os.environ, {"GH_TOKEN": "gho_from_env"}, clear=True)
    def test_reads_gh_token_env(self):
        from dxrk.update import _resolve_github_token

        assert _resolve_github_token() == "gho_from_env"


class TestCheckAll:
    @patch("dxrk.update.check_filtered")
    def test_check_all_delegates(self, mock_filtered):
        mock_filtered.return_value = []
        from dxrk.update import check_all

        p = MagicMock()
        result = check_all("dev", p)
        mock_filtered.assert_called_once_with("dev", p, None)
        assert result == []


class TestCheckFiltered:
    @patch("dxrk.update._check_single_tool")
    @patch("dxrk.update.Tools", [ToolInfo(name="a"), ToolInfo(name="b")])
    def test_filters_by_tool_names(self, mock_single):
        mock_single.return_value = UpdateResult(
            tool=ToolInfo(name="a"), status=UpdateStatus.UP_TO_DATE
        )
        from dxrk.update import check_filtered

        p = MagicMock()
        result = check_filtered("dev", p, ["a"])
        assert len(result) == 1
        assert result[0].tool.name == "a"

    @patch("dxrk.update._check_single_tool")
    @patch("dxrk.update.Tools", [ToolInfo(name="a"), ToolInfo(name="b")])
    def test_no_filter_checks_all(self, mock_single):
        mock_single.return_value = UpdateResult(
            tool=ToolInfo(name="x"), status=UpdateStatus.UP_TO_DATE
        )
        from dxrk.update import check_filtered

        p = MagicMock()
        result = check_filtered("dev", p, None)
        assert len(result) == 2


class TestFetchLatestReleaseWithToken:
    @patch("dxrk.update.urllib.request.urlopen")
    @patch("dxrk.update._resolve_github_token", return_value="ghs_token123")
    def test_includes_token_in_header(self, mock_token, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"tag_name": "v1.0.0", "html_url": ""}
        ).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        from dxrk.update import fetch_latest_release

        rel = fetch_latest_release("o", "r")
        assert rel.tag_name == "v1.0.0"
        # Verify auth header was set
        call_args = mock_urlopen.call_args[0][0]
        assert call_args.get_header("Authorization") == "Bearer ghs_token123"
