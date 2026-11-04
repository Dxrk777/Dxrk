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
uv sync --all-extras --dev
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

## Dxrk Omni

Omni convierte un tema en un short vertical o en una producción long-form por capítulos. Requiere Python 3.14+, `ffmpeg`/`ffprobe` en `PATH` y el extra `omni`:

```bash
uv sync --extra omni
```

### Short-form

```bash
uv run python scripts/omni.py "el futuro de la IA en Tokio"
```

Modo offline y determinista:

```bash
uv run python scripts/omni.py "el futuro de la IA en Tokio" \
  --no-llm --image-source placeholder --no-music --subtitle-source proportional
```

### Long-form

```bash
uv run python scripts/omni.py "el futuro de la IA en Tokio" \
  --longform --chapters 3 --shots-per-chapter 3 --chapter-duration 60
```

### Backends visuales

```bash
# ComfyUI local
uv run python scripts/omni.py "mi tema" \
  --image-source comfyui \
  --comfyui-url http://127.0.0.1:8188 \
  --comfy-checkpoint sd_xl_base_1.0.safetensors

# Stable Diffusion WebUI
uv run python scripts/omni.py "mi tema" \
  --image-source sdwebui \
  --sdwebui-url http://127.0.0.1:7860
```

La guía completa está en [Dxrk Omni](omni.md) y la referencia de flags en [`scripts/README.md`](https://github.com/Dxrk777/Dxrk/blob/main/scripts/README.md).

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
