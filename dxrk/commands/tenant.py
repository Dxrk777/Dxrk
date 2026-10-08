# SPDX-License-Identifier: MIT
"""Tenant command — multi-tenant management (R07)"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from dxrk.security.enforcement import require_op, resolve_user
from dxrk.security.jwt import validate_id
from dxrk.security.rbac import VALID_ROLES, TenantRoleResolver
from dxrk.tenant.migration import ensure_tenant, is_migrated, migrate_legacy_to_default, tenant_root

from .registry import Command, CommandContext, Flag, Registry


def _tenants_root() -> Path:
    return Path.home() / ".dxrk" / "tenants"


def _active_path() -> Path:
    return _tenants_root() / "_active"


def _read_active() -> str:
    p = _active_path()
    try:
        if not p.exists():
            return ""
        text = p.read_text(encoding="utf-8")
        # only first line, strip
        line = text.strip().splitlines()[0] if text.strip() else ""
        return line.strip()
    except OSError:
        return ""


def _write_active(tenant_id: str) -> bool:
    try:
        root = _tenants_root()
        root.mkdir(parents=True, exist_ok=True)
        try:
            root.chmod(0o750)
        except OSError:
            pass
        p = _active_path()
        p.write_text(tenant_id, encoding="utf-8")
        try:
            p.chmod(0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False


def _effective_tenant(ctx: CommandContext | None = None) -> str:
    # priority: ctx.tenant_id > env DXRK_TENANT > _active > default if migrated
    if ctx is not None and ctx.tenant_id:
        tid = ctx.tenant_id.strip()
        if tid:
            return tid
    env = os.environ.get("DXRK_TENANT", "").strip()
    if env:
        return env
    active = _read_active()
    if active:
        return active
    try:
        if is_migrated():
            return "default"
    except Exception:
        pass
    return ""


def _list_tenants() -> list[str]:
    root = _tenants_root()
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    tenants: list[str] = []
    for e in entries:
        if e.is_dir():
            name = e.name
            # validate via validate_id and exclude hidden? tenant ids are validated
            if validate_id(name):
                tenants.append(name)
    return sorted(tenants)


def register_tenant_command(reg: Registry) -> None:
    """Registers the `dxrk tenant` command and its subcommands."""

    def parent_run(ctx: CommandContext) -> int:
        ctx.err.write("Error: usa 'dxrk tenant list', 'create', 'switch', 'current', 'delete', 'whoami' o 'migrate'\n")
        return 1

    def list_run(ctx: CommandContext) -> int:
        tenants = _list_tenants()
        if not tenants:
            ctx.out.write("No se encontraron tenants.\n")
            return 0
        active = _effective_tenant(ctx)
        for t in tenants:
            marker = " * activo" if t == active else ""
            ctx.out.write(f"{t}{marker}\n")
        return 0

    def create_run(ctx: CommandContext) -> int:
        try:
            require_op(_effective_tenant(ctx), resolve_user(), "manage")
        except PermissionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        tid = ctx.args[0].strip() if ctx.args else ""
        if not validate_id(tid):
            ctx.err.write(f"Error: id de tenant inválido {tid!r}\n")
            return 1
        try:
            ensure_tenant(tid)
        except ValueError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        except OSError as exc:
            ctx.err.write(f"Error: al crear el tenant: {exc}\n")
            return 1
        ctx.out.write(f"Tenant {tid} creado\n")
        return 0

    def switch_run(ctx: CommandContext) -> int:
        tid = ctx.args[0].strip() if ctx.args else ""
        if not validate_id(tid):
            ctx.err.write(f"Error: id de tenant inválido {tid!r}\n")
            return 1
        # check exists
        try:
            p = tenant_root(tid)
        except ValueError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        if not p.exists() or not p.is_dir():
            ctx.err.write(f"Error: tenant {tid!r} no encontrado\n")
            return 1
        if not _write_active(tid):
            ctx.err.write("Error: al escribir el tenant activo\n")
            return 1
        # propagate to env for current process
        os.environ["DXRK_TENANT"] = tid
        ctx.out.write(f"Tenant activo: {tid}\n")
        return 0

    def current_run(ctx: CommandContext) -> int:
        tid = _effective_tenant(ctx)
        if not tid:
            ctx.out.write("No hay tenant actual\n")
            return 0
        ctx.out.write(f"{tid}\n")
        return 0

    def delete_run(ctx: CommandContext) -> int:
        try:
            require_op(_effective_tenant(ctx), resolve_user(), "manage")
        except PermissionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        tid = ctx.args[0].strip() if ctx.args else ""
        if not validate_id(tid):
            ctx.err.write(f"Error: id de tenant inválido {tid!r}\n")
            return 1
        force = ctx.flag_bool("force", False)
        if not force:
            ctx.err.write(f"Error: usa --force para eliminar el tenant {tid!r}\n")
            return 1
        try:
            p = tenant_root(tid)
        except ValueError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        if not p.exists():
            ctx.err.write(f"Error: tenant {tid!r} no encontrado\n")
            return 1
        try:
            shutil.rmtree(p)
        except OSError as exc:
            ctx.err.write(f"Error: al eliminar el tenant: {exc}\n")
            return 1
        # clean _active if points to deleted
        if _read_active() == tid:
            try:
                _active_path().unlink()
            except OSError:
                pass
            if os.environ.get("DXRK_TENANT") == tid:
                os.environ.pop("DXRK_TENANT", None)
        ctx.out.write(f"Tenant {tid} eliminado\n")
        return 0

    def whoami_run(ctx: CommandContext) -> int:
        tid = _effective_tenant(ctx)
        if not tid:
            ctx.out.write("Sin tenant\n")
            return 0
        ctx.out.write(f"{tid}\n")
        return 0

    def migrate_run(ctx: CommandContext) -> int:
        try:
            result = migrate_legacy_to_default()
        except Exception as exc:
            ctx.err.write(f"Error: al migrar: {exc}\n")
            return 1
        copied = result.get("copied", [])
        skipped = result.get("skipped", [])
        ctx.out.write(f"{len(copied)} archivo(s) migrados, {len(skipped)} omitidos\n")
        for c in copied:
            ctx.out.write(f"  copiado: {c}\n")
        return 0

    # RBAC Role commands
    def role_list_run(ctx: CommandContext) -> int:
        try:
            require_op(_effective_tenant(ctx), resolve_user(), "manage")
        except PermissionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        tid = _effective_tenant(ctx)
        resolver = TenantRoleResolver(tid)
        data = resolver.load()
        users = data.get("users", {})
        default_role = data.get("default_role", "readonly")
        ctx.out.write(f"Tenant: {_effective_tenant(ctx)} (default: {default_role})\n")
        if not users:
            ctx.out.write("  (sin asignaciones de usuario)\n")
        else:
            for user, role in sorted(users.items()):
                ctx.out.write(f"  {user}: {role}\n")
        return 0

    def role_set_run(ctx: CommandContext) -> int:
        try:
            require_op(_effective_tenant(ctx), resolve_user(), "manage")
        except PermissionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        tid = _effective_tenant(ctx)
        if len(ctx.args) < 2:
            ctx.err.write("Error: usa 'dxrk tenant role set <user> <role>'\n")
            return 1
        user = ctx.args[0]
        role = ctx.args[1]
        if role not in VALID_ROLES:
            ctx.err.write(f"Error: rol inválido {role!r}. Válidos: {', '.join(VALID_ROLES)}\n")
            return 1
        resolver = TenantRoleResolver(tid)
        try:
            resolver.set_user_role(user, role)
        except ValueError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        ctx.out.write(f"Usuario {user} -> rol {role} en tenant {_effective_tenant(ctx)}\n")
        return 0

    def role_default_run(ctx: CommandContext) -> int:
        try:
            require_op(_effective_tenant(ctx), resolve_user(), "manage")
        except PermissionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        tid = _effective_tenant(ctx)
        if not ctx.args:
            ctx.err.write("Error: usa 'dxrk tenant role default <role>'\n")
            return 1
        role = ctx.args[0]
        if role not in VALID_ROLES:
            ctx.err.write(f"Error: rol inválido {role!r}. Válidos: {', '.join(VALID_ROLES)}\n")
            return 1
        resolver = TenantRoleResolver(tid)
        data = resolver.load()
        users = data.get("users", {})
        try:
            resolver.save(users, role)
        except ValueError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        ctx.out.write(f"Rol por defecto del tenant {tid} -> {role}\n")
        return 0

    def role_show_run(ctx: CommandContext) -> int:

        tid = _effective_tenant(ctx)
        resolver = TenantRoleResolver(tid)
        role = resolver.resolve(ctx.args[0] if ctx.args else resolve_user())
        ctx.out.write(f"{role}\n")
        return 0

    parent_cmd = Command(name="tenant", short="Gestionar tenants", run=parent_run)
    list_cmd = Command(name="tenant list", short="Listar tenants", run=list_run)
    create_cmd = Command(
        name="tenant create",
        short="Crear un tenant",
        min_args=1,
        max_args=1,
        run=create_run,
    )
    switch_cmd = Command(
        name="tenant switch",
        short="Cambiar el tenant activo",
        min_args=1,
        max_args=1,
        run=switch_run,
    )
    current_cmd = Command(name="tenant current", short="Mostrar el tenant actual", run=current_run)
    delete_cmd = Command(
        name="tenant delete",
        short="Eliminar un tenant",
        min_args=1,
        max_args=1,
        flags={"force": Flag("force", is_bool=True, help="Forzar la eliminación")},
        run=delete_run,
    )
    whoami_cmd = Command(name="tenant whoami", short="Mostrar el id de tenant", run=whoami_run)
    migrate_cmd = Command(name="tenant migrate", short="Migrar datos heredados", run=migrate_run)

    # RBAC subcommands
    role_parent_cmd = Command(
        name="tenant role",
        short="Gestionar roles RBAC",
        run=lambda ctx: ctx.err.write("Error: usa 'dxrk tenant role list|set|default|show'\n") or 1,
    )
    role_list_cmd = Command(name="tenant role list", short="Listar roles de usuarios", run=role_list_run)
    role_set_cmd = Command(
        name="tenant role set", short="Asignar rol a usuario", min_args=2, max_args=2, run=role_set_run
    )
    role_default_cmd = Command(
        name="tenant role default", short="Cambiar rol por defecto", min_args=1, max_args=1, run=role_default_run
    )
    role_show_cmd = Command(
        name="tenant role show", short="Mostrar rol de usuario", min_args=0, max_args=1, run=role_show_run
    )

    reg.add_command(parent_cmd)
    reg.add_command(list_cmd)
    reg.add_command(create_cmd)
    reg.add_command(switch_cmd)
    reg.add_command(current_cmd)
    reg.add_command(delete_cmd)
    reg.add_command(whoami_cmd)
    reg.add_command(migrate_cmd)
    reg.add_command(role_parent_cmd)
    reg.add_command(role_list_cmd)
    reg.add_command(role_set_cmd)
    reg.add_command(role_default_cmd)
    reg.add_command(role_show_cmd)
