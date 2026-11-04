# Ejemplos

Ejemplos ejecutables para probar Dxrk sin leer todo el código.

## Requisitos

- Python 3.14+
- `uv`
- `ffmpeg` y `ffprobe` en `PATH`
- Dependencias instaladas:

```bash
uv sync --all-extras --dev
```

## Quick Omni demo

`quick_omni_demo.py` invoca el pipeline de Omni directamente desde Python,
sin pasar por la CLI. Usa un tema de tecnología/ciencia, placeholders locales,
música sintetizada con FFmpeg y subtítulos proporcionales.

```bash
uv run python examples/quick_omni_demo.py
```

Variante long-form de dos capítulos:

```bash
uv run python examples/quick_omni_demo.py --longform
```

El video queda en `outputs/<slug>-<timestamp>/final.mp4` y el manifest en
`outputs/<slug>-<timestamp>/manifest.json`.

> La narración usa Edge-TTS, así que esa etapa necesita red. Las imágenes,
> la música y los subtítulos del demo son locales y deterministas.

### Qué muestra el ejemplo

- Cómo construir un `OmniConfig` válido.
- Cómo llamar a `run_pipeline()` y leer el `PipelineResult`.
- Cómo cambiar entre short-form y long-form.
- Cómo mantener el demo barato: sin LLM, sin modelos de imagen y sin
  descargas de música.

### Próximos pasos

Para usar backends reales, cambiá `image_source` en `build_config()`:

```python
image_source="comfyui"   # requiere ComfyUI en http://127.0.0.1:8188
image_source="sdwebui"   # requiere AUTOMATIC1111 con --api
```

Para usar un LLM, construí un `OpenAICompatibleClient` y pasalo a
`run_pipeline(config, llm=llm)`. La CLI ya lo hace automáticamente cuando
`use_llm=True`.

La referencia completa del pipeline está en
[`scripts/README.md`](../scripts/README.md) y la guía de usuario en
[`docs/omni.md`](../docs/omni.md).

## Otros ejemplos

| Archivo | Qué demuestra |
| --- | --- |
| `mine_and_search.py` | Flujo `mine -> search` de DxrkMemory con un `HOME` aislado. |
| `tenant_rbac_demo.py` | Aislamiento multi-tenant y denegación RBAC. |
| `quick_omni_demo.py` | Pipeline Omni desde Python, short-form y long-form. |

```bash
uv run python examples/mine_and_search.py
uv run python examples/tenant_rbac_demo.py
```
