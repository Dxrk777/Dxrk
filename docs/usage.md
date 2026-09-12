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
python -m dxrk.memory search "Spec-Driven Development"
```

Sincronizar tu configuración (vista previa con `--dry-run`):

```bash
dxrk-py sync --agent claude-code --dry-run
```

## Configuración por proyecto

- `/sdd-init`: inicia el workflow Spec-Driven Development en el proyecto.
- `dxrk-py install --component skills`: instala las skills curadas.

## Memoria

La memoria persistente es DxrkMemory 2.0 nativa (100% Python stdlib-only,
sin binarios externos):

```bash
python -m dxrk.memory search "Spec-Driven Development"
```

## TUI

Lanzar la interfaz Textual:

```bash
dxrk-py tui
```
