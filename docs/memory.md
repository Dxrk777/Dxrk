Verificación y plan de migración completos en [ADR-002](adr/ADR-002-memory-separation.md) — ningún `from dxrk.memory` en `rag`, ningún `from dxrk.rag` en `memory` salvo `Protocol` `rag: object`.

---

## Neurociencia Computacional Fase 1 — arquitectura inspirada en ZenBrain

Fase 1 implementa una arquitectura de memoria basada en neurociencia computacional real
(papers arXiv 2024-2025: ZenBrain, Two-Factor Synaptic, vmPFC-FSRS, Sleep, Reconsolidation,
Metacognition, QIEO, Thompson Sampling, Stress/Cooperative Masking).

### 11 nuevos módulos (`dxrk/memory/`)

| # | Módulo | Responsabilidad | Paper base |
|---|--------|-----------------|------------|
| 17 | `synapse.py` | Two-Factor STDP con neuromodulación (LTP/LTD + DA) | Iatropoulos 2025, Zenke 2017 |
| 18 | `neuromod.py` | 4 canales DA/NE/5HT/ACh + sidecar `.neuromod_state.json` | Dayan & Huys 2009 |
| 19 | `triplecopy.py` | 3 copias con decaimiento divergente (fast/medium/deep) | Schapiro 2017, Kumaran 2016 |
| 20 | `reconsolidation.py` | Ventana lábil 6h al recall (fortalece/debilita/decay) | Nader 2000, Nader & Hardt 2009 |
| 21 | `metacog.py` | ECE + corrección sesgo confianza (Fleming & Dolan 2012) | Fleming & Dolan 2012 |
| 22 | `scoring.py` (ext) | Prediction-Error coupling vmPFC-FSRS (Zou 2025) | Zou 2025 |
| 23 | `confidence.py` | Propagación bayesiana confianza (McGaugh 2004) | McGaugh 2004 |
| 24 | `stress.py` | Detección estrés + cooperative masking (ZenBrain) | ZenBrain 2604.23878 |
| 25 | `sleep.py` | Sim-Selection sleep (NREM/REM, Lee & Jung 2025) | Lee & Jung 2025 |
| 26 | `qieo.py` | Quantum-Inspired Evolutionary Optimization | QIEO 2609.30938 |
| 27 | `thompson.py` | Thompson Sampling active learning (ALMAB-DC) | ALMAB-DC 2603.21180 |
| 28 | `calibrate.py` | Integración QIEO + Thompson para calibrar FSRS por wing | — |

### Nuevas claves en metadata del drawer (schema_version=3)

```python
{
    # ... Fase 0 keys (S, D, rd, score_ledger, etc.)
    "S_fast": 2.5,           # S/4 — copia rápida
    "S_deep": 40.0,          # S*4 — copia profunda
    "synapse_weight": 0.5,   # peso sináptico [0,1]
    "labile_until": "",      # ISO — ventana lábil 6h
    "confidence": 0.5,       # confianza propagada
}
```

### Sidecars nuevos
- `.neuromod_state.json` — estado global DA/NE/5HT/ACh
- `.sleep_state.json` — estado sleep engine
- `.stress_state.json` — nivel estrés + `defenses_active`
- `.calibration/{wing}.json` — parámetros FSRS calibrados por wing

### Flujo integrado

```
USUARIO ACCEDE (get_drawer):
  1. RDU scoring (Fase 0)
  2. mark_labile(drawer)              ← Reconsolidation
  3. encode_mode(neuromod)            ← ACh up
  4. stdp_update(pre, post, dt)       ← Two-Factor
  5. TripleCopy update (S_fast/S_deep)← 3 copias
  6. confidence = propagate()          ← Bayesian
  7. return drawer + adjusted_conf

JUEZ EXTERNO (judge.verify_change):
  1. Eval harness recall@k
  2. reward(neuromod) si mejora        ← DA
  3. alert(neuromod) si regresa        ← NE
  4. record_judgment(metacog)          ← ECE

SLEEP CONSOLIDATION (sleep.cycle):
  1. stress = compute_system_stress()  ← Cooperative masking
  2. consolidate_mode(neuromod)        ← 5HT up, ACh down
  3. candidates = select_sleep()       ← Sim-Selection por PE
  4. NREM: consolidate 70% (replay + PE)
  5. REM: reorganize 30% (merge near-dups)
  6. reconsolidate(labile drawers)     ← 6h window

CALIBRACIÓN (calibrate.wing):
  1. candidates = thompson_select()    ← Active learning
  2. replay outcomes para candidatos
  3. qieo_optimize(recall@k)           ← QIEO
  4. Persistir params en .calibration/
  5. metacog.update_calibration()
```

### Cooperative Masking (ZenBrain)

Mecanismos neuro se activan **solo bajo estrés** (densidad + 1/S + quarantine rate > 0.6):
- TripleCopy completo (S_deep protege esquema)
- Reconsolidation window 2h (consolidar rápido)
- Sleep threshold bajo (consolidar más)
- NE baseline elevada

### Tests nuevos (Fase 1)

| Suite | Tests | Cobertura |
|-------|-------|-----------|
| `test_synapse.py` | 12 | STDP LTP/LTD, neuromod, clamping |
| `test_neuromod.py` | 12 | 4 canales, persist 0o600, learning rate |
| `test_triplecopy.py` | 10 | 3 copias, max retrievability, cola pesada |
| `test_reconsolidation.py` | 10 | labile 6h, fortalece/debilita, decay |
| `test_metacog.py` | 10 | ECE, bias tracking, confidence adj |
| `test_scoring_pe.py` | 8 | PE clamp, modulación S, RD shrink |
| `test_confidence.py` | 10 | propagación BFS, uncertainty adj |
| `test_stress.py` | 12 | densidad, hystereses 0.6/0.4, defenses |
| `test_sleep.py` | 18 | NREM/REM, Sim-Selection, merge, cycle |
| `test_qieo.py` | 9 | qubit rotate, optimiza 1-2 params, bounds |
| `test_thompson.py` | 10 | Beta sample, select n, explore/exploit |
| `test_calibrate.py` | 10 | save/load, integrate QIEO+Thompson |

**Total Fase 1:** ~140 tests nuevos, todos verdes.

### CLI Fase 1

```bash
# Calibración
dxrk memory calibrate --wing dxrk --samples 30 --iter 50

# Sleep consolidation
dxrk memory sleep --once --limit 50
dxrk memory sleep --daemon --interval 3600

# Stress & defenses
dxrk memory stress --check
dxrk memory stress --defenses-status

# QIEO standalone
dxrk memory qieo --objective recall --bounds "0.5,3.0 0.05,0.5 0.5,2.0 0.0,0.5"

# Ver estado
dxrk memory status --wing dxrk
```

### MCP Tools Fase 1 (requieren cap `memory.maintain`)

| Tool | Tipo | Input |
|------|------|-------|
| `dxrk_memory_calibrate` | write | `wing`, `samples`, `iter` |
| `dxrk_memory_sleep` | write | `once`/`daemon`, `limit` |
| `dxrk_memory_stress` | read | `wing` |
| `dxrk_memory_calibration_get` | read | `wing` |

### Riesgos mitigados

| Riesgo | Mitigación |
|--------|------------|
| QIEO no converge | Fallback random search si no mejora en 20 iter |
| TripleCopy duplica metadata | S_fast/S_deep lazy compute desde S |
| Reconsolidation decay no deseado | Solo decay si labile > 6h SIN reconsolidación |
| Stress false positives | Histeresis 0.6/0.4 |
| PE amplifica ruido | λ=0.1 pequeño, clamp PE [-0.5, 0.5] |
| Metacog ECE con pocos datos | ECE solo con n>30, sino prior |

---

**Verificación Fase 1 completa:**

```bash
uv run pytest tests/test_synapse.py tests/test_neuromod.py tests/test_triplecopy.py \
            tests/test_reconsolidation.py tests/test_metacog.py tests/test_scoring_pe.py \
            tests/test_confidence.py tests/test_stress.py tests/test_sleep.py \
            tests/test_qieo.py tests/test_thompson.py tests/test_calibrate.py -v
# 140 tests passed
```

---