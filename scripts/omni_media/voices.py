# SPDX-License-Identifier: MIT
"""Multi-voice narration and timeline helpers for Dxrk Omni.

The single-voice pipeline is intentionally left untouched. This module only
handles the data model and the pure timeline math needed when a script assigns
different voices to scenes, characters, or dialogue lines.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .music import concat_audio_tracks
from .words import NarrationResult, WordTiming

logger = logging.getLogger("dxrk.omni.voices")

DEFAULT_SPEAKER = "narrator"
Synthesizer = Callable[[str, Path, str], NarrationResult]
Probe = Callable[[Path], float]
Concat = Callable[[Sequence[Path], Path], Path]


class VoiceError(RuntimeError):
    """A multi-voice script or narration could not be resolved."""


@dataclass(frozen=True, slots=True)
class VoiceSpec:
    name: str
    voice: str
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"


@dataclass(frozen=True, slots=True)
class VoiceLine:
    speaker: str
    text: str


@dataclass(frozen=True, slots=True)
class VoiceRequest:
    index: int
    scene_index: int
    speaker: str
    text: str


@dataclass(frozen=True, slots=True)
class VoiceSegment:
    index: int
    scene_index: int
    speaker: str
    text: str
    audio: Path
    words: tuple[WordTiming, ...]
    duration: float
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class MultiVoiceNarration:
    audio: Path
    segments: tuple[VoiceSegment, ...]
    words: tuple[WordTiming, ...]
    source: str


def _clean_speaker(value: Any, default: str = DEFAULT_SPEAKER) -> str:
    speaker = str(value or default).strip()
    return speaker or default


def parse_voice_specs(values: Sequence[str], *, default_speaker: str = DEFAULT_SPEAKER) -> tuple[VoiceSpec, ...]:
    """Parse ``speaker=voice`` CLI values into specs.

    The first ``=`` is the separator, so Edge-TTS voice names that contain
    punctuation keep working. Duplicate speakers are allowed; the last value
    wins, which makes repeated CLI flags predictable.
    """
    specs: dict[str, VoiceSpec] = {}
    for raw in values:
        item = raw.strip()
        if not item:
            continue
        if "=" not in item:
            raise VoiceError(f"voice mapping inválido: {item!r} (esperado speaker=voice)")
        speaker, voice = item.split("=", 1)
        speaker = _clean_speaker(speaker, default_speaker)
        voice = voice.strip()
        if not voice:
            raise VoiceError(f"voice mapping inválido: {item!r} (voz vacía)")
        specs[speaker] = VoiceSpec(speaker, voice)
    return tuple(specs.values())


def _spec_from_value(name: str, value: Any) -> VoiceSpec:
    if isinstance(value, str):
        voice = value.strip()
        if not voice:
            raise VoiceError(f"la voz de {name!r} está vacía")
        return VoiceSpec(name, voice)
    if not isinstance(value, Mapping):
        raise VoiceError(f"la voz de {name!r} debe ser un string o un objeto")
    voice = str(value.get("voice") or "").strip()
    if not voice:
        raise VoiceError(f"la voz de {name!r} necesita el campo 'voice'")
    return VoiceSpec(
        name=name,
        voice=voice,
        rate=str(value.get("rate") or "+0%"),
        pitch=str(value.get("pitch") or "+0Hz"),
        volume=str(value.get("volume") or "+0%"),
    )


def load_voice_map(path: Path | None) -> dict[str, VoiceSpec]:
    """Load a JSON voice map.

    Accepted shapes::

        {"narrator": "es-AR-TomasNeural"}
        {"voices": {"narrator": {"voice": "es-AR-TomasNeural", "rate": "+5%"}}}
    """
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VoiceError(f"no pude leer el voice map {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise VoiceError(f"voice map inválido {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise VoiceError("el voice map debe ser un objeto JSON")
    raw = data.get("voices", data)
    if not isinstance(raw, dict):
        raise VoiceError("el campo 'voices' debe ser un objeto")
    return {
        _clean_speaker(name): _spec_from_value(_clean_speaker(name), value)
        for name, value in raw.items()
    }


def resolve_voices(
    default_voice: str,
    specs: Sequence[VoiceSpec] = (),
    voice_map: Mapping[str, VoiceSpec] | None = None,
    *,
    default_speaker: str = DEFAULT_SPEAKER,
) -> dict[str, VoiceSpec]:
    """Resolve the default voice plus optional per-speaker overrides."""
    default_voice = default_voice.strip()
    if not default_voice:
        raise VoiceError("la voz por defecto no puede estar vacía")
    default_speaker = _clean_speaker(default_speaker)
    resolved: dict[str, VoiceSpec] = {default_speaker: VoiceSpec(default_speaker, default_voice)}
    for name, spec in (voice_map or {}).items():
        resolved[_clean_speaker(name)] = spec
    for spec in specs:
        resolved[_clean_speaker(spec.name)] = spec
    return resolved


def _normalize_line(line: Any, default_speaker: str) -> VoiceLine:
    if isinstance(line, VoiceLine):
        return VoiceLine(_clean_speaker(line.speaker, default_speaker), line.text.strip())
    if isinstance(line, Mapping):
        speaker = line.get("speaker")
        text = line.get("text") or line.get("narration") or ""
    else:
        speaker = getattr(line, "speaker", None)
        text = getattr(line, "text", "")
    return VoiceLine(_clean_speaker(speaker, default_speaker), str(text).strip())


def segment_scenes(
    scenes: Sequence[Any],
    *,
    default_speaker: str = DEFAULT_SPEAKER,
) -> tuple[VoiceRequest, ...]:
    """Flatten scenes into synthesis requests.

    A scene with ``lines`` becomes one request per line. A scene without
    ``lines`` becomes a single request using the scene ``speaker``.
    """
    default_speaker = _clean_speaker(default_speaker)
    requests: list[VoiceRequest] = []
    for scene in scenes:
        scene_index = int(getattr(scene, "index", len(requests) + 1))
        raw_lines = getattr(scene, "lines", ()) or ()
        if not isinstance(raw_lines, (list, tuple)):
            raise VoiceError(f"las líneas de la escena {scene_index} deben ser una lista")
        lines: tuple[Any, ...] = tuple(raw_lines)
        if lines:
            for line_index, line in enumerate(lines):
                if not isinstance(line, (VoiceLine, Mapping)) and not hasattr(line, "text"):
                    raise VoiceError(
                        f"la línea {line_index + 1} de la escena {scene_index} no es un objeto"
                    )
                normalized = _normalize_line(line, default_speaker)
                if not normalized.text:
                    raise VoiceError(f"la escena {scene_index} tiene una línea vacía")
                requests.append(
                    VoiceRequest(
                        index=len(requests) + 1,
                        scene_index=scene_index,
                        speaker=normalized.speaker,
                        text=normalized.text,
                    )
                )
            continue
        text = str(getattr(scene, "narration", "") or "").strip()
        if not text:
            raise VoiceError(f"la escena {scene_index} no tiene narración")
        requests.append(
            VoiceRequest(
                index=len(requests) + 1,
                scene_index=scene_index,
                speaker=_clean_speaker(getattr(scene, "speaker", None), default_speaker),
                text=text,
            )
        )
    return tuple(requests)


def synthesize_requests(
    requests: Sequence[VoiceRequest],
    out_dir: Path,
    voices: Mapping[str, VoiceSpec],
    *,
    synthesize: Synthesizer,
    probe: Probe | None = None,
    concat: Concat | None = None,
    default_speaker: str = DEFAULT_SPEAKER,
) -> MultiVoiceNarration:
    """Synthesize every request and concatenate the result without gaps."""
    if not requests:
        raise VoiceError("no hay requests de voz para sintetizar")
    default_speaker = _clean_speaker(default_speaker)
    fallback = voices.get(default_speaker)
    if fallback is None:
        raise VoiceError(f"falta la voz por defecto {default_speaker!r}")
    out_dir.mkdir(parents=True, exist_ok=True)
    concat_fn = concat or (lambda tracks, dest: concat_audio_tracks(tracks, dest))
    segments: list[VoiceSegment] = []
    elapsed = 0.0
    sources: list[str] = []
    for request in requests:
        spec = voices.get(request.speaker)
        if spec is None:
            logger.warning("speaker %r has no voice; using %r", request.speaker, default_speaker)
            spec = fallback
        dest = out_dir / f"segment_{request.index:03d}.mp3"
        result = synthesize(request.text, dest, spec.voice)
        words = tuple(
            WordTiming(word.text, word.start, word.end, request.speaker)
            for word in result.words
        )
        if probe is not None:
            duration = float(probe(result.audio))
        elif words:
            duration = words[-1].end
        else:
            raise VoiceError(
                f"no pude determinar la duración del segmento {request.index}; pasá un probe"
            )
        if duration <= 0:
            raise VoiceError(f"el segmento {request.index} no tiene duración válida")
        segments.append(
            VoiceSegment(
                index=request.index,
                scene_index=request.scene_index,
                speaker=request.speaker,
                text=request.text,
                audio=result.audio,
                words=words,
                duration=duration,
                start=elapsed,
                end=elapsed + duration,
            )
        )
        sources.append(result.source)
        elapsed += duration
    audio = concat_fn([segment.audio for segment in segments], out_dir / "narration.m4a")
    all_words = tuple(
        WordTiming(word.text, segment.start + word.start, segment.start + word.end, segment.speaker)
        for segment in segments
        for word in segment.words
    )
    return MultiVoiceNarration(
        audio=audio,
        segments=tuple(segments),
        words=all_words,
        source="+".join(sorted(set(sources))) or "multi",
    )


def _scene_order(segments: Sequence[VoiceSegment]) -> tuple[int, ...]:
    order: list[int] = []
    for segment in segments:
        if segment.scene_index not in order:
            order.append(segment.scene_index)
    return tuple(order)


def assign_scene_durations(
    segments: Sequence[VoiceSegment],
    target_duration: float,
    tempo: float,
) -> tuple[float, ...]:
    """Return one video duration per scene, derived from real audio.

    The audio is concatenated without gaps and then sped up with ``atempo``.
    Each scene clip gets the matching scaled duration. If the narration is
    shorter than the target, the extra time is appended to the last scene so
    the video and the final audio pad agree.
    """
    if target_duration <= 0:
        raise VoiceError("la duración objetivo debe ser positiva")
    if tempo <= 0:
        raise VoiceError("el tempo debe ser positivo")
    order = _scene_order(segments)
    if not order:
        raise VoiceError("no hay segmentos para calcular duraciones")
    raw = {index: 0.0 for index in order}
    for segment in segments:
        raw[segment.scene_index] += segment.duration
    durations = [raw[index] / tempo for index in order]
    total = sum(durations)
    if total <= 0:
        raise VoiceError("la narración no tiene duración válida")
    if total < target_duration:
        durations[-1] += target_duration - total
    return tuple(durations)


def timeline_words(
    segments: Sequence[VoiceSegment],
    scene_durations: Sequence[float],
    tempo: float,
) -> tuple[WordTiming, ...]:
    """Scale and offset every word into the final video timeline."""
    if tempo <= 0:
        raise VoiceError("el tempo debe ser positivo")
    order = _scene_order(segments)
    if len(order) != len(scene_durations):
        raise VoiceError("scene_durations no coincide con las escenas de los segmentos")
    starts: dict[int, float] = {}
    elapsed = 0.0
    for scene_index, duration in zip(order, scene_durations, strict=True):
        starts[scene_index] = elapsed
        elapsed += duration
    cursors = {index: 0.0 for index in order}
    words: list[WordTiming] = []
    for segment in segments:
        base = starts[segment.scene_index] + cursors[segment.scene_index]
        for word in segment.words:
            words.append(
                WordTiming(
                    word.text,
                    base + word.start / tempo,
                    base + word.end / tempo,
                    segment.speaker,
                )
            )
        cursors[segment.scene_index] += segment.duration / tempo
    return tuple(words)


def speaker_style_name(speaker: str) -> str:
    """Convert a speaker label into a safe ASS style name."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", speaker.strip())
    return cleaned or "Speaker"
