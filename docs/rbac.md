# RBAC en Dxrk

Tres roles, tres capas de enforcement (`dxrk/security/rbac.py`,
`dxrk/security/permissions.py`, `dxrk/security/jwt.py`).

## Roles

| Rol        | Capacidades                              | Defecto |
|------------|------------------------------------------|---------|
| `admin`    | lectura + escritura + minería + gestión de tenants | no |
| `dev`      | lectura + escritura + minería (sin borrado de tenants / sudo) | no |
| `readonly` | solo búsqueda/recuerdo (`fs.read`)       | **sí** |

Usuario desconocido → `readonly`. Los roles `member`/`viewer` que acepta
`TenantAuthorizer.VALID_ROLES` (JWT) se degradan a `readonly` en
`authorize_via_jwt` / `get_caps_for_role` / `build_permission_store_for_role`.

## Capas de enforcement

1. **Clasificación** (`classify_tool`): `Read` → `ALLOWED`, `Bash` →
   `NEEDS_PROMPT`. No distingue escritura/admin.
2. **Política** (`PermissionContext.check`): aquí vive la denegación real de
   escritura según rol. Devuelve `None` = permitido, `str` = motivo de
   denegación. Sin regla POLICY, las lecturas dan `NEEDS_PROMPT` en los 3 roles.
3. **JWT cross-tenant** (`authorize_via_jwt`): token del tenant A **no**
   autoriza nada en el tenant B (`PermissionError`); `tid` ausente o rol no
   permitido también se rechazan.
4. **Gate de dispatch** (`dxrk/security/enforcement.py`): `require_op`
   mapea `read`/`mine`/`manage` → caps `fs.read`/`fs.write`/`sudo` y
   deniega con `PermissionError("RBAC_DENIED: ...")`. Cableado en
   `tenant create/delete` (manage), `python -m dxrk.memory mine/search`
   (mine/read) y tools MCP de escritura (`_check_mcp_op`, responden
   error `RBAC_DENIED` con `isError=true`). Sin tenant o sin `DXRK_USER`
   → trusted mode local (retorna `""`, no rompe nada).

## Política por tenant

Archivo JSON por tenant (ver `TenantRoleResolver`):

```json
{"users": {"alice": "admin"}, "default_role": "readonly"}
```

- Archivo ausente → `{"users": {}, "default_role": "readonly"}`.
- API: `load` / `save` / `resolve` / `get_role` / `set_user_role` /
  `ensure_default`, más `load_policy_for_tenant` y
  `build_permission_store_for_role` (produce un `PermissionStore` funcional
  coherente con el rol).

## JWT

- Claim `tid` (fallback `tenant_id`); sin tenant → `None`.
- Clave de firma por tenant: `tenant_key_func` / `make_tenant_key_func`
  (mismo tenant misma key, distinto tenant distinta key vía
  `DXRK_JWT_SECRET_{TENANT}`; `tid` ausente → `ValueError`).
- `is_token_expired`, `classify_token` (3 clases), `parse_token_safe`
  (input malformado o firma manipulada → siempre `ValueError`, nunca
  excepciones crípticas), `redact_token` (`prefijo...sufijo`, cortos →
  `[REDACTED]`).

## Tests

Matriz rol×acción completa en `tests/test_enterprise_rbac_matrix.py`
(25 tests: 16 casos POLICY + resolución, roundtrip load/save,
`build_permission_store_for_role`, `authorize_via_jwt` cross-tenant),
`tests/test_enterprise_jwt_vault.py` (18 tests),
`tests/test_rbac_enforcement.py` (32 tests: matriz `require_op` +
wiring CLI) y `tests/test_memory_rbac.py` (30 tests: gate mine/search +
MCP `RBAC_DENIED` con `isError=true`).
