# Tutorial: de cero a memoria multi-tenant en 10 minutos

Cada comando de esta guía fue ejecutado tal cual contra Dxrk 1.0.0.
Si algo difiere en tu máquina, abre un issue: el tutorial no miente.

## 0) Instala (1 min)

```bash
uv tool install dxrk
# o: pip install dxrk
dxrk-py --version   # Dxrk v1.0.0
```

Requisito: Python 3.13+.

## 1) Vista previa del setup (1 min)

Antes de tocar tu `~/.claude.json` o equivalentes, mira qué haría:

```bash
dxrk-py install --agent claude-code --preset full-dxrk --dry-run
```

Verás agentes detectados, componentes y preset. Sin `--dry-run` escribe la
configuración real. Presets: `full-dxrk`, `ecosystem-only`, `minimal`, `custom`.

## 2) Crea tu primer tenant (2 min)

```bash
dxrk-py --tenant acme tenant create acme
dxrk-py --tenant acme tenant list
DXRK_TENANT=acme dxrk-py tenant whoami   # acme
```

Esto crea `~/.dxrk/tenants/acme/` (dirs `0o750`, archivos `0o600`).
El flag `--tenant` y la variable `DXRK_TENANT` son equivalentes.
`tenant switch acme` lo deja como activo para no repetir el flag.

## 3) Indexa tu código (2 min)

```bash
python -m dxrk.memory mine ./mi-proyecto
# mine: {'files_mined': 12, 'files_skipped': 3, 'drawers_added': 40}
```

Notas honestas:

- Indexa archivos de código (p. ej. `.py`); los `.txt` se omiten.
- Fragmentos de menos de ~50 caracteres se omiten (ruido).
- Todo queda en `~/.dxrk/memory/sqlite_palace.db` (SQLite FTS5, sin servidor).

## 4) Busca (2 min)

```bash
python -m dxrk.memory search "arquitectura memoria" --n 5
# {"id": "drawer_default_general_...", "content": "...", "project": "default"}
```

Semántica: multi-palabra = **AND de tokens** (cada palabra debe aparecer en el
documento, en cualquier orden). Una sola palabra basta para empezar.

## 5) Prueba el RBAC (2 min)

Tres roles: `admin`, `dev`, `readonly` (defecto). El usuario sale de `DXRK_USER`:

```bash
# tenant inválido → denegado, salida 1
DXRK_TENANT="bad!id" DXRK_USER=alice python -m dxrk.memory search hola
# search denied: invalid tenant id 'bad!id'

# búsqueda con tenant válido → permitida (read lo tienen los 3 roles)
DXRK_TENANT=acme python -m dxrk.memory search "Hola Mundo"
```

Sin `DXRK_TENANT` ni `DXRK_USER` estás en modo local de confianza (sin fricción
para uso personal). En cuanto fijas tenant + usuario, el gate RBAC exige el rol.

## 6) Siguientes pasos

- [Comparativa](comparison.md): por qué local-first y cuándo no usar Dxrk.
- [Multi-tenant](tenants.md) y [RBAC](rbac.md): aislamiento, `roles.json`, vault.
- [Configuración](config.md): precedencia global → usuario → proyecto → entorno.
- `dxrk-py sync --agent claude-code --dry-run`: sincronizar tu setup.
- `dxrk-py` sin argumentos abre la TUI (conmutador de tenants incluido).
