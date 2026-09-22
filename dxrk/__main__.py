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
    upgrade_parser = sub.add_parser("upgrade", help="Upgrade installed components")
    upgrade_parser.add_argument("--dry-run", "-n", action="store_true", help="Preview without upgrading")
    upgrade_parser.add_argument("tool", nargs="*", help="Only upgrade these tools (default: all)")

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

    # dxrk enterprise
    enterprise_parser = sub.add_parser("enterprise", help="Dxrk Enterprise, la empresa de IA")
    enterprise_sub = enterprise_parser.add_subparsers(dest="enterprise_command")
    enterprise_sub.add_parser("start", help="Iniciar empresa")
    enterprise_sub.add_parser("stop", help="Detener empresa")
    enterprise_sub.add_parser("status", help="Ver estado")
    execute_p = enterprise_sub.add_parser("execute", help="Ejecutar tarea")
    execute_p.add_argument("task", help="Task description")
    execute_p.add_argument("department", nargs="?", help="Department ID (optional)")
    enterprise_sub.add_parser("skills", help="Listar skills")
    enterprise_sub.add_parser("report", help="Generar reporte")

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

    from dxrk import __version__

    version = os.environ.get("DXRK_VERSION") or __version__

    if args.version or args.command == "version":
        print(f"Dxrk v{version}")
        return

    if args.health:
        from dxrk.system import detect, render_dependency_report

        result = detect()
        if result.dependencies is None:
            print("health check failed: detection did not populate dependencies", file=sys.stderr)
            sys.exit(1)
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
        _run_upgrade_cli(args)
        return

    if args.command == "model":
        _run_model_cli(args)
        return

    if args.command == "tenant":
        _run_tenant_cli(args)
        return

    if args.command == "enterprise":
        _run_enterprise_cli(args)
        return

    if args.command:
        print(f"Command '{args.command}' not yet implemented", file=sys.stderr)
        sys.exit(2)

    _launch_single_installer(version)


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


def _run_enterprise_cli(args: argparse.Namespace) -> None:
    from dxrk.commands import register_all

    reg = register_all()
    argv: list[str] = ["enterprise"]
    ec = getattr(args, "enterprise_command", None)
    if ec:
        argv.append(str(ec))
        task = getattr(args, "task", None)
        if task:
            argv.append(str(task))
        dept = getattr(args, "department", None)
        if dept:
            argv.append(str(dept))
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
    if out.error:
        print(f"Install failed: {out.error}", file=sys.stderr)
        sys.exit(1)
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


def _launch_tui(version: str, initial_screen: str = "welcome") -> None:
    from dxrk.tui.app import run as run_tui

    run_tui(version, initial_screen=initial_screen)


def _is_installed(home: str) -> bool:
    """True cuando una instalación previa registró agentes en el estado."""
    try:
        from dxrk.state import read as state_read
    except ImportError:
        return False
    try:
        st = state_read(home)
    except (FileNotFoundError, ValueError, OSError):
        return False
    return bool(getattr(st, "installed_agents", []))


def _launch_single_installer(version: str) -> None:
    """Instalador único (estilo opencode): instala una vez y abre el chat.

    La primera ejecución corre la instalación completa de una sola vez
    (la misma lógica que `dxrk-py install` sin banderas) y luego abre el
    chat. Las siguientes ejecuciones van directo al chat.
    """
    import os

    home = os.path.expanduser("~")
    if not _is_installed(home):
        from dxrk.cli.install import run_install
        from dxrk.system import detect

        print("Instalando Dxrk (una sola vez: agentes + componentes + MCP)…", flush=True)
        try:
            result = run_install([], detect())
        except Exception as e:
            print(f"La instalación falló con excepción: {e}", flush=True)
            print("Se abre Dxrk de todos modos.", flush=True)
            print("Reintenta con `dxrk-py install` para ver el detalle.", flush=True)
            _launch_tui(version, initial_screen="chat")
            return
        if result.error:
            print(f"La instalación reportó errores: {result.error}", flush=True)
        if _is_installed(home):
            print("Instalación completa. Abriendo Dxrk…", flush=True)
        else:
            print("La instalación no pudo completarse; se abre Dxrk de todos modos.", flush=True)
            print("Reintenta con `dxrk-py install` para ver el detalle.", flush=True)
    _launch_tui(version, initial_screen="chat")


def _run_sync_cli(args) -> None:
    from dxrk.cli.sync import RunSync

    raw = sys.argv[2:]
    try:
        result = RunSync(raw)
    except Exception as e:
        print(f"Sync failed: {e}", file=sys.stderr)
        sys.exit(1)
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
    try:
        result = RunUninstall(raw)
    except Exception as e:
        print(f"Uninstall failed: {e}", file=sys.stderr)
        sys.exit(1)
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
    try:
        result = RunRestore(raw)
    except ValueError as e:
        print(f"Restore failed: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Restore failed: {e}", file=sys.stderr)
        sys.exit(1)
    if isinstance(result, str) and result:
        print(result, file=sys.stderr)
        sys.exit(1)


def _run_upgrade_cli(args: argparse.Namespace) -> None:
    from dxrk.system import detect

    result = detect()
    if not result.system.supported:
        print("Unsupported system:", result.system.os)
        sys.exit(1)

    from dxrk.cli.install import resolve_install_profile

    profile = resolve_install_profile(result)

    from dxrk import __version__

    version = os.environ.get("DXRK_VERSION") or __version__

    from dxrk.update import (
        ToolUpgradeStatus,
        check_failures,
        check_filtered,
        execute,
        has_check_failures,
        has_updates,
        render_upgrade_report,
        update_summary_line,
    )

    tools: list[str] | None = list(getattr(args, "tool", []) or []) or None
    dry_run: bool = bool(getattr(args, "dry_run", False))

    results = check_filtered(version, profile, tools)
    if has_check_failures(results):
        failed = check_failures(results)
        print(f"la verificación de actualizaciones falló para: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)

    if has_updates(results):
        print(f"Actualizaciones disponibles: {update_summary_line(results)}")

    home_dir = os.path.expanduser("~")
    report = execute(results, profile, home_dir, dry_run=dry_run)
    print(render_upgrade_report(report))

    failed_upgrades = [r for r in report.results if r.status == ToolUpgradeStatus.FAILED or r.err]
    if failed_upgrades:
        for r in failed_upgrades:
            print(f"la actualización falló para {r.tool_name!r}: {r.err}", file=sys.stderr)
        sys.exit(1)


def _run_model_cli(args: argparse.Namespace) -> None:
    from dxrk.model import get_model_assignments, set_model_assignment

    phase = str(getattr(args, "phase", "") or "").strip()
    provider = str(getattr(args, "provider", "") or "").strip()
    model = str(getattr(args, "model", "") or "").strip()

    if not phase:
        assignments = get_model_assignments()
        if not assignments:
            print("No model assignments configured")
            return
        for name in sorted(assignments):
            print(f"  {name}: {assignments[name].full_id()}")
        return

    if not provider and not model:
        assignments = get_model_assignments()
        current = assignments.get(phase)
        if current is None:
            print(f"No model configured for phase '{phase}'")
            return
        print(f"  {phase}: {current.full_id()}")
        return

    if not provider or not model:
        print(f"Model config for phase '{phase}' requires both --provider and --model", file=sys.stderr)
        sys.exit(2)

    try:
        saved = set_model_assignment(phase, provider, model)
    except (ValueError, OSError) as e:
        print(f"Model config failed: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Model for phase '{phase}' set to {saved.full_id()}")


if __name__ == "__main__":
    main()
