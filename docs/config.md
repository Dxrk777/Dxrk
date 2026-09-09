# Configuración

Dxrk lee su configuración de varias capas con una **escalera de prioridad** fija: la primera capa que define un valor gana. De mayor a menor prioridad:

| # | Capa | Origen |
|---|---|---|
| 1 | Flags CLI | `--model`, `--tenant`, etc. (solo runtime, no persisten) |
| 2 | Variables de entorno | `DXRK_*` (p. ej. `DXRK_TENANT`, `DXRK_MODEL`) |
| 3 | Settings de proyecto | `.dxrk/settings.json` |
| 4 | Settings de tenant | store tenant (prioridad 150) |
| 5 | Settings de usuario | `~/.dxrk/settings.json` |
| 6 | Config de proyecto | `.dxrk/config.yaml` |
| 7 | Config de usuario | `~/.dxrk/config.yaml` |
| 8 | Config global | `/etc/dxrk/config.yaml` |
| 9 | Defaults internos | `HierarchicalConfig` en `dxrk/config/config.py` |

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
4. El tenant solo afecta hoy a la capa 4 (settings); `config.yaml` aún no es tenant-aware — es parte del plan v2.0 ([ADR-004](adr/ADR-004-config-unify.md)).
