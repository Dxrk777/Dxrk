# SPDX-License-Identifier: MIT
"""Config command"""

from __future__ import annotations

import json
import os
from typing import Any

from dxrk.config import Config, Default, Load, Save
from dxrk.security.enforcement import require_op, resolve_user

from .registry import Command, CommandContext, Flag, Registry


def user_config_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".dxrk", "config.yaml")


def load_user_config() -> Config:
    path = user_config_path()
    if os.path.exists(path):
        return Load(path)
    return Default()


def save_user_config(cfg: Config) -> None:
    os.makedirs(os.path.dirname(user_config_path()), mode=0o750, exist_ok=True)
    Save(user_config_path(), cfg)


def register_config_command(reg: Registry) -> None:
    """Registers the `dxrk config` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        path = user_config_path()
        if not os.path.exists(path):
            out.write(f"No se encontró el archivo de configuración en {path}\n")
            out.write("Ejecuta 'dxrk init' para crear uno.\n")
            return 0

        cfg = load_user_config()
        out.write(f"Configuración: {path}\n")
        out.write(f"Proyecto: {cfg.project.name} ({cfg.project.root})\n")
        out.write(f"Proveedor predeterminado: {cfg.project.default_provider}\n\n")
        out.write("Proveedores:\n")
        for p in cfg.providers:
            env = p.api_key_env or "-"
            out.write(f"  {p.name:<10} {p.model:<30} env={env}\n")
        if cfg.sandbox is not None:
            out.write(f"\nImagen de sandbox: {cfg.sandbox.default_image}\n")
        return 0

    cmd = Command(
        name="config",
        short="Mostrar la configuración actual",
        run=run,
    )
    reg.add_command(cmd)
    reg.add_command(_config_get_cmd())
    reg.add_command(_config_set_cmd())
    reg.add_command(_config_layers_cmd())
    reg.add_command(_config_migrate_cmd())


def _unified_config(tenant_id: str = ""):  # type: ignore[no-untyped-def]
    """Builds a tenant-aware UnifiedConfig and loads both layers.

    All paths resolve at call time (not import time) so tests isolating
    HOME/cwd via monkeypatch behave correctly.
    """
    from dxrk.config.config import ConfigManager, WithGlobalPath, WithProjectPath, WithTenantPath, WithUserPath
    from dxrk.config.unified import UnifiedConfig

    opts = [
        WithGlobalPath("/etc/dxrk/config.yaml"),
        WithUserPath(user_config_path()),
        WithProjectPath(".dxrk/config.yaml"),
    ]
    tid = (tenant_id or "").strip()
    if tid:
        try:
            from dxrk.tenant.migration import tenant_root

            opts.append(WithTenantPath(str(tenant_root(tid) / "config.yaml")))
        except Exception:
            pass
    uni = UnifiedConfig(config=ConfigManager(opts))
    uni.load()
    return uni


def _parse_cli_value(raw: str) -> Any:
    """Parses a CLI value: JSON first (numbers, bools, quoted strings), else raw string."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


def _config_get_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        try:
            require_op(ctx.tenant_id, resolve_user(), "read")
        except PermissionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        uni = _unified_config(ctx.tenant_id)
        try:
            value = uni.get_typed(ctx.args[0])
        except ValueError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        ctx.out.write(f"{value}\n" if value is not None else "(sin valor)\n")
        return 0

    return Command(
        name="config get",
        short="Leer un valor de la escalera unificada (p. ej. ui.theme)",
        min_args=1,
        max_args=1,
        run=run,
    )


def _config_set_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        try:
            require_op(ctx.tenant_id, resolve_user(), "write")
        except PermissionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        uni = _unified_config(ctx.tenant_id)
        path, raw = ctx.args[0], ctx.args[1]
        if path.split(".")[0] == "settings":
            ctx.err.write("Error: la sección settings.* es de solo lectura; usa 'dxrk config migrate'\n")
            return 1
        try:
            uni.set_typed(path, _parse_cli_value(raw))
        except ValueError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        tid = ctx.tenant_id.strip()
        if tid:
            _save_tenant_snapshot(tid, uni)
            ctx.out.write(f"{path} actualizado en tenant {tid}\n")
        else:
            uni.config.Save()
            ctx.out.write(f"{path} actualizado\n")
        return 0

    return Command(
        name="config set",
        short="Escribir un valor (persiste vista fusionada en usuario o tenant)",
        min_args=2,
        max_args=2,
        run=run,
    )


def _save_tenant_snapshot(tenant_id: str, uni) -> None:  # type: ignore[no-untyped-def]
    """Persists the merged config snapshot as tenant YAML (0o600)."""
    import yaml

    from dxrk.tenant.migration import tenant_root

    root = tenant_root(tenant_id)
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o750)
    except OSError:
        pass
    from dataclasses import asdict

    data = asdict(uni.config.Config())
    target = root / "config.yaml"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    os.replace(tmp, target)
    try:
        target.chmod(0o600)
    except OSError:
        pass


def _config_layers_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        try:
            require_op(ctx.tenant_id, resolve_user(), "read")
        except PermissionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        uni = _unified_config(ctx.tenant_id)
        path = ctx.args[0]
        effective = uni.get_typed(path)
        rows = _layer_rows(path, uni)
        ctx.out.write(f"{path} = {effective!r}\n")
        winner_marked = False
        for name, present, value in rows:
            mark = ""
            if present and not winner_marked and value == effective and effective is not None:
                mark = " <-- gana"
                winner_marked = True
            shown = "—" if value is None else repr(value)
            ctx.out.write(f"  [{name}] {shown}{mark}\n")
        return 0

    return Command(
        name="config layers",
        short="Mostrar qué capa gana para una ruta (p. ej. ui.theme)",
        min_args=1,
        max_args=1,
        run=run,
    )


def _config_migrate_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        try:
            require_op(ctx.tenant_id, resolve_user(), "write")
        except PermissionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        from dxrk.config.migration import migrate_settings_to_yaml

        dry = ctx.flag_bool("dry-run", False)
        result = migrate_settings_to_yaml(dry_run=dry, tenant=ctx.tenant_id)
        out = ctx.out
        out.write(f"{len(result['copied'])} clave(s) migradas, {len(result['skipped'])} omitidas\n")
        for c in result["copied"]:
            out.write(f"  migrada: {c}\n")
        return 0

    return Command(
        name="config migrate",
        short="Migrar settings.json a la sección settings de config.yaml (idempotente)",
        flags={"dry-run": Flag("dry-run", is_bool=True, help="Mostrar el plan sin escribir")},
        run=run,
    )


def _layer_rows(path: str, uni) -> list[tuple[str, bool, Any]]:  # type: ignore[no-untyped-def]
    """Probes each ladder layer for a dotted path. Returns (name, seen, value)."""
    rows: list[tuple[str, bool, Any]] = []

    # L2 env
    env_name = "DXRK_" + path.upper().replace(".", "_")
    env_val = os.environ.get(env_name)
    rows.append((f"env {env_name}", env_val is not None, env_val))

    # L6/L7/L8/L9 file layers (global, user, tenant, project YAML)
    cfg = uni.config
    candidates = [
        ("global", getattr(cfg, "_global_path", "")),
        ("user", getattr(cfg, "_user_path", "")),
        ("tenant", _active_tenant_path()),
        ("project", getattr(cfg, "_project_path", "")),
    ]
    for name, file_path in candidates:
        rows.append((f"yaml {name}", *_read_yaml_path(file_path, path)))

    # L10 defaults
    try:
        from dxrk.config.config import default_hierarchical_config

        defaults = default_hierarchical_config()
        node: Any = defaults
        for part in path.split("."):
            node = getattr(node, part)
        rows.append(("defaults", True, node))
    except Exception:
        rows.append(("defaults", False, None))
    return rows


def _active_tenant_path() -> str:
    tid = (os.environ.get("DXRK_TENANT", "") or "").strip()
    if not tid:
        return ""
    try:
        from dxrk.tenant.migration import tenant_root

        return str(tenant_root(tid) / "config.yaml")
    except Exception:
        return ""


def _read_yaml_path(file_path: str, path: str) -> tuple[bool, Any]:
    """Reads a dotted path from a YAML file. Returns (seen, value)."""
    import yaml

    if not file_path or not os.path.exists(file_path):
        return False, None
    try:
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return False, None
    if not isinstance(data, dict):
        return False, None
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node
