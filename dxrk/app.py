# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

from dxrk.cli.run import run_install
from dxrk.system import (
    DetectionResult,
    detect,
    ensure_supported_os,
    ensure_supported_platform,
)
from dxrk.update import UpdateResult, UpdateStatus, check_failures, check_filtered

__all__ = [
    "VERSION",
    "SelfUpdateChecker",
    "print_help",
    "resolve_version",
    "run_cli",
]

APP_NAME = "gentle-ai"
VERSION = "dev"

HELP_TEXT = """dxrk — AI Gentle Stack ({version})

USAGE
  dxrk                     Launch interactive TUI
  dxrk <command> [flags]

COMMANDS
  install      Configure AI coding agents on this machine
  uninstall    Remove Gentle AI managed files from this machine
  sync         Sync agent configs and skills to current version
  update       Check for available updates
  upgrade      Apply updates to managed tools
  restore      Restore a config backup
  version      Print version

FLAGS
  --help, -h    Show this help

Run 'dxrk help' for this message.
Documentation: https://github.com/Dxrk777/Dxrk
"""


def resolve_version(ldflags_version: str) -> str:
    if ldflags_version != "dev":
        return ldflags_version
    return "dev"


def print_help(version: str = VERSION) -> str:
    return HELP_TEXT.format(version=version)


@dataclass
class SelfUpdateChecker:
    version: str = ""
    profile: Any = None
    enabled: bool = True

    def skip_reason(self) -> str | None:
        if os.environ.get("DXRK_SELF_UPDATE_DONE") == "1":
            return "already updated this invocation"
        if os.environ.get("DXRK_NO_SELF_UPDATE") == "1":
            return "opt-out via DXRK_NO_SELF_UPDATE"
        if self.version == "dev":
            return "dev build"
        return None

    def check(self, stdout=sys.stdout) -> str | None:
        reason = self.skip_reason()
        if reason is not None:
            return None

        results = check_filtered(self.version, self.profile, ["gentle-ai"])
        target: UpdateResult | None = None
        for r in results:
            if r.tool.name == "gentle-ai":
                target = r
                break

        if target is None or target.status != UpdateStatus.UPDATE_AVAILABLE:
            return None

        print(f"Updated to v{target.latest_version}, restarting...", file=stdout)
        return target.latest_version


def run_cli(args: list[str]) -> int:
    early_commands = {"version", "--version", "-v", "help", "--help", "-h", "uninstall"}

    if args:
        cmd = args[0]
        if cmd in ("version", "--version", "-v"):
            print(f"{APP_NAME} {VERSION}")
            return 0

        if cmd in ("help", "--help", "-h"):
            print(print_help(VERSION))
            return 0

        if cmd == "uninstall":
            from dxrk.cli.install import parse_uninstall_flags

            try:
                parse_uninstall_flags(args[1:])
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
            return 0

    try:
        ensure_supported_os(sys.platform)
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        detection: DetectionResult = detect()
    except Exception as e:
        print(f"detect system: {e}", file=sys.stderr)
        return 1

    if not detection.system.supported:
        try:
            ensure_supported_platform(detection.system.profile)
        except OSError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    from dxrk.cli.install import resolve_install_profile

    profile = resolve_install_profile(detection)
    checker = SelfUpdateChecker(version=VERSION, profile=profile)
    try:
        checker.check()
    except Exception as e:
        print(f"Warning: self-update failed: {e}", file=sys.stderr)

    if not args:
        print("TUI mode not available in Python port")
        return 0

    cmd = args[0]
    try:
        if cmd == "update":
            from dxrk.update import (
                check_all as update_check_all,
            )
            from dxrk.update import (
                render_cli as update_render_cli,
            )

            results = update_check_all(VERSION, profile)
            print(update_render_cli(results))
            failed = check_failures(results)
            if failed:
                print(f"update check failed for: {', '.join(failed)}", file=sys.stderr)
                return 1
            return 0

        elif cmd == "upgrade":
            dry_run = False
            tool_filter: list[str] = []
            for arg in args[1:]:
                if arg in ("--dry-run", "-n"):
                    dry_run = True
                elif not arg.startswith("-"):
                    tool_filter.append(arg)

            from dxrk.update import (
                check_filtered as upgrade_check,
            )
            from dxrk.update import (
                execute as upgrade_execute,
            )
            from dxrk.update import (
                render_upgrade_report,
            )

            if tool_filter:
                check_results = upgrade_check(VERSION, profile, tool_filter)
            else:
                check_results = upgrade_check(VERSION, profile, None)

            failed = check_failures(check_results)
            if failed and tool_filter:
                print(f"update check failed for: {', '.join(failed)}", file=sys.stderr)
                return 1

            home_dir = os.path.expanduser("~")
            report = upgrade_execute(check_results, profile, home_dir, dry_run=dry_run)
            print(render_upgrade_report(report))

            for r in report.results:
                if r.err:
                    print(
                        f"upgrade failed for {r.tool_name!r}: {r.err}", file=sys.stderr
                    )
                    return 1
            return 0

        elif cmd == "install":
            install_result = run_install(args[1:], detection)
            if install_result.dry_run:
                print("Dry-run: install plan built successfully")
            elif install_result.verify and not getattr(
                install_result.verify, "ready", True
            ):
                print("Post-apply verification failed")
                return 1
            return 0

        elif cmd == "sync":
            from dxrk.cli.install import parse_sync_flags

            try:
                parse_sync_flags(args[1:])
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
            print("Sync completed")
            return 0

        elif cmd == "restore":
            print("Restore requires TUI mode")
            return 0

        else:
            print(
                f"unknown command {cmd!r} — run 'gentle-ai help' for available commands",
                file=sys.stderr,
            )
            return 1

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
