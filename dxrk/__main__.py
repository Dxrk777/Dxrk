# SPDX-License-Identifier: MIT
#!/usr/bin/env python3
"""
Dxrk — Unified CLI + TUI entry point.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Dxrk — Agent Ecosystem Manager")
    parser.add_argument("--version", "-v", action="store_true", help="Show version")
    parser.add_argument("--health", action="store_true", help="Run health check")
    parser.add_argument("--tui", action="store_true", help="Launch TUI (default if no args)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--tenant", "-t", default=os.environ.get("DXRK_TENANT", ""), help="Tenant ID")

    sub = parser.add_subparsers(dest="command")

    # dxrk install
    install_parser = sub.add_parser("install", help="Install agents and components")
    install_parser.add_argument("--agent", "-a", action="append", dest="agents", help="Agent to install")
    install_parser.add_argument(
        "--component",
        "-c",
        action="append",
        dest="components",
        help="Component to install",
    )
    install_parser.add_argument("--persona", choices=["dxrk", "neutral", "custom"], default="dxrk")
    install_parser.add_argument("--preset", choices=["full-dxrk", "ecosystem-only", "minimal", "custom"])
    install_parser.add_argument("--dry-run", action="store_true", help="Preview without installing")

    # dxrk sync
    sync_parser = sub.add_parser("sync", help="Sync configuration to disk")
    sync_parser.add_argument("--agent", "-a", action="append", dest="agents", help="Agent to sync")
    sync_parser.add_argument("--dry-run", action="store_true", help="Preview without syncing")
    sync_parser.add_argument("--sdd-mode", type=str, default="", help="SDD mode (single/multi)")
    sync_parser.add_argument("--strict-tdd", action="store_true", default=False, help="Enable strict TDD")
    sync_parser.add_argument(
        "--include-permissions",
        action="store_true",
        default=False,
        help="Include permissions",
    )
    sync_parser.add_argument("--include-theme", action="store_true", default=False, help="Include theme")

    # dxrk upgrade
    sub.add_parser("upgrade", help="Upgrade installed components")

    # dxrk uninstall
    uninstall_parser = sub.add_parser("uninstall", help="Uninstall agents and components")
    uninstall_parser.add_argument("--agent", action="append", dest="agents")
    uninstall_parser.add_argument("--component", action="append", dest="components")
    uninstall_parser.add_argument("--all", action="store_true", default=False, help="Uninstall all")
    uninstall_parser.add_argument("--yes", "-y", action="store_true", default=False, help="Skip confirmation")

    # dxrk backup / restore
    sub.add_parser("backup", help="Manage backups")
    restore_parser = sub.add_parser("restore", help="Restore from a backup")
    restore_parser.add_argument("backup_id", nargs="?", help="Backup ID to restore")

    # dxrk model
    model_parser = sub.add_parser("model", help="Configure model assignments")
    model_parser.add_argument("phase", nargs="?", help="SDD phase to configure")
    model_parser.add_argument("--provider", help="Provider ID")
    model_parser.add_argument("--model", help="Model ID")

    # dxrk version
    sub.add_parser("version", help="Show version")

    # dxrk tenant
    tenant_parser = sub.add_parser("tenant", help="Manage tenants")
    tenant_sub = tenant_parser.add_subparsers(dest="tenant_command")
    tenant_sub.add_parser("list", help="List tenants")
    create_p = tenant_sub.add_parser("create", help="Create a tenant")
    create_p.add_argument("tenant_id", help="Tenant ID")
    switch_p = tenant_sub.add_parser("switch", help="Switch active tenant")
    switch_p.add_argument("tenant_id", help="Tenant ID")
    tenant_sub.add_parser("current", help="Show current tenant")
    delete_p = tenant_sub.add_parser("delete", help="Delete a tenant")
    delete_p.add_argument("tenant_id", help="Tenant ID")
    delete_p.add_argument("--force", action="store_true", help="Force deletion")
    tenant_sub.add_parser("whoami", help="Show tenant ID")
    tenant_sub.add_parser("migrate", help="Migrate legacy data")

    # early tenant resolution via DXRK_TENANT / --tenant, validated via validate_id
    pre_args, _ = parser.parse_known_args()
    tenant_id = str(getattr(pre_args, "tenant", "") or "").strip()
    if tenant_id:
        from dxrk.security.jwt import validate_id

        if not validate_id(tenant_id):
            parser.error(f"invalid tenant id {tenant_id!r}")
        os.environ["DXRK_TENANT"] = tenant_id

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    version = os.environ.get("DXRK_VERSION", "dev")

    if args.version or args.command == "version":
        print(f"Dxrk v{version}")
        return

    if args.health:
        from dxrk.system import detect, render_dependency_report

        result = detect()
        assert result.dependencies is not None, "detection did not populate dependencies"
        print(render_dependency_report(result.dependencies))
        return

    if args.command == "install":
        _run_install_cli(args)
        return

    if args.command == "sync":
        _run_sync_cli(args)
        return

    if args.command == "uninstall":
        _run_uninstall_cli(args)
        return

    if args.command == "backup":
        _run_backup_cli()
        return

    if args.command == "restore":
        _run_restore_cli(args)
        return

    if args.command == "upgrade":
        print("Upgrade not yet implemented")
        return

    if args.command == "model":
        _run_model_cli(args)
        return

    if args.command == "tenant":
        _run_tenant_cli(args)
        return

    if args.command:
        print(f"Command '{args.command}' not yet implemented")
        return

    _launch_tui(version)


def _run_tenant_cli(args: argparse.Namespace) -> None:
    from dxrk.commands import register_all

    reg = register_all()
    argv: list[str] = ["tenant"]
    tc = getattr(args, "tenant_command", None)
    if tc:
        argv.append(str(tc))
        tid = getattr(args, "tenant_id", None)
        if tid:
            argv.append(str(tid))
        if getattr(args, "force", False):
            argv.append("--force")
    code = reg.execute(argv)
    if code != 0:
        sys.exit(code)


def _run_install_cli(args) -> None:
    from dxrk.system import detect

    result = detect()
    if not result.system.supported:
        print("Unsupported system:", result.system.os)
        sys.exit(1)

    from dxrk.cli.install import run_install

    raw = sys.argv[2:]

    out = run_install(raw, detection=result)
    if out.dry_run:
        rev = out.review
        if rev:
            print("=== Dry Run Review ===")
            print(f"  Agents selected: {len(rev.agents)}")
            print(f"  Unsupported agents: {len(rev.unsupported_agents)}")
            print(f"  Persona: {rev.persona}")
            print(f"  Preset: {rev.preset}")
            print(f"  Components: {len(rev.components)}")
            print(f"  Skills: {len(rev.skills)}")
            print(f"  Strict TDD: {rev.strict_tdd}")
            print(f"  Has SDD: {rev.has_sdd}")
            if rev.platform_decision:
                pd = rev.platform_decision
                print(f"  OS: {pd.os} / {pd.linux_distro}")
        return


def _launch_tui(version: str) -> None:
    from dxrk.tui.app import run as run_tui

    run_tui(version)


def _run_sync_cli(args) -> None:
    from dxrk.cli.sync import RunSync

    raw = sys.argv[2:]
    result = RunSync(raw)
    if hasattr(result, "dry_run") and result.dry_run:
        print("=== Dry Run Sync ===")
        print(f"  Agents: {len(result.agents)}")
        print(f"  SDD Mode: {getattr(result.selection, 'sdd_mode', 'N/A')}")
        print(f"  Strict TDD: {result.selection.strict_tdd}")
        return

    print(f"Sync complete — {getattr(result, 'files_changed', 0)} files changed")


def _run_uninstall_cli(args) -> None:
    from dxrk.cli.uninstall import RunUninstall

    raw = sys.argv[2:]
    result = RunUninstall(raw)
    if hasattr(result, "removed_files"):
        manual = getattr(result, "manual_actions", [])
        if manual:
            print("Manual actions required:")
            for a in manual:
                print(f"  {a}")
        print("Uninstall complete")


def _run_backup_cli() -> None:
    from dxrk.backup import list_backups

    backups = list_backups()
    if not backups:
        print("No backups found")
        return
    for b in backups:
        print(f"  {b}")


def _run_restore_cli(args) -> None:
    from dxrk.cli.restore import RunRestore

    raw = sys.argv[2:]
    RunRestore(raw)


def _run_model_cli(args) -> None:
    if args.phase:
        print(f"Model config for phase '{args.phase}' not yet implemented")
    else:
        print("Model configuration not yet implemented")


if __name__ == "__main__":
    main()
