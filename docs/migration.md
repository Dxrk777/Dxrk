# Migración single-tenant → multi-tenant

`dxrk/tenant/migration.py`: migración **idempotente** del layout legado
(`~/.dxrk/*` suelto) al layout por tenant (`~/.dxrk/tenants/default/`).
Ver también `tenants.md` para el layout destino.

## Qué migra

| Origen legado | Destino en `tenants/default/` |
|---------------|-------------------------------|
| `palace/sqlite_palace.db` (+ sidecars `-wal`/`-shm`) | `palace/sqlite_palace.db` |
| `locks/` | `locks/` |
| `knowledge_graph.sqlite3` | `knowledge_graph.sqlite3` |
| `identity.txt` | `identity.txt` |
| `config.yaml` | `config.yaml` |
| `settings.json` | `settings.json` |
| `vault.enc` | `vault.enc` |
| `memories.json` | `memories.json` |
| `iq.json` | `iq.json` |

## Garantías

- **No borra el legado**: solo copia (`moved` siempre vacío, se mantiene por
  compatibilidad en el dict de retorno).
- **Idempotente**: si el destino ya existe se registra como `skipped`;
  directorios se fusionan (solo faltantes). Segunda corrida → `copied == []`.
- **Permisos**: dirs `0o750`, archivos `0o600` (incluidos sidecars sqlite).
- **`dry_run=True`**: no muta nada, reporta el plan (`"origen -> destino"`).
- Al final (no dry-run) escribe `tenants/_registry.json`
  (`default` / `Default (migrated)` / `single-tenant`) y `tenants/_active`
  (`default`).

```bash
dxrk-py tenant migrate           # corre la migración
```

```python
from dxrk.tenant import migrate_legacy_to_default, is_migrated

plan = migrate_legacy_to_default(dry_run=True)
result = migrate_legacy_to_default()  # {"moved", "copied", "skipped"}
```

## Nota para tests

`LEGACY_PATHS` se materializa a import time con el HOME real: los tests que
aíslan HOME deben re-apuntarlo vía `monkeypatch.setattr` (la cabecera de
`migration.py` lo documenta). Patrón en
`tests/test_enterprise_cli_migration.py`.
