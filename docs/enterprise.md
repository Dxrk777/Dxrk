# Enterprise: Cortex + Autonomous + Empresa IA

Desde v1.1.0, Dxrk incluye tres capas nuevas sobre DxrkMemory 2.0.
Todo stdlib, sin red, sin servidor: los tres módulos solo usan SQLite
local y el filesystem del tenant activo.

## Mapa rápido

| Capa | Paquete | Qué es |
|---|---|---|
| Cortex | `dxrk.memory.cortex` | Motor cognitivo: IQ vectorial, evolución de prompts, sueño creativo |
| Autonomous | `dxrk.memory.autonomous` | Aprendizaje autónomo 24/7 en 7 motores |
| Enterprise | `dxrk.enterprise` | Empresa IA: 7 departamentos, 79 skills, orquestador |

## Cortex (`dxrk.memory.cortex`)

14 clases exportadas (`dxrk/memory/cortex/__init__.py`). El punto de
entrada es `DxrkMemoryCognitiveCore`:

```python
from dxrk.memory.cortex import DxrkMemoryCognitiveCore

core = DxrkMemoryCognitiveCore()  # db en ~/.dxrk/memory/cortex.db
await core.start_cognitive_loop()  # evolución + medición de IQ en fondo
core.record_interaction({"input": "...", "output": "..."})
core.get_cognitive_status()  # dict con estado del loop
core.get_iq_report()  # dict con el reporte de IQ actual
core.stop_cognitive_loop()
```

Componentes (todos importables desde `dxrk.memory.cortex`):

- `DxrkIQEngine`: IQ vectorial — `measure_current_iq()`, `record_iq()`,
  `calculate_evolution_trend(days=30)`, `project_future_iq()`,
  `get_weakest_dimensions()`, `get_strongest_dimensions()`,
  `get_learning_velocity()`, `add_skill()`.
- `UsageBasedIQ`: el IQ crece con el uso (`record_interaction`,
  `calculate_current_iq`).
- `GeneticPromptEvolution`, `MetaLearningEngine`, `DreamingMode`,
  `AutonomousThinking`, `SelfAwarenessLayer`, `SynapticPlasticity`,
  `NetworkEffect`, `ContributionWeighting`, `CollectiveIntelligence`,
  `SynapseTokenSaver`, `IQDatabase`.

## Autonomous (`dxrk.memory.autonomous`)

7 motores, todos aceptan `memory_engine=None` (funcionan sin memoria
conectada) y exponen un `get_*_stats()`:

| Motor | Loop principal |
|---|---|
| `OmniscientReader` | `start_continuous_reading(interval_minutes=30)`, `get_sources()` |
| `SelfPracticeEngine` | `daily_practice_session()` (genera problemas, intenta, evalúa, aprende) |
| `DeepReflectionEngine` | reflexión nocturna sobre experiencias guardadas |
| `ExpertImitationEngine` | estudia estrategias de expertos |
| `SelfExperimentationEngine` | corre experimentos y mide mejora |
| `CreativeSynthesisEngine` | combina ideas en insights nuevos |
| `SelfAssessmentEngine` | evaluación semanal con IQ por dimensión |

```python
from dxrk.memory.autonomous import OmniscientReader, SelfPracticeEngine

reader = OmniscientReader()
await reader.start_continuous_reading(interval_minutes=30)
reader.get_reading_stats()

practice = SelfPracticeEngine(iq_engine=iq)
await practice.daily_practice_session()
```

## Enterprise (`dxrk.enterprise`)

`DxrkEnterprise` (en `dxrk/enterprise/company.py`, estado en
`~/.dxrk/enterprise`) + `TaskOrchestrator` (ruteo) + `AIWorkforce`
(contratar/despedir agentes):

```python
from dxrk.enterprise import DxrkEnterprise

company = DxrkEnterprise()
company.start_company()
result = company.execute_task("Crear un contrato NDA", "legal")
company.generate_company_report()
company.stop_company()
```

Departamentos (`DEPARTMENT_ID` real): `legal`, `developers`,
`designers`, `finance`, `marketing`, `small_business`, `social_media`.
Si `execute_task` se llama sin departamento, el orquestador lo rutea
(`TaskOrchestrator.route_task`).

Skills por departamento en `dxrk/enterprise/skills/`
(`business`, `designer`, `developer`, `finance`, `legal`, `marketing`,
`social` + `registry.py` y `skill_base.py`):
`company.list_all_skills()` devuelve `installed`/`available` por skill,
`company.install_skill(department, skill_name)` instala una.

### CLI

```bash
dxrk-py enterprise start                # inicia + imprime reporte
dxrk-py enterprise status               # reporte sin iniciar
dxrk-py enterprise execute "Crear un contrato NDA" legal
dxrk-py enterprise execute "Optimizar el funnel"   # ruteo automático
dxrk-py enterprise skills               # lista installed/available
dxrk-py enterprise report               # reporte
dxrk-py enterprise stop
```

## Tests

`tests/test_cortex.py` (98), `tests/test_autonomous.py` (41),
`tests/test_enterprise.py` (102): todos con SQLite en `tmp_path`,
sin red ni sleeps.
