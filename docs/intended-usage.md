# Uso previsto

## Para qué sirve Dxrk

Dxrk es un configurador y orquestador de ecosistemas para agentes de IA.
En lugar de configurar cada agente a mano, Dxrk:

1. **Detecta** el entorno (SO, package managers, agentes instalados).
2. **Instala** la configuración del agente elegido (presets: `full-dxrk`, ...).
3. **Sincroniza** perfiles de modelos por proveedor y por fase del workflow.
4. **Habilita** skills curadas, hooks, permisos y servidores MCP.
5. **Conecta** la memoria persistente (`dxrk-memory`) y el RAG local.

## Flujos típicos

### Nuevo proyecto con SDD

```bash
dxrk-py install --agent claude-code --preset full-dxrk
# dentro del proyecto:
/sdd-init
dxrk-py skill-registry refresh
```

### Trabajo diario

```bash
dxrk-py plan "refactor del módulo de auth"
dxrk-py commit
dxrk-py pr
```

### Modelos baratos para tareas rutinarias

```bash
dxrk-py sync --profile cheap:openrouter/qwen/qwen3-30b-a3b:free
dxrk-py sync --profile-phase cheap:sdd-design:anthropic/claude-sonnet-4-20250514
```

## Cuándo NO usar Dxrk

- Para tareas de edición de texto simple: un agente solo es suficiente.
- En entornos sin Python 3.13+ o sin acceso a la red para la primera instalación.

## Modelo mental

Dxrk = capa de configuración + orquestación encima del agente de código.
El agente escribe el código; Dxrk decide con qué memoria, skills, modelos
y permisos lo hace.
