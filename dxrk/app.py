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

APP_NAME = "dxrk"
VERSION = "dev"

HELP_TEXT = """dxrk — AI Gentle Stack ({version})

USO
  dxrk                     Iniciar la TUI interactiva
  dxrk <command> [flags]

COMANDOS
  install      Configurar los agentes de codificación IA en este equipo
  uninstall    Eliminar los archivos gestionados de Gentle AI de este equipo
  sync         Sincronizar las configs de agentes y skills con la versión actual
  update       Comprobar las actualizaciones disponibles
  upgrade      Aplicar actualizaciones a las herramientas gestionadas
  restore      Restaurar una copia de configuración
  version      Mostrar la versión

OPCIONES
  --help, -h    Mostrar esta ayuda

Ejecuta 'dxrk help' para ver este mensaje.
Documentación: https://github.com/Dxrk777/Dxrk
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
            return "ya actualizado en esta invocación"
        if os.environ.get("DXRK_NO_SELF_UPDATE") == "1":
            return "exclusión vía DXRK_NO_SELF_UPDATE"
        if self.version == "dev":
            return "versión dev"
        return None

    def check(self, stdout=sys.stdout) -> str | None:
        reason = self.skip_reason()
        if reason is not None:
            return None

        results = check_filtered(self.version, self.profile, ["dxrk"])
        target: UpdateResult | None = None
        for r in results:
            if r.tool.name == "dxrk":
                target = r
                break

        if target is None or target.status != UpdateStatus.UPDATE_AVAILABLE:
            return None

        print(f"Actualizado a v{target.latest_version}, reiniciando...", file=stdout)
        return target.latest_version


def run_cli(args: list[str]) -> int:

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
        print(f"error al detectar el sistema: {e}", file=sys.stderr)
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
        print(f"Advertencia: falló la autoactualización: {e}", file=sys.stderr)

    if not args:
        print("Modo TUI no disponible en la versión Python")
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
                print(f"la verificación de actualizaciones falló para: {', '.join(failed)}", file=sys.stderr)
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
                print(f"la verificación de actualizaciones falló para: {', '.join(failed)}", file=sys.stderr)
                return 1

            home_dir = os.path.expanduser("~")
            report = upgrade_execute(check_results, profile, home_dir, dry_run=dry_run)
            print(render_upgrade_report(report))

            for r in report.results:
                if r.err:
                    print(f"la actualización falló para {r.tool_name!r}: {r.err}", file=sys.stderr)
                    return 1
            return 0

        elif cmd == "install":
            install_result = run_install(args[1:], detection)
            if install_result.dry_run:
                print("Simulación: plan de instalación generado correctamente")
            elif install_result.verify and not getattr(install_result.verify, "ready", True):
                print("Falló la verificación posterior")
                return 1
            return 0

        elif cmd == "sync":
            from dxrk.cli.install import parse_sync_flags

            try:
                parse_sync_flags(args[1:])
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
            print("Sincronización completa")
            return 0

        elif cmd == "restore":
            print("Restaurar requiere el modo TUI")
            return 0

        else:
            print(
                f"comando desconocido {cmd!r} — ejecuta 'dxrk-py help' para ver los comandos disponibles",
                file=sys.stderr,
            )
            return 1

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
