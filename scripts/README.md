# Dxrk Omni — short-video MVP

`scripts/omni.py` turns a topic into a publishable vertical video:

```text
topic -> LLM script -> scene images -> TTS narration -> music -> FFmpeg edit -> final.mp4
```

It is intentionally isolated from the `dxrk` package. This is an experimental media
pipeline with external binaries and network services; it should not weaken the core
package's test and coverage contract.

## Requirements

- Python 3.12+
- `ffmpeg` and `ffprobe` available on `PATH`
- The optional `omni` Python extra:

```bash
uv sync --extra omni
```

If you are developing Dxrk itself:

```bash
uv sync --all-extras --dev
```

## Quick start

```bash
# Full pipeline: local Ollama LLM, Edge-TTS, Pollinations images, synthesized music
uv run python scripts/omni.py "el futuro de la IA en Tokio"

# Fully offline / deterministic: no LLM, placeholder cards, no music
uv run python scripts/omni.py "el futuro de la IA en Tokio" \
  --no-llm --image-source placeholder --no-music

# Your own images (they are cropped to 1080x1920)
uv run python scripts/omni.py "mi tema" \
  --image-source local --images-dir ./assets/mi-carpeta

# Your own royalty-free track
uv run python scripts/omni.py "mi tema" --music ./assets/music/track.mp3

# Shorter smoke test
uv run python scripts/omni.py "prueba" \
  --duration 10 --scenes 2 --image-source placeholder --no-llm
```

The final file is printed to stdout:

```text
video: outputs/<slug>-<timestamp>/final.mp4
manifest: outputs/<slug>-<timestamp>/manifest.json
```

## Options

| Flag | Default | Purpose |
| --- | --- | --- |
| `--duration` | `30` | Target duration in seconds (5–180) |
| `--scenes` | `5` | Scene count (2–12) |
| `--voice` | `es-AR-TomasNeural` | Edge-TTS voice |
| `--image-source` | `pollinations` | `pollinations`, `local`, or `placeholder` |
| `--images-dir` | — | Required for `--image-source local` |
| `--music` | — | Own music track; otherwise an ambient bed is synthesized |
| `--no-music` | off | Skip background music |
| `--no-subtitles` | off | Skip ASS subtitle burn-in |
| `--no-llm` | off | Use the deterministic Spanish fallback script |
| `--seed` | `42` | Image generation seed |
| `--llm-base-url` | `http://127.0.0.1:11434/v1` | OpenAI-compatible endpoint |
| `--llm-model` | `llama3.2` | Model name |
| `--llm-api-key` | `ollama` | API key for the endpoint |
| `--output-dir` | `outputs` | Root output directory |
| `--verbose` | off | Debug logging |

Environment variables:

```bash
DXRK_OMNI_VOICE=es-AR-TomasNeural
DXRK_OMNI_LLM_BASE_URL=http://127.0.0.1:11434/v1
DXRK_OMNI_LLM_MODEL=llama3.2
DXRK_OMNI_LLM_API_KEY=ollama
```

## Output layout

```text
outputs/
└── <slug>-<timestamp>/
    ├── final.mp4          # 1080x1920, H.264 + AAC, subtitles burned in
    ├── manifest.json      # status, config, scene metadata, artifact paths
    ├── script.json        # narration and visual prompts per scene
    └── assets/
        ├── scene_01.jpg
        ├── scene_01.mp4
        ├── ...
        ├── narration.mp3
        ├── music.wav
        ├── audio.m4a
        ├── video.mp4
        └── subtitles.ass
```

Generated media is ignored by Git. Only `outputs/.gitkeep` is tracked.

## Pipeline details

1. **Script** — `OpenAICompatibleClient` asks for strict JSON with `title` and
   `scenes[{narration, visual_prompt}]`. Any LLM error falls back to
   `fallback_script()`, a deterministic Spanish 8-beat structure.
2. **Images** — Pollinations is used by default. A failed request produces a
   Pillow cinematic placeholder card instead of aborting the run. Local images
   are EXIF-corrected and cropped to 1080x1920.
3. **Narration** — Edge-TTS writes `narration.mp3`. The voice is configurable.
4. **Music** — By default an original ambient bed is synthesized with FFmpeg
   sine filters, so there is no licensing ambiguity. `--music` overrides it.
5. **Audio edit** — Narration is padded or tempo-compressed to the target
   duration, mixed with music at low volume, and normalized to 44.1 kHz stereo.
6. **Video edit** — Each image becomes a 30 fps clip with a subtle zoom and
   fade. Clips are concatenated, then muxed with audio. ASS subtitles use a
   proportional timing model and a fade animation.
7. **Manifest** — Every stage writes into the work directory. A failure leaves
   `manifest.json` with `status: failed`, `stage`, and `error` for debugging.

## LLM contract

The model must return JSON only:

```json
{
  "title": "Short title",
  "scenes": [
    {
      "narration": "Spanish narration for this scene.",
      "visual_prompt": "English cinematic visual prompt, vertical 9:16, no text."
    }
  ]
}
```

Markdown fences and surrounding prose are tolerated by `parse_script_json()`.
Invalid JSON, fewer than 2 scenes, or empty fields trigger the deterministic
fallback.

## Troubleshooting

- **`edge-tts` not installed**: `uv sync --extra omni`.
- **TTS network error**: Edge-TTS needs network access. Retry, or pass a custom
  voice/endpoint. The failure is reported in `manifest.json`.
- **Pollinations slow or rate-limited**: use `--image-source placeholder` for a
  local render, or `--image-source local --images-dir ...`.
- **`ffmpeg`/`ffprobe` missing**: install them with your package manager.
- **LLM unavailable**: the script logs a warning and uses the fallback script.
  Use `--no-llm` to skip the network attempt entirely.
- **Subtitles not visible**: check that FFmpeg was built with `libass`
  (`ffmpeg -filters | grep ass`). DejaVu Sans is used as the ASS font.

## Tests

```bash
uv run python -m pytest -q --no-cov tests/test_omni_script.py
uvx ruff check scripts tests/test_omni_script.py
```

The tests cover script parsing/fallback, image preparation, command builders,
subtitle generation, pipeline success/failure manifests, and the CLI. A real
render is intentionally not part of the unit suite because it depends on
FFmpeg, network access, and TTS.

## Known limitations / next steps

- Subtitles are phrase-level, not word-level. Edge-TTS word boundaries can make
  them karaoke-style.
- Scene transitions are fade-to-black via per-clip fades, not crossfades.
- Pollinations is the only remote image adapter. A ComfyUI/local Stable
  Diffusion adapter is the natural next step.
- No automatic publishing to TikTok/YouTube/Instagram; the MVP stops at
  `final.mp4`.
- If the pipeline stabilizes, promote it to `dxrk/omni/` and add a `dxrk omni`
  subcommand with proper coverage and packaging.
