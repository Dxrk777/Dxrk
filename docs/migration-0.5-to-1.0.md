# Migración beta 0.5 → GA 1.0

Guía corta para pasar de la beta multi-tenant a la GA sin sorpresas.
La migración de datos legacy ya está cubierta en `migration.md` (no se duplica aquí).

## Qué cambia en 1.0.0

1. **Enforcement RBAC activo con `DXRK_USER`** (`dxrk/security/enforcement.py`).
   `require_op(tenant, user, op)` con ops `read`/`mine`/`manage`:
   `read` ← `fs.read` (los 3 roles pasan), `mine` ← `fs.write`
   (solo `admin`/`dev`), `manage` ← `sudo` (solo `admin`).
   Sin `DXRK_USER` no hay identidad y no se enforcea (ver punto 4).
   Superficies: `tenant create/delete` (manage), `python -m dxrk.memory
   mine/search` (mine/read) y tools MCP de escritura
   (`add/update/delete_drawer`, `mine`, `kg_add`, `kg_invalidate` → mine;
   denegado responde error `RBAC_DENIED` con `isError=true`).
2. **`roles.json` defaults `readonly`** (`dxrk/security/rbac.py`).
   Archivo por tenant `~/.dxrk/tenants/{id}/roles.json`
   (`{"users": {"alice": "admin"}, "default_role": "readonly"}`, `0o600`).
   Archivo ausente o usuario desconocido → `readonly`.
3. **`STATE` proxy compat** (`dxrk/tui/shared.py`, R11 cerrado).
   `from dxrk.tui.shared import STATE` sigue funcionando: reenvía al
   `ContextVar` actual (`get_ctx()` / `DxrkApp.ctx`). Código nuevo debe usar
   `get_ctx()`, pero nada viejo se rompe.
4. **Modo local sin tenant no rompe nada.**
   `tenant_id` vacío o `user` vacío → `require_op` devuelve `""` sin denegar
   (local trusted mode). Sin `--tenant` ni `DXRK_TENANT` ni `DXRK_USER`,
   todo funciona como en 0.5.

## Pasos

```bash
dxrk-py tenant migrate              # legacy → tenants/default (idempotente, ver migration.md)
dxrk-py tenant create acme
dxrk-py tenant switch acme
DXRK_USER=alice dxrk-py --tenant acme query "..."   # alice → rol según roles.json
```

- Dar rol: editar `~/.dxrk/tenants/acme/roles.json`
  (`users` + `default_role`) o `TenantRoleResolver("acme").set_user_role("alice", "admin")`.
- TUI: tecla `t` abre el switcher; el badge muestra `tenant: {id} · role: {rol}`.
- Sin `DXRK_USER`: se opera en modo local (sin enforcement), igual que en beta.

## Enlaces

- Migración de datos legacy (idempotente, `dry_run`, permisos): `migration.md`.
- Layout, CLI `--tenant`/`DXRK_TENANT` y aislamiento: `tenants.md`.
- Roles, capas de enforcement y `roles.json`: `rbac.md`.
- Enforcement (`read`/`mine`/`manage` + trusted mode): `dxrk/security/enforcement.py`.
