# SPDX-License-Identifier: MIT
"""Dxrk Omni — topic-to-short-video MVP.

The pipeline is deliberately boring and inspectable:

    topic -> script -> images -> narration -> music -> edit -> final.mp4

Every stage writes its artifact under ``outputs/<slug>-<timestamp>/`` so a
failed run can be resumed or debugged without regenerating everything.

External tools:
  * ffmpeg/ffprobe (system)
  * edge-tts (optional Python extra ``omni``)
  * Pillow (optional Python extra ``omni``)
  * an OpenAI-compatible LLM endpoint (Ollama by default), optional
  * Pollinations for images, optional; falls back to local placeholder cards

Run:
    uv run python scripts/omni.py "el futuro de la IA en Tokio"
    uv run python scripts/omni.py "tema" --image-source placeholder --no-music
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unicodedata
import urllib.parse
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

if __package__:
    from scripts.omni_media.images import (
        DEFAULT_COMFY_CHECKPOINT,
        DEFAULT_COMFY_URL,
        DEFAULT_NEGATIVE_PROMPT,
        DEFAULT_SDWEBUI_URL,
        ComfyUIClient,
        ImageResult,
        SDWebUIClient,
    )
    from scripts.omni_media.longform import (
        LongformPlan,
        generate_longform_plan,
        plan_to_dict,
    )
    from scripts.omni_media.music import (
        build_music_generator,
        concat_audio_tracks,
        prepare_track,
        synthesize_ambient,
    )
    from scripts.omni_media.upscale import (
        Resolution,
        UpscaleConfig,
        parse_resolution,
        upscale_image,
    )
    from scripts.omni_media.voices import (
        DEFAULT_SPEAKER,
        VoiceLine,
        VoiceSpec,
        assign_scene_durations,
        load_voice_map,
        parse_voice_specs,
        resolve_voices,
        segment_scenes,
        synthesize_requests,
        timeline_words,
    )
    from scripts.omni_media.words import (
        NarrationResult,
        WordTiming,
        ass_header,
        offset_timings,
        proportional_timings,
        scale_timings,
        style_for_speaker,
        timings_from_edge_events,
        transcribe_words,
        words_to_dict,
        write_word_ass,
    )
else:
    from omni_media.images import (
        DEFAULT_COMFY_CHECKPOINT,
        DEFAULT_COMFY_URL,
        DEFAULT_NEGATIVE_PROMPT,
        DEFAULT_SDWEBUI_URL,
        ComfyUIClient,
        ImageResult,
        SDWebUIClient,
    )
    from omni_media.longform import (
        LongformPlan,
        generate_longform_plan,
        plan_to_dict,
    )
    from omni_media.music import (
        build_music_generator,
        concat_audio_tracks,
        prepare_track,
        synthesize_ambient,
    )
    from omni_media.upscale import (
        Resolution,
        UpscaleConfig,
        parse_resolution,
        upscale_image,
    )
    from omni_media.voices import (
        DEFAULT_SPEAKER,
        VoiceLine,
        VoiceSpec,
        assign_scene_durations,
        load_voice_map,
        parse_voice_specs,
        resolve_voices,
        segment_scenes,
        synthesize_requests,
        timeline_words,
    )
    from omni_media.words import (
        NarrationResult,
        WordTiming,
        ass_header,
        offset_timings,
        proportional_timings,
        scale_timings,
        style_for_speaker,
        timings_from_edge_events,
        transcribe_words,
        words_to_dict,
        write_word_ass,
    )

logger = logging.getLogger("dxrk.omni")

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30
DEFAULT_VOICE = os.environ.get("DXRK_OMNI_VOICE", "es-AR-TomasNeural")
DEFAULT_LLM_BASE_URL = os.environ.get("DXRK_OMNI_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
DEFAULT_LLM_MODEL = os.environ.get("DXRK_OMNI_LLM_MODEL", "llama3.2")
DEFAULT_LLM_API_KEY = os.environ.get("DXRK_OMNI_LLM_API_KEY", "ollama")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class OmniError(RuntimeError):
    """A pipeline stage could not complete."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scene:
    index: int
    narration: str
    visual_prompt: str
    speaker: str = DEFAULT_SPEAKER
    lines: tuple[VoiceLine, ...] = ()

    @property
    def text(self) -> str:
        if self.lines:
            return " ".join(line.text for line in self.lines)
        return self.narration


@dataclass(frozen=True, slots=True)
class VideoScript:
    topic: str
    title: str
    scenes: tuple[Scene, ...]

    @property
    def narration(self) -> str:
        return " ".join(scene.text for scene in self.scenes)


@dataclass(frozen=True, slots=True)
class OmniConfig:
    topic: str
    output_root: Path = Path("outputs")
    duration: int = 30
    scene_count: int = 5
    voice: str = DEFAULT_VOICE
    script_path: Path | None = None
    default_speaker: str = DEFAULT_SPEAKER
    voice_map: tuple[VoiceSpec, ...] = ()
    voices_path: Path | None = None
    resolution: str = "1080p"
    upscale: str = "none"
    upscale_model: str = ""
    upscale_sharpen: float = 0.0
    video_crf: int = 20
    video_preset: str = "veryfast"
    image_source: str = "auto"
    images_dir: Path | None = None
    music_path: Path | None = None
    no_music: bool = False
    no_subtitles: bool = False
    seed: int = 42
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    llm_api_key: str = DEFAULT_LLM_API_KEY
    use_llm: bool = True
    comfyui_url: str = DEFAULT_COMFY_URL
    comfy_checkpoint: str = DEFAULT_COMFY_CHECKPOINT
    comfy_workflow: Path | None = None
    sdwebui_url: str = DEFAULT_SDWEBUI_URL
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    image_timeout: float = 300.0
    subtitle_source: str = "edge"
    whisper_model: str = "small"
    music_source: str = "synth"
    music_model: str = ""
    music_prompt: str = ""
    music_chunk_seconds: float = 30.0
    longform: bool = False
    chapters: int = 3
    shots_per_chapter: int = 3
    chapter_duration: int = 60

    def __post_init__(self) -> None:
        topic = self.topic.strip()
        if not topic and self.script_path is None:
            raise OmniError("el tema no puede estar vacío")
        object.__setattr__(self, "topic", topic)
        if self.longform and self.script_path is not None:
            raise OmniError("--script no está soportado con --longform")
        if not self.default_speaker.strip():
            raise OmniError("default_speaker no puede estar vacío")
        for spec in self.voice_map:
            if not spec.name.strip() or not spec.voice.strip():
                raise OmniError("voice_map tiene un speaker o una voz vacía")
        try:
            parse_resolution(self.resolution)
        except Exception as exc:
            raise OmniError(str(exc)) from exc
        if self.upscale not in {"none", "ffmpeg", "realesrgan", "comfyui", "sdwebui", "auto"}:
            raise OmniError("upscale debe ser none, ffmpeg, realesrgan, comfyui, sdwebui o auto")
        if self.upscale_sharpen < 0:
            raise OmniError("upscale_sharpen no puede ser negativo")
        if not 0 <= self.video_crf <= 51:
            raise OmniError("video_crf debe estar entre 0 y 51")
        if self.video_preset not in {
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        }:
            raise OmniError("video_preset inválido")
        if self.longform:
            if not 5 <= self.duration <= 14400:
                raise OmniError("la duración longform debe estar entre 5 y 14400 segundos")
            if not 2 <= self.chapters <= 24:
                raise OmniError("los capítulos deben ser entre 2 y 24")
            if not 1 <= self.shots_per_chapter <= 12:
                raise OmniError("los shots por capítulo deben ser entre 1 y 12")
            if not 15 <= self.chapter_duration <= 600:
                raise OmniError("la duración por capítulo debe estar entre 15 y 600 segundos")
        else:
            if not 5 <= self.duration <= 180:
                raise OmniError("la duración debe estar entre 5 y 180 segundos")
            if not 2 <= self.scene_count <= 12:
                raise OmniError("las escenas deben ser entre 2 y 12")
        if self.image_source not in {"auto", "comfyui", "sdwebui", "pollinations", "local", "placeholder"}:
            raise OmniError("image_source debe ser auto, comfyui, sdwebui, pollinations, local o placeholder")
        if self.image_source == "local" and self.images_dir is None:
            raise OmniError("image_source=local requiere --images-dir")
        if self.subtitle_source not in {"edge", "whisper", "proportional"}:
            raise OmniError("subtitle_source debe ser edge, whisper o proportional")
        if self.music_source not in {"synth", "musicgen", "stable-audio", "file"}:
            raise OmniError("music_source debe ser synth, musicgen, stable-audio o file")
        if self.music_source == "file" and self.music_path is None:
            raise OmniError("music_source=file requiere --music")
        if self.music_chunk_seconds <= 0:
            raise OmniError("music_chunk_seconds debe ser positivo")

    @property
    def resolution_size(self) -> Resolution:
        return parse_resolution(self.resolution)

    @property
    def base_resolution_size(self) -> Resolution:
        """Resolution used before an optional upscale pass.

        Generating 4K directly is slow and makes ``--upscale`` a no-op. When
        upscaling is enabled above 1080p, generate/prepare at 1080p and let the
        selected backend reach the target resolution.
        """
        target = self.resolution_size
        if self.upscale == "none":
            return target
        short_side = min(target.width, target.height)
        if short_side <= 1080:
            return target
        scale = 1080 / short_side
        width = max(2, round(target.width * scale))
        height = max(2, round(target.height * scale))
        width -= width % 2
        height -= height % 2
        return Resolution(width, height, f"{width}x{height}")


@dataclass(frozen=True, slots=True)
class PipelineResult:
    workdir: Path
    video: Path
    script: VideoScript
    manifest: Path


class LlmClient(Protocol):
    def complete(self, prompt: str) -> str:
        """Return the model response as text."""
        ...


# ---------------------------------------------------------------------------
# Script generation
# ---------------------------------------------------------------------------

_BEATS: tuple[tuple[str, str], ...] = (
    (
        "Esto es lo que nadie te cuenta sobre {topic}.",
        "cinematic close-up of a mysterious object representing {topic}, neon reflections, shallow depth of field",
    ),
    (
        "En los próximos segundos vas a entender por qué {topic} importa de verdad.",
        "wide establishing shot of a futuristic city at night, holographic data streams about {topic}",
    ),
    (
        "La primera clave: {topic} no es una moda. Es una herramienta que ya está cambiando decisiones.",
        "macro shot of a human hand interacting with a glowing interface, {topic} visualised as light",
    ),
    (
        "La segunda clave: el impacto aparece cuando la usás con criterio, no cuando la usás por usarla.",
        "split composition of a calm human face and a chaotic digital storm, {topic} in the background",
    ),
    (
        "La tercera clave: lo que hoy parece futuro, mañana va a ser el estándar.",
        "time-lapse of a city transforming from analog to cyberpunk, {topic} as the visual anchor",
    ),
    (
        "Pero hay un riesgo: confundir velocidad con dirección.",
        "dramatic low-angle shot of a crossroads in a rain-soaked neon city, {topic} signage",
    ),
    (
        "La diferencia está en las decisiones que tomás ahora.",
        "portrait of a determined creator looking at a wall of screens, {topic} reflected in the eyes",
    ),
    (
        "Si querés más, seguime. Esto recién empieza.",
        "hero shot of a lone figure walking toward a bright horizon, {topic} symbol in the sky",
    ),
)


def fallback_script(
    topic: str,
    scene_count: int = 5,
    *,
    default_speaker: str = DEFAULT_SPEAKER,
) -> VideoScript:
    """Build a deterministic script when no LLM is available."""
    clean = topic.strip().rstrip(".!?") or "el futuro"
    if scene_count == 2:
        chosen = [_BEATS[0], _BEATS[-1]]
    elif scene_count >= len(_BEATS):
        chosen = list(_BEATS) + [_BEATS[i % len(_BEATS)] for i in range(scene_count - len(_BEATS))]
    else:
        chosen = list(_BEATS[: scene_count - 1]) + [_BEATS[-1]]
    scenes = tuple(
        Scene(
            index=i + 1,
            narration=narration.format(topic=clean),
            visual_prompt=(
                f"{visual.format(topic=clean)}. Topic: {clean}. Vertical 9:16, cinematic, ultra detailed, no text."
            ),
            speaker=default_speaker,
        )
        for i, (narration, visual) in enumerate(chosen)
    )
    title = f"{clean[0].upper()}{clean[1:]}" if clean else "Dxrk Omni"
    return VideoScript(topic=clean, title=title, scenes=scenes)


def build_script_prompt(topic: str, scene_count: int, duration: int) -> str:
    words = max(20, round(duration * 2.5))
    return (
        "Sos un guionista de shorts verticales. Devolvé SOLO JSON válido, sin markdown.\n"
        f"Tema: {topic}\n"
        f"Escenas: exactamente {scene_count}.\n"
        f"Duración total: {duration} segundos. La narración completa debe rondar las {words} palabras.\n"
        "Cada escena debe tener 'narration' (español rioplatense, natural, sin muletillas) y "
        "'visual_prompt' (inglés, cinematográfico, vertical 9:16, sin texto ni logos).\n"
        "La primera escena es el hook; la última es el CTA. No repitas frases.\n"
        'Formato: {"title": "...", "scenes": [{"narration": "...", "visual_prompt": "..."}]}'
    )


def _parse_scene_lines(raw_lines: Any, scene_index: int, default_speaker: str) -> tuple[VoiceLine, ...]:
    if raw_lines is None:
        return ()
    if not isinstance(raw_lines, list):
        raise OmniError(f"las líneas de la escena {scene_index} deben ser una lista")
    lines: list[VoiceLine] = []
    for line_index, item in enumerate(raw_lines):
        if not isinstance(item, dict):
            raise OmniError(f"la línea {line_index + 1} de la escena {scene_index} no es un objeto")
        speaker = str(item.get("speaker") or default_speaker).strip() or default_speaker
        text = str(item.get("text") or item.get("narration") or "").strip()
        if not text:
            raise OmniError(f"la línea {line_index + 1} de la escena {scene_index} está vacía")
        lines.append(VoiceLine(speaker=speaker, text=text))
    return tuple(lines)


def parse_script_json(
    raw: str,
    topic: str,
    *,
    default_speaker: str = DEFAULT_SPEAKER,
) -> VideoScript:
    """Parse an LLM response, tolerating markdown fences and surrounding prose."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise OmniError("el LLM no devolvió un objeto JSON")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise OmniError(f"JSON inválido del LLM: {exc}") from exc
    if not isinstance(data, dict):
        raise OmniError("el JSON del LLM debe ser un objeto")
    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not 2 <= len(raw_scenes) <= 12:
        raise OmniError("el JSON del LLM debe traer entre 2 y 12 escenas")
    scenes: list[Scene] = []
    for i, item in enumerate(raw_scenes):
        if not isinstance(item, dict):
            raise OmniError(f"la escena {i + 1} no es un objeto")
        speaker = str(item.get("speaker") or default_speaker).strip() or default_speaker
        lines = _parse_scene_lines(item.get("lines"), i + 1, speaker)
        narration = str(item.get("narration", "")).strip()
        if not narration and lines:
            narration = " ".join(line.text for line in lines)
        visual_prompt = str(item.get("visual_prompt", "")).strip()
        if not narration or not visual_prompt:
            raise OmniError(f"la escena {i + 1} necesita narration y visual_prompt")
        scenes.append(
            Scene(
                index=i + 1,
                narration=narration,
                visual_prompt=visual_prompt,
                speaker=speaker,
                lines=lines,
            )
        )
    script_topic = str(data.get("topic") or topic).strip() or topic or "Dxrk Omni"
    title = str(data.get("title") or script_topic).strip() or script_topic
    return VideoScript(topic=script_topic, title=title, scenes=tuple(scenes))


def load_script(path: Path, *, default_speaker: str = DEFAULT_SPEAKER) -> VideoScript:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OmniError(f"no pude leer el script {path}: {exc}") from exc
    return parse_script_json(raw, "", default_speaker=default_speaker)


def generate_script(
    topic: str,
    scene_count: int,
    duration: int,
    llm: LlmClient | None,
    *,
    default_speaker: str = DEFAULT_SPEAKER,
) -> VideoScript:
    if llm is None:
        return fallback_script(topic, scene_count, default_speaker=default_speaker)
    try:
        raw = llm.complete(build_script_prompt(topic, scene_count, duration))
        return parse_script_json(raw, topic, default_speaker=default_speaker)
    except Exception as exc:
        logger.warning("LLM script failed (%s); using deterministic fallback", exc)
        return fallback_script(topic, scene_count, default_speaker=default_speaker)


@dataclass(frozen=True, slots=True)
class OpenAICompatibleClient:
    base_url: str
    model: str
    api_key: str
    timeout: float = 90.0
    transport: httpx.BaseTransport | None = None

    def complete(self, prompt: str) -> str:
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Respondé únicamente con JSON válido."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
            "stream": False,
        }
        with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
            response = client.post(url, headers={"Authorization": f"Bearer {self.api_key}"}, json=payload)
            response.raise_for_status()
            data = response.json()
        return str(data["choices"][0]["message"]["content"])


# ---------------------------------------------------------------------------
# Paths, images and audio assets
# ---------------------------------------------------------------------------


def slugify(text: str, max_length: int = 60) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug[:max_length].rstrip("-") or "short-video"


def unique_workdir(output_root: Path, topic: str, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = output_root / f"{slugify(topic)}-{stamp}"
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = base.with_name(f"{base.name}-{suffix:02d}")
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def build_pollinations_url(
    prompt: str,
    seed: int,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
) -> str:
    encoded = urllib.parse.quote(prompt, safe="")
    return f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&nologo=true&seed={seed}"


def _pillow() -> tuple[Any, Any, Any, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps
    except ImportError as exc:  # pragma: no cover - environment guard
        raise OmniError("Pillow no está instalado. Ejecutá: uv sync --extra omni") from exc
    return Image, ImageDraw, ImageFont, ImageOps


def placeholder_image(
    prompt: str,
    dest: Path,
    seed: int = 42,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
) -> Path:
    """Create a cinematic card so the pipeline still works offline."""
    Image, ImageDraw, ImageFont, _ = _pillow()
    rng = random.Random(seed)
    base = (rng.randint(4, 12), rng.randint(4, 12), rng.randint(10, 24))
    accent = (rng.randint(0, 60), rng.randint(180, 255), rng.randint(180, 255))
    scale_x = width / VIDEO_WIDTH
    scale_y = height / VIDEO_HEIGHT
    image = Image.new("RGB", (width, height), base)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(int(base[i] * (1 - t) + accent[i] * t * 0.28) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    grid = ImageDraw.Draw(overlay)
    step_x = max(1, round(90 * scale_x))
    step_y = max(1, round(90 * scale_y))
    for x in range(0, width, step_x):
        grid.line([(x, 0), (x, height)], fill=(*accent, 18), width=1)
    for y in range(0, height, step_y):
        grid.line([(0, y), (width, y)], fill=(*accent, 18), width=1)
    gradient_start = round(height * 1180 / VIDEO_HEIGHT)
    gradient_height = max(1, height - gradient_start)
    for y in range(gradient_start, height):
        alpha = int(190 * (y - gradient_start) / gradient_height)
        grid.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(image)
    font_big_size = max(1, round(58 * scale_y))
    font_small_size = max(1, round(38 * scale_y))
    try:
        font_big = ImageFont.truetype("DejaVuSans-Bold.ttf", font_big_size)
        font_small = ImageFont.truetype("DejaVuSans.ttf", font_small_size)
    except OSError:
        font_big = ImageFont.load_default(size=font_big_size)
        font_small = ImageFont.load_default(size=font_small_size)
    left = round(70 * scale_x)
    draw.text((left, round(90 * scale_y)), "DXRK / OMNI", font=font_small, fill=accent)
    draw.text((left, round(150 * scale_y)), "PLACEHOLDER FRAME", font=font_small, fill=(150, 160, 180))
    draw.line(
        [(left, round(760 * scale_y)), (round(1010 * scale_x), round(760 * scale_y))],
        fill=accent,
        width=max(1, round(4 * scale_y)),
    )
    wrapped = textwrap.wrap(prompt, width=30)[:4]
    y = round(800 * scale_y)
    line_height = max(1, round(74 * scale_y))
    for line in wrapped:
        draw.text((left, y), line, font=font_big, fill=(240, 240, 245))
        y += line_height
    image.save(dest, "JPEG", quality=92)
    return dest


def prepare_image(src: Path, dest: Path, width: int = VIDEO_WIDTH, height: int = VIDEO_HEIGHT) -> Path:
    Image, _, _, ImageOps = _pillow()
    try:
        with Image.open(src) as image:
            prepared = ImageOps.exif_transpose(image).convert("RGB")
            prepared = ImageOps.fit(prepared, (width, height), method=Image.Resampling.LANCZOS)
            prepared.save(dest, "JPEG", quality=92)
    except OSError as exc:
        raise OmniError(f"no pude preparar la imagen {src}: {exc}") from exc
    return dest


def _load_workflow(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.exists():
        raise OmniError(f"no existe el workflow de ComfyUI: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OmniError(f"workflow de ComfyUI inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise OmniError("el workflow de ComfyUI debe ser un objeto JSON")
    return data


def generate_image(
    prompt: str,
    dest: Path,
    *,
    source: str,
    seed: int,
    client: httpx.Client | None = None,
    timeout: float = 60.0,
    comfyui_url: str = DEFAULT_COMFY_URL,
    comfy_checkpoint: str = DEFAULT_COMFY_CHECKPOINT,
    comfy_workflow: Path | None = None,
    sdwebui_url: str = DEFAULT_SDWEBUI_URL,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
    ws_connect: Any | None = None,
    use_websocket: bool = True,
) -> ImageResult:
    if source == "placeholder":
        placeholder_image(prompt, dest, seed, width, height)
        return ImageResult(dest, "placeholder")
    if source == "pollinations":
        url = build_pollinations_url(prompt, seed, width, height)
        try:
            if client is None:
                with httpx.Client(timeout=timeout, follow_redirects=True) as owned:
                    response = owned.get(url)
                    response.raise_for_status()
                    payload = response.content
            else:
                response = client.get(url)
                response.raise_for_status()
                payload = response.content
            with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
                fh.write(payload)
                tmp = Path(fh.name)
            try:
                prepare_image(tmp, dest, width, height)
            finally:
                tmp.unlink(missing_ok=True)
            return ImageResult(dest, "pollinations")
        except Exception as exc:
            logger.warning("Pollinations failed (%s); using placeholder", exc)
            placeholder_image(prompt, dest, seed, width, height)
            return ImageResult(dest, "placeholder", str(exc)[:200])
    if source in {"comfyui", "sdwebui", "auto"}:
        errors: list[str] = []
        if source in {"comfyui", "auto"}:
            try:
                backend = ComfyUIClient(
                    base_url=comfyui_url,
                    checkpoint=comfy_checkpoint,
                    workflow=_load_workflow(comfy_workflow),
                    timeout=timeout,
                    client=client,
                    ws_connect=ws_connect,
                    use_websocket=use_websocket,
                )
                return backend.generate(
                    prompt,
                    dest,
                    seed=seed,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                )
            except Exception as exc:
                errors.append(f"comfyui: {exc}")
                logger.warning("ComfyUI failed (%s)", exc)
        if source in {"sdwebui", "auto"}:
            try:
                backend = SDWebUIClient(base_url=sdwebui_url, timeout=timeout, client=client)
                return backend.generate(
                    prompt,
                    dest,
                    seed=seed,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                )
            except Exception as exc:
                errors.append(f"sdwebui: {exc}")
                logger.warning("SD WebUI failed (%s)", exc)
        placeholder_image(prompt, dest, seed, width, height)
        return ImageResult(dest, "placeholder", "; ".join(errors)[:200])
    raise OmniError(f"fuente de imagen desconocida: {source}")


def list_local_images(images_dir: Path | None) -> list[Path]:
    if images_dir is None:
        raise OmniError("image_source=local requiere --images-dir")
    if not images_dir.is_dir():
        raise OmniError(f"no existe el directorio de imágenes: {images_dir}")
    images = sorted(path for path in images_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        raise OmniError(f"no encontré imágenes en {images_dir}")
    return images


def run_command(cmd: Sequence[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, check=True, capture_output=capture, text=True)
    except FileNotFoundError as exc:
        raise OmniError(f"no encontré {cmd[0]}; instalá ffmpeg y ffprobe") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise OmniError(f"falló {cmd[0]}: {detail[-600:]}") from exc


def run_capture(cmd: Sequence[str]) -> str:
    return run_command(cmd, capture=True).stdout or ""


def ensure_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise OmniError(f"faltan binarios del sistema: {', '.join(missing)}")


def probe_duration(path: Path, runner: Any | None = None) -> float:
    capture = runner or run_capture
    output = capture(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)]
    )
    try:
        return float(str(output).strip())
    except ValueError as exc:
        raise OmniError(f"no pude leer la duración de {path}") from exc


def tts_narrate(
    text: str,
    dest: Path,
    voice: str,
    tts: Any | None = None,
) -> Path:
    if tts is not None:
        tts(text, dest, voice)
    else:
        try:
            import edge_tts  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment guard
            raise OmniError("edge-tts no está instalado. Ejecutá: uv sync --extra omni") from exc

        async def _save() -> None:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(dest))

        try:
            asyncio.run(_save())
        except Exception as exc:
            raise OmniError(f"TTS falló: {exc}") from exc
    if not dest.exists() or dest.stat().st_size == 0:
        raise OmniError("el TTS no generó audio")
    return dest


def tts_narrate_with_timings(
    text: str,
    dest: Path,
    voice: str,
    *,
    tts: Any | None = None,
    whisper: Any | None = None,
    whisper_model: str = "small",
    fallback_duration: float | None = None,
    prefer_whisper: bool = False,
) -> NarrationResult:
    """Generate narration and capture word-level timings.

    Priority: Edge-TTS ``WordBoundary`` events, then Whisper word timestamps,
    then a proportional model over the real audio duration.
    """
    if tts is not None:
        result = tts(text, dest, voice)
        if isinstance(result, NarrationResult):
            return result
        words = tuple(result or ())
        if words and not prefer_whisper:
            return NarrationResult(dest, words, "injected")
        if whisper:
            try:
                whisper_words = transcribe_words(
                    dest,
                    model_size=whisper_model,
                    transcriber=whisper if callable(whisper) else None,
                )
                if whisper_words:
                    return NarrationResult(dest, whisper_words, "whisper")
            except Exception as exc:
                logger.warning("Whisper failed (%s)", exc)
        if words:
            return NarrationResult(dest, words, "injected")
        duration = fallback_duration if fallback_duration is not None else probe_duration(dest)
        return NarrationResult(dest, proportional_timings(text, duration), "proportional")

    events: list[dict[str, Any]] = []
    try:
        import edge_tts  # type: ignore[import-not-found]

        async def _stream() -> None:
            try:
                communicate = edge_tts.Communicate(text, voice, boundary="WordBoundary")
            except TypeError:  # older edge-tts versions
                communicate = edge_tts.Communicate(text, voice)
            with dest.open("wb") as fh:
                async for event in communicate.stream():
                    kind = event.get("type")
                    if kind == "audio":
                        fh.write(event.get("data") or b"")
                    elif kind == "WordBoundary":
                        events.append(dict(event))

        asyncio.run(_stream())
    except Exception as exc:
        logger.warning("Edge-TTS stream failed (%s); retrying save", exc)
        if not dest.exists() or dest.stat().st_size == 0:
            tts_narrate(text, dest, voice)
    if not dest.exists() or dest.stat().st_size == 0:
        raise OmniError("el TTS no generó audio")
    words = timings_from_edge_events(events)
    if words and not prefer_whisper:
        return NarrationResult(dest, words, "edge-tts")
    if whisper:
        try:
            whisper_words = transcribe_words(
                dest,
                model_size=whisper_model,
                transcriber=whisper if callable(whisper) else None,
            )
            if whisper_words:
                return NarrationResult(dest, whisper_words, "whisper")
        except Exception as exc:
            logger.warning("Whisper failed (%s)", exc)
    if words:
        return NarrationResult(dest, words, "edge-tts")
    duration = fallback_duration if fallback_duration is not None else probe_duration(dest)
    return NarrationResult(dest, proportional_timings(text, duration), "proportional")


def narration_tempo(narration_duration: float, duration: float) -> float:
    if duration <= 0:
        raise OmniError("la duración objetivo debe ser positiva")
    return max(1.0, min(2.0, narration_duration / duration))


def generate_music(dest: Path, duration: int, runner: Any | None = None) -> Path:
    """Synthesize an original ambient bed with ffmpeg (no licensing issues)."""
    return synthesize_ambient(dest, duration, runner)


def prepare_music(src: Path, dest: Path, duration: int, runner: Any | None = None) -> Path:
    try:
        return prepare_track(src, dest, duration, runner)
    except Exception as exc:
        if isinstance(exc, OmniError):
            raise
        raise OmniError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def build_scene_clip(
    image: Path,
    out: Path,
    duration: float,
    runner: Any | None = None,
    *,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
    fps: int = VIDEO_FPS,
    preset: str = "veryfast",
    crf: int = 20,
) -> Path:
    run = runner or run_command
    fade = min(0.2, max(0.05, duration / 10))
    fade_out = max(0.0, duration - fade)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        "zoompan=z='min(zoom+0.0007,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={width}x{height}:fps={fps},"
        f"fade=t=in:st=0:d={fade:.3f},fade=t=out:st={fade_out:.3f}:d={fade:.3f},"
        "format=yuv420p"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image),
        "-t",
        f"{duration:.3f}",
        "-vf",
        vf,
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out),
    ]
    run(cmd)
    return out


def _concat_line(path: Path) -> str:
    # FFmpeg resolves relative concat entries against the list file directory.
    safe = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{safe}'\n"


def concat_clips(clips: Sequence[Path], out: Path, runner: Any | None = None) -> Path:
    if not clips:
        raise OmniError("no hay clips para concatenar")
    run = runner or run_command
    list_file = out.with_suffix(".txt")
    list_file.write_text("".join(_concat_line(clip) for clip in clips), encoding="utf-8")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(out),
    ]
    run(cmd)
    return out


def mix_audio(
    narration: Path,
    music: Path | None,
    out: Path,
    duration: float,
    narration_duration: float,
    runner: Any | None = None,
) -> Path:
    if narration_duration <= 0:
        raise OmniError("la narración no tiene duración válida")
    run = runner or run_command
    tempo = narration_tempo(narration_duration, duration)
    speed = f"atempo={tempo:.4f}," if tempo > 1.01 else ""
    if music is None:
        audio_filter = (
            f"{speed}apad=whole_dur={duration},atrim=0:{duration},"
            f"afade=t=in:st=0:d=0.4,afade=t=out:st={duration - 0.6}:d=0.6"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(narration),
            "-af",
            audio_filter,
            "-t",
            str(duration),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(out),
        ]
    else:
        filter_complex = (
            f"[0:a]{speed}apad=whole_dur={duration},atrim=0:{duration},volume=1.0[n];"
            f"[1:a]volume=0.12,afade=t=in:st=0:d=2,afade=t=out:st={duration - 2}:d=2[m];"
            "[n][m]amix=inputs=2:duration=first:dropout_transition=0[a]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(narration),
            "-i",
            str(music),
            "-filter_complex",
            filter_complex,
            "-map",
            "[a]",
            "-t",
            str(duration),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(out),
        ]
    run(cmd)
    return out


def _ass_filter_path(path: Path) -> str:
    return path.as_posix().replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def mux_video(
    video: Path,
    audio: Path,
    out: Path,
    subtitles: Path | None = None,
    runner: Any | None = None,
    *,
    preset: str = "veryfast",
    crf: int = 20,
) -> Path:
    run = runner or run_command
    if subtitles is not None:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-vf",
            f"ass={_ass_filter_path(subtitles)}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out),
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out),
        ]
    run(cmd)
    return out


# ---------------------------------------------------------------------------
# Subtitles
# ---------------------------------------------------------------------------


def caption_chunks(text: str, max_words: int = 5) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        if len(current) >= max_words or word.endswith((".", "!", "?", ",", ";", ":")):
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks.append(" ".join(current))
    return chunks


def ass_time(seconds: float) -> str:
    total_cs = max(0, round(seconds * 100))
    hours, remainder = divmod(total_cs, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def escape_ass(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def build_ass(
    chunks: Sequence[str],
    duration: float,
    *,
    play_res: tuple[int, int] = (VIDEO_WIDTH, VIDEO_HEIGHT),
) -> str:
    if not chunks:
        raise OmniError("no hay texto para subtítulos")
    header = ass_header(play_res=play_res)
    weights = [max(1, len(chunk)) for chunk in chunks]
    total = sum(weights)
    lines: list[str] = []
    elapsed = 0
    for chunk, weight in zip(chunks, weights, strict=True):
        start = duration * elapsed / total
        elapsed += weight
        end = duration * elapsed / total
        lines.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Dxrk,,0,0,0,,{{\\fad(120,120)}}{escape_ass(chunk)}"
        )
    return header + "\n".join(lines) + "\n"


def write_ass(
    path: Path,
    chunks: Sequence[str],
    duration: float,
    *,
    play_res: tuple[int, int] = (VIDEO_WIDTH, VIDEO_HEIGHT),
) -> Path:
    path.write_text(build_ass(chunks, duration, play_res=play_res), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def script_to_dict(script: VideoScript) -> dict[str, Any]:
    return {
        "topic": script.topic,
        "title": script.title,
        "narration": script.narration,
        "scenes": [asdict(scene) for scene in script.scenes],
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _touch_manifest(
    manifest_path: Path,
    manifest: dict[str, Any],
    stage: str,
    *,
    progress: float | None = None,
) -> None:
    manifest["stage"] = stage
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if progress is not None:
        manifest["progress"] = max(0.0, min(1.0, progress))
    _write_json(manifest_path, manifest)


def _probe(path: Path, probe: Any | None) -> float:
    return (probe or probe_duration)(path)


def _generate_image_for_scene(
    prompt: str,
    dest: Path,
    config: OmniConfig,
    image_client: httpx.Client | None,
    seed: int,
) -> ImageResult:
    resolution = config.base_resolution_size
    return generate_image(
        prompt,
        dest,
        source=config.image_source,
        seed=seed,
        client=image_client,
        timeout=config.image_timeout,
        comfyui_url=config.comfyui_url,
        comfy_checkpoint=config.comfy_checkpoint,
        comfy_workflow=config.comfy_workflow,
        sdwebui_url=config.sdwebui_url,
        negative_prompt=config.negative_prompt,
        width=resolution.width,
        height=resolution.height,
    )


def _generate_music_track(
    config: OmniConfig,
    dest: Path,
    duration: float,
    runner: Any | None,
    music_generator: Any | None,
) -> Path | None:
    if config.music_path is not None:
        return prepare_music(config.music_path, dest, int(round(duration)), runner=runner)
    if config.no_music:
        return None
    prompt = config.music_prompt or config.topic
    if music_generator is not None:
        return music_generator.generate(dest, duration, prompt)
    if config.music_source == "synth":
        return generate_music(dest, int(round(duration)), runner=runner)
    generator = build_music_generator(
        config.music_source,
        model=config.music_model,
        chunk_seconds=config.music_chunk_seconds,
        runner=runner,
    )
    return generator.generate(dest, duration, prompt)


def _plan_to_script(plan: LongformPlan, *, default_speaker: str = DEFAULT_SPEAKER) -> VideoScript:
    scenes: list[Scene] = []
    index = 0
    for chapter in plan.chapters:
        for shot in chapter.shots:
            index += 1
            scenes.append(
                Scene(
                    index=index,
                    narration=shot.narration,
                    visual_prompt=shot.visual_prompt,
                    speaker=(getattr(shot, "speaker", "") or getattr(chapter, "speaker", "") or default_speaker),
                    lines=tuple(getattr(shot, "lines", ()) or ()),
                )
            )
    return VideoScript(topic=plan.topic, title=plan.title, scenes=tuple(scenes))


def _attach_run_logger(workdir: Path) -> logging.Handler:
    handler = logging.FileHandler(workdir / "engine.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.setLevel(logging.DEBUG)
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return handler


def _detach_run_logger(handler: logging.Handler) -> None:
    logger.removeHandler(handler)
    handler.close()


def _build_contact_sheet(workdir: Path) -> Path | None:
    try:
        if __package__:
            from scripts.omni_media.contact_sheet import contact_sheet_for_run
        else:
            from omni_media.contact_sheet import contact_sheet_for_run
    except Exception as exc:  # pragma: no cover - import guard
        logger.warning("contact sheet import failed: %s", exc)
        return None
    try:
        return contact_sheet_for_run(workdir)
    except Exception as exc:
        logger.warning("contact sheet failed: %s", exc)
        return None


def _finalize_image(
    prompt: str,
    dest: Path,
    config: OmniConfig,
    image_client: httpx.Client | None,
    seed: int,
    runner: Any | None,
    local_source: Path | None = None,
) -> ImageResult:
    resolution = config.resolution_size
    if local_source is not None:
        prepare_image(local_source, dest, resolution.width, resolution.height)
        result = ImageResult(dest, "local")
    else:
        result = _generate_image_for_scene(prompt, dest, config, image_client, seed)
    if config.upscale == "none":
        return result
    upscaled = dest.with_name(f"{dest.stem}_upscaled{dest.suffix}")
    upscale_config = UpscaleConfig(
        enabled=True,
        backend=config.upscale,
        model=config.upscale_model,
        sharpen=config.upscale_sharpen,
    )
    try:
        upscale_image(
            result.path,
            upscaled,
            upscale_config,
            target=resolution,
            runner=runner,
            client=image_client,
            comfyui_url=config.comfyui_url,
            sdwebui_url=config.sdwebui_url,
            timeout=config.image_timeout,
        )
    except Exception as exc:
        if config.upscale != "auto":
            raise OmniError(f"falló el upscaling de {dest.name}: {exc}") from exc
        logger.warning("upscaling failed for %s; keeping the original (%s)", dest.name, exc)
        return result
    logger.info("upscaled %s -> %s", dest.name, upscaled.name)
    return ImageResult(upscaled, f"{result.source}+upscale")


def _render_clips(
    prompts: Sequence[str],
    durations: Sequence[float],
    out_dir: Path,
    prefix: str,
    config: OmniConfig,
    image_client: httpx.Client | None,
    runner: Any | None,
    local_images: Sequence[Path] = (),
    seed_offset: int = 0,
) -> tuple[list[Path], list[ImageResult]]:
    if len(prompts) != len(durations):
        raise OmniError("prompts y durations no coinciden")
    out_dir.mkdir(parents=True, exist_ok=True)
    resolution = config.resolution_size
    clips: list[Path] = []
    results: list[ImageResult] = []
    for index, (prompt, duration) in enumerate(zip(prompts, durations, strict=True)):
        logger.info("%s image %d/%d", prefix, index + 1, len(prompts))
        image_path = out_dir / f"{prefix}_{index + 1:02d}.jpg"
        local_source = local_images[index % len(local_images)] if local_images else None
        result = _finalize_image(
            prompt,
            image_path,
            config,
            image_client,
            config.seed + seed_offset + index,
            runner,
            local_source,
        )
        results.append(result)
        clip_path = out_dir / f"{prefix}_{index + 1:02d}.mp4"
        build_scene_clip(
            result.path,
            clip_path,
            duration,
            runner=runner,
            width=resolution.width,
            height=resolution.height,
            fps=VIDEO_FPS,
            preset=config.video_preset,
            crf=config.video_crf,
        )
        clips.append(clip_path)
    return clips, results


def _speaker_styles(words: Sequence[WordTiming], play_res: tuple[int, int]) -> dict[str, Any]:
    styles: dict[str, Any] = {}
    for word in words:
        if word.speaker and word.speaker not in styles:
            styles[word.speaker] = style_for_speaker(word.speaker, len(styles), play_res)
    return styles


def _is_multivoice(script: VideoScript, config: OmniConfig) -> bool:
    if config.voice_map or config.voices_path is not None:
        return True
    return any(scene.lines or scene.speaker != config.default_speaker for scene in script.scenes)


def _run_multivoice_short(
    config: OmniConfig,
    script: VideoScript,
    workdir: Path,
    assets: Path,
    manifest: dict[str, Any],
    manifest_path: Path,
    image_client: httpx.Client | None,
    tts: Any | None,
    runner: Any | None,
    probe: Any | None,
    music_generator: Any | None,
) -> PipelineResult:
    stage = "voices"
    try:
        voice_map = load_voice_map(config.voices_path)
        voices = resolve_voices(
            config.voice,
            config.voice_map,
            voice_map,
            default_speaker=config.default_speaker,
        )
        requests = segment_scenes(script.scenes, default_speaker=config.default_speaker)
        _touch_manifest(manifest_path, manifest, stage, progress=0.05)
        fallback_duration = float(config.duration) / max(1, len(requests))

        def synthesize(text: str, dest: Path, voice: str) -> NarrationResult:
            result = tts_narrate_with_timings(
                text,
                dest,
                voice,
                tts=tts,
                whisper=True if config.subtitle_source == "whisper" else None,
                whisper_model=config.whisper_model,
                fallback_duration=fallback_duration,
                prefer_whisper=config.subtitle_source == "whisper",
            )
            if config.subtitle_source == "proportional":
                duration = result.words[-1].end if result.words else _probe(result.audio, probe)
                result = NarrationResult(
                    result.audio,
                    proportional_timings(text, duration),
                    "proportional",
                )
            return result

        narration = synthesize_requests(
            requests,
            assets / "voice",
            voices,
            synthesize=synthesize,
            probe=lambda path: _probe(path, probe),
            concat=lambda tracks, dest: concat_audio_tracks(tracks, dest, runner=runner),
            default_speaker=config.default_speaker,
        )
        narration_duration = _probe(narration.audio, probe)
        if narration_duration <= 0:
            raise OmniError("la narración multi-voz no tiene duración válida")
        tempo = narration_tempo(narration_duration, config.duration)
        scene_durations = assign_scene_durations(narration.segments, float(config.duration), tempo)
        timed_words = timeline_words(narration.segments, scene_durations, tempo)
        speakers = {segment.speaker for segment in narration.segments}
        logger.info(
            "multi-voice: %d segments, %.1fs, %d speakers",
            len(narration.segments),
            narration_duration,
            len(speakers),
        )

        stage = "images"
        _touch_manifest(manifest_path, manifest, stage, progress=0.15)
        local_images = list_local_images(config.images_dir) if config.image_source == "local" else []
        clips, image_results = _render_clips(
            [scene.visual_prompt for scene in script.scenes],
            scene_durations,
            assets,
            "scene",
            config,
            image_client,
            runner,
            local_images=local_images,
        )

        stage = "music"
        _touch_manifest(manifest_path, manifest, stage, progress=0.65)
        music_path = _generate_music_track(
            config,
            assets / "music.wav",
            float(config.duration),
            runner,
            music_generator,
        )
        stage = "audio"
        _touch_manifest(manifest_path, manifest, stage, progress=0.72)
        audio_path = mix_audio(
            narration.audio,
            music_path,
            assets / "audio.m4a",
            config.duration,
            narration_duration,
            runner=runner,
        )
        stage = "video"
        _touch_manifest(manifest_path, manifest, stage, progress=0.82)
        video_path = concat_clips(clips, assets / "video.mp4", runner=runner)

        stage = "subtitles"
        _touch_manifest(manifest_path, manifest, stage, progress=0.9)
        resolution = config.resolution_size
        play_res = (resolution.width, resolution.height)
        subtitles_path: Path | None = None
        if timed_words:
            _write_json(
                assets / "words.json",
                {"source": narration.source, "words": words_to_dict(timed_words)},
            )
        if not config.no_subtitles:
            if timed_words:
                subtitles_path = write_word_ass(
                    assets / "subtitles.ass",
                    timed_words,
                    styles=_speaker_styles(timed_words, play_res),
                    play_res=play_res,
                )
            else:
                subtitles_path = write_ass(
                    assets / "subtitles.ass",
                    caption_chunks(script.narration),
                    config.duration,
                    play_res=play_res,
                )

        stage = "mux"
        _touch_manifest(manifest_path, manifest, stage, progress=0.95)
        final_path = workdir / "final.mp4"
        mux_video(
            video_path,
            audio_path,
            final_path,
            subtitles_path,
            runner=runner,
            preset=config.video_preset,
            crf=config.video_crf,
        )
        contact_sheet = _build_contact_sheet(workdir)
        manifest.update(
            {
                "status": "ok",
                "video": final_path,
                "assets": assets,
                "image_sources": [asdict(result) for result in image_results],
                "narration_duration": narration_duration,
                "narration_tempo": tempo,
                "subtitle_source": narration.source,
                "word_timings": words_to_dict(timed_words),
                "music": music_path,
                "subtitles": subtitles_path,
                "scene_durations": list(scene_durations),
                "multi_voice": True,
                "voices": [asdict(spec) for spec in voices.values()],
                "voice_segments": [
                    {
                        "index": segment.index,
                        "scene_index": segment.scene_index,
                        "speaker": segment.speaker,
                        "text": segment.text,
                        "audio": segment.audio,
                        "duration": segment.duration,
                        "start": segment.start,
                        "end": segment.end,
                    }
                    for segment in narration.segments
                ],
                "contact_sheet": contact_sheet,
                "resolution": config.resolution,
                "upscale": config.upscale,
            }
        )
        _touch_manifest(manifest_path, manifest, "done", progress=1.0)
        return PipelineResult(workdir=workdir, video=final_path, script=script, manifest=manifest_path)
    except Exception as exc:
        manifest.update({"status": "failed", "stage": stage, "error": str(exc)})
        _write_json(manifest_path, manifest)
        if isinstance(exc, OmniError):
            raise
        raise OmniError(f"falló la etapa {stage}: {exc}") from exc


def run_pipeline(
    config: OmniConfig,
    *,
    llm: LlmClient | None = None,
    image_client: httpx.Client | None = None,
    tts: Any | None = None,
    runner: Any | None = None,
    probe: Any | None = None,
    music_generator: Any | None = None,
) -> PipelineResult:
    if config.longform:
        return run_longform_pipeline(
            config,
            llm=llm,
            image_client=image_client,
            tts=tts,
            runner=runner,
            probe=probe,
            music_generator=music_generator,
        )
    ensure_ffmpeg()
    try:
        script = (
            load_script(config.script_path, default_speaker=config.default_speaker)
            if config.script_path is not None
            else generate_script(
                config.topic,
                config.scene_count,
                config.duration,
                llm if config.use_llm else None,
                default_speaker=config.default_speaker,
            )
        )
    except Exception as exc:
        if isinstance(exc, OmniError):
            raise
        raise OmniError(f"falló la etapa script: {exc}") from exc
    topic = config.topic or script.topic
    workdir = unique_workdir(config.output_root, topic)
    assets = workdir / "assets"
    assets.mkdir(parents=True)
    logger.info("output: %s", workdir)
    manifest_path = workdir / "manifest.json"
    manifest: dict[str, Any] = {
        "status": "running",
        "topic": topic,
        "duration": config.duration,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "engine_log": workdir / "engine.log",
        "resolution": config.resolution,
        "upscale": config.upscale,
    }
    log_handler = _attach_run_logger(workdir)
    stage = "script"
    try:
        _write_json(workdir / "script.json", script_to_dict(script))
        manifest["script"] = script_to_dict(script)
        _touch_manifest(manifest_path, manifest, stage, progress=0.02)
        logger.info("script: %s (%d scenes)", script.title, len(script.scenes))

        if _is_multivoice(script, config):
            return _run_multivoice_short(
                config,
                script,
                workdir,
                assets,
                manifest,
                manifest_path,
                image_client,
                tts,
                runner,
                probe,
                music_generator,
            )

        scene_duration = config.duration / len(script.scenes)
        stage = "images"
        _touch_manifest(manifest_path, manifest, stage, progress=0.1)
        local_images = list_local_images(config.images_dir) if config.image_source == "local" else []
        clips, image_results = _render_clips(
            [scene.visual_prompt for scene in script.scenes],
            [scene_duration] * len(script.scenes),
            assets,
            "scene",
            config,
            image_client,
            runner,
            local_images=local_images,
        )

        stage = "narration"
        _touch_manifest(manifest_path, manifest, stage, progress=0.55)
        narration_path = assets / "narration.mp3"
        whisper = True if config.subtitle_source == "whisper" else None
        narration = tts_narrate_with_timings(
            script.narration,
            narration_path,
            config.voice,
            tts=tts,
            whisper=whisper,
            whisper_model=config.whisper_model,
            fallback_duration=float(config.duration),
            prefer_whisper=config.subtitle_source == "whisper",
        )
        narration_duration = _probe(narration.audio, probe)
        if narration_duration <= 0:
            raise OmniError("la narración no tiene duración válida")
        if config.subtitle_source == "proportional":
            narration = NarrationResult(
                narration.audio,
                proportional_timings(script.narration, narration_duration),
                "proportional",
            )
        logger.info("narration: %.1fs (%s words)", narration_duration, narration.source)

        stage = "music"
        _touch_manifest(manifest_path, manifest, stage, progress=0.65)
        music_path = _generate_music_track(
            config,
            assets / "music.wav",
            float(config.duration),
            runner,
            music_generator,
        )
        logger.info("music: %s", music_path.name if music_path is not None else "none")

        stage = "audio"
        _touch_manifest(manifest_path, manifest, stage, progress=0.72)
        audio_path = mix_audio(
            narration.audio,
            music_path,
            assets / "audio.m4a",
            config.duration,
            narration_duration,
            runner=runner,
        )
        logger.info("audio: mixed")

        stage = "video"
        _touch_manifest(manifest_path, manifest, stage, progress=0.82)
        video_path = concat_clips(clips, assets / "video.mp4", runner=runner)
        logger.info("video: concatenated")

        stage = "subtitles"
        _touch_manifest(manifest_path, manifest, stage, progress=0.9)
        tempo = narration_tempo(narration_duration, config.duration)
        timed_words = scale_timings(narration.words, 1.0 / tempo)
        resolution = config.resolution_size
        play_res = (resolution.width, resolution.height)
        if timed_words:
            _write_json(
                assets / "words.json",
                {"source": narration.source, "words": words_to_dict(timed_words)},
            )
        subtitles_path: Path | None = None
        if not config.no_subtitles:
            if timed_words:
                subtitles_path = write_word_ass(assets / "subtitles.ass", timed_words, play_res=play_res)
            else:
                subtitles_path = write_ass(
                    assets / "subtitles.ass",
                    caption_chunks(script.narration),
                    config.duration,
                    play_res=play_res,
                )
        logger.info("subtitles: %s", "on" if subtitles_path is not None else "off")

        stage = "mux"
        _touch_manifest(manifest_path, manifest, stage, progress=0.95)
        final_path = workdir / "final.mp4"
        mux_video(
            video_path,
            audio_path,
            final_path,
            subtitles_path,
            runner=runner,
            preset=config.video_preset,
            crf=config.video_crf,
        )
        logger.info("final: %s", final_path)
        contact_sheet = _build_contact_sheet(workdir)

        manifest.update(
            {
                "status": "ok",
                "video": final_path,
                "assets": assets,
                "image_sources": [asdict(result) for result in image_results],
                "narration_duration": narration_duration,
                "narration_tempo": tempo,
                "subtitle_source": narration.source,
                "word_timings": words_to_dict(timed_words),
                "music": music_path,
                "subtitles": subtitles_path,
                "scene_duration": scene_duration,
                "contact_sheet": contact_sheet,
            }
        )
        _touch_manifest(manifest_path, manifest, "done", progress=1.0)
        return PipelineResult(workdir=workdir, video=final_path, script=script, manifest=manifest_path)
    except Exception as exc:
        if manifest.get("status") != "failed":
            manifest.update({"status": "failed", "stage": stage, "error": str(exc)})
            _write_json(manifest_path, manifest)
        if isinstance(exc, OmniError):
            raise
        raise OmniError(f"falló la etapa {stage}: {exc}") from exc
    finally:
        _detach_run_logger(log_handler)


def run_longform_pipeline(
    config: OmniConfig,
    *,
    llm: LlmClient | None = None,
    image_client: httpx.Client | None = None,
    tts: Any | None = None,
    runner: Any | None = None,
    probe: Any | None = None,
    music_generator: Any | None = None,
) -> PipelineResult:
    ensure_ffmpeg()
    workdir = unique_workdir(config.output_root, config.topic)
    assets = workdir / "assets"
    assets.mkdir(parents=True)
    logger.info("output: %s", workdir)
    manifest_path = workdir / "manifest.json"
    manifest: dict[str, Any] = {
        "status": "running",
        "topic": config.topic,
        "longform": True,
        "chapters": config.chapters,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "engine_log": workdir / "engine.log",
        "resolution": config.resolution,
        "upscale": config.upscale,
    }
    log_handler = _attach_run_logger(workdir)
    stage = "plan"
    try:
        plan = generate_longform_plan(
            config.topic,
            config.chapters,
            config.shots_per_chapter,
            config.chapter_duration,
            llm if config.use_llm else None,
        )
        _write_json(workdir / "plan.json", plan_to_dict(plan))
        manifest["longform"] = plan_to_dict(plan)
        _touch_manifest(manifest_path, manifest, stage, progress=0.02)
        logger.info("plan: %s (%d chapters)", plan.title, len(plan.chapters))

        multi = _is_multivoice(_plan_to_script(plan, default_speaker=config.default_speaker), config)
        voices: dict[str, VoiceSpec] | None = None
        if multi:
            voice_map = load_voice_map(config.voices_path)
            voices = resolve_voices(
                config.voice,
                config.voice_map,
                voice_map,
                default_speaker=config.default_speaker,
            )

        chapter_videos: list[Path] = []
        chapter_audios: list[Path] = []
        chapter_durations: list[float] = []
        image_results: list[ImageResult] = []
        all_words: list[WordTiming] = []
        voice_segments: list[dict[str, Any]] = []
        offset = 0.0
        for chapter in plan.chapters:
            stage = f"chapter {chapter.index}"
            progress = 0.05 + 0.8 * (chapter.index - 1) / max(1, len(plan.chapters))
            _touch_manifest(manifest_path, manifest, stage, progress=progress)
            chapter_dir = assets / f"chapter_{chapter.index:02d}"
            chapter_dir.mkdir(parents=True, exist_ok=True)
            chapter_speaker = getattr(chapter, "speaker", "") or config.default_speaker
            if multi and voices is not None:
                requests = segment_scenes(chapter.shots, default_speaker=chapter_speaker)
                fallback_duration = float(config.chapter_duration) / max(1, len(requests))

                def synthesize(text: str, dest: Path, voice: str) -> NarrationResult:
                    result = tts_narrate_with_timings(
                        text,
                        dest,
                        voice,
                        tts=tts,
                        whisper=True if config.subtitle_source == "whisper" else None,
                        whisper_model=config.whisper_model,
                        fallback_duration=fallback_duration,
                        prefer_whisper=config.subtitle_source == "whisper",
                    )
                    if config.subtitle_source == "proportional":
                        duration = result.words[-1].end if result.words else _probe(result.audio, probe)
                        result = NarrationResult(
                            result.audio,
                            proportional_timings(text, duration),
                            "proportional",
                        )
                    return result

                narration = synthesize_requests(
                    requests,
                    chapter_dir / "voice",
                    voices,
                    synthesize=synthesize,
                    probe=lambda path: _probe(path, probe),
                    concat=lambda tracks, dest: concat_audio_tracks(tracks, dest, runner=runner),
                    default_speaker=chapter_speaker,
                )
                narration_duration = _probe(narration.audio, probe)
                if narration_duration <= 0:
                    raise OmniError(f"la narración del capítulo {chapter.index} no tiene duración válida")
                chapter_duration = max(float(config.chapter_duration), narration_duration + 0.5)
                chapter_tempo = narration_tempo(narration_duration, chapter_duration)
                shot_durations = assign_scene_durations(
                    narration.segments,
                    chapter_duration,
                    chapter_tempo,
                )
                chapter_words = timeline_words(narration.segments, shot_durations, chapter_tempo)
                clips, results = _render_clips(
                    [shot.visual_prompt for shot in chapter.shots],
                    shot_durations,
                    chapter_dir,
                    "shot",
                    config,
                    image_client,
                    runner,
                    seed_offset=(chapter.index - 1) * 100,
                )
                image_results.extend(results)
                for segment in narration.segments:
                    voice_segments.append(
                        {
                            "chapter": chapter.index,
                            "index": segment.index,
                            "scene_index": segment.scene_index,
                            "speaker": segment.speaker,
                            "text": segment.text,
                            "audio": segment.audio,
                            "duration": segment.duration,
                            "start": offset + segment.start,
                            "end": offset + segment.end,
                        }
                    )
            else:
                narration_text = " ".join(shot.text for shot in chapter.shots)
                narration_path = chapter_dir / "narration.mp3"
                whisper = True if config.subtitle_source == "whisper" else None
                narration = tts_narrate_with_timings(
                    narration_text,
                    narration_path,
                    config.voice,
                    tts=tts,
                    whisper=whisper,
                    whisper_model=config.whisper_model,
                    fallback_duration=float(config.chapter_duration),
                    prefer_whisper=config.subtitle_source == "whisper",
                )
                narration_duration = _probe(narration.audio, probe)
                if narration_duration <= 0:
                    raise OmniError(f"la narración del capítulo {chapter.index} no tiene duración válida")
                chapter_duration = max(float(config.chapter_duration), narration_duration + 0.5)
                chapter_tempo = narration_tempo(narration_duration, chapter_duration)
                chapter_words = scale_timings(narration.words, 1.0 / chapter_tempo)
                shot_duration = chapter_duration / len(chapter.shots)
                clips, results = _render_clips(
                    [shot.visual_prompt for shot in chapter.shots],
                    [shot_duration] * len(chapter.shots),
                    chapter_dir,
                    "shot",
                    config,
                    image_client,
                    runner,
                    seed_offset=(chapter.index - 1) * 100,
                )
                image_results.extend(results)
            chapter_videos.append(concat_clips(clips, chapter_dir / "chapter.mp4", runner=runner))
            chapter_audios.append(
                mix_audio(
                    narration.audio,
                    None,
                    chapter_dir / "chapter.m4a",
                    chapter_duration,
                    narration_duration,
                    runner=runner,
                )
            )
            chapter_durations.append(chapter_duration)
            all_words.extend(offset_timings(chapter_words, offset))
            offset += chapter_duration
            logger.info("chapter %d: %.1fs", chapter.index, chapter_duration)
        total_duration = offset

        stage = "video"
        _touch_manifest(manifest_path, manifest, stage, progress=0.88)
        video_path = concat_clips(chapter_videos, assets / "video.mp4", runner=runner)
        stage = "audio"
        _touch_manifest(manifest_path, manifest, stage, progress=0.92)
        narration_full = concat_audio_tracks(chapter_audios, assets / "narration.m4a", runner=runner)
        music_path = _generate_music_track(
            config,
            assets / "music.wav",
            total_duration,
            runner,
            music_generator,
        )
        audio_path = mix_audio(
            narration_full,
            music_path,
            assets / "audio.m4a",
            total_duration,
            total_duration,
            runner=runner,
        )
        stage = "subtitles"
        _touch_manifest(manifest_path, manifest, stage, progress=0.95)
        resolution = config.resolution_size
        play_res = (resolution.width, resolution.height)
        subtitles_path: Path | None = None
        if all_words:
            _write_json(
                assets / "words.json",
                {"source": "mixed", "words": words_to_dict(all_words)},
            )
        if not config.no_subtitles:
            if all_words:
                subtitles_path = write_word_ass(
                    assets / "subtitles.ass",
                    all_words,
                    styles=_speaker_styles(all_words, play_res),
                    play_res=play_res,
                )
            else:
                subtitles_path = write_ass(
                    assets / "subtitles.ass",
                    caption_chunks(" ".join(shot.text for shot in plan.shots)),
                    total_duration,
                    play_res=play_res,
                )
        stage = "mux"
        _touch_manifest(manifest_path, manifest, stage, progress=0.97)
        final_path = workdir / "final.mp4"
        mux_video(
            video_path,
            audio_path,
            final_path,
            subtitles_path,
            runner=runner,
            preset=config.video_preset,
            crf=config.video_crf,
        )
        contact_sheet = _build_contact_sheet(workdir)
        manifest.update(
            {
                "status": "ok",
                "video": final_path,
                "assets": assets,
                "image_sources": [asdict(result) for result in image_results],
                "chapter_durations": chapter_durations,
                "total_duration": total_duration,
                "word_timings": words_to_dict(all_words),
                "music": music_path,
                "subtitles": subtitles_path,
                "multi_voice": multi,
                "contact_sheet": contact_sheet,
            }
        )
        if multi and voices is not None:
            manifest["voices"] = [asdict(spec) for spec in voices.values()]
            manifest["voice_segments"] = voice_segments
        _touch_manifest(manifest_path, manifest, "done", progress=1.0)
        return PipelineResult(
            workdir=workdir,
            video=final_path,
            script=_plan_to_script(plan, default_speaker=config.default_speaker),
            manifest=manifest_path,
        )
    except Exception as exc:
        if manifest.get("status") != "failed":
            manifest.update({"status": "failed", "stage": stage, "error": str(exc)})
            _write_json(manifest_path, manifest)
        if isinstance(exc, OmniError):
            raise
        raise OmniError(f"falló la etapa {stage}: {exc}") from exc
    finally:
        _detach_run_logger(log_handler)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dxrk-omni",
        description="Genera un short vertical de 30s a partir de un tema.",
    )
    parser.add_argument("topic", nargs="?", default="", help="Tema o idea del video")
    parser.add_argument("--output-dir", default="outputs", help="Directorio raíz de salidas (default: outputs)")
    parser.add_argument("--duration", type=int, default=30, help="Duración objetivo en segundos (default: 30)")
    parser.add_argument("--scenes", type=int, default=5, help="Cantidad de escenas (default: 5)")
    parser.add_argument("--script", help="Script JSON propio (permite speakers y líneas)")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help="Voz por defecto de Edge-TTS")
    parser.add_argument(
        "--voice-map",
        action="append",
        default=[],
        metavar="SPEAKER=VOICE",
        help="Asignación repetible de voz por speaker (ej. narrator=es-AR-TomasNeural)",
    )
    parser.add_argument("--voices", help="JSON con el mapa de voces por speaker")
    parser.add_argument(
        "--default-speaker",
        default=DEFAULT_SPEAKER,
        help="Speaker que usa la voz por defecto (default: narrator)",
    )
    parser.add_argument(
        "--resolution",
        default="1080p",
        help="Resolución de salida: 1080p, 1440p, 4k o WxH (default: 1080p)",
    )
    parser.add_argument(
        "--upscale",
        choices=("none", "auto", "ffmpeg", "realesrgan", "comfyui", "sdwebui"),
        default="none",
        help="Backend de upscaling de imágenes (default: none)",
    )
    parser.add_argument("--upscale-model", default="", help="Modelo/upscaler para el backend elegido")
    parser.add_argument("--upscale-sharpen", type=float, default=0.0, help="Unsharp amount para FFmpeg")
    parser.add_argument("--crf", type=int, default=20, help="CRF de x264 (default: 20)")
    parser.add_argument(
        "--preset",
        choices=(
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        ),
        default="veryfast",
        help="Preset de x264 (default: veryfast)",
    )
    parser.add_argument(
        "--image-source",
        choices=("auto", "comfyui", "sdwebui", "pollinations", "local", "placeholder"),
        default="auto",
        help="Origen de las imágenes (auto prueba ComfyUI y SD WebUI antes del placeholder)",
    )
    parser.add_argument("--images-dir", help="Directorio con imágenes locales")
    parser.add_argument("--comfyui-url", default=DEFAULT_COMFY_URL, help="URL de ComfyUI")
    parser.add_argument("--comfy-checkpoint", default=DEFAULT_COMFY_CHECKPOINT, help="Checkpoint de ComfyUI")
    parser.add_argument("--comfy-workflow", help="Workflow JSON de ComfyUI con placeholders {{PROMPT}}, {{SEED}}, etc.")
    parser.add_argument("--sdwebui-url", default=DEFAULT_SDWEBUI_URL, help="URL de Stable Diffusion WebUI")
    parser.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE_PROMPT, help="Prompt negativo")
    parser.add_argument("--image-timeout", type=float, default=300.0, help="Timeout por imagen en segundos")
    parser.add_argument(
        "--subtitle-source",
        choices=("edge", "whisper", "proportional"),
        default="edge",
        help="Fuente de los timings de subtítulos",
    )
    parser.add_argument("--whisper-model", default="small", help="Modelo de faster-whisper")
    parser.add_argument(
        "--music-source",
        choices=("synth", "musicgen", "stable-audio", "file"),
        default="synth",
        help="Backend de música de fondo",
    )
    parser.add_argument("--music-model", default="", help="Modelo de MusicGen o Stable Audio")
    parser.add_argument("--music-prompt", default="", help="Prompt para el modelo de música")
    parser.add_argument("--music-chunk-seconds", type=float, default=30.0, help="Duración de cada chunk de música")
    parser.add_argument("--music", help="Pista de música propia (si no, se sintetiza una)")
    parser.add_argument("--no-music", action="store_true", help="No agregar música de fondo")
    parser.add_argument("--no-subtitles", action="store_true", help="No quemar subtítulos")
    parser.add_argument("--no-llm", action="store_true", help="Usar el guion determinístico")
    parser.add_argument("--longform", action="store_true", help="Generar un corto/película por capítulos")
    parser.add_argument("--chapters", type=int, default=3, help="Capítulos para longform (default: 3)")
    parser.add_argument(
        "--shots-per-chapter",
        type=int,
        default=3,
        help="Shots por capítulo para longform (default: 3)",
    )
    parser.add_argument(
        "--chapter-duration",
        type=int,
        default=60,
        help="Duración objetivo por capítulo en segundos (default: 60)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Semilla para imágenes")
    parser.add_argument("--llm-base-url", default=DEFAULT_LLM_BASE_URL, help="Endpoint OpenAI-compatible")
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL, help="Modelo del LLM")
    parser.add_argument("--llm-api-key", default=DEFAULT_LLM_API_KEY, help="API key del LLM")
    parser.add_argument("--verbose", action="store_true", help="Log detallado")
    return parser


def config_from_args(args: argparse.Namespace) -> OmniConfig:
    images_dir = Path(args.images_dir).expanduser() if args.images_dir else None
    music_path = Path(args.music).expanduser() if args.music else None
    comfy_workflow_arg = getattr(args, "comfy_workflow", None)
    comfy_workflow = Path(comfy_workflow_arg).expanduser() if comfy_workflow_arg else None
    script_arg = getattr(args, "script", None)
    script_path = Path(script_arg).expanduser() if script_arg else None
    voices_arg = getattr(args, "voices", None)
    voices_path = Path(voices_arg).expanduser() if voices_arg else None
    default_speaker = str(getattr(args, "default_speaker", DEFAULT_SPEAKER))
    voice_map = parse_voice_specs(
        getattr(args, "voice_map", []) or [],
        default_speaker=default_speaker,
    )
    longform = bool(getattr(args, "longform", False))
    chapters = int(getattr(args, "chapters", 3))
    chapter_duration = int(getattr(args, "chapter_duration", 60))
    duration = chapters * chapter_duration if longform else int(args.duration)
    return OmniConfig(
        topic=str(args.topic),
        output_root=Path(args.output_dir).expanduser(),
        duration=duration,
        scene_count=int(args.scenes),
        voice=str(args.voice),
        script_path=script_path,
        default_speaker=default_speaker,
        voice_map=voice_map,
        voices_path=voices_path,
        resolution=str(getattr(args, "resolution", "1080p")),
        upscale=str(getattr(args, "upscale", "none")),
        upscale_model=str(getattr(args, "upscale_model", "")),
        upscale_sharpen=float(getattr(args, "upscale_sharpen", 0.0)),
        video_crf=int(getattr(args, "crf", 20)),
        video_preset=str(getattr(args, "preset", "veryfast")),
        image_source=str(getattr(args, "image_source", "auto")),
        images_dir=images_dir,
        music_path=music_path,
        no_music=bool(args.no_music),
        no_subtitles=bool(args.no_subtitles),
        seed=int(args.seed),
        llm_base_url=str(args.llm_base_url),
        llm_model=str(args.llm_model),
        llm_api_key=str(args.llm_api_key),
        use_llm=not bool(args.no_llm),
        comfyui_url=str(getattr(args, "comfyui_url", DEFAULT_COMFY_URL)),
        comfy_checkpoint=str(getattr(args, "comfy_checkpoint", DEFAULT_COMFY_CHECKPOINT)),
        comfy_workflow=comfy_workflow,
        sdwebui_url=str(getattr(args, "sdwebui_url", DEFAULT_SDWEBUI_URL)),
        negative_prompt=str(getattr(args, "negative_prompt", DEFAULT_NEGATIVE_PROMPT)),
        image_timeout=float(getattr(args, "image_timeout", 300.0)),
        subtitle_source=str(getattr(args, "subtitle_source", "edge")),
        whisper_model=str(getattr(args, "whisper_model", "small")),
        music_source=str(getattr(args, "music_source", "synth")),
        music_model=str(getattr(args, "music_model", "")),
        music_prompt=str(getattr(args, "music_prompt", "")),
        music_chunk_seconds=float(getattr(args, "music_chunk_seconds", 30.0)),
        longform=longform,
        chapters=chapters,
        shots_per_chapter=int(getattr(args, "shots_per_chapter", 3)),
        chapter_duration=chapter_duration,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        config = config_from_args(args)
        llm: LlmClient | None = None
        if config.use_llm:
            llm = OpenAICompatibleClient(
                base_url=config.llm_base_url,
                model=config.llm_model,
                api_key=config.llm_api_key,
            )
        result = run_pipeline(config, llm=llm)
    except OmniError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"video: {result.video}")
    print(f"manifest: {result.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
