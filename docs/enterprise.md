# Enterprise: Empresa IA

Dxrk incluye una capa de empresa IA sobre DxrkMemory 2.0.
Todo stdlib, sin red, sin servidor: el módulo solo usa SQLite
local y el filesystem del tenant activo.

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

`tests/test_enterprise.py` (102): con SQLite en `tmp_path`,
sin red ni sleeps.
