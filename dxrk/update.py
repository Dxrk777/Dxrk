# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Optional, TextIO

from dxrk.system import PlatformProfile

logger = logging.getLogger(__name__)

# Types


class UpdateStatus(str, Enum):
    UP_TO_DATE = "up-to-date"
    UPDATE_AVAILABLE = "update-available"
    NOT_INSTALLED = "not-installed"
    VERSION_UNKNOWN = "version-unknown"
    CHECK_FAILED = "check-failed"
    DEV_BUILD = "dev-build"


class InstallMethod(str, Enum):
    BREW = "brew"
    GO_INSTALL = "go-install"
    BINARY = "binary"
    SCRIPT = "script"
    OPENCODE_PLUGIN = "opencode-plugin"


@dataclass
class ToolInfo:
    name: str = ""
    owner: str = ""
    repo: str = ""
    detect_cmd: list[str] | None = None
    version_prefix: str = ""
    install_method: InstallMethod = InstallMethod.BINARY
    go_import_path: str = ""
    npm_package: str = ""


@dataclass
class UpdateResult:
    tool: ToolInfo = field(default_factory=ToolInfo)
    installed_version: str = ""
    latest_version: str = ""
    status: UpdateStatus = UpdateStatus.UP_TO_DATE
    release_url: str = ""
    update_hint: str = ""
    err: str = ""


@dataclass
class GitHubRelease:
    tag_name: str = ""
    html_url: str = ""


class ToolUpgradeStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ManualFallbackError(Exception):
    def __init__(self, hint: str = "") -> None:
        self.hint = hint
        super().__init__(hint)


def as_manual_fallback(err: Exception) -> tuple[str, bool]:
    if isinstance(err, ManualFallbackError):
        return err.hint, True
    return "", False


@dataclass
class ToolUpgradeResult:
    tool_name: str = ""
    old_version: str = ""
    new_version: str = ""
    method: InstallMethod = InstallMethod.BINARY
    status: ToolUpgradeStatus = ToolUpgradeStatus.SKIPPED
    err: str = ""
    manual_hint: str = ""


@dataclass
class UpgradeReport:
    backup_id: str = ""
    backup_warning: str = ""
    results: list[ToolUpgradeResult] = field(default_factory=list)
    dry_run: bool = False


# Registry

Tools: list[ToolInfo] = [
    ToolInfo(
        name="gentle-ai",
        owner="Dxrk777",
        repo="gentle-ai",
        detect_cmd=None,
        version_prefix="v",
        install_method=InstallMethod.BINARY,
    ),
    ToolInfo(
        name="engram",
        owner="Dxrk777",
        repo="engram",
        detect_cmd=["engram", "version"],
        version_prefix="v",
        install_method=InstallMethod.BINARY,
    ),
    ToolInfo(
        name="gga",
        owner="Dxrk777",
        repo="gentleman-guardian-angel",
        detect_cmd=["gga", "--version"],
        version_prefix="v",
        install_method=InstallMethod.SCRIPT,
    ),
    ToolInfo(
        name="opencode-subagent-statusline",
        owner="Dxrk777",
        repo="sub-agent-statusline",
        version_prefix="v",
        install_method=InstallMethod.OPENCODE_PLUGIN,
        npm_package="opencode-subagent-statusline",
    ),
    ToolInfo(
        name="opencode-sdd-engram-manage",
        owner="Dxrk777",
        repo="sdd-engram-plugin",
        version_prefix="v",
        install_method=InstallMethod.OPENCODE_PLUGIN,
        npm_package="opencode-sdd-engram-manage",
    ),
]


# Version helpers

_version_regex = re.compile(r"(\d+\.\d+(?:\.\d+)?)")
_dev_version_regex = re.compile(r"(?i)(?:^|\s)dev(?:$|\s)")


def normalize_version(raw: str) -> str:
    raw = raw.strip().lstrip("v")
    m = _version_regex.search(raw)
    return m.group(1) if m else raw


def is_semver(v: str) -> bool:
    return bool(_version_regex.search(v))


def compare_versions(local: str, remote: str) -> UpdateStatus:
    local_parts = _parse_version_parts(local)
    remote_parts = _parse_version_parts(remote)
    for i in range(3):
        if local_parts[i] > remote_parts[i]:
            return UpdateStatus.UP_TO_DATE
        if local_parts[i] < remote_parts[i]:
            return UpdateStatus.UPDATE_AVAILABLE
    return UpdateStatus.UP_TO_DATE


def _parse_version_parts(version: str) -> list[int]:
    parts = version.split(".")
    result = [0, 0, 0]
    for i in range(min(3, len(parts))):
        try:
            result[i] = int(parts[i])
        except ValueError:
            pass
    return result


# Detection


def _look_path(name: str) -> str | None:
    return shutil.which(name)


def detect_installed_version(
    tool: ToolInfo, current_build_version: str, timeout: int = 10
) -> str:
    npm = tool.npm_package.strip()
    if npm:
        return _detect_npm_package_version(npm)

    if tool.detect_cmd is None:
        return current_build_version

    if not tool.detect_cmd:
        return ""

    binary = tool.detect_cmd[0]
    if not _look_path(binary):
        return ""

    try:
        result = subprocess.run(
            tool.detect_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

    return parse_version_from_output(result.stdout.strip())


def _detect_npm_package_version(pkg: str) -> str:
    home = os.path.expanduser("~")
    if not home or home == "~":
        return ""
    pkg_json = os.path.join(
        home, ".config", "opencode", "node_modules", pkg, "package.json"
    )
    try:
        with open(pkg_json) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""
    version = data.get("version", "")
    return parse_version_from_output(version)


def parse_version_from_output(output: str) -> str:
    if not output:
        return ""
    if _dev_version_regex.search(output):
        return "dev"
    m = _version_regex.search(output)
    return m.group(1) if m else ""


# GitHub API


def _resolve_github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    token = os.environ.get("GH_TOKEN", "").strip()
    if token:
        return token
    gh_path = _look_path("gh")
    if gh_path:
        try:
            result = subprocess.run(
                [gh_path, "auth", "token"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                token = result.stdout.strip()
                if token:
                    return token
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return ""


def fetch_latest_release(owner: str, repo: str, timeout_sec: int = 10) -> GitHubRelease:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "gentle-ai-update-check")
    token = _resolve_github_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = json.loads(resp.read().decode())
            return GitHubRelease(
                tag_name=data.get("tag_name", ""),
                html_url=data.get("html_url", ""),
            )
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise RuntimeError("GitHub API rate limit exceeded (HTTP 403)") from e
        if e.code == 404:
            raise RuntimeError(
                f"No releases found for {owner}/{repo} (HTTP 404)"
            ) from e
        raise RuntimeError(
            f"GitHub API returned HTTP {e.code} for {owner}/{repo}"
        ) from e


# Check


def check_all(current_version: str, profile: PlatformProfile) -> list[UpdateResult]:
    return check_filtered(current_version, profile, None)


def check_filtered(
    current_version: str, profile: PlatformProfile, tool_names: list[str] | None
) -> list[UpdateResult]:
    if tool_names:
        name_set = set(tool_names)
        targets = [t for t in Tools if t.name in name_set]
    else:
        targets = list(Tools)

    results: list[UpdateResult | None] = [None] * len(targets)
    with ThreadPoolExecutor(max_workers=len(targets)) as executor:
        futures = {
            executor.submit(_check_single_tool, t, current_version, profile): i
            for i, t in enumerate(targets)
        }
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()

    return [r for r in results if r is not None]


def _check_single_tool(
    tool: ToolInfo, current_build_version: str, profile: PlatformProfile
) -> UpdateResult:
    result = UpdateResult(tool=tool)
    result.update_hint = update_hint(tool, profile)

    # Run local detection and remote fetch concurrently
    local_version: str = ""
    release: GitHubRelease | None = None
    fetch_err: Exception | None = None

    with ThreadPoolExecutor(max_workers=2) as ex:
        local_fut = ex.submit(detect_installed_version, tool, current_build_version)
        remote_fut = ex.submit(fetch_latest_release, tool.owner, tool.repo)
        local_version = local_fut.result()
        try:
            release = remote_fut.result()
        except Exception as e:
            fetch_err = e

    result.installed_version = local_version

    if fetch_err is not None:
        result.err = str(fetch_err)
        result.status = UpdateStatus.CHECK_FAILED
        return result

    assert release is not None

    result.latest_version = release.tag_name
    result.release_url = release.html_url

    if not local_version:
        npm = tool.npm_package.strip()
        if npm:
            result.status = UpdateStatus.NOT_INSTALLED
            return result
        if tool.detect_cmd is None:
            result.status = UpdateStatus.VERSION_UNKNOWN
        else:
            if not _look_path(tool.detect_cmd[0]):
                result.status = UpdateStatus.NOT_INSTALLED
            else:
                result.status = UpdateStatus.VERSION_UNKNOWN
        return result

    normalized_local = normalize_version(local_version)
    if normalized_local == "dev":
        result.status = UpdateStatus.DEV_BUILD
        return result
    if not is_semver(normalized_local):
        result.status = UpdateStatus.VERSION_UNKNOWN
        return result

    # Compare versions
    latest_tag = normalize_version(release.tag_name) if release.tag_name else ""
    result.latest_version = latest_tag
    result.status = compare_versions(normalized_local, latest_tag)
    return result


# Instructions


def update_hint(tool: ToolInfo, profile: PlatformProfile) -> str:
    hints: dict[str, str] = {
        "dxrk": _dxrk_hint(profile),
        "DXRK_MEMORY": _DXRK_MEMORY_hint(profile),
        "DXRK_GUARDIAN": _DXRK_GUARDIAN_hint(profile),
        "opencode-subagent-statusline": "Restart/reload OpenCode; plugins are registered in ~/.config/opencode/tui.json",
        "opencode-sdd-engram-manage": "Restart/reload OpenCode; plugins are registered in ~/.config/opencode/tui.json",
    }
    return hints.get(tool.name, "")


def _dxrk_hint(profile: PlatformProfile) -> str:
    os_map = {
        "darwin": "brew upgrade dxrk",
        "linux": "curl -fsSL https://raw.githubusercontent.com/Dxrk777/Dxrk/main/scripts/install.sh | bash",
        "windows": "irm https://raw.githubusercontent.com/Dxrk777/Dxrk/main/scripts/install.ps1 | iex",
    }
    return os_map.get(profile.os, "")


def _DXRK_MEMORY_hint(profile: PlatformProfile) -> str:
    if profile.package_manager == "brew":
        return "brew upgrade DXRK_MEMORY"
    return "dxrk upgrade (downloads pre-built binary)"


def _DXRK_GUARDIAN_hint(profile: PlatformProfile) -> str:
    if profile.package_manager == "brew":
        return "brew upgrade DXRK_GUARDIAN"
    return "See https://github.com/Dxrk777/gentleman-guardian-angel"


# CLI render


def render_cli(results: list[UpdateResult]) -> str:
    lines: list[str] = []
    lines.append("Update Check")
    lines.append("============")
    lines.append("")

    updates_available = 0
    checks_failed = 0

    for r in results:
        status = _status_icon(r.status)
        installed = r.installed_version or "-"
        latest = r.latest_version or "-"
        line = f"  {status} {r.tool.name:<12s}  installed: {installed:<10s}  latest: {latest:<10s}"

        if r.status == UpdateStatus.UPDATE_AVAILABLE:
            updates_available += 1
            if r.update_hint:
                line += f"  {r.update_hint}"
        elif r.status == UpdateStatus.CHECK_FAILED:
            checks_failed += 1
            line += "  check failed"

        lines.append(line)

    lines.append("")

    if updates_available > 0 and checks_failed > 0:
        lines.append(
            f"{updates_available} update(s) available. {checks_failed} check(s) failed."
        )
    elif updates_available > 0:
        lines.append(f"{updates_available} update(s) available.")
    elif checks_failed > 0:
        lines.append(
            f"Update check incomplete: {checks_failed} tool(s) failed to check."
        )
    else:
        lines.append("All tools are up to date!")

    return "\n".join(lines)


def _status_icon(status: UpdateStatus) -> str:
    icons = {
        UpdateStatus.UP_TO_DATE: "[ok]",
        UpdateStatus.UPDATE_AVAILABLE: "[UP]",
        UpdateStatus.NOT_INSTALLED: "[--]",
        UpdateStatus.VERSION_UNKNOWN: "[??]",
        UpdateStatus.CHECK_FAILED: "[!!]",
        UpdateStatus.DEV_BUILD: "[dev]",
    }
    return icons.get(status, "[  ]")


def update_summary_line(results: list[UpdateResult]) -> str:
    parts: list[str] = []
    for r in results:
        if r.status == UpdateStatus.UPDATE_AVAILABLE:
            parts.append(f"{r.tool.name} {r.installed_version} -> {r.latest_version}")
    return ", ".join(parts)


def has_updates(results: list[UpdateResult]) -> bool:
    return any(r.status == UpdateStatus.UPDATE_AVAILABLE for r in results)


def check_failures(results: list[UpdateResult]) -> list[str]:
    return [r.tool.name for r in results if r.status == UpdateStatus.CHECK_FAILED]


def has_check_failures(results: list[UpdateResult]) -> bool:
    return len(check_failures(results)) > 0


# Upgrade types and executor


def upgrade_icon(status: ToolUpgradeStatus) -> str:
    icons = {
        ToolUpgradeStatus.SUCCEEDED: "[ok]",
        ToolUpgradeStatus.FAILED: "[!!]",
        ToolUpgradeStatus.SKIPPED: "[--]",
    }
    return icons.get(status, "[  ]")


def render_upgrade_report(report: UpgradeReport) -> str:
    lines: list[str] = []
    header = "Upgrade (dry-run)" if report.dry_run else "Upgrade"
    lines.append(header)
    lines.append("=" * len(header))
    lines.append("")
    lines.append("  Upgrades managed tool binaries only.")
    lines.append(
        "  Agent configs are preserved \u2014 no install or sync is performed."
    )
    lines.append("")

    if not report.results:
        lines.append("  No upgrades available. All managed tools are up to date.")
        return "\n".join(lines)

    succeeded = 0
    failed = 0
    skipped = 0

    for r in report.results:
        icon = upgrade_icon(r.status)
        line = f"  {icon} {r.tool_name:<12s}"

        if r.status == ToolUpgradeStatus.SUCCEEDED:
            line += f"  {r.old_version} \u2192 {r.new_version}"
            succeeded += 1
        elif r.status == ToolUpgradeStatus.FAILED:
            err_msg = r.err or ""
            line += f"  FAILED: {err_msg}"
            failed += 1
        elif r.status == ToolUpgradeStatus.SKIPPED:
            if r.manual_hint:
                line += f"  manual update required: {r.manual_hint}"
            elif report.dry_run:
                line += f"  {r.old_version} \u2192 {r.new_version}  (dry-run)"
            else:
                line += "  skipped"
            skipped += 1

        lines.append(line)

    lines.append("")

    if report.backup_id:
        lines.append(f"  Config backup: {report.backup_id}")
    if report.backup_warning:
        lines.append(f"  WARNING: {report.backup_warning}")

    if report.dry_run:
        actionable = sum(
            1
            for r in report.results
            if r.status == ToolUpgradeStatus.SKIPPED and not r.manual_hint
        )
        if actionable > 0:
            lines.append(
                f"  {actionable} upgrade(s) pending. Run without --dry-run to apply."
            )
        if (skipped - actionable) > 0:
            lines.append(
                f"  {skipped - actionable} tool(s) require manual attention (see hints above)."
            )
        if actionable == 0 and skipped == 0:
            lines.append("  No actionable upgrades found.")
    else:
        lines.append(f"  {succeeded} succeeded, {failed} failed, {skipped} skipped.")

    return "\n".join(lines)


# Spinner

_spinner_frames = [
    "\u280b",
    "\u2819",
    "\u2839",
    "\u2838",
    "\u283c",
    "\u2834",
    "\u2826",
    "\u2827",
    "\u2807",
    "\u280f",
]


class CLISpinner:
    def __init__(self, w, message: str) -> None:
        self._w = w
        self._message = message
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        i = 0
        line = f"  {_spinner_frames[0]} {self._message}..."
        self._w.write(line)
        self._w.flush()
        while not self._stop.wait(0.08):
            i = (i + 1) % len(_spinner_frames)
            line = f"  {_spinner_frames[i]} {self._message}..."
            self._w.write(f"\r{line}")
            self._w.flush()

    def finish(self, success: bool) -> None:
        self._stop.set()
        self._thread.join()
        icon = "\u2713" if success else "\u2717"
        clear = "\r" + " " * (len(self._message) + 20) + "\r"
        self._w.write(f"{clear}  {icon} {self._message}\n")
        self._w.flush()

    def finish_skipped(self) -> None:
        self._stop.set()
        self._thread.join()
        clear = "\r" + " " * (len(self._message) + 20) + "\r"
        self._w.write(f"{clear}  -- {self._message}\n")
        self._w.flush()


# File enumeration for backup

_backup_exclude_subdirs: set[str] = {
    "backups",
    "cache",
    "debug",
    "downloads",
    "plugins",
    "sessions",
    "tasks",
    "telemetry",
    "node_modules",
    "file-history",
    "ide",
    "paste-cache",
    "plans",
    "projects",
    "session-env",
    "shell-snapshots",
    "troubleshooting",
    "browser_recordings",
    "antigravity-browser-profile",
    "brain",
    "conversations",
    "context_state",
    "html_artifacts",
    "tmp",
}


def enumerate_files_in_dir(
    dir_path: str, exclude_names: set[str] | None = None
) -> list[str]:
    if exclude_names is None:
        exclude_names = _backup_exclude_subdirs
    files: list[str] = []
    clean_dir = os.path.normpath(dir_path)

    for root, dirs, filenames in os.walk(clean_dir):
        dirs[:] = [
            d for d in dirs if d.lower() not in exclude_names or root == clean_dir
        ]
        for f in filenames:
            fp = os.path.join(root, f)
            if os.path.islink(fp):
                resolved = os.path.realpath(fp)
                if os.path.isdir(resolved):
                    continue
            files.append(fp)

    return files


def config_paths_for_backup(home_dir: str) -> list[str]:
    # NOTE: original uses agents.NewDefaultRegistry + agents.ConfigRootsForBackup
    # and gga.ConfigPath + gga.RuntimeLibDir. Fall back to scanning canonical dirs.
    from dxrk.system import scan_configs

    configs = scan_configs(home_dir)
    paths: list[str] = []
    for cfg in configs:
        if os.path.isdir(cfg.path):
            try:
                paths.extend(enumerate_files_in_dir(cfg.path))
            except OSError:
                continue
    return paths


# Executor

AppVersion = "dev"


def effective_method(tool: ToolInfo, profile: PlatformProfile) -> InstallMethod:
    if tool.install_method == InstallMethod.OPENCODE_PLUGIN:
        return InstallMethod.OPENCODE_PLUGIN
    if profile.package_manager == "brew":
        return InstallMethod.BREW
    return tool.install_method


def _detect_command_hint(tool: ToolInfo) -> str:
    if not tool.detect_cmd:
        return tool.name
    return " ".join(tool.detect_cmd)


def execute(
    results: list[UpdateResult],
    profile: PlatformProfile,
    home_dir: str,
    dry_run: bool = False,
    progress=None,
) -> UpgradeReport:
    options = ExecuteOptions()
    if progress is not None:
        options.progress = progress
        options.backup_diagnostics = progress
    return execute_with_options(results, profile, home_dir, dry_run, options)


@dataclass
class ExecuteOptions:
    progress: Optional[TextIO] = None
    backup_diagnostics: Optional[TextIO] = None


def execute_with_options(
    results: list[UpdateResult],
    profile: PlatformProfile,
    home_dir: str,
    dry_run: bool,
    options: ExecuteOptions,
) -> UpgradeReport:
    pw = options.progress if options.progress is not None else None

    executable: list[UpdateResult] = []
    dev_builds: list[UpdateResult] = []
    version_unknowns: list[UpdateResult] = []

    for r in results:
        if r.status == UpdateStatus.UPDATE_AVAILABLE:
            executable.append(r)
        elif r.status == UpdateStatus.DEV_BUILD:
            dev_builds.append(r)
        elif r.status == UpdateStatus.VERSION_UNKNOWN:
            version_unknowns.append(r)

    if not executable and not dev_builds and not version_unknowns:
        return UpgradeReport(dry_run=dry_run)

    # Backup
    backup_id = ""
    backup_warning = ""
    if not dry_run and executable:
        from dxrk.backup import (
            BackupSource as BackupSrc,
        )
        from dxrk.backup import (
            ManifestFilename as BManifestFilename,
        )
        from dxrk.backup import Snapshotter
        from dxrk.backup import write_manifest as bw_manifest

        sp = CLISpinner(pw, "Creating pre-upgrade backup") if pw else None
        snapshot_dir = os.path.join(
            home_dir,
            ".gentle-ai",
            "backups",
            f"upgrade-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        )
        try:
            snap = Snapshotter()
            manifest = snap.create(snapshot_dir, config_paths_for_backup(home_dir))
            manifest.source = BackupSrc.UPGRADE
            manifest.description = "pre-upgrade snapshot"
            manifest.created_by_version = AppVersion
            manifest_path = os.path.join(snapshot_dir, BManifestFilename)
            bw_manifest(manifest_path, manifest)
            if sp:
                sp.finish(True)
            backup_id = manifest.id
        except (OSError, ValueError) as e:
            if sp:
                sp.finish(False)
            backup_warning = f"pre-upgrade backup failed \u2014 upgrade will run without a backup: {e}"

    # Build results
    tool_results: list[ToolUpgradeResult] = []

    for r in dev_builds:
        tool_results.append(
            ToolUpgradeResult(
                tool_name=r.tool.name,
                old_version=r.installed_version,
                new_version=r.latest_version,
                method=effective_method(r.tool, profile),
                status=ToolUpgradeStatus.SKIPPED,
                manual_hint=f"source build \u2014 upgrade manually or install a release binary from "
                f"https://github.com/Dxrk777/{r.tool.repo}/releases",
            )
        )

    for r in version_unknowns:
        tool_results.append(
            ToolUpgradeResult(
                tool_name=r.tool.name,
                old_version=r.installed_version,
                new_version=r.latest_version,
                method=effective_method(r.tool, profile),
                status=ToolUpgradeStatus.SKIPPED,
                manual_hint=f"installed binary was found but its version could not be determined \u2014 "
                f"check `{_detect_command_hint(r.tool)}` and reinstall if it is a stale source/dev build",
            )
        )

    for r in executable:
        method = effective_method(r.tool, profile)
        msg = f"Upgrading {r.tool.name} via {method.value} ({r.installed_version} \u2192 {r.latest_version})"
        sp = CLISpinner(pw, msg) if pw else None
        tool_result = _execute_one(r, profile, dry_run)
        if sp:
            if tool_result.status == ToolUpgradeStatus.SUCCEEDED:
                sp.finish(True)
            elif tool_result.status == ToolUpgradeStatus.SKIPPED:
                sp.finish_skipped()
            else:
                sp.finish(False)
        tool_results.append(tool_result)

    return UpgradeReport(
        backup_id=backup_id,
        backup_warning=backup_warning,
        results=tool_results,
        dry_run=dry_run,
    )


def _execute_one(
    r: UpdateResult, profile: PlatformProfile, dry_run: bool
) -> ToolUpgradeResult:
    base = ToolUpgradeResult(
        tool_name=r.tool.name,
        old_version=r.installed_version,
        new_version=r.latest_version,
        method=effective_method(r.tool, profile),
    )
    if dry_run:
        base.status = ToolUpgradeStatus.SKIPPED
        return base

    try:
        _run_strategy(r, profile)
        base.status = ToolUpgradeStatus.SUCCEEDED
    except ManualFallbackError as e:
        base.status = ToolUpgradeStatus.SKIPPED
        base.manual_hint = e.hint
    except Exception as e:
        base.status = ToolUpgradeStatus.FAILED
        base.err = str(e)

    return base


# Upgrade strategies


def _run_strategy(r: UpdateResult, profile: PlatformProfile) -> None:
    method = effective_method(r.tool, profile)

    if method == InstallMethod.BREW:
        _brew_upgrade(r.tool.name)
    elif method == InstallMethod.GO_INSTALL:
        _go_install_upgrade(r.tool, r.latest_version)
    elif method == InstallMethod.BINARY:
        _binary_upgrade(r, profile)
    elif method == InstallMethod.SCRIPT:
        if r.tool.name == "gga":
            _gga_script_upgrade(r)
        else:
            _script_upgrade(r, profile)
    elif method == InstallMethod.OPENCODE_PLUGIN:
        _opencode_plugin_upgrade(r)
    else:
        raise ManualFallbackError(
            f"upgrade {r.tool.name!r}: unsupported install method {method.value!r} \u2014 "
            f"please update manually. See: https://github.com/Dxrk777/{r.tool.repo}"
        )


def _brew_upgrade(tool_name: str) -> None:
    subprocess.run(["brew", "update"], capture_output=True, timeout=60)
    result = subprocess.run(
        ["brew", "upgrade", tool_name],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"brew upgrade {tool_name}: {result.stderr.strip()}")


def _go_install_upgrade(tool: ToolInfo, latest_version: str) -> None:
    if not tool.go_import_path:
        raise RuntimeError(f"upgrade {tool.name!r}: GoImportPath is empty")
    target = f"{tool.go_import_path}@v{latest_version}"
    result = subprocess.run(
        ["go", "install", target],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"go install {target}: {result.stderr.strip()}")


def _binary_upgrade(r: UpdateResult, profile: PlatformProfile) -> None:
    if r.tool.name == "engram":
        _engram_binary_upgrade(profile)
        return

    if profile.os == "windows":
        hint = (
            r.update_hint
            or f"Download manually from https://github.com/Dxrk777/{r.tool.repo}/releases"
        )
        raise ManualFallbackError(
            f"upgrade {r.tool.name!r} on Windows requires manual update: {hint}"
        )

    _download_and_replace(r, profile)


def _engram_binary_upgrade(profile: PlatformProfile) -> None:
    # NOTE: original uses engram.DownloadLatestBinary(profile).
    # This is an external dependency not yet ported. Raise a manual fallback.
    raise ManualFallbackError(
        "engram auto-downloader not available in Python port yet. "
        "Run: gentle-ai upgrade or download from https://github.com/Dxrk777/engram/releases"
    )


def _download_and_replace(r: UpdateResult, profile: PlatformProfile) -> None:
    _download(r, profile)


# Download


def _download(r: UpdateResult, profile: PlatformProfile) -> None:
    if profile.os == "windows":
        hint = (
            r.update_hint
            or f"Download from https://github.com/Dxrk777/{r.tool.repo}/releases"
        )
        raise RuntimeError(
            f"upgrade {r.tool.name!r} on Windows requires manual update \u2014 {hint}"
        )

    binary_path = _look_path(r.tool.name)
    if not binary_path:
        raise RuntimeError(f"locate {r.tool.name!r} binary: not found on PATH")

    asset_url = _resolve_asset_url(
        r.tool.owner, r.tool.repo, r.latest_version, profile.os
    )
    tmp_path = binary_path + ".new"
    try:
        _download_binary(asset_url, r.tool.name, tmp_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    _atomic_replace(tmp_path, binary_path)


def _resolve_asset_url(owner: str, repo: str, version: str, goos: str) -> str:
    arch = _go_arch()
    filename = f"{repo}_{version}_{goos}_{arch}.tar.gz"
    return f"https://github.com/{owner}/{repo}/releases/download/v{version}/{filename}"


def _go_arch() -> str:
    machine = os.uname().machine
    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    return arch_map.get(machine, machine)


_http_client_timeout = 5 * 60


def _download_binary(url: str, binary_name: str, out_path: str) -> None:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=_http_client_timeout) as resp:
        _extract_binary_from_tar_gz(resp, binary_name, out_path)


def _extract_binary_from_tar_gz(stream, binary_name: str, out_path: str) -> None:
    with tarfile.open(fileobj=stream, mode="r|gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            if os.path.basename(member.name) == binary_name:
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as f:
                    shutil.copyfileobj(tar.extractfile(member), f)  # type: ignore
                os.chmod(out_path, 0o755)
                return
    raise RuntimeError(f"binary {binary_name!r} not found in archive")


def _atomic_replace(src: str, dst: str) -> None:
    os.replace(src, dst)


# Script upgrade

_script_http_timeout = 2 * 60
_max_script_size = 1 * 1024 * 1024


def _install_script_url(owner: str, repo: str) -> str:
    return f"https://raw.githubusercontent.com/{owner}/{repo}/main/install.sh"


def _script_upgrade(r: UpdateResult, profile: PlatformProfile) -> None:
    if profile.os == "windows":
        hint = (
            r.update_hint
            or f"Download manually from https://github.com/{r.tool.owner}/{r.tool.repo}/releases"
        )
        raise ManualFallbackError(
            f"upgrade {r.tool.name!r} on Windows requires manual update: {hint}"
        )

    url = _install_script_url(r.tool.owner, r.tool.repo)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=_script_http_timeout) as resp:
        body = resp.read(_max_script_size + 1)

    if len(body) > _max_script_size:
        raise RuntimeError(
            f"download install.sh: response body exceeds {_max_script_size} bytes limit"
        )

    result = subprocess.run(
        ["bash", "-c", body.decode()],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"install.sh failed for {r.tool.name!r}: {result.stderr.strip() or result.stdout.strip()}"
        )


def _gga_script_upgrade(r: UpdateResult) -> None:
    _gga_script_upgrade_for_os(r, sys.platform)


def _gga_script_upgrade_for_os(r: UpdateResult, os_name: str) -> None:
    if os_name == "win32":
        hint = (
            r.update_hint
            or f"Download manually from https://github.com/{r.tool.owner}/{r.tool.repo}/releases"
        )
        raise ManualFallbackError(
            f"upgrade {r.tool.name!r} on Windows requires manual update: {hint}"
        )

    tmp_dir = tempfile.mkdtemp(prefix="gentle-ai-gga-")
    try:
        repo_url = f"https://github.com/{r.tool.owner}/{r.tool.repo}.git"
        subprocess.run(
            ["git", "clone", repo_url, tmp_dir],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        install_script = os.path.join(tmp_dir, "install.sh")
        result = subprocess.run(
            ["bash", install_script],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"install.sh failed for {r.tool.name!r}: {result.stderr.strip() or result.stdout.strip()}"
            )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# OpenCode plugin upgrade


def _opencode_plugin_upgrade(r: UpdateResult) -> None:
    pkg = r.tool.npm_package.strip()
    if not pkg:
        raise ManualFallbackError(hint=_opencode_manual_hint(r))

    home_dir = os.path.expanduser("~")
    if not home_dir or home_dir == "~":
        raise ManualFallbackError(
            hint=f"{_opencode_manual_hint(r)} Could not resolve the user home directory; update {pkg} manually."
        )

    opencode_dir = os.path.join(home_dir, ".config", "opencode")
    if not os.path.isdir(opencode_dir):
        raise ManualFallbackError(
            hint=f"{_opencode_manual_hint(r)} OpenCode config directory was not found at {opencode_dir}; "
            f"{pkg} is not installed/materialized yet."
        )

    materialized = _opencode_plugin_registered_or_materialized(opencode_dir, pkg)
    if not materialized:
        raise ManualFallbackError(
            hint=f"{_opencode_manual_hint(r)} {pkg} is not registered in tui.json and is not present in "
            f"node_modules; start/reload OpenCode first so it materializes the plugin."
        )

    pm = _select_opencode_package_manager(opencode_dir)
    if pm is None:
        raise ManualFallbackError(
            hint=f"OpenCode plugin {pkg} can be upgraded from {opencode_dir}, but no supported "
            f"package manager is available in PATH. Install bun or npm, then run update tools again."
        )

    target = pkg + "@latest"
    if pm == "bun":
        cmd = ["bun", "add", target]
    else:
        cmd = ["npm", "install", "--save", "--no-audit", "--no-fund", target]

    env = os.environ.copy()
    env.update(
        {
            "CI": "1",
            "npm_config_yes": "true",
            "npm_config_audit": "false",
            "npm_config_fund": "false",
        }
    )

    result = subprocess.run(
        cmd,
        cwd=opencode_dir,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{pm} upgrade {pkg} in {opencode_dir}: {result.stderr.strip() or result.stdout.strip()}"
        )


def _opencode_plugin_registered_or_materialized(opencode_dir: str, pkg: str) -> bool:
    node_modules_pkg = os.path.join(opencode_dir, "node_modules", pkg)
    if os.path.isdir(node_modules_pkg):
        return True

    tui_path = os.path.join(opencode_dir, "tui.json")
    try:
        with open(tui_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False

    plugins = data.get("plugin", []) if isinstance(data, dict) else []
    return pkg in plugins


def _select_opencode_package_manager(opencode_dir: str) -> str | None:
    candidates: list[str] = []
    pm_from_meta = _opencode_pm_from_metadata(opencode_dir)
    if pm_from_meta:
        candidates.append(pm_from_meta)
    for pm in ("bun", "npm"):
        if pm not in candidates:
            candidates.append(pm)

    for pm in candidates:
        if _look_path(pm):
            return pm
    return None


def _opencode_pm_from_metadata(opencode_dir: str) -> str | None:
    pkg_json = os.path.join(opencode_dir, "package.json")
    try:
        with open(pkg_json) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    else:
        pm_raw = data.get("packageManager", "")
        pm_lower = pm_raw.strip().lower()
        if pm_lower.startswith("bun@") or pm_lower == "bun":
            return "bun"
        if pm_lower.startswith("npm@") or pm_lower == "npm":
            return "npm"

    for lock in ("bun.lock", "bun.lockb"):
        if os.path.isfile(os.path.join(opencode_dir, lock)):
            return "bun"
    for lock in ("package-lock.json", "npm-shrinkwrap.json"):
        if os.path.isfile(os.path.join(opencode_dir, lock)):
            return "npm"

    return None


def _opencode_manual_hint(r: UpdateResult) -> str:
    hint = r.update_hint.strip()
    if hint:
        return hint
    npm = r.tool.npm_package.strip()
    if npm:
        return f"OpenCode manages {npm} from tui.json. Restart or reload OpenCode so it refreshes the plugin package."
    return "OpenCode manages TUI plugin packages from tui.json. Restart or reload OpenCode so it refreshes plugins."
