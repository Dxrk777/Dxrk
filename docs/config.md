# Configuración

Dxrk lee su configuración de varias capas con una **escalera de prioridad** fija: la primera capa que define un valor gana. De mayor a menor prioridad:

| # | Capa | Origen |
|---|---|---|
| 1 | Overrides runtime | `UnifiedConfig.override()` (p. ej. flags CLI; solo runtime, no persisten) |
| 2 | Variables de entorno | `DXRK_*` (p. ej. `DXRK_TENANT`, `DXRK_UI_THEME`) |
| 3 | Settings de proyecto | `.dxrk/settings.json` |
| 4 | Settings de tenant | store tenant (prioridad 150) |
| 5 | Settings de usuario | `~/.dxrk/settings.json` |
| 6 | Config de proyecto | `.dxrk/config.yaml` |
| 7 | Config de tenant | `~/.dxrk/tenants/<tid>/config.yaml` (vía `DXRK_TENANT` o `WithTenantPath`) |
| 8 | Config de usuario | `~/.dxrk/config.yaml` |
| 9 | Config global | `/etc/dxrk/config.yaml` |
| 10 | Defaults internos | `HierarchicalConfig` en `dxrk/config/config.py` |

## Dos sistemas, una fachada

Históricamente hay dos sistemas (ver [ADR-004](adr/ADR-004-config-unify.md) para el plan de unificación v2.0):

- **Config jerárquica tipada** (`config.yaml`): secciones `model`, `api`, `auth`, `session`, `tools`, `ui`, `advanced`. Se lee con rutas de puntos: `model.provider`, `ui.theme`.
- **Settings planos** (`settings.json`): clave-valor libre (`theme`, `last_tenant`, ...), con stores por prioridad (proyecto 200 > tenant 150 > usuario 100).

La fachada `UnifiedConfig` (`dxrk/config/unified.py`) une ambas:

```python
from dxrk.config.unified import UnifiedConfig

cfg = UnifiedConfig()
cfg.load()
provider = cfg.get_typed("model.provider")  # jerárquico, None si falta
theme = cfg.get_raw("theme")                # plano, KeyError si falta
cfg.set_typed("ui.theme", "dark")
cfg.save()  # persiste ambas capas
```

## Variables de entorno

Todas empiezan por `DXRK_` (prefijo configurable). Las más usadas:

```bash
export DXRK_TENANT=acme   # tenant activo (ver tenants.md)
export DXRK_USER=alice    # usuario para enforcement RBAC (ver rbac.md)
```

## Reglas prácticas

1. **Secretos nunca en YAML/JSON** — usa variables de entorno o el vault por tenant (`DXRK_VAULT_KEY`).
2. **`config.yaml` admite comentarios**; `settings.json` no — prefiere YAML para lo que edites a mano.
3. **Proyecto > usuario**: lo que pongas en `.dxrk/` del repo gana sobre tu `~/.dxrk/`.
4. El tenant afecta a la capa 4 (settings) y a la capa 7 (`config.yaml` por tenant). Los aliases `CamelCase` de `UnifiedConfig` están deprecados (aviso `DeprecationWarning`, se remueven no antes de v3.0) — ver [ADR-004](adr/ADR-004-config-unify.md).

## CLI unificada (`dxrk config get/set/layers`)

Lee y escribe a través de `UnifiedConfig` (todas las rutas se resuelven a
call-time, tenant-aware vía `--tenant`/`DXRK_TENANT`):

```bash
dxrk config get ui.theme
dxrk config layers ui.theme     # muestra cada capa y cuál gana
dxrk config set ui.theme dark
dxrk --tenant acme config set ui.theme acme-dark   # persiste en el tenant
```

- `get`/`layers` requieren op `read`; `set` requiere op `write`
  (`readonly` recibe `RBAC_DENIED` en `set`).
- `set` persiste la vista fusionada (en usuario o tenant); las capas
  inferiores siguen aplicando por debajo. La sección `settings.*` es de
  solo lectura en `set` (para no romper el fallback de claves libres);
  esas claves llegan a YAML vía `migrate`.
- Valores con formato JSON (`50`, `true`, `"texto"`) se tipan; el resto
  queda como string.

## Migración `settings.json` → `config.yaml`

```bash
dxrk config migrate --dry-run   # plan sin escribir
dxrk config migrate              # mueve claves planas a la sección settings:
                                 #   ~/.dxrk/settings.json → ~/.dxrk/config.yaml
                                 #   .dxrk/settings.json   → .dxrk/config.yaml
dxrk --tenant acme config migrate  # además las siembra en el tenant
```

- Idempotente: las claves ya presentes se omiten; segunda corrida no escribe.
- Cada YAML reescrito conserva backup `.bak` (solo primera vez).
- Nota: el volcado YAML no preserva comentarios del archivo previo
  (limitación de PyYAML); el `.bak` permite recuperarlos.
- Las claves migradas se leen como `settings.<clave>` en toda la escalera
  (incluida la capa 7 de tenant).
