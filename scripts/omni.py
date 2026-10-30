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


@dataclass(frozen=True, slots=True)
class VideoScript:
    topic: str
    title: str
    scenes: tuple[Scene, ...]

    @property
    def narration(self) -> str:
        return " ".join(scene.narration for scene in self.scenes)


@dataclass(frozen=True, slots=True)
class OmniConfig:
    topic: str
    output_root: Path = Path("outputs")
    duration: int = 30
    scene_count: int = 5
    voice: str = DEFAULT_VOICE
    image_source: str = "pollinations"
    images_dir: Path | None = None
    music_path: Path | None = None
    no_music: bool = False
    no_subtitles: bool = False
    seed: int = 42
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    llm_api_key: str = DEFAULT_LLM_API_KEY
    use_llm: bool = True

    def __post_init__(self) -> None:
        topic = self.topic.strip()
        if not topic:
            raise OmniError("el tema no puede estar vacío")
        object.__setattr__(self, "topic", topic)
        if not 5 <= self.duration <= 180:
            raise OmniError("la duración debe estar entre 5 y 180 segundos")
        if not 2 <= self.scene_count <= 12:
            raise OmniError("las escenas deben ser entre 2 y 12")
        if self.image_source not in {"pollinations", "local", "placeholder"}:
            raise OmniError("image_source debe ser pollinations, local o placeholder")
        if self.image_source == "local" and self.images_dir is None:
            raise OmniError("image_source=local requiere --images-dir")


@dataclass(frozen=True, slots=True)
class ImageResult:
    path: Path
    source: str
    error: str = ""


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


def fallback_script(topic: str, scene_count: int = 5) -> VideoScript:
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


def parse_script_json(raw: str, topic: str) -> VideoScript:
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
        narration = str(item.get("narration", "")).strip()
        visual_prompt = str(item.get("visual_prompt", "")).strip()
        if not narration or not visual_prompt:
            raise OmniError(f"la escena {i + 1} necesita narration y visual_prompt")
        scenes.append(Scene(index=i + 1, narration=narration, visual_prompt=visual_prompt))
    title = str(data.get("title") or topic).strip() or topic
    return VideoScript(topic=topic, title=title, scenes=tuple(scenes))


def generate_script(topic: str, scene_count: int, duration: int, llm: LlmClient | None) -> VideoScript:
    if llm is None:
        return fallback_script(topic, scene_count)
    try:
        raw = llm.complete(build_script_prompt(topic, scene_count, duration))
        return parse_script_json(raw, topic)
    except Exception as exc:
        logger.warning("LLM script failed (%s); using deterministic fallback", exc)
        return fallback_script(topic, scene_count)


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


def build_pollinations_url(prompt: str, seed: int) -> str:
    encoded = urllib.parse.quote(prompt, safe="")
    return (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={VIDEO_WIDTH}&height={VIDEO_HEIGHT}&nologo=true&seed={seed}"
    )


def _pillow() -> tuple[Any, Any, Any, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps
    except ImportError as exc:  # pragma: no cover - environment guard
        raise OmniError("Pillow no está instalado. Ejecutá: uv sync --extra omni") from exc
    return Image, ImageDraw, ImageFont, ImageOps


def placeholder_image(prompt: str, dest: Path, seed: int = 42) -> Path:
    """Create a cinematic card so the pipeline still works offline."""
    Image, ImageDraw, ImageFont, _ = _pillow()
    rng = random.Random(seed)
    base = (rng.randint(4, 12), rng.randint(4, 12), rng.randint(10, 24))
    accent = (rng.randint(0, 60), rng.randint(180, 255), rng.randint(180, 255))
    image = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), base)
    draw = ImageDraw.Draw(image)
    for y in range(VIDEO_HEIGHT):
        t = y / (VIDEO_HEIGHT - 1)
        color = tuple(int(base[i] * (1 - t) + accent[i] * t * 0.28) for i in range(3))
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=color)

    overlay = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    grid = ImageDraw.Draw(overlay)
    for x in range(0, VIDEO_WIDTH, 90):
        grid.line([(x, 0), (x, VIDEO_HEIGHT)], fill=(*accent, 18), width=1)
    for y in range(0, VIDEO_HEIGHT, 90):
        grid.line([(0, y), (VIDEO_WIDTH, y)], fill=(*accent, 18), width=1)
    for y in range(1180, VIDEO_HEIGHT):
        alpha = int(190 * (y - 1180) / (VIDEO_HEIGHT - 1180))
        grid.line([(0, y), (VIDEO_WIDTH, y)], fill=(0, 0, 0, alpha))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(image)
    try:
        font_big = ImageFont.truetype("DejaVuSans-Bold.ttf", 76)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 38)
    except OSError:
        font_big = ImageFont.load_default(size=76)
        font_small = ImageFont.load_default(size=38)
    draw.text((70, 90), "DXRK / OMNI", font=font_small, fill=accent)
    wrapped = textwrap.wrap(prompt, width=24)[:6]
    y = 1420
    for line in wrapped:
        draw.text((70, y), line, font=font_big, fill=(240, 240, 245))
        y += 92
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


def generate_image(
    prompt: str,
    dest: Path,
    *,
    source: str,
    seed: int,
    client: httpx.Client | None = None,
    timeout: float = 60.0,
) -> ImageResult:
    if source == "placeholder":
        placeholder_image(prompt, dest, seed)
        return ImageResult(dest, "placeholder")
    if source != "pollinations":
        raise OmniError(f"fuente de imagen desconocida: {source}")
    url = build_pollinations_url(prompt, seed)
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
            prepare_image(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
        return ImageResult(dest, "pollinations")
    except Exception as exc:
        logger.warning("Pollinations failed (%s); using placeholder", exc)
        placeholder_image(prompt, dest, seed)
        return ImageResult(dest, "placeholder", str(exc)[:200])


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


def generate_music(dest: Path, duration: int, runner: Any | None = None) -> Path:
    """Synthesize an original ambient bed with ffmpeg (no licensing issues)."""
    run = runner or run_command
    fade_out = max(0, duration - 2)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=110:duration={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=164.81:duration={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=220:duration={duration}",
        "-filter_complex",
        (
            "[0:a]volume=0.08[a0];[1:a]volume=0.05[a1];[2:a]volume=0.04[a2];"
            "[a0][a1][a2]amix=inputs=3:duration=longest,"
            f"afade=t=in:st=0:d=2,afade=t=out:st={fade_out}:d=2,"
            "aecho=0.8:0.6:60:0.3[a]"
        ),
        "-map",
        "[a]",
        "-c:a",
        "pcm_s16le",
        str(dest),
    ]
    run(cmd)
    return dest


def prepare_music(src: Path, dest: Path, duration: int, runner: Any | None = None) -> Path:
    if not src.exists():
        raise OmniError(f"no existe la música: {src}")
    run = runner or run_command
    fade_out = max(0, duration - 2)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-t",
        str(duration),
        "-af",
        f"afade=t=in:st=0:d=1,afade=t=out:st={fade_out}:d=2",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(dest),
    ]
    run(cmd)
    return dest


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def build_scene_clip(
    image: Path,
    out: Path,
    duration: float,
    runner: Any | None = None,
) -> Path:
    run = runner or run_command
    fade = min(0.2, max(0.05, duration / 10))
    fade_out = max(0.0, duration - fade)
    vf = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
        "zoompan=z='min(zoom+0.0007,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS},"
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
        str(VIDEO_FPS),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out),
    ]
    run(cmd)
    return out


def _concat_line(path: Path) -> str:
    safe = path.as_posix().replace("'", "'\\''")
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
    duration: int,
    narration_duration: float,
    runner: Any | None = None,
) -> Path:
    if narration_duration <= 0:
        raise OmniError("la narración no tiene duración válida")
    run = runner or run_command
    tempo = max(1.0, min(2.0, narration_duration / duration))
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
            "veryfast",
            "-crf",
            "20",
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


def build_ass(chunks: Sequence[str], duration: float) -> str:
    if not chunks:
        raise OmniError("no hay texto para subtítulos")
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {VIDEO_WIDTH}\n"
        f"PlayResY: {VIDEO_HEIGHT}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Dxrk,DejaVu Sans,64,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,180,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
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


def write_ass(path: Path, chunks: Sequence[str], duration: float) -> Path:
    path.write_text(build_ass(chunks, duration), encoding="utf-8")
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
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(
    config: OmniConfig,
    *,
    llm: LlmClient | None = None,
    image_client: httpx.Client | None = None,
    tts: Any | None = None,
    runner: Any | None = None,
    probe: Any | None = None,
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
        "duration": config.duration,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    stage = "script"
    try:
        script = generate_script(
            config.topic,
            config.scene_count,
            config.duration,
            llm if config.use_llm else None,
        )
        _write_json(workdir / "script.json", script_to_dict(script))
        manifest["script"] = script_to_dict(script)
        scene_duration = config.duration / len(script.scenes)
        logger.info("script: %s (%d scenes)", script.title, len(script.scenes))

        stage = "images"
        local_images = list_local_images(config.images_dir) if config.image_source == "local" else []
        image_results: list[ImageResult] = []
        for i, scene in enumerate(script.scenes):
            logger.info("image %d/%d", i + 1, len(script.scenes))
            image_path = assets / f"scene_{i + 1:02d}.jpg"
            if config.image_source == "local":
                prepare_image(local_images[i % len(local_images)], image_path)
                result = ImageResult(image_path, "local")
            else:
                result = generate_image(
                    scene.visual_prompt,
                    image_path,
                    source=config.image_source,
                    seed=config.seed + i,
                    client=image_client,
                )
            image_results.append(result)
            build_scene_clip(
                image_path,
                assets / f"scene_{i + 1:02d}.mp4",
                scene_duration,
                runner=runner,
            )

        stage = "narration"
        narration_path = assets / "narration.mp3"
        tts_narrate(script.narration, narration_path, config.voice, tts=tts)
        narration_duration = (probe or probe_duration)(narration_path)
        if narration_duration <= 0:
            raise OmniError("la narración no tiene duración válida")
        logger.info("narration: %.1fs", narration_duration)

        stage = "music"
        music_path: Path | None = None
        if config.music_path is not None:
            music_path = prepare_music(config.music_path, assets / "music.wav", config.duration, runner=runner)
        elif not config.no_music:
            music_path = generate_music(assets / "music.wav", config.duration, runner=runner)
        logger.info("music: %s", music_path.name if music_path is not None else "none")

        stage = "audio"
        audio_path = mix_audio(
            narration_path,
            music_path,
            assets / "audio.m4a",
            config.duration,
            narration_duration,
            runner=runner,
        )
        logger.info("audio: mixed")

        stage = "video"
        clips = [assets / f"scene_{i + 1:02d}.mp4" for i in range(len(script.scenes))]
        video_path = concat_clips(clips, assets / "video.mp4", runner=runner)
        logger.info("video: concatenated")

        stage = "subtitles"
        subtitles_path: Path | None = None
        if not config.no_subtitles:
            subtitles_path = write_ass(
                assets / "subtitles.ass",
                caption_chunks(script.narration),
                config.duration,
            )
        logger.info("subtitles: %s", "on" if subtitles_path is not None else "off")

        stage = "mux"
        final_path = workdir / "final.mp4"
        mux_video(video_path, audio_path, final_path, subtitles_path, runner=runner)
        logger.info("final: %s", final_path)

        manifest.update(
            {
                "status": "ok",
                "video": final_path,
                "assets": assets,
                "image_sources": [asdict(result) for result in image_results],
                "narration_duration": narration_duration,
                "music": music_path,
                "subtitles": subtitles_path,
                "scene_duration": scene_duration,
            }
        )
        _write_json(manifest_path, manifest)
        return PipelineResult(workdir=workdir, video=final_path, script=script, manifest=manifest_path)
    except Exception as exc:
        manifest.update({"status": "failed", "stage": stage, "error": str(exc)})
        _write_json(manifest_path, manifest)
        if isinstance(exc, OmniError):
            raise
        raise OmniError(f"falló la etapa {stage}: {exc}") from exc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dxrk-omni",
        description="Genera un short vertical de 30s a partir de un tema.",
    )
    parser.add_argument("topic", help="Tema o idea del video")
    parser.add_argument("--output-dir", default="outputs", help="Directorio raíz de salidas (default: outputs)")
    parser.add_argument("--duration", type=int, default=30, help="Duración objetivo en segundos (default: 30)")
    parser.add_argument("--scenes", type=int, default=5, help="Cantidad de escenas (default: 5)")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help="Voz de Edge-TTS")
    parser.add_argument(
        "--image-source",
        choices=("pollinations", "local", "placeholder"),
        default="pollinations",
        help="Origen de las imágenes",
    )
    parser.add_argument("--images-dir", help="Directorio con imágenes locales")
    parser.add_argument("--music", help="Pista de música propia (si no, se sintetiza una)")
    parser.add_argument("--no-music", action="store_true", help="No agregar música de fondo")
    parser.add_argument("--no-subtitles", action="store_true", help="No quemar subtítulos")
    parser.add_argument("--no-llm", action="store_true", help="Usar el guion determinístico")
    parser.add_argument("--seed", type=int, default=42, help="Semilla para imágenes")
    parser.add_argument("--llm-base-url", default=DEFAULT_LLM_BASE_URL, help="Endpoint OpenAI-compatible")
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL, help="Modelo del LLM")
    parser.add_argument("--llm-api-key", default=DEFAULT_LLM_API_KEY, help="API key del LLM")
    parser.add_argument("--verbose", action="store_true", help="Log detallado")
    return parser


def config_from_args(args: argparse.Namespace) -> OmniConfig:
    images_dir = Path(args.images_dir).expanduser() if args.images_dir else None
    music_path = Path(args.music).expanduser() if args.music else None
    return OmniConfig(
        topic=str(args.topic),
        output_root=Path(args.output_dir).expanduser(),
        duration=int(args.duration),
        scene_count=int(args.scenes),
        voice=str(args.voice),
        image_source=str(args.image_source),
        images_dir=images_dir,
        music_path=music_path,
        no_music=bool(args.no_music),
        no_subtitles=bool(args.no_subtitles),
        seed=int(args.seed),
        llm_base_url=str(args.llm_base_url),
        llm_model=str(args.llm_model),
        llm_api_key=str(args.llm_api_key),
        use_llm=not bool(args.no_llm),
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
