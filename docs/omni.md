# Dxrk Omni — video y audio

**Dxrk Omni** es el pipeline multimedia de Dxrk. Convierte un tema en un short vertical o en una producción long-form por capítulos, usando backends locales cuando están disponibles y fallbacks deterministas cuando no.

```text
tema
  └─> guion (LLM opcional)
      └─> imágenes (ComfyUI / SD WebUI / locales / placeholder)
          └─> narración (Edge-TTS) + word timings (Whisper / proporcional)
              └─> música (FFmpeg synth / MusicGen / Stable Audio / track)
                  └─> montaje FFmpeg
                      └─> final.mp4 (1080x1920, 30 fps, H.264/AAC)
```

El pipeline vive en `scripts/omni.py` y `scripts/omni_media/`, fuera del paquete `dxrk`. Tiene tests propios y no debilita el contrato de cobertura del core.

## Requisitos

- Python 3.14+
- `ffmpeg` y `ffprobe` en `PATH`
- Extra `omni`:

```bash
uv sync --extra omni
```

Para desarrollo completo:

```bash
uv sync --all-extras --dev
```

## Short-form

```bash
uv run python scripts/omni.py "el futuro de la IA en Tokio"
```

Salida: `outputs/<slug>-<timestamp>/final.mp4`.

Modo offline y determinista:

```bash
uv run python scripts/omni.py "el futuro de la IA en Tokio" \
  --no-llm \
  --image-source placeholder \
  --no-music \
  --subtitle-source proportional
```

Smoke test:

```bash
uv run python scripts/omni.py "prueba" \
  --duration 10 --scenes 2 --image-source placeholder --no-llm
```

## Ejemplo desde Python

El script [`examples/quick_omni_demo.py`](https://github.com/Dxrk777/Dxrk/blob/main/examples/quick_omni_demo.py) muestra cómo invocar el pipeline sin pasar por la CLI:

```bash
uv run python examples/quick_omni_demo.py
uv run python examples/quick_omni_demo.py --longform
```

Usa `OmniConfig` + `run_pipeline()` y un tema de tecnología/ciencia preconfigurado. El demo es determinista (sin LLM, placeholders, synth, subtítulos proporcionales); solo la narración con Edge-TTS necesita red.

## Backends visuales

### ComfyUI

```bash
uv run python scripts/omni.py "mi tema" \
  --image-source comfyui \
  --comfyui-url http://127.0.0.1:8188 \
  --comfy-checkpoint sd_xl_base_1.0.safetensors
```

El cliente envía el workflow a `POST /prompt`, sigue el progreso por WebSocket cuando `websockets` está instalado y cae a `GET /history/{prompt_id}`. La imagen final se obtiene de `GET /view`.

Workflow propio:

```bash
uv run python scripts/omni.py "mi tema" \
  --image-source comfyui \
  --comfy-workflow ./mi-workflow.json
```

Placeholders disponibles: `{{PROMPT}}`, `{{NEGATIVE_PROMPT}}`, `{{SEED}}`, `{{WIDTH}}`, `{{HEIGHT}}`, `{{CHECKPOINT}}`.

### Stable Diffusion WebUI

```bash
uv run python scripts/omni.py "mi tema" \
  --image-source sdwebui \
  --sdwebui-url http://127.0.0.1:7860
```

Requiere AUTOMATIC1111 con `--api`.

### Imágenes locales y placeholders

```bash
uv run python scripts/omni.py "mi tema" \
  --image-source local --images-dir ./assets/mi-carpeta
```

`--image-source auto` es el default: prueba ComfyUI, luego SD WebUI, luego dibuja un placeholder con Pillow. Pollinations se usa solo con `--image-source pollinations`.

## Audio, música y subtítulos

### Narración y subtítulos karaoke

Edge-TTS es el backend por defecto. Emite eventos `WordBoundary` que se guardan en `assets/words.json` y se queman como ASS con `\kf` por palabra. Si la narración se acelera, los timings se escalan con el mismo factor.

Whisper opcional:

```bash
uv pip install faster-whisper
uv run python scripts/omni.py "mi tema" \
  --subtitle-source whisper --whisper-model small
```

Fallback proporcional:

```bash
uv run python scripts/omni.py "mi tema" \
  --subtitle-source proportional
```

### Música

Synth con FFmpeg (default, sin dependencias extra):

```bash
uv run python scripts/omni.py "mi tema" --music-source synth
```

MusicGen:

```bash
uv pip install transformers torch scipy
uv run python scripts/omni.py "mi tema" \
  --music-source musicgen \
  --music-model facebook/musicgen-small \
  --music-prompt "cinematic ambient score, no vocals"
```

Stable Audio Open:

```bash
uv pip install stable-audio-tools
uv run python scripts/omni.py "mi tema" \
  --music-source stable-audio \
  --music-model stabilityai/stable-audio-open-1.0
```

Track propio:

```bash
uv run python scripts/omni.py "mi tema" --music ./assets/music/track
```

Los backends generativos producen por chunks y unen con crossfades para superar el contexto de un solo modelo. `--music-chunk-seconds` controla el tamaño del chunk (default 30).

## Long-form

```bash
uv run python scripts/omni.py "el futuro de la IA en Tokio" \
  --longform \
  --chapters 3 \
  --shots-per-chapter 3 \
  --chapter-duration 60
```

Cada capítulo tiene su propia narración y word timings. La duración mínima es `--chapter-duration` y crece si la narración es más larga. Los videos y audios se concatenan, se genera una sola cama musical para la duración total y los subtítulos se offsetean globalmente.

El plan se escribe en `plan.json` y se embebe en `manifest.json`. Si el LLM no está disponible o devuelve JSON inválido, se usa un plan determinista.

## Salida

```text
outputs/<slug>-<timestamp>/
├── final.mp4
├── manifest.json
├── script.json
├── plan.json
└── assets/
    ├── scene_01.jpg
    ├── scene_01.mp4
    ├── narration.mp3
    ├── music.wav
    ├── audio.m4a
    ├── video.mp4
    ├── subtitles.ass
    ├── words.json
    └── chapter_01/
```

`manifest.json` registra estado, timings, fuentes de imagen, errores y motivos de fallback.

## Flags principales

| Flag | Default | Propósito |
| --- | --- | --- |
| `--duration` | `30` | Duración del short (5–180 s) |
| `--scenes` | `5` | Escenas del short (2–12) |
| `--image-source` | `auto` | `auto`, `comfyui`, `sdwebui`, `pollinations`, `local`, `placeholder` |
| `--subtitle-source` | `edge` | `edge`, `whisper`, `proportional` |
| `--music-source` | `synth` | `synth`, `musicgen`, `stable-audio`, `file` |
| `--longform` | off | Activa capítulos y shots |
| `--chapters` | `3` | Capítulos (2–24) |
| `--shots-per-chapter` | `3` | Shots por capítulo (1–12) |
| `--chapter-duration` | `60` | Mínimo por capítulo (15–600 s) |
| `--no-llm` | off | Guion y plan deterministas |
| `--seed` | `42` | Semilla de imágenes |
| `--output-dir` | `outputs` | Directorio raíz |

La referencia completa está en [`scripts/README.md`](https://github.com/Dxrk777/Dxrk/blob/main/scripts/README.md).

## Tests

```bash
uv run python -m pytest -q --no-cov \
  tests/test_omni_script.py tests/test_omni_advanced.py
```

Suite completa:

```bash
uv run python -m pytest
```
