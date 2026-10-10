# ADR-005: Migración Go → Python puro — cierre de la era Go

| Campo | Valor |
|-------|-------|
| **Título** | Migración Go → Python puro: cierre de la era Go, 14 agentes curados, sin `agent/skills`, con `SECURITY.md` |
| **Estado** | **Accepted** |
| **Fecha** | 2026-10-10 |
| **Autores** | Dxrk Core |
| **Relacionado** | `docs/agents.md`, `SECURITY.md`, `dxrk/__main__.py`, `dxrk/commands/__init__.py`, `pyproject.toml`, `mkdocs.yml`, `ADR-003` |
| **Supersede** | N/A (formaliza una migración ya consumada; no revierte ningún ADR previo) |

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** Dxrk Principal Architect
- **Context:** Post-migración — el repo ya no contiene código Go; esta ADR lo declara formalmente y archiva la auditoría de la era Go.

---

## Contexto

Hasta agosto de 2026 Dxrk era un proyecto **Go**: `go.mod` con piso mínimo Go 1.25.12,
`internal/commands` (~6.028 líneas sin tests), `internal/cli`, `internal/tui`,
`internal/webui/server.go`, binario externo `dxrk-memory` descargado vía
`dxrk/components/memory.py:Download()`, 22 sitios de `exec.Command` en producción
sin auditoría dedicada, y un sistema de skills **96.9% contenido sin curar**
(import masivo de 4 fuentes externas). El conteo de agentes era inconsistente
(28 vs 42 según la fuente) y no existía `SECURITY.md` ni proceso de reporte privado.

La auditoría profunda del **2026-08-09** (`/home/dxrk/DXRK-AUDITORIA-2026-08-09.md`,
externa al repo, commit `74d6280`) describe **exclusivamente esa era Go**:
intento real de compilar Go 1.25.12 (§24), superficie `exec.Command` (§32),
conteo de agentes con fecha exacta (§29), licencias de las 4 fuentes de skills (§31).
Sus hallazgos P0–P3, scorecard y roadmap asumen `internal/`, `go.mod`, `web/src`
y el binario `dxrk-memory` — ninguno de los cuales existe ya en `main`.

El estado actual en `main` (verificado 2026-10-10):

- **Cero código Go**: `find -name "*.go" -not -path "*/.git/*"` → `0` archivos.
  No hay `go.mod`, ni `internal/`, ni `web/src`, ni binario sidecar.
- **Python puro `>=3.13`**: paquete raíz `dxrk/` (`pyproject.toml: requires-python >=3.13`),
  entry point `dxrk/__main__.py` (`main()`), console script publicado `dxrk-py`
  (no `dxrk`). El módulo `dxrk/commands/*.py` es espejo deliberado de los históricos
  `internal/commands/*.go` (trazabilidad nominal, no código heredado).
- **14 agentes curados**: `docs/agents.md` + `mkdocs.yml: site_description`
  + `dxrk/agents/` con 14 adaptadores
  (`antigravity, claude, codex, cursor, gemini, kilocode, kimi, kiro, openclaw, opencode, pi, qwen, vscode, windsurf`).
  Cada módulo en `dxrk/commands/*.py` expone `register_<name>_command(reg: Registry)`
  y se registra en `dxrk/commands/__init__.py` (`register_all`).
- **Sin `agent/` ni `skills/`**: no existe `agent/`, `skills/` ni `.agents/skills`
  en el repo — decisión consciente contra el import masivo sin curar (§6 de la auditoría).
  El único contenido bajo `.agents/` es `social-media-skills` (dominio acotado, no skills de agente).
- **Con `SECURITY.md`**: política de seguridad con versiones soportadas (1.5.x/1.4.x),
  reporte privado vía GitHub Security Advisories (no issues públicos) y SLA de 48 h.

### Problema

Sin una declaración formal, la auditoría 2026-08-09 sigue circulando como
"documento maestro" y sus recomendaciones (auditar los 22 `exec.Command`,
testear `internal/commands`, reconciliar 28 vs 42 agentes, decidir sobre
`dxrk-memory` como prerrequisito) parecen trabajo pendiente. Aplicarlas hoy
sería teatro: **el código que describen ya no existe**. Además, futuros
contribuyentes podrían reintroducir patrones Go (binario sidecar, `agent/skills`
masivo) sin saber que fueron decisiones rechazadas, no olvidos.

---

## Decisión

**Cerrar la era Go. Python puro es el único stack. La auditoría 2026-08-09 queda archivada y obsoleta.**

1. **Python puro `>=3.13`, cero toolchain Go/Rust**: sin `go.mod`, sin `internal/`,
   sin binario sidecar, sin `cargo`. Consistente con `ADR-003` (stdlib-only,
   rechazo de híbrido Rust/Go y de sidecar `dxrk-memory` para v1.0).
2. **14 agentes curados, conteo canónico**: la tabla de `docs/agents.md` es la
   fuente de verdad. Ni 28 ni 42 (cifras de la era Go). Añadir un agente requiere
   adaptador en `dxrk/agents/` + fila en `docs/agents.md` + comando registrado
   en `dxrk/commands/__init__.py`.
3. **Sin `agent/skills` masivo**: no se reintroduce el import de skills externos
   sin curaduría (§6 auditoría: 96.9% sin curar). Contenido de skills solo acotado
   por dominio (precedente: `.agents/social-media-skills`).
4. **`SECURITY.md` como contrato**: reporte privado obligatorio, sin issues públicos
   para vulnerabilidades. Los 22 `exec.Command` de la era Go no se auditan porque
   no existen; el código Python equivalente vive bajo `dxrk/` con `ruff` + `mypy`
   + `pytest` en CI (ver `CONTRIBUTING.md`, `.github/workflows/ci.yml`).
5. **Auditoría 2026-08-09 archivada/obsoleta**: el archivo vive fuera del repo
   (`/home/dxrk/DXRK-AUDITORIA-2026-08-09.md`) y **no se importa a `docs/`**.
   Su valor restante es histórico (entender por qué se migró), no operativo.
   Ninguna de sus tablas P0–P3 aplica a `main`.

---

## Alternativas consideradas

- **Importar la auditoría a `docs/` como referencia viva**: rechazado —
  anclaría en la navegación un documento de ~90 KB que describe código inexistente
  (`internal/`, `go.mod`, `web/src`) y confundiría a contribuyentes nuevos.
  El archivo externo basta como archivo histórico.
- **Mantener compatibilidad nominal Go (shims, `internal/` vacío, alias `dxrk`)**:
  rechazado — el console script es `dxrk-py` por diseño; shims Go serían deuda
  sin usuarios. La trazabilidad nominal (`dxrk/commands` espejo de
  `internal/commands/*.go`) ya cubre la orientación histórica.
- **Re-migrar a Go/híbrido si Python no rinde**: rechazado para v1.x —
  ya decidido en `ADR-003` (re-evaluar solo en v2.0 con benchmarks >3×).
  Esta ADR no reabre ese debate, lo hereda.

---

## Consecuencias

### Positivas

- **Fin de la ambigüedad**: nadie pierde tiempo aplicando hallazgos P0–P3 a código
  que no existe; el conteo canónico es 14, no 28/42.
- **Coherencia con ADR-003**: stdlib-only + `pip install dxrk` <5 s + `mypy`/`ruff`/
  `pytest` verdes, sin toolchain Go en CI (`ubuntu/macos/windows` con Python único).
- **Superficie de skills acotada**: sin reimportación masiva; cada skill nuevo se
  justifica por dominio, no por volumen.
- **Seguridad con proceso**: `SECURITY.md` + advisories privados reemplazan el vacío
  de la era Go (donde `exec.Command` ×22 no tenía auditoría dedicada).

### Negativas / Costes

- **Pérdida de contexto histórico fino**: quien quiera saber *por qué* se migró
  debe leer el archivo externo (fuera del repo, no versionado). Mitigado: esta ADR
  resume el antes/después y cita las secciones relevantes (§6, §24, §29, §31, §32).
- **Sin plan de rollback a Go**: deliberado. Si v2.0 re-evalúa híbrido (vía ADR-003),
  será como *plugin* (`dxrk/memory/backend/vector.py`), no como retorno a `internal/`.

### Neutras

- `dxrk/commands` conserva nombres espejo de `internal/commands/*.go` solo como
  convención de orientación; no implica compatibilidad ni deuda de port.

---

## Plan de migración

No hay migración pendiente — la migración **ya ocurrió** y esta ADR la formaliza.
La verificación es de cierre, no de trabajo futuro:

| Paso | Acción | Estado |
|------|--------|--------|
| 1 | Verificar cero Go: `find . -name "*.go" -not -path "*/.git/*"` → `0` | ✅ Hecho (2026-10-10) |
| 2 | Verificar sin `go.mod` / `internal/` / `web/src` / binario sidecar | ✅ Hecho |
| 3 | Verificar 14 adaptadores en `dxrk/agents/` + tabla en `docs/agents.md` | ✅ Hecho |
| 4 | Verificar ausencia de `agent/` / `skills/` / `.agents/skills` | ✅ Hecho |
| 5 | Verificar `SECURITY.md` con advisories privados + SLA 48 h | ✅ Hecho |
| 6 | Declarar auditoría 2026-08-09 archivada/obsoleta (esta ADR, sin importar el archivo) | ✅ Esta ADR |
| 7 | Añadir entrada `mkdocs.yml` `nav: ADR-005: adr/ADR-005-migracion-go-python.md` | ✅ Esta ADR |
| 8 | No existe doc de migración Go→Python previa; esta ADR es el doc canónico | ✅ Esta ADR |

### Rollback

No hay rollback a Go. Si un futuro ADR propone híbrido, debe pasar por la
re-evaluación prevista en `ADR-003` (benchmarks >3×) y citar esta ADR como
superseded parcial, no ignorarla.

---

## Referencias

- `docs/agents.md` — tabla canónica de 14 agentes
- `SECURITY.md` — política de reporte privado, versiones soportadas, SLA 48 h
- `dxrk/__main__.py` — entry point `main()`, console script `dxrk-py`
- `dxrk/commands/__init__.py` — `register_all`, patrón `register_<name>_command`
- `dxrk/agents/` — 14 adaptadores (ver listado en Decisión)
- `pyproject.toml` — `requires-python >=3.13`, `[project.scripts] dxrk-py`
- `docs/adr/ADR-003-hybrid-vs-stdlib.md` — rechazo de híbrido Rust/Go y sidecar `dxrk-memory`
- `mkdocs.yml` — `nav` incluye `ADR-005`, `site_description` (14 agents)
- Archivo externo (NO importado, solo histórico): `/home/dxrk/DXRK-AUDITORIA-2026-08-09.md`
  (§6 skills 96.9%, §24 compilación Go 1.25.12, §29 conteo de agentes, §31 licencias skills, §32 `exec.Command` ×22)

> **Verificación**: `find . -name "*.go" -not -path "*/.git/*" | wc -l` → `0`;
> `ls dxrk/agents/` → 14 adaptadores; `ls agent/ skills/ .agents/skills` → no existen;
> `ls SECURITY.md docs/agents.md` → existen. `uvx ruff` no aplica a Markdown.
