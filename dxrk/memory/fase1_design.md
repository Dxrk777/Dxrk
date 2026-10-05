# Fase 1: Spine RDU — Calibración, Juez y Consolidación Nocturna

**Estado**: Diseño para revisión — NO implementar hasta aprobación  
**Contexto**: Fase 0 completa (RDU core, schema v2, quarantine, ledger hash-chain, cap memory.maintain, PolicyEngine opt-in, autonomy cull). Gates: 4880 passed, cov 85.91%.

---

## 1. Objetivos de Fase 1 (orden de prioridad)

| # | Objetivo | Descripción |
|---|----------|-------------|
| 1 | **Eval harness de calibración** | Framework para optimizar constantes FSRS por wing usando datos de recall (goldens + eval queries) |
| 2 | **Juez externo mejorado** | `Judge` class que usa `Verifier` + eval harness para validar cambios de memoria (no solo tests) |
| 3 | **Sleep consolidation** | Background daemon / scheduled task que corre consolidación inteligente durante "sleep" |

---

## 2. Arquitectura General

```
dxrk/memory/
├── calibrate.py          # Eval harness + optimización FSRS por wing
├── judge.py              # Juez externo mejorado (Judge class)
├── sleep.py              # Sleep consolidation daemon
├── palace.py             # Existente — hooks de integración
├── scoring.py            # Existente — FSRS constants expuestos para calibración
├── migrate.py            # Existente — SPINE_*_DEFAULT
└── mcp_server.py         # Existente — nuevas tools: calibrate, sleep_consolidate
```

**Principios de diseño**:
- **stdlib only** — sin `optuna`, `scipy`, `sklearn`. Grid search + random sampling OK.
- **Determinista** — mismo input → mismo output, seeds controlados.
- **Cero dependencias nuevas** — todo en `dxrk/memory/`.
- **Commits atómicos, conventional, SIN Co-Authored-By**.
- **Tests espejo** para cada componente nuevo.
- **No romper gates existentes** — goldens recall intactos.

---

## 3. Componente 1: Eval Harness de Calibración (`dxrk/memory/calibrate.py`)

### 3.1 Responsabilidades

- Cargar corpus de evaluación (goldens + queries graded estilo `test_memory_recall_eval.py`)
- Barrer espacio de parámetros FSRS (grid + random sampling, stdlib only)
- Métricas: `recall@k`, `MRR`, `NDCG`, `calibration error (ECE)` entre `R(t,S)` predicho vs observado
- Persistir mejor config por wing en `palace/.calibration/{wing}.json`
- CLI `dxrk memory calibrate --wing WING --trials N`
- Entrypoint en mcp_server como read-tool (no write): `dxrk_memory_calibrate`

### 3.2 Estructuras de Datos

```python
# dxrk/memory/calibrate.py

from dataclasses import dataclass, field
from typing import Any
from datetime import UTC, datetime

@dataclass(slots=True)
class FSRSParams:
    """Parámetros FSRS calibrables por wing."""
    DECAY: float = -0.5
    FACTOR: float = 19.0 / 81.0
    a: float = 1.5
    b: float = 0.2
    c: float = 1.0
    k: float = 2.0
    p: float = 0.2
    q: float = 0.2
    r: float = 1.0

@dataclass(slots=True)
class EvalQuery:
    """Query calificada estilo test_memory_recall_eval.py"""
    query: str
    target_marker: str  # ej. "auth", "deploy", "backup", "verify"
    k: int = 3
    # grade opcional: 1.0 = perfect match, 0.5 = partial, 0.0 = miss
    grade: float = 1.0

@dataclass(slots=True)
class EvalCorpus:
    """Corpus de evaluación: drawers base + queries graded."""
    drawers: list[dict[str, Any]]  # {wing, room, content, source_file, chunk_index}
    queries: list[EvalQuery]
    wing: str

@dataclass(slots=True)
class CalibrationMetrics:
    """Métricas de una corrida de calibración."""
    recall_at_k: dict[int, float]
    mrr: float
    ndcg: float
    ece: float  # Expected Calibration Error
    trials: int
    best_params: FSRSParams
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

@dataclass(slots=True)
class WingCalibration:
    """Persistido en palace/.calibration/{wing}.json"""
    schema_version: int = 1
    wing: str = ""
    params: FSRSParams = field(default_factory=FSRSParams)
    metrics: CalibrationMetrics | None = None
    calibrated_at: str = ""
    trials_total: int = 0
```

### 3.3 Espacio de Búsqueda (Search Space)

```python
# Límites razonables derivados de literatura FSRS + heurísticas propias
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "DECAY": (-1.0, -0.1),        # exponent de retrievability
    "FACTOR": (0.1, 0.5),         # (19/81) ≈ 0.234
    "a": (0.5, 3.0),              # growth exponent en update_success
    "b": (0.05, 0.5),             # S^-0.2 factor
    "c": (0.5, 2.0),              # e^(1-R) scaling
    "k": (0.5, 5.0),              # lapse stability multiplier
    "p": (0.05, 0.5),             # lapse difficulty base
    "q": (0.05, 0.5),             # lapse difficulty mean-reversion
    "r": (0.5, 2.0),              # lapse e^(1-R) scaling
}
```

### 3.4 Algoritmo de Optimización (stdlib only)

```python
def calibrate_wing(
    corpus: EvalCorpus,
    trials: int = 200,
    grid_density: int = 5,
    seed: int = 42,
) -> WingCalibration:
    """
    1. Grid search grueso (grid_density^9 combinaciones → podado a top-20)
    2. Random sampling alrededor de mejores (trials - grid_evals)
    3. Evaluación: correr search con params temporales → métricas
    4. Return best WingCalibration
    """
    pass
```

**Métricas implementadas**:

- **recall@k**: `sum(1 for q in queries if target in top_k) / len(queries)`
- **MRR**: `mean(1/rank_i)` donde `rank_i` es posición del primer target correcto
- **NDCG@k**: DCG normalizado con grades binarios (1/0)
- **ECE**: `sum(|predicted_retrievability - observed_recall| * bin_weight)` sobre 10 bins de R(t,S)

### 3.5 Persistencia

```
{palace_path}/.calibration/
├── proj.json          # Wing "proj"
├── ops.json           # Wing "ops"
└── default.json       # Wing "default"
```

Schema JSON:
```json
{
  "schema_version": 1,
  "wing": "proj",
  "params": {"DECAY": -0.5, "FACTOR": 0.234, "a": 1.5, "b": 0.2, "c": 1.0, "k": 2.0, "p": 0.2, "q": 0.2, "r": 1.0},
  "metrics": {"recall_at_k": {"1": 1.0, "3": 1.0, "5": 1.0}, "mrr": 1.0, "ndcg": 1.0, "ece": 0.02, "trials": 200},
  "calibrated_at": "2026-10-02T12:00:00Z",
  "trials_total": 200
}
```

### 3.6 Integración con `scoring.py`

```python
# scoring.py — exponer factory para params calibrados
def get_fsrs_params(wing: str, palace_path: str | None = None) -> FSRSParams:
    """Lee palace/.calibration/{wing}.json o retorna defaults hardcodeados."""
    pass

# r_fsrs, update_success, update_lapse usan get_fsrs_params(wing) en vez de constants globales
```

### 3.7 CLI

```bash
dxrk memory calibrate --wing proj --trials 200 --seed 42
# Output: JSON con best params + métricas
```

### 3.8 MCP Tool (read-only)

```python
# mcp_server.py TOOLS dict
"dxrk_memory_calibrate": {
    "description": "Calibrar parámetros FSRS para un wing usando corpus de evaluación (read-only)",
    "inputSchema": {
        "type": "object",
        "properties": {
            "wing": {"type": "string"},
            "trials": {"type": "integer", "default": 200},
            "seed": {"type": "integer", "default": 42},
            "palace": {"type": "string"},
        },
        "required": ["wing"],
    },
},
```

---

## 4. Componente 2: Juez Externo Mejorado (`dxrk/memory/judge.py`)

### 4.1 Responsabilidades

- Extender `dxrk/judge/verifier.py` (ya existe, aislado, `auto_fix=False` default)
- Nueva clase `Judge` que usa `Verifier` + eval harness para validar **cambios de memoria**
- API: `Judge.verify_change(before_state, after_state, eval_corpus) -> Verdict`
- **Sin auto-fix** — solo observa y reporta

### 4.2 Estructuras de Datos

```python
# dxrk/memory/judge.py

from dataclasses import dataclass, field
from typing import Any
from dxrk.judge.verifier import Verifier, VerifyResult

@dataclass(slots=True)
class MemoryStateSnapshot:
    """Snapshot del estado de memoria antes/después de un cambio."""
    wing: str
    drawer_count: int
    drawer_ids: list[str]
    # sample de drawers para eval (top-N por rank_score)
    sample_drawers: list[dict[str, Any]]
    merkle_root: str
    timestamp: str

@dataclass(slots=True)
class Verdict:
    """Resultado del juez."""
    passed: bool
    verify_result: VerifyResult
    recall_delta: float  # recall@k after - recall@k before
    mrr_delta: float
    ndcg_delta: float
    ece_delta: float
    regression_detected: bool
    details: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class JudgeConfig:
    eval_corpus: EvalCorpus
    verifier_commands: tuple[tuple[str, ...], ...] = ()
    min_recall_threshold: float = 0.95  # recall no puede bajar más de 5%
    min_mrr_threshold: float = 0.90
```

### 4.3 Algoritmo

```python
class Judge:
    def __init__(self, config: JudgeConfig) -> None:
        self.config = config
        self.verifier = Verifier(
            project_root=config.eval_corpus.palace_path,  # o cwd
            auto_fix=False,
            commands=config.verifier_commands,
        )

    def verify_change(
        self,
        before_state: MemoryStateSnapshot,
        after_state: MemoryStateSnapshot,
        eval_corpus: EvalCorpus | None = None,
    ) -> Verdict:
        """
        1. Ejecutar Verifier (tests, lint, typecheck, etc.)
        2. Si verifier pasa → correr eval harness sobre before/after
        3. Comparar métricas recall@k, MRR, NDCG, ECE
        4. Si alguna métrica baja más de threshold → regression_detected=True
        5. Return Verdict
        """
        pass

    @staticmethod
    def snapshot_memory(palace_path: str, wing: str, sample_size: int = 50) -> MemoryStateSnapshot:
        """Toma snapshot del estado actual de un wing."""
        pass
```

### 4.4 Integración con `Verifier` existente

```python
# El Verifier existente ya corre comandos arbitrarios
# Judge añade evaluación semántica de memoria:
# - before_state: snapshot antes del cambio
# - after_state: snapshot después del cambio  
# - eval_corpus: queries graded para medir recall real
```

### 4.5 CLI

```bash
dxrk memory judge --before before.json --after after.json --corpus eval_corpus.json
# Output: Verdict JSON
```

---

## 5. Componente 3: Sleep Consolidation (`dxrk/memory/sleep.py`)

### 5.1 Responsabilidades

- Background daemon / scheduled task que corre consolidación inteligente durante "sleep"
- Detectar candidatos:
  - Drawers viejos (`filed_at > 30d`)
  - Baja importancia (`importance < 0.3` o `rank_score` bottom 20%)
  - Near-dupes (`Dedupe > 0.85` via `classify_content_pair`)
  - Contradicciones pendientes (drawers con `supersedes` sin consolidar)
- Llamar `consolidate_drawers` en lotes (max 50 drawers/sleep)
- Respetar cap/quarantine/pinned; no tocar drawers con `valid_to` reciente (< 7d)
- Log estructurado en ledger de cada drawer afectado (`reason: "sleep_consolidation"`)
- CLI `dxrk memory sleep --once` (one-shot) y `--daemon` (loop con intervalo configurable, default 4h)
- MCP tool write `dxrk_memory_sleep_consolidate{once:bool}` gateada por `memory.maintain`

### 5.2 Estructuras de Datos

```python
# dxrk/memory/sleep.py

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

@dataclass(slots=True)
class SleepConfig:
    max_drawers_per_sleep: int = 50
    min_age_days: int = 30
    min_importance: float = 0.3
    recent_valid_to_days: int = 7
    dedupe_threshold: float = 0.85  # DEDUPE_SIM_THRESHOLD
    daemon_interval_hours: int = 4
    dry_run: bool = False

@dataclass(slots=True)
class ConsolidationCandidate:
    drawer_ids: list[str]
    wing: str
    room: str
    reason: str  # "old_low_importance", "near_duplicate", "contradiction"
    score: float  # priority score (higher = more urgent)

@dataclass(slots=True)
class SleepResult:
    processed: int
    consolidated: int
    skipped: int
    errors: list[str]
    affected_drawers: list[dict[str, Any]]  # {id, action, reason}
    duration_seconds: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
```

### 5.3 Detección de Candidatos

```python
def find_consolidation_candidates(
    dm: DxrkMemory,
    wing: str,
    config: SleepConfig,
) -> list[ConsolidationCandidate]:
    """
    1. Escanear wing (STATUS_SCAN_LIMIT = 10000)
    2. Filtrar:
       - filed_at > min_age_days
       - NOT quarantined, NOT pinned, NOT valid_to recent
       - importance < min_importance OR rank_score bottom 20%
    3. Agrupar por similitud (vector cosine >= dedupe_threshold)
    4. Clasificar pares con classify_content_pair:
       - "duplicate" → agrupar para consolidar
       - "contradiction" → marcar para revisión (no auto-consolidar)
    5. Rankear candidatos por score combinado (edad + importancia + similitud)
    6. Return top max_drawers_per_sleep
    """
    pass
```

### 5.4 Ejecución de Consolidación

```python
def run_sleep_consolidation(
    dm: DxrkMemory,
    wing: str | None = None,
    config: SleepConfig | None = None,
) -> SleepResult:
    """
    Para cada wing (o wing específico):
    1. find_consolidation_candidates
    2. Para cada grupo de candidatos:
       - Llamar dm.consolidate_drawers(ids, wing, room)
       - En ledger de CADA drawer afectado: ledger_append(..., reason="sleep_consolidation")
    3. Return SleepResult
    """
    pass
```

### 5.5 Ledger Entry para Sleep Consolidation

```python
# En migrate.py ledger_append ya existe
# Sleep consolidation añade entrada:
ledger_append(meta, score=new_score, S=new_S, D=new_D, reason="sleep_consolidation")
# Esto permite auditoría completa: cada drawer consolidado tiene trazabilidad
```

### 5.6 CLI

```bash
# One-shot
dxrk memory sleep --once --wing proj --max-drawers 50

# Daemon (loop cada 4h por defecto)
dxrk memory sleep --daemon --interval-hours 4 --wings proj,ops

# Dry-run para ver qué haría
dxrk memory sleep --once --dry-run
```

### 5.7 MCP Tool (write, gated by memory.maintain)

```python
# mcp_server.py TOOLS dict
"dxrk_memory_sleep_consolidate": {
    "description": "Ejecutar consolidación nocturna (sleep) — gated by memory.maintain",
    "inputSchema": {
        "type": "object",
        "properties": {
            "once": {"type": "boolean", "default": True},
            "wing": {"type": "string"},
            "max_drawers": {"type": "integer", "default": 50},
            "dry_run": {"type": "boolean", "default": False},
            "palace": {"type": "string"},
        },
    },
},
```

En `_MCP_WRITE_TOOLS` y `_MCP_TOOL_OPS`:
```python
_MCP_WRITE_TOOLS.add("dxrk_memory_sleep_consolidate")
_MCP_TOOL_OPS["dxrk_memory_sleep_consolidate"] = "memory.maintain"
```

---

## 6. Esquema Persistente Consolidado

### 6.1 Estructura de Directorios

```
{palace_path}/
├── .calibration/
│   ├── proj.json
│   ├── ops.json
│   └── default.json
├── .sleep/
│   └── last_run.json      # timestamp + result del último sleep
└── (palace DB + ledger existentes)
```

### 6.2 `.calibration/{wing}.json` — Schema v1

```json
{
  "schema_version": 1,
  "wing": "proj",
  "params": {
    "DECAY": -0.5,
    "FACTOR": 0.234567,
    "a": 1.5,
    "b": 0.2,
    "c": 1.0,
    "k": 2.0,
    "p": 0.2,
    "q": 0.2,
    "r": 1.0
  },
  "metrics": {
    "recall_at_k": {"1": 1.0, "3": 1.0, "5": 1.0},
    "mrr": 1.0,
    "ndcg": 1.0,
    "ece": 0.015,
    "trials": 200
  },
  "calibrated_at": "2026-10-02T12:00:00Z",
  "trials_total": 200
}
```

### 6.3 `.sleep/last_run.json` — Schema v1

```json
{
  "schema_version": 1,
  "last_run": "2026-10-02T04:00:00Z",
  "result": {
    "processed": 50,
    "consolidated": 12,
    "skipped": 38,
    "errors": [],
    "affected_drawers": [
      {"id": "proj:backend:auth:0", "action": "consolidated", "reason": "old_low_importance"},
      {"id": "proj:ops:deploy:0", "action": "consolidated", "reason": "near_duplicate"}
    ],
    "duration_seconds": 3.2
  }
}
```

---

## 7. Orden de Tareas (12-15 tareas testeables)

| # | Tarea | Archivo(s) | Tests | Descripción |
|---|-------|------------|-------|-------------|
| 1 | **Calibrate: Data structures** | `calibrate.py` | `test_calibrate_structures.py` | `FSRSParams`, `EvalQuery`, `EvalCorpus`, `CalibrationMetrics`, `WingCalibration` |
| 2 | **Calibrate: Search space & bounds** | `calibrate.py` | `test_calibrate_bounds.py` | `PARAM_BOUNDS`, validación de rangos |
| 3 | **Calibrate: Metrics (recall@k, MRR, NDCG, ECE)** | `calibrate.py` | `test_calibrate_metrics.py` | Implementar 4 métricas, tests con datos conocidos |
| 4 | **Calibrate: Grid search + random sampling** | `calibrate.py` | `test_calibrate_search.py` | Algoritmo de optimización stdlib-only |
| 5 | **Calibrate: Persistence (.calibration/{wing}.json)** | `calibrate.py` | `test_calibrate_persist.py` | Read/write JSON, schema versioning |
| 6 | **Calibrate: Integration con scoring.py** | `scoring.py`, `calibrate.py` | `test_calibrate_integration.py` | `get_fsrs_params(wing)`, `r_fsrs` usa params calibrados |
| 7 | **Calibrate: CLI `dxrk memory calibrate`** | `commands/memory.py`, `calibrate.py` | `test_cli_calibrate.py` | Subcomando con args --wing --trials --seed |
| 8 | **Calibrate: MCP tool read-only** | `mcp_server.py` | `test_mcp_calibrate.py` | `dxrk_memory_calibrate` tool |
| 9 | **Judge: Data structures + Verdict** | `judge.py` | `test_judge_structures.py` | `MemoryStateSnapshot`, `Verdict`, `JudgeConfig` |
| 10 | **Judge: verify_change implementation** | `judge.py` | `test_judge_verify.py` | Snapshot before/after, run verifier + eval harness |
| 11 | **Judge: CLI `dxrk memory judge`** | `commands/memory.py`, `judge.py` | `test_cli_judge.py` | Subcomando con --before --after --corpus |
| 12 | **Sleep: Data structures + Config** | `sleep.py` | `test_sleep_structures.py` | `SleepConfig`, `ConsolidationCandidate`, `SleepResult` |
| 13 | **Sleep: Candidate detection** | `sleep.py` | `test_sleep_candidates.py` | `find_consolidation_candidates` con palace real |
| 14 | **Sleep: Consolidation execution + ledger** | `sleep.py`, `palace.py` | `test_sleep_execution.py` | `run_sleep_consolidation`, ledger_append reason |
| 15 | **Sleep: CLI + daemon + MCP tool** | `commands/memory.py`, `mcp_server.py`, `sleep.py` | `test_cli_sleep.py`, `test_mcp_sleep.py` | `--once`, `--daemon`, `dxrk_memory_sleep_consolidate` |

---

## 8. Riesgos y Mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| **Calibración overfit a goldens** | Media | Alto | ECE (calibration error) detecta overconfidence; holdout queries no vistas durante calibración |
| **Sleep consolidation rompe recall** | Baja | Alto | Solo consolida drawers viejos + baja importancia; pinned/quarantine/valid_to recientes intocables; ledger trazabilidad completa |
| **Judge false positives (regression_detected)** | Media | Medio | Thresholds conservadores (5% recall, 10% MRR); métricas múltiples deben fallar juntas |
| **Calibración por wing fragmenta modelo** | Baja | Medio | Defaults globales como fallback; calibración opcional por wing |
| **Daemon sleep consume recursos** | Baja | Bajo | Max 50 drawers/sleep, intervalo 4h configurable, dry-run por defecto en CLI |
| **Grid search explosión combinatoria** | Media | Medio | Podar a top-20 tras grid grueso; random sampling focalizado; trials cap |

---

## 9. Decisiones de Diseño Clave

### 9.1 ¿Por qué FSRS params por wing y no global?

Diferentes wings tienen dinámicas de memoria distintas:
- `proj` (código/docs técnicos): decay lento, estabilidad alta
- `ops` (runbooks/incidentes): decay medio, frecuencia importa
- `personal` (notas): decay rápido, importancia subjetiva

Calibración por wing permite especialización sin fragmentar el modelo base.

### 9.2 ¿Por qué ECE (Expected Calibration Error)?

El modelo FSRS predice `R(t,S)` = probabilidad de recall en `t` días. ECE mide si esa predicción está calibrada:
- Si `R=0.9` pero recall observado es `0.5` → modelo overconfident
- Si `R=0.5` pero recall observado es `0.9` → modelo underconfident
- ECE bajo = predicciones confiables para decisiones de eviction/consolidation

### 9.3 ¿Por qué no auto-fix en Judge?

El juez **observa y reporta**. La remediación es decisión humana (o política explícita). Esto evita:
- Cambios silenciosos que rompen invariantes
- Cascadas de auto-fix que ocultan root cause
- Violación de `memory.maintain` cap (solo maintainers pueden fixear)

### 9.4 ¿Por qué ledger entry `reason: "sleep_consolidation"`?

Trazabilidad completa: cada drawer consolidado durante sleep deja rastro en su score_ledger. Permite:
- Auditar qué se consolidó y por qué
- Revertir si consolidation introdujo regresión
- Debugging de "¿por qué desapareció este drawer?"

---

## 10. Criterios de Aceptación (Definition of Done)

### Calibración
- [ ] `dxrk memory calibrate --wing proj --trials 100` corre y produce `.calibration/proj.json`
- [ ] Métricas: recall@k ≥ 0.95, MRR ≥ 0.90, NDCG ≥ 0.90, ECE ≤ 0.05 en goldens
- [ ] `scoring.r_fsrs` usa params calibrados cuando existe `.calibration/{wing}.json`
- [ ] MCP tool `dxrk_memory_calibrate` expuesto como read-only
- [ ] Tests espejo pasan (`test_calibrate_*.py`)

### Juez
- [ ] `Judge.verify_change(before, after, corpus)` retorna `Verdict` con deltas
- [ ] Integra `Verifier` existente (commands configurables)
- [ ] Regression detectado si recall@k baja >5% O MRR baja >10%
- [ ] CLI `dxrk memory judge` funcional
- [ ] Tests espejo pasan

### Sleep
- [ ] `dxrk memory sleep --once --dry-run` lista candidatos sin mutar
- [ ] `dxrk memory sleep --once` consolida ≤50 drawers, respeta pinned/quarantine/valid_to reciente
- [ ] Ledger entry `reason: "sleep_consolidation"` en cada drawer afectado
- [ ] Daemon `--daemon --interval-hours 4` corre loop controlado
- [ ] MCP tool `dxrk_memory_sleep_consolidate` gated by `memory.maintain`
- [ ] Tests espejo pasan

### Global
- [ ] Gates existentes intactos (4880 passed, cov ≥ 80%)
- [ ] Goldens recall intactos (`test_memory_recall_eval.py` pasa)
- [ ] Commits atómicos, conventional, sin Co-Authored-By

---

## 11. Próximos Pasos (tras aprobación)

1. **Aprobar diseño** → usuario confirma o solicita cambios
2. **Implementar Tareas 1-8** (Calibración) en branch `feat/fase1-calibrate`
3. **Implementar Tareas 9-11** (Juez) en branch `feat/fase1-judge`
4. **Implementar Tareas 12-15** (Sleep) en branch `feat/fase1-sleep`
5. **Merge secuencial** con verification gates en cada paso
6. **Fase 2**: Per-wing parameter override en runtime, policy-driven consolidation, advanced judge policies

---

*Documento generado para revisión. NO implementar hasta aprobación explícita.*