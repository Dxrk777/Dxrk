# ADR-004: Unificación del sistema de configuración — Plan v2.0

- **Status:** Proposed (diferido a v2.0)
- **Date:** 2026-09-09
- **Deciders:** Dxrk Principal Architect
- **Context:** Fase post-GA v1.0.0 — deuda técnica documentada en roadmap (R14, v0.3.0)

## Contexto

El paquete `dxrk/config/` (v1.0.0) contiene **tres capas** con orígenes distintos:

| Módulo | Líneas | Modelo | Formato | API |
|---|---|---|---|---|
| `config.py` | 733 | Jerárquico tipado (`HierarchicalConfig`: model/api/auth/session/tools/ui/advanced) | YAML (`/etc/dxrk/config.yaml`, `~/.dxrk/config.yaml`, `.dxrk/config.yaml`) + env `DXRK_*` | `CamelCase` (espejo Go: `Get/Set/Load/Save/Validate/Watch`) |
| `settings.py` | 213 | Clave-valor plano (`SettingsManager` + stores con prioridad 0–200) | JSON (`~/.dxrk/settings.json`, `.dxrk/settings.json`) | `CamelCase` Go-style (`Get/Set/Delete/List/Save/Load`) |
| `unified.py` | 281 | Fachada: `UnifiedConfig` + adaptador `ConfigSettingsStore` (prioridad 150, tenant) | delega a ambas capas | `snake_case` + alias `CamelCase` |

La fachada `UnifiedConfig` ya define la **escalera de prioridad real** (1 CLI flags → 9 defaults), pero:

1. **Doble persistencia**: YAML + JSON, dos formatos, dos rutas, dos formas de corromperse.
2. **Doble API**: `snake_case` nuevo vs `CamelCase` legado — el código llama a ambas.
3. **Rutas no tenant-aware**: `config.yaml` es global/usuario/proyecto; solo `settings` tiene store tenant (prioridad 150). `DXRK_TENANT` no afecta a `config.py`.
4. **`_SECTION_FIELDS` duplicado**: `unified.py:18-26` re-lista los campos de las secciones que `config.py` ya define como dataclasses — divergencia garantizada.

El smoke GA (v1.0.0) confirmó que el sistema **funciona**; esto es deuda de diseño, no bug.

## Decisión (propuesta)

**Unificar en v2.0 bajo una sola API `snake_case` y una sola capa de persistencia, sin romper v1.x:**

1. `UnifiedConfig` pasa a ser **la** API pública (`dxrk config get/set`, Python `get_typed/get_raw`). `ConfigManager` y `SettingsManager` quedan como internals.
2. Persistencia única: **YAML jerárquico** como fuente de verdad; `settings.json` se migra una vez vía `tenant migrate`-style (`config migrate`) y queda como legacy read-only.
3. Rutas tenant-aware: `~/.dxrk/tenants/<tid>/config.yaml` entra en la escalera entre proyecto y usuario.
4. `CamelCase` se depreca con shims (no se borra en v2.0; se borra en v3.0).
5. `_SECTION_FIELDS` se genera por introspección de los dataclasses (`dataclasses.fields`), cero duplicación.

## Alternativas consideradas

- **Mantener las tres capas para siempre**: rechazado — la divergencia `_SECTION_FIELDS` vs dataclasses ya es un bug latente, y doble persistencia duplica los paths de corrupción.
- **Big-bang en v1.x**: rechazado — rompería `dxrk config` CLI y los stores tenant en pleno GA. v2.0 con migración idempotente es el vehículo correcto.
- **JSON como formato único**: rechazado — YAML ya soporta comentarios y es lo que edita el usuario a mano; JSON queda para stores internos.

## Consecuencias

- v2.0 requiere comando `dxrk config migrate` (idempotente, dry-run, backup) siguiendo el patrón de `tenant migrate`.
- Tests: matriz de precedencia 9 niveles (una por nivel) + roundtrip YAML→objeto→YAML.
- `docs/config.md` documenta el estado v1.x (escalera, archivos, env vars) y apunta a este ADR para v2.0.
