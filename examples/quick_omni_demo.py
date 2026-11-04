"""Quickstart: invoke Dxrk Omni directly from Python.

Run from the repository root:

    uv run python examples/quick_omni_demo.py
    uv run python examples/quick_omni_demo.py --longform

The demo is intentionally deterministic:

- no LLM (``use_llm=False``)
- placeholder images (Pillow)
- FFmpeg synth music
- proportional subtitles

Narration still uses Edge-TTS, so the demo needs network access for that
stage. Everything else runs locally. The generated video is written under
``outputs/<slug>-<timestamp>/final.mp4``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Running ``python examples/quick_omni_demo.py`` puts ``examples/`` on
# sys.path, not the repository root. Add the root so ``scripts.omni`` is
# importable without installing the project as a package.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.omni import OmniConfig, OmniError, run_pipeline  # noqa: E402

TOPIC = "Cómo la inteligencia artificial está acelerando el descubrimiento científico"


def build_config(*, longform: bool) -> OmniConfig:
    """Return a small, deterministic configuration for the demo.

    ``OmniConfig`` is a frozen dataclass with validation in
    ``__post_init__``. Invalid ranges raise ``OmniError`` before any
    expensive work starts.
    """
    common = {
        "topic": TOPIC,
        "output_root": REPO_ROOT / "outputs",
        "image_source": "placeholder",
        "use_llm": False,
        "subtitle_source": "proportional",
        "music_source": "synth",
        "seed": 7,
    }
    if longform:
        return OmniConfig(
            **common,
            longform=True,
            chapters=2,
            shots_per_chapter=2,
            chapter_duration=15,
            duration=30,  # 2 chapters × 15 s; validated as a long-form duration
        )
    return OmniConfig(
        **common,
        duration=12,
        scene_count=3,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--longform",
        action="store_true",
        help="Render a two-chapter long-form demo instead of a short vertical.",
    )
    args = parser.parse_args()

    config = build_config(longform=args.longform)
    mode = "long-form" if config.longform else "short-form"
    print(f"topic:  {config.topic}")
    print(f"mode:   {mode}")
    print(f"output: {config.output_root}")

    try:
        result = run_pipeline(config)
    except OmniError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"video:    {result.video}")
    print(f"manifest: {result.manifest}")
    print(f"scenes:   {len(result.script.scenes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
