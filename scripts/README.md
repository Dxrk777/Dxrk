# Dxrk Omni — video pipeline

`scripts/omni.py` turns a topic into a publishable vertical video:

```text
topic -> script -> images -> narration + word timings -> music -> FFmpeg edit -> final.mp4
```

The short-video loop produces 1080x1920, 30 fps, H.264/AAC clips. The same
building blocks also drive a long-form mode that renders chapters and joins
them into a corto or película.

The pipeline is intentionally isolated from the `dxrk` package. It is an
experimental media pipeline with external binaries and network services; it
must not weaken the core package's test and coverage contract.

## Requirements

- Python 3.12+
- `ffmpeg` and `ffprobe` available on `PATH`
- The optional `omni` Python extra:

```bash
uv sync --extra omni
```

That extra installs `edge-tts`, Pillow, and `websockets` (used for ComfyUI
progress events). If you are developing Dxrk itself:

```bash
uv sync --all-extras --dev
```

## Quick start

```bash
# Local-first: try ComfyUI, then SD WebUI, then a placeholder card.
# Edge-TTS narration, word-level subtitles, synthesized music.
uv run python scripts/omni.py "el futuro de la IA en Tokio"

# Fully offline / deterministic: no LLM, placeholder cards, proportional
# subtitles, no music.
uv run python scripts/omni.py "el futuro de la IA en Tokio" \
  --no-llm --image-source placeholder --no-music --subtitle-source proportional

# ComfyUI (default checkpoint must exist in your ComfyUI models folder)
uv run python scripts/omni.py "mi tema" \
  --image-source comfyui \
  --comfyui-url http://127.0.0.1:8188 \
  --comfy-checkpoint sd_xl_base_1.0.safetensors

# Stable Diffusion WebUI (AUTOMATIC1111 API)
uv run python scripts/omni.py "mi tema" \
  --image-source sdwebui \
  --sdwebui-url http://127.0.0.1:7860

# Your own images (they are cropped to 1080x1920)
uv run python scripts/omni.py "mi tema" \
  --image-source local --images-dir ./assets/mi-carpeta

# Your own royalty-free track
uv run python scripts/omni.py "mi tema" --music ./assets/music/track.mp3

# Legacy remote images (Pollinations is flaky; placeholder fallback applies)
uv run python scripts/omni.py "mi tema" --image-source pollinations

# Shorter smoke test
uv run python scripts/omni.py "prueba" \
  --duration 10 --scenes 2 --image-source placeholder --no-llm

# Long-form: two 15s chapters, one shot each
uv run python scripts/omni.py "el futuro de la IA en Tokio" \
  --longform --chapters 2 --shots-per-chapter 1 --chapter-duration 15 \
  --image-source placeholder --no-llm --no-music
```

The final file is printed to stdout:

```text
video: outputs/<slug>-<timestamp>/final.mp4
manifest: outputs/<slug>-<timestamp>/manifest.json
```

## Output layout

```text
outputs/<slug>-<timestamp>/
├── final.mp4
├── manifest.json          # status, timings, image sources, errors
├── script.json            # short-form script
├── plan.json              # long-form chapter/shot plan
└── assets/
    ├── scene_01.jpg       # short-form images
    ├── scene_01.mp4       # short-form clips
    ├── narration.mp3
    ├── music.wav
    ├── audio.m4a
    ├── video.mp4
    ├── subtitles.ass
    ├── words.json         # word-level timings (text/start/end)
    └── chapter_01/        # long-form chapter assets
```

## Local image backends

### ComfyUI

`--image-source comfyui` submits a workflow to `POST /prompt`, follows progress
over `/ws?clientId=...` when `websockets` is installed, and falls back to
`GET /history/{prompt_id}` polling. The result is fetched from `GET /view` and
cropped to 1080x1920.

The built-in workflow uses these node ids:

| Node | Class | Purpose |
| --- | --- | --- |
| `3` | `KSampler` | sampling |
| `4` | `CheckpointLoaderSimple` | checkpoint |
| `5` | `EmptyLatentImage` | 1080x1920 latent |
| `6` | `CLIPTextEncode` | positive prompt |
| `7` | `CLIPTextEncode` | negative prompt |
| `8` | `VAEDecode` | decode |
| `9` | `SaveImage` | output |

Set `--comfy-checkpoint` to a checkpoint that exists in your ComfyUI install.
For a custom graph, pass `--comfy-workflow path.json`. String values support
these placeholders:

| Placeholder | Value |
| --- | --- |
| `{{PROMPT}}` | scene visual prompt |
| `{{NEGATIVE_PROMPT}}` | negative prompt |
| `{{SEED}}` | image seed |
| `{{WIDTH}}` / `{{HEIGHT}}` | target size |
| `{{CHECKPOINT}}` | `--comfy-checkpoint` |

Exact placeholders keep their type (`{{SEED}}` becomes an integer). Embedded
placeholders are stringified.

### Stable Diffusion WebUI

`--image-source sdwebui` calls `POST /sdapi/v1/txt2img` on AUTOMATIC1111 and
decodes the base64 image. Start the server with the `--api` flag.

### Automatic fallback

`--image-source auto` is the default. It tries ComfyUI, then SD WebUI, then
draws a local placeholder card. The manifest records each image source and the
reason for any fallback. Pollinations is no longer in the automatic path; use
`--image-source pollinations` explicitly if you want the remote service.

## Word-level subtitles

Edge-TTS emits `WordBoundary` events while streaming audio. The pipeline stores
them in `assets/words.json` and burns karaoke-style ASS subtitles with `\kf`
timing per word. When the narration is sped up to fit the target duration, the
word timings are scaled by the same tempo factor.

Fallback order:

1. `--subtitle-source edge` (default): Edge-TTS word boundaries.
2. `--subtitle-source whisper`: `faster-whisper` word timestamps.
3. `--subtitle-source proportional`: distribute words across the audio
   duration by character weight.

Whisper is optional and is not installed by the `omni` extra:

```bash
uv pip install faster-whisper
uv run python scripts/omni.py "mi tema" \
  --subtitle-source whisper --whisper-model small
```

## Long-duration music

`--music-source synth` (default) uses the dependency-free FFmpeg ambient
synthesizer. The other backends generate chunks and join them with FFmpeg
crossfades, so the track can be longer than one model context window.

```bash
# MusicGen (transformers + torch + scipy)
uv pip install transformers torch scipy
uv run python scripts/omni.py "mi tema" \
  --music-source musicgen \
  --music-model facebook/musicgen-small \
  --music-prompt "cinematic ambient score, no vocals"

# Stable Audio Open (stable-audio-tools)
uv pip install stable-audio-tools
uv run python scripts/omni.py "mi tema" \
  --music-source stable-audio \
  --music-model stabilityai/stable-audio-open-1.0
```

The models are loaded lazily and only when the corresponding source is
selected. `--music-chunk-seconds` controls the chunk size (default 30).

## Long-form mode

`--longform` renders a plan of chapters and shots. Each chapter gets its own
narration and word timings; the chapter duration is at least
`--chapter-duration` seconds and grows if the narration is longer. Chapter
videos and audios are concatenated, one music bed is generated for the total
duration, and subtitle timings are offset globally.

```bash
uv run python scripts/omni.py "el futuro de la IA en Tokio" \
  --longform --chapters 3 --shots-per-chapter 3 --chapter-duration 60
```

The plan is written to `plan.json` and embedded in `manifest.json`. The LLM
prompt asks for exactly the requested number of chapters and shots; if the LLM
is unavailable or returns invalid JSON, a deterministic fallback plan is used.

## Options

| Flag | Default | Purpose |
| --- | --- | --- |
| `--duration` | `30` | Short target duration in seconds (5–180) |
| `--scenes` | `5` | Short scene count (2–12) |
| `--voice` | `es-AR-TomasNeural` | Edge-TTS voice |
| `--image-source` | `auto` | `auto`, `comfyui`, `sdwebui`, `pollinations`, `local`, `placeholder` |
| `--images-dir` | — | Directory for `--image-source local` |
| `--comfyui-url` | `http://127.0.0.1:8188` | ComfyUI base URL |
| `--comfy-checkpoint` | `sd_xl_base_1.0.safetensors` | ComfyUI checkpoint name |
| `--comfy-workflow` | — | Custom ComfyUI workflow JSON with placeholders |
| `--sdwebui-url` | `http://127.0.0.1:7860` | SD WebUI base URL |
| `--negative-prompt` | built-in | Negative prompt for local backends |
| `--image-timeout` | `300` | Timeout per image in seconds |
| `--subtitle-source` | `edge` | `edge`, `whisper`, `proportional` |
| `--whisper-model` | `small` | faster-whisper model size |
| `--music-source` | `synth` | `synth`, `musicgen`, `stable-audio`, `file` |
| `--music-model` | backend default | MusicGen or Stable Audio model id |
| `--music-prompt` | topic | Music generation prompt |
| `--music-chunk-seconds` | `30` | Chunk size for long music generation |
| `--music` | — | Your own track (implies file input) |
| `--no-music` | off | Disable background music |
| `--no-subtitles` | off | Do not burn subtitles |
| `--longform` | off | Enable chapter/shot mode |
| `--chapters` | `3` | Long-form chapter count (2–24) |
| `--shots-per-chapter` | `3` | Shots per chapter (1–12) |
| `--chapter-duration` | `60` | Minimum seconds per chapter (15–600) |
| `--no-llm` | off | Use deterministic scripts/plans |
| `--seed` | `42` | Image seed |
| `--llm-base-url` | `http://127.0.0.1:11434/v1` | OpenAI-compatible endpoint |
| `--llm-model` | `llama3.2` | LLM model |
| `--llm-api-key` | `ollama` | LLM API key |
| `--output-dir` | `outputs` | Output root |
| `--verbose` | off | Debug logging |

## Tests

```bash
# Fast, no coverage
uv run python -m pytest -q --no-cov tests/test_omni_script.py tests/test_omni_advanced.py

# Full project gate
uv run python -m pytest -q
```

## Limitations

- ComfyUI, SD WebUI, Whisper, MusicGen, and Stable Audio are not bundled. The
  pipeline fails over to a placeholder image, proportional timings, or the
  FFmpeg synth when an optional backend is unavailable.
- The default ComfyUI checkpoint is only a placeholder name; set
  `--comfy-checkpoint` to a model you actually have.
- Pollinations remains available but is flaky. Prefer a local backend for
  production.
- The LLM path expects an OpenAI-compatible `/chat/completions` endpoint. The
  deterministic fallback keeps the pipeline usable without one.
