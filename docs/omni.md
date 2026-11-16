# Dxrk Omni — video y audio

**Dxrk Omni** es el pipeline multimedia de Dxrk. Convierte un tema en un short vertical o en una producción long-form por capítulos, usando backends locales cuando están disponibles y fallbacks deterministas cuando no.

```text
tema
  └─> guion (LLM opcional, speakers y líneas opcionales)
      └─> imágenes (ComfyUI / SD WebUI / locales / placeholder)
          └─> upscaling opcional (FFmpeg / Real-ESRGAN / SD WebUI)
              └─> narración (Edge-TTS, una o varias voces) + word timings
                  └─> música (FFmpeg synth / MusicGen / Stable Audio / track)
                      └─> montaje FFmpeg + ASS karaoke por speaker
                          └─> final.mp4 (1080p / 1440p / 4K, 30 fps, H.264/AAC)
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

## Resolución y upscaling

La resolución objetivo se define con `--resolution`:

```bash
# Vertical 4K: 2160x3840
uv run python scripts/omni.py "mi tema" \
  --resolution 4k \
  --upscale auto \
  --upscale-sharpen 0.6 \
  --crf 18 --preset slow
```

Valores aceptados: `1080p`, `1440p`, `4k`, o `WxH` (por ejemplo `1080x1920`).
En orientación vertical, `1920x1080` se normaliza a `1080x1920`; usá
`WxH` con el orden que quieras para forzar una orientación horizontal.

Backends de `--upscale`:

| Backend | Comportamiento |
| --- | --- |
| `none` | Genera a la resolución objetivo sin post-proceso |
| `ffmpeg` | Lanczos + `unsharp`; determinista y siempre disponible |
| `auto` | Real-ESRGAN si `realesrgan-ncnn-vulkan` está en `PATH`; si no, FFmpeg |
| `realesrgan` | Requiere el binario `realesrgan-ncnn-vulkan` |
| `sdwebui` | `POST /sdapi/v1/extra-single-image` en AUTOMATIC1111 |
| `comfyui` | Generación nativa a la resolución objetivo; el upscale standalone necesita un workflow propio y falla con un error claro |

`--upscale-model` pasa el modelo/upscaler al backend. `--upscale-sharpen`
controla el `unsharp` de FFmpeg. `--crf` y `--preset` se aplican tanto a los
clips como al mux final. Las imágenes upscaleadas se guardan como
`scene_01_upscaled.jpg` y el manifest registra `placeholder+upscale` como
fuente.

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

### Multi-voz

Un guion puede asignar una voz por escena, personaje o línea. La forma más
explícita es `--script` con `speaker` y `lines`:

```json
{
  "title": "Diálogo",
  "scenes": [
    {
      "visual_prompt": "neon city",
      "lines": [
        {"speaker": "narrator", "text": "Esto es lo que nadie te cuenta."},
        {"speaker": "guest", "text": "Y por eso importa."}
      ]
    },
    {
      "visual_prompt": "rain",
      "speaker": "narrator",
      "narration": "La diferencia está en las decisiones."
    }
  ]
}
```

```bash
uv run python scripts/omni.py \
  --script examples/omni_multivoice_script.json \
  --voices examples/omni_voices.json \
  --image-source placeholder --no-llm
```

También podés mapear speakers desde la CLI, sin archivo:

```bash
uv run python scripts/omni.py "mi tema" \
  --voice-map narrator=es-AR-TomasNeural \
  --voice-map guest=es-ES-AlvaroNeural \
  --default-speaker narrator
```

Reglas:

- `--voice` sigue siendo la voz por defecto para `--default-speaker`.
- `--voice-map speaker=voice` es repetible; el último valor gana.
- `--voices` acepta `{"narrator": "voz"}` o
  `{"voices": {"narrator": {"voice": "voz", "rate": "+5%", "pitch": "+0Hz", "volume": "+0%"}}}`.
- Un speaker sin voz asignada usa la voz por defecto y queda un warning.
- Cada línea se sintetiza como un segmento; la duración de cada escena sale
  del audio real, no de un reparto uniforme.
- El tempo se limita a `2.0`; si la narración es más corta que el target, el
  tiempo extra se agrega a la última escena.
- El ASS lleva un estilo por speaker y los subtítulos nunca mezclan palabras
  de speakers distintos en una misma línea.

El manifest agrega `multi_voice`, `voices`, `voice_segments`,
`scene_durations`, `narration_duration` y `narration_tempo`.

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

En long-form, cada capítulo puede tener `speaker` y cada shot puede tener
`speaker` o `lines`; el pipeline reutiliza la misma segmentación multi-voz,
calcula duraciones por shot desde el audio real y offsetea los timings de
todos los capítulos en un solo ASS global.

## Preview dashboard

El dashboard local es un servidor stdlib, read-only y sin FastAPI/uvicorn:

```bash
uv run python scripts/omni_preview.py --root outputs
# Dxrk Omni preview: http://127.0.0.1:8765/
```

Abre `http://127.0.0.1:8765/` para ver cada run, estado, progreso, video
final, contact sheet y log. También podés consumir la API:

| Ruta | Devuelve |
| --- | --- |
| `/healthz` | Estado del servidor y cantidad de runs |
| `/api/runs` | Catálogo de runs con URLs de video, contact sheet y log |
| `/api/runs/<slug>` | Manifest completo y URLs resueltas |
| `/api/runs/<slug>/log` | Tail de `engine.log` |
| `/media/<slug>/<path>` | Archivo del run, con `Range` y `HEAD` |

Seguridad y operación:

- Bindea `127.0.0.1` por default; `--host 0.0.0.0` es una decisión explícita.
- Valida el header `Host` contra localhost y el host bindeado.
- Resuelve cada archivo dentro del run; rechaza traversal y symlinks que
  escapan del directorio.
- Nunca escribe en `outputs/`.
- Soporta `Range` (`bytes=a-b`, `bytes=a-`, `bytes=-n`) para seeking de video.

## Salida

```text
outputs/<slug>-<timestamp>/
├── final.mp4
├── contact_sheet.png
├── engine.log
├── manifest.json
├── script.json
├── plan.json
└── assets/
    ├── scene_01.jpg
    ├── scene_01_upscaled.jpg   # solo con --upscale
    ├── scene_01.mp4
    ├── narration.mp3
    ├── music.wav
    ├── audio.m4a
    ├── video.mp4
    ├── subtitles.ass
    ├── words.json
    ├── voice/                  # segmentos multi-voz
    └── chapter_01/
```

`manifest.json` registra estado, timings, fuentes de imagen, resolución,
upscaling, speakers, errores y motivos de fallback. `engine.log` guarda el
log de esa corrida y `contact_sheet.png` es una grilla de las imágenes
generadas.

## Flags principales

| Flag | Default | Propósito |
| --- | --- | --- |
| `--duration` | `30` | Duración del short (5–180 s) |
| `--scenes` | `5` | Escenas del short (2–12) |
| `--script` | — | Script JSON propio con `speaker`/`lines` |
| `--voice` | `es-AR-TomasNeural` | Voz Edge-TTS por defecto |
| `--voice-map` | — | `speaker=voice`, repetible |
| `--voices` | — | JSON con mapa de voces por speaker |
| `--default-speaker` | `narrator` | Speaker que usa `--voice` |
| `--resolution` | `1080p` | `1080p`, `1440p`, `4k` o `WxH` |
| `--upscale` | `none` | `none`, `auto`, `ffmpeg`, `realesrgan`, `comfyui`, `sdwebui` |
| `--upscale-model` | — | Modelo/upscaler del backend |
| `--upscale-sharpen` | `0` | Cantidad de `unsharp` para FFmpeg |
| `--crf` | `20` | CRF de x264 (0–51) |
| `--preset` | `veryfast` | Preset de x264 |
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
  tests/test_omni_script.py tests/test_omni_advanced.py \
  tests/test_omni_voices.py tests/test_omni_words_multi.py \
  tests/test_omni_upscale.py tests/test_omni_contact_sheet.py \
  tests/test_omni_preview.py tests/test_omni_preview_server.py \
  tests/test_omni_multivoice_pipeline.py
```

Coverage específico de los módulos v1.6:

```bash
uv run pytest tests/test_omni_*.py -o addopts="" \
  --cov=scripts.omni_media.voices \
  --cov=scripts.omni_media.upscale \
  --cov=scripts.omni_media.contact_sheet \
  --cov=scripts.omni_media.preview \
  --cov=scripts.omni_preview \
  --cov-report=term-missing --cov-fail-under=100
```

Suite completa:

```bash
uv run python -m pytest
```
