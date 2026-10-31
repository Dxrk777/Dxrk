# SPDX-License-Identifier: MIT
"""Word-level timing and karaoke subtitles for Dxrk Omni.

Edge-TTS emits ``WordBoundary`` events while streaming audio. Those events are
the cheapest and most accurate source of word timings because they come from
the synthesizer itself. When a TTS engine does not expose boundaries, Whisper
can transcribe the generated audio with word timestamps, and a proportional
model is the final offline fallback.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EDGE_TICKS_PER_SECOND = 10_000_000


@dataclass(frozen=True, slots=True)
class WordTiming:
    text: str
    start: float
    end: float

    def scaled(self, factor: float) -> WordTiming:
        return WordTiming(self.text, self.start * factor, self.end * factor)

    def shifted(self, offset: float) -> WordTiming:
        return WordTiming(self.text, self.start + offset, self.end + offset)


@dataclass(frozen=True, slots=True)
class NarrationResult:
    audio: Path
    words: tuple[WordTiming, ...]
    source: str


def timings_from_edge_events(events: Iterable[Mapping[str, Any]]) -> tuple[WordTiming, ...]:
    """Convert Edge-TTS ``WordBoundary`` events into seconds."""
    words: list[WordTiming] = []
    for event in events:
        if event.get("type") != "WordBoundary":
            continue
        text = str(event.get("text") or "").strip()
        if not text:
            continue
        start = float(event.get("offset") or 0) / EDGE_TICKS_PER_SECOND
        duration = float(event.get("duration") or 0) / EDGE_TICKS_PER_SECOND
        words.append(WordTiming(text, start, start + max(0.0, duration)))
    return tuple(words)


def proportional_timings(text: str, duration: float) -> tuple[WordTiming, ...]:
    """Distribute words across the audio duration by character weight."""
    words = text.split()
    if not words:
        return ()
    duration = max(0.0, duration)
    weights = [max(1, len(word)) for word in words]
    total = sum(weights)
    timings: list[WordTiming] = []
    elapsed = 0
    for word, weight in zip(words, weights, strict=True):
        start = duration * elapsed / total
        elapsed += weight
        end = duration * elapsed / total
        timings.append(WordTiming(word, start, end))
    return tuple(timings)


def scale_timings(words: Sequence[WordTiming], factor: float) -> tuple[WordTiming, ...]:
    return tuple(word.scaled(max(0.0, factor)) for word in words)


def offset_timings(words: Sequence[WordTiming], offset: float) -> tuple[WordTiming, ...]:
    return tuple(word.shifted(offset) for word in words)


def group_word_timings(
    words: Sequence[WordTiming],
    *,
    max_words: int = 4,
    max_chars: int = 36,
    max_gap: float = 0.75,
) -> tuple[tuple[WordTiming, ...], ...]:
    """Group words into caption lines without breaking punctuation or pauses."""
    if max_words < 1:
        raise ValueError("max_words debe ser mayor que cero")
    if max_gap < 0:
        raise ValueError("max_gap no puede ser negativo")
    groups: list[tuple[WordTiming, ...]] = []
    current: list[WordTiming] = []
    current_chars = 0
    for word in words:
        if current and word.start - current[-1].end > max_gap:
            groups.append(tuple(current))
            current = []
            current_chars = 0
        if current and (len(current) >= max_words or current_chars + len(word.text) + 1 > max_chars):
            groups.append(tuple(current))
            current = []
            current_chars = 0
        current.append(word)
        current_chars += len(word.text) + 1
        if word.text.endswith((".", "!", "?", ",", ";", ":")):
            groups.append(tuple(current))
            current = []
            current_chars = 0
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def ass_time(seconds: float) -> str:
    total_cs = max(0, round(seconds * 100))
    hours, remainder = divmod(total_cs, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def escape_ass(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def _ass_header() -> str:
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
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


def build_word_ass(words: Sequence[WordTiming], *, max_words: int = 4) -> str:
    """Build an ASS file with per-word ``\\kf`` karaoke highlighting."""
    if not words:
        raise ValueError("no hay palabras para subtítulos")
    groups = group_word_timings(words, max_words=max_words)
    lines: list[str] = []
    for group in groups:
        start = group[0].start
        end = group[-1].end
        if end <= start:
            end = start + 0.01
        parts: list[str] = []
        for index, word in enumerate(group):
            next_start = group[index + 1].start if index + 1 < len(group) else end
            duration_cs = max(1, round((next_start - word.start) * 100))
            suffix = " " if index + 1 < len(group) else ""
            parts.append(f"{{\\kf{duration_cs}}}{escape_ass(word.text)}{suffix}")
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Dxrk,,0,0,0,,{{\\fad(120,120)}}{''.join(parts)}")
    return _ass_header() + "\n".join(lines) + "\n"


def write_word_ass(path: Path, words: Sequence[WordTiming], *, max_words: int = 4) -> Path:
    path.write_text(build_word_ass(words, max_words=max_words), encoding="utf-8")
    return path


def words_to_dict(words: Sequence[WordTiming]) -> list[dict[str, Any]]:
    return [{"text": word.text, "start": word.start, "end": word.end} for word in words]


def _normalize_words(items: Iterable[Any]) -> tuple[WordTiming, ...]:
    words: list[WordTiming] = []
    for item in items:
        if isinstance(item, WordTiming):
            words.append(item)
            continue
        if isinstance(item, Mapping):
            text = str(item.get("text") or item.get("word") or "").strip()
            start = float(item.get("start") or 0.0)
            end = float(item.get("end") or start)
        else:
            text = str(getattr(item, "text", getattr(item, "word", ""))).strip()
            start = float(getattr(item, "start", 0.0))
            end = float(getattr(item, "end", start))
        if text:
            words.append(WordTiming(text, start, end))
    return tuple(words)


def transcribe_words(
    audio: Path,
    *,
    model_size: str = "small",
    device: str = "auto",
    compute_type: str = "int8",
    transcriber: Any | None = None,
) -> tuple[WordTiming, ...]:
    """Transcribe ``audio`` with word timestamps.

    ``transcriber`` is an injection point for tests and custom models. It
    receives ``(audio, model_size=..., device=..., compute_type=...)`` and
    returns word-like objects or mappings.
    """
    if transcriber is not None:
        return _normalize_words(transcriber(audio, model_size=model_size, device=device, compute_type=compute_type))
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError("faster-whisper no está instalado. Ejecutá: uv pip install faster-whisper") from exc
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _ = model.transcribe(str(audio), word_timestamps=True)
    words: list[WordTiming] = []
    for segment in segments:
        for word in getattr(segment, "words", None) or []:
            text = str(getattr(word, "word", "")).strip()
            if text:
                words.append(WordTiming(text, float(word.start), float(word.end)))
    return tuple(words)
