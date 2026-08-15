# Uso

## Instalación

### Desde PyPI-lite (git)

```bash
uv tool install --from git+https://github.com/Dxrk777/Dxrk.git dxrk
```

o con pip:

```bash
pip install git+https://github.com/Dxrk777/Dxrk.git
```

### Desde fuente

```bash
git clone https://github.com/Dxrk777/Dxrk.git
cd Dxrk
uv sync --all-extras
uv run dxrk-py --help
```

## Comandos rápidos

Instalar la configuración para un agente:

```bash
dxrk-py install --agent claude-code --preset full-dxrk
```

Consultar contexto o memoria:

```bash
dxrk-py query "explica qué es Spec-Driven Development"
```

Sincronizar perfiles de modelos por proveedor y por fase:

```bash
dxrk-py sync --profile cheap:openrouter/qwen/qwen3-30b-a3b:free
dxrk-py sync --profile-phase cheap:sdd-design:anthropic/claude-sonnet-4-20250514
```

## Configuración por proyecto

- `/sdd-init`: inicia el workflow Spec-Driven Development en el proyecto.
- `dxrk-py skill-registry refresh`: regenera el registro de skills.

## Memoria

La memoria persistente usa el binario `dxrk-memory` (repo `Dxrk777/dxrk-memory`):

```bash
dxrk-memory search "Spec-Driven Development"
```

## TUI

Lanzar la interfaz Textual:

```bash
dxrk-py tui
```
