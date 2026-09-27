# Sesiones — durabilidad + backend SQLite opt-in

Persistencia de sesiones (`dxrk/utils/session_storage.py`,
`dxrk/commands/session.py`): un crash nunca deja un archivo roto, un
índice corrupto se reconstruye solo y un payload corrupto se cuarentena
en vez de romper el listado.

## Comandos

```bash
dxrk-py session list                    # lista (IDs truncados a 8 chars)
dxrk-py session create [título]         # crea
dxrk-py session info <id>               # detalle
dxrk-py session switch <id>             # cambia la activa
dxrk-py session delete <id>             # borra
dxrk-py rewind <id> <count>             # recorta últimos <count> mensajes
dxrk-py resume [id|título] [--limit N]  # retoma por prefijo de ID o título
dxrk-py share <id> --output f.md        # exporta (requiere --output o ruta; --force si existe)
```

Cobertura actual: `rewind.py` 98%, `resume.py` 100%, `share.py` 100%
(`tests/test_commands_rewind_resume_share.py`, 33 tests).

## Durabilidad — escrituras atómicas

`_atomic_write_text()` en todos los paths de escritura (`FileStorage` y
`SQLiteSessionStorage` vía su propia transaccionalidad):

1. tmp en el mismo directorio + `fsync` del archivo,
2. `os.replace` (rename atómico),
3. `fsync` best-effort del directorio padre (portable: en Windows el
   `fsync` de directorios falla y se ignora).

Errores con etapa etiquetada (`write temp` / `atomic rename`).

## Índice — self-heal + fallback `.gz`

- `FileStorage` mantiene `.index.json`; si falta o está corrupto se
  reconstruye desde disco (`_rebuild_index_from_disk`) y el siguiente
  arranque lo persiste.
- Lectura con fallback: si el `.json` está roto se intenta su copia
  `.json.gz` antes de rendirse (error `SessionError` si ambas fallan).
- Migración-on-load: cada payload pasa por `migrate_to_current()`
  (`dxrk/utils/session_migrate.py`); si la migración falla, el raw pasa
  tal cual (sin romper la carga).

## Cuarentena

`list_session_files_with_quarantine()` (`dxrk/commands/session.py`):
archivos legibles-pero-corruptos se mueven a
`<sessions>/.quarantine/` (`QUARANTINE_DIR_NAME`) y el listado avisa:

```text
Advertencia: N archivo(s) de sesión corrupto(s) movido(s) a cuarentena.
```

Cada sesión corrupta pone en cuarentena a sus hermanos
(`<id>.json` y/o `<id>.json.gz` si ambos están corruptos); una copia
sana nunca se mueve (el store lee `.json` primero y usa `.gz` como
fallback). Con el backend SQLite no hay archivos que mover: las filas
corruptas se omiten y se cuentan con un aviso ajustado
(`fila(s) ... omitida(s) ... sin cuarentena en disco`).

Nombres no-sesión (`.index.json`, tmps, sufijos que no son
`.json`/`.json.gz`) y directorios (incluido `.quarantine/`) se ignoran.

## IDs sanitizados — sin path traversal

`_validate_session_id()` (compartida por todos los stores en disco)
rechaza IDs vacíos, `.`/`..`, separadores, bytes NUL y cualquier cosa
que resuelva fuera del directorio base.

## Backend SQLite-WAL opt-in

```bash
DXRK_SESSION_BACKEND=sqlite dxrk-py session list
```

- `open_session_storage()` elige el backend:
  `DXRK_SESSION_BACKEND=sqlite` → `SQLiteSessionStorage` (WAL);
  cualquier otro valor → `FileStorage` (default, dir JSON).
- El CLI honra la variable de punta a punta: `session
  list/create/switch/delete/info` (más `rename`, `rewind`, `tag`,
  `resume`, `share`) operan sobre el store seleccionado — con
  `sqlite`, `list`/`info` leen de `sessions.db`.
- Misma semántica (`save`/`load`/`delete`/`exists`/`list`,
  contrato `SessionError`, sanitización, migración-on-load).
- Diferencia intencional (fijada en test): una fila con payload corrupto
  es **visible** en `list` de SQLite pero `load` lanza `SessionError`;
  `FileStorage` en cambio descarta el `.json` roto (usa el `.gz` o lo
  cuarentena) — ver
  `tests/test_session_phase03_sqlite.py::test_pinned_difference_corrupt_visibility`.
- Migración JSON→SQLite: `migrate_json_dir_to_sqlite()` (lee `*.json` +
  `*.json.gz` solo-comprimidos vía `FileStorage.load`, reporta
  `skipped_ids`).
- Suite de conformancia: `tests/test_session_phase03_sqlite.py`
  (29 tests).

## Linkage sesión↔swarm

El coordinador swarm registra cada task/resultado contra su sesión
(`dxrk/utils/swarm_session.py`: `SwarmTaskStore`,
`session_summary(session_id)` → `"session <id>: swarm c/s tasks
completed"`). Ver release notes
[`releases/v1.3.0.md`](releases/v1.3.0.md) § Swarm.

## Verificación

```bash
uv run python -m pytest -q tests/test_commands_rewind_resume_share.py tests/test_commands_session.py tests/test_session_phase01_safety.py tests/test_session_phase02_unify.py tests/test_session_phase03_sqlite.py
```
