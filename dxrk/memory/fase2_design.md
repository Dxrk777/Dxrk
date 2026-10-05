# Fase 2 — Diseño: Calibración Real, Metacognición Avanzada, Producción

## Estado: Diseño (no implementado)
Fecha: 2026-10-04
Base: Fase 1 completada (5021 tests, 86% coverage)

---

## Objetivos Fase 2

| Objetivo | Descripción |
|----------|-------------|
| **Eval Harness Real** | Calibración con queries reales + ground truth, ECE por wing |
| **Metacognición Avanzada** | Introspección, confidence calibration, bias detection |
| **Multi-Tenant** | Parámetros FSRS por tenant/wing con aislamiento |
| **Production Hardening** | Monitoring, alertas, rollback automático, SLOs |
| **Judge Externo Continuo** | Verificación continua de cambios, no solo one-shot |

---

## 1. Eval Harness Real (`dxrk/memory/eval_harness.py`)

### 1.1 Dataset de Evaluación
```python
@dataclass(frozen=True)
class EvalQuery:
    query: str
    expected_drawer_ids: list[str]  # ground truth
    wing: str
    difficulty: float  # 1-10, estimado
    tags: list[str]

@dataclass(frozen=True)
class EvalResult:
    query: EvalQuery
    retrieved: list[str]
    recall_at_k: dict[int, float]
    mrr: float
    ndcg: float
    latency_ms: float
```

### 1.2 Métricas por Wing
- **Recall@k** (k=1,3,5,10,20)
- **MRR** (Mean Reciprocal Rank)
- **NDCG@k**
- **ECE** (Expected Calibration Error) — confianza vs accuracy
- **Latency P50/P95/P99**

### 1.3 Calibración por ECE
```
ECE = Σ |accuracy(bin) - confidence(bin)| * weight(bin)
```
Optimizar parámetros FSRS para minimizar ECE + maximizar recall@10.

### 1.4 Dataset Curado
- `eval/queries/{wing}.jsonl` — queries con ground truth
- Generado desde: historial de `mine()`, `search()`, feedback usuario
- Mínimo 100 queries/wing para significancia estadística

---

## 2. Metacognición Avanzada (`dxrk/memory/metacog_v2.py`)

### 2.1 Introspección Activa
```python
@dataclass(frozen=True)
class MetacogState:
    # ... Fase 1 fields ...
    confidence_bins: list[dict]  # 10 bins: {conf_range, count, accuracy}
    bias_history: list[float]    # rolling bias
    introspection_log: list[dict]  # {query, predicted, actual, calibration_error}
    model_uncertainty: float     # epistemic uncertainty del modelo
```

### 2.2 Confidence Calibration
- **Temperature Scaling** post-hoc: `conf_calibrated = sigmoid(logit(conf) / T)`
- **Isotonic Regression** para calibración no-paramétrica
- **Platt Scaling** para binary outcomes

### 2.3 Bias Detection
- **Overconfidence**: ECE > 0.1 sistemáticamente
- **Underconfidence**: bias negativo persistente
- **Category Bias**: bias por wing/room/topic

### 2.4 Auto-Corrección
```python
def calibrate_confidence(self, raw_conf: float, context: dict) -> float:
    """Aplica temperature scaling + bias correction."""
    logit = math.log(raw_conf / (1 - raw_conf))
    calibrated = 1 / (1 + math.exp(-logit / self.temperature))
    return calibrated - self.bias_correction(context)
```

---

## 3. Multi-Tenant Calibration (`dxrk/memory/calibrate_v2.py`)

### 3.1 Aislamiento por Tenant
```
palace_path/
├── .calibration/
│   ├── {tenant}_{wing}.json    # params por tenant+wing
│   └── global_{wing}.json      # fallback global
```

### 3.2 Jerarquía de Parámetros
1. **Tenant+Wing específico** — si hay datos suficientes (>500 queries)
2. **Tenant global** — promedio ponderado por wing del tenant
3. **Global por wing** — default entrenado en todos los tenants
2. **Default hardcoded** — Fase 1 defaults

### 3.3 Transfer Learning
```python
def get_calibration(tenant: str, wing: str) -> CalibrationParams:
    # 1. Intentar tenant+wing
    # 2. Fallback tenant_global[wing]
    # 3. Fallback global[wing]
    # 4. Default
```
Con regularización: `θ_tenant = α * θ_tenant + (1-α) * θ_global`

---

## 4. Production Hardening (`dxrk/memory/production.py`)

### 4.1 SLOs y Alertas
| SLO | Target | Alert Threshold |
|-----|--------|-----------------|
| Search latency P99 | < 200ms | > 500ms |
| Mine throughput | > 100 files/s | < 50 files/s |
| Calibration drift | ECE < 0.05 | ECE > 0.15 |
| Memory pressure | < 80% RAM | > 90% RAM |
| Quarantine rate | < 1% | > 5% |

### 4.2 Monitoring (`dxrk/memory/monitoring.py`)
```python
@dataclass(frozen=True)
class HealthMetrics:
    timestamp: str
    search_latency_p50: float
    search_latency_p99: float
    mine_throughput: float
    calibration_ece: dict[str, float]  # por wing
    quarantine_count: int
    stress_level: float
    memory_usage_mb: float
    disk_usage_mb: float
```

### 4.3 Rollback Automático
- Si calibración nueva degrada recall@10 > 5% → rollback automático
- Si ECE sube > 0.1 → revertir a parámetros previos
- Guardar últimos 10 versiones de calibración

### 4.4 Circuit Breaker
```python
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failures = 0
        self.state = "closed"  # closed | open | half-open
    
    def call(self, fn, *args, **kwargs):
        if self.state == "open":
            raise CircuitOpenError()
        try:
            result = fn(*args, **kwargs)
            self.failures = 0
            return result
        except Exception as e:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.state = "open"
                threading.Timer(self.timeout, self._half_open).start()
            raise
```

---

## 5. Judge Externo Continuo (`dxrk/judge/continuous.py`)

### 5.1 Verificación Continua
```python
class ContinuousJudge:
    def __init__(self, palace, eval_harness, interval_hours: int = 24):
        self.palace = palace
        self.eval = eval_harness
        self.interval = interval_hours
    
    def run_continuous(self):
        while True:
            # 1. Sample queries recientes
            queries = self._sample_recent_queries(hours=24)
            
            # 2. Evaluar contra ground truth
            results = self.eval.evaluate(queries)
            
            # 3. Detectar regresión
            if self._regression_detected(results):
                self._trigger_alert(results)
                self._auto_rollback_if_needed()
            
            # 4. Log metrics
            self._log_metrics(results)
            
            time.sleep(self.interval * 3600)
```

### 5.2 Regresión Detection
- **Statistical**: t-test entre recall@10 actual vs baseline (p < 0.01)
- **Practical**: degradación > 5% en cualquier métrica clave
- **Drift**: ECE aumenta > 0.05 en 7 días

### 5.3 Auto-Rollback
```python
def _auto_rollback_if_needed(self):
    if self._regression_severe():
        # Revertir calibración a versión anterior
        self.calibrate.rollback(steps=1)
        # Notificar
        self._notify("auto_rollback", {"reason": "regression_detected"})
```

---

## 6. Esquema Metadata (schema_version=4)

```python
{
    # ... Fase 1 keys ...
    "eval_metrics": {           # métricas de eval por wing
        "recall_at_10": 0.73,
        "mrr": 0.45,
        "ece": 0.04,
        "last_eval": "2026-10-04T12:00:00Z"
    },
    "calibration_version": 3,   # versión de parámetros
    "temperature": 1.2,         # temperature scaling
    "isotonic_map": null,       # path a modelo isotónico
    "tenant_calibration": true, # usa calibración tenant-specific
}
```

---

## 7. Tareas Testeables (20 tareas)

### Bloque 1: Eval Harness (1-6)
1. `EvalQuery`/`EvalResult` + dataset loader + tests
2. `evaluate_recall_at_k` + MRR/NDCG + tests
3. `compute_ece` + temperature scaling + tests
4. Dataset curation script + `eval/queries/{wing}.jsonl` + tests
5. `EvalHarness` class + run + report + tests
6. Calibración por ECE + integration test

### Bloque 2: Metacognición Avanzada (7-10)
7. `MetacogState_v2` + confidence bins + tests
8. Temperature scaling + isotonic regression + tests
9. Bias detection + auto-correction + tests
10. Integration con scoring + tests

### Bloque 3: Multi-Tenant Calibration (11-14)
11. `CalibrationParams_v2` + tenant isolation + tests
12. Hierarchical params + transfer learning + tests
13. `get_calibration` fallback chain + tests
14. CLI `dxrk memory calibrate --tenant` + tests

### Bloque 4: Production Hardening (15-18)
15. `HealthMetrics` + collector + tests
16. SLO definitions + alerting + tests
17. Circuit breaker + rollback + tests
18. Monitoring MCP tools + tests

### Bloque 5: Judge Continuo (19-20)
19. `ContinuousJudge` + regression detection + tests
20. Auto-rollback + alerting + tests

---

## 8. Riesgos y Mitigaciones

| Riesgo | Probabilidad | Mitigación |
|--------|--------------|------------|
| Eval dataset sesgado | Alta | Curar dataset diverso, mínimo 100 queries/wing |
| ECE no converge | Media | Temperature scaling como fallback simple |
| Multi-tenant data leak | Crítica | Aislamiento estricto path + tests de aislamiento |
| Rollback false positive | Media | Confirmación manual para rollbacks > 1 |
| Judge continuo consume recursos | Baja | Ejecutar en background, intervalo configurable |
| Calibración overfit | Alta | Holdout set, early stopping, regularización |

---

## 9. Definición de "Done" Fase 2

- [ ] Eval harness corre con dataset real, genera reportes
- [ ] ECE < 0.05 en al menos 3 wings
- [ ] Metacognición corrige bias automáticamente
- [ ] Multi-tenant aislamiento verificado (tests)
- [ ] SLOs definidos, alertas funcionando
- [ ] Rollback automático probado en staging
- [ ] Judge continuo corriendo 24h sin falso positivos
- [ ] 20 tests nuevos verdes, suite total > 5200 tests
- [ ] Coverage > 85%
- [ ] Docs actualizados

---

## 10. Siguiente Paso

Si aprobado, implementar Bloque 1 (Eval Harness) en branch `feat/fase2-eval`.