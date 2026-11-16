# SPDX-License-Identifier: MIT
"""Word-level timing and karaoke subtitles for Dxrk Omni.

Edge-TTS emits ``WordBoundary`` events while streaming audio. Those events are
the cheapest and most accurate source of word timings because they come from
the synthesizer itself. When a TTS engine does not expose boundaries, Whisper
can transcribe the generated audio with word timestamps, and a proportional
model is the final offline fallback.

Words can carry an optional ``speaker`` label. Caption grouping never merges
words from different speakers, and the ASS header gets one style per speaker.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

EDGE_TICKS_PER_SECOND = 10_000_000
DEFAULT_PLAY_RES = (1080, 1920)


@dataclass(frozen=True, slots=True)
class WordTiming:
    text: str
    start: float
    end: float
    speaker: str = ""

    def scaled(self, factor: float) -> WordTiming:
        return WordTiming(self.text, self.start * factor, self.end * factor, self.speaker)

    def shifted(self, offset: float) -> WordTiming:
        return WordTiming(self.text, self.start + offset, self.end + offset, self.speaker)


@dataclass(frozen=True, slots=True)
class NarrationResult:
    audio: Path
    words: tuple[WordTiming, ...]
    source: str


@dataclass(frozen=True, slots=True)
class AssStyle:
    name: str = "Dxrk"
    fontname: str = "DejaVu Sans"
    fontsize: int = 64
    primary: str = "&H00FFFFFF"
    secondary: str = "&H0000FFFF"
    outline: str = "&H00000000"
    back: str = "&H80000000"
    bold: int = -1
    italic: int = 0
    underline: int = 0
    strikeout: int = 0
    scale_x: int = 100
    scale_y: int = 100
    spacing: int = 0
    angle: int = 0
    border_style: int = 1
    outline_width: int = 4
    shadow: int = 1
    alignment: int = 2
    margin_l: int = 60
    margin_r: int = 60
    margin_v: int = 180
    encoding: int = 1


_ASS_COLORS = (
    "&H00FFFFFF",
    "&H0080FFFF",
    "&H0000FFFF",
    "&H00FF80FF",
    "&H0080FF80",
    "&H00FF8080",
    "&H00FFFF80",
    "&H00C080FF",
)


def sanitize_style_name(speaker: str) -> str:
    """Convert a speaker label into a safe ASS style name."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", speaker.strip())
    return cleaned or "Speaker"


def _scale_style(style: AssStyle, play_res: tuple[int, int]) -> AssStyle:
    scale = max(1.0, play_res[1] / DEFAULT_PLAY_RES[1])
    if scale == 1.0:
        return style
    return replace(
        style,
        fontsize=max(1, round(style.fontsize * scale)),
        outline_width=max(1, round(style.outline_width * scale)),
        shadow=max(1, round(style.shadow * scale)),
        margin_l=round(style.margin_l * scale),
        margin_r=round(style.margin_r * scale),
        margin_v=round(style.margin_v * scale),
    )


def default_style(play_res: tuple[int, int] = DEFAULT_PLAY_RES) -> AssStyle:
    return _scale_style(AssStyle(), play_res)


def style_for_speaker(
    speaker: str,
    index: int = 0,
    play_res: tuple[int, int] = DEFAULT_PLAY_RES,
) -> AssStyle:
    """Build a deterministic speaker style with a distinct colour."""
    name = sanitize_style_name(speaker)
    if name == "Dxrk":
        return default_style(play_res)
    style = AssStyle(
        name=name,
        primary=_ASS_COLORS[index % len(_ASS_COLORS)],
        secondary=_ASS_COLORS[(index + 1) % len(_ASS_COLORS)],
    )
    return _scale_style(style, play_res)


def ass_style_line(style: AssStyle) -> str:
    return (
        f"Style: {style.name},{style.fontname},{style.fontsize},{style.primary},{style.secondary},"
        f"{style.outline},{style.back},{style.bold},{style.italic},{style.underline},{style.strikeout},"
        f"{style.scale_x},{style.scale_y},{style.spacing},{style.angle},{style.border_style},"
        f"{style.outline_width},{style.shadow},{style.alignment},{style.margin_l},{style.margin_r},"
        f"{style.margin_v},{style.encoding}"
    )


def ass_header(
    styles: Mapping[str, AssStyle] | None = None,
    *,
    play_res: tuple[int, int] = DEFAULT_PLAY_RES,
) -> str:
    """Build the ASS header with the default style plus any speaker styles."""
    resolved: dict[str, AssStyle] = {"Dxrk": default_style(play_res)}
    for key, style in (styles or {}).items():
        name = sanitize_style_name(key)
        resolved[name] = replace(style, name=name)
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res[0]}\n"
        f"PlayResY: {play_res[1]}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        + "\n".join(ass_style_line(style) for style in resolved.values())
        + "\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


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
    """Group words into caption lines without breaking punctuation, pauses, or speakers."""
    if max_words < 1:
        raise ValueError("max_words debe ser mayor que cero")
    if max_gap < 0:
        raise ValueError("max_gap no puede ser negativo")
    groups: list[tuple[WordTiming, ...]] = []
    current: list[WordTiming] = []
    current_chars = 0
    for word in words:
        if current and word.speaker != current[-1].speaker:
            groups.append(tuple(current))
            current = []
            current_chars = 0
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


def build_word_ass(
    words: Sequence[WordTiming],
    *,
    max_words: int = 4,
    styles: Mapping[str, AssStyle] | None = None,
    play_res: tuple[int, int] = DEFAULT_PLAY_RES,
) -> str:
    """Build an ASS file with per-word ``\\kf`` karaoke highlighting."""
    if not words:
        raise ValueError("no hay palabras para subtítulos")
    groups = group_word_timings(words, max_words=max_words)
    resolved: dict[str, AssStyle] = {"Dxrk": default_style(play_res)}
    for key, style in (styles or {}).items():
        name = sanitize_style_name(key)
        resolved[name] = replace(style, name=name)
    for index, word in enumerate(words):
        if not word.speaker:
            continue
        name = sanitize_style_name(word.speaker)
        if name not in resolved:
            resolved[name] = style_for_speaker(word.speaker, index, play_res)
    lines: list[str] = []
    for group in groups:
        start = group[0].start
        end = group[-1].end
        if end <= start:
            end = start + 0.01
        style_name = sanitize_style_name(group[0].speaker) if group[0].speaker else "Dxrk"
        if style_name not in resolved:
            style_name = "Dxrk"
        parts: list[str] = []
        for index, word in enumerate(group):
            next_start = group[index + 1].start if index + 1 < len(group) else end
            duration_cs = max(1, round((next_start - word.start) * 100))
            suffix = " " if index + 1 < len(group) else ""
            parts.append(f"{{\\kf{duration_cs}}}{escape_ass(word.text)}{suffix}")
        lines.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},{style_name},,0,0,0,,"
            f"{{\\fad(120,120)}}{''.join(parts)}"
        )
    return ass_header(resolved, play_res=play_res) + "\n".join(lines) + "\n"


def write_word_ass(
    path: Path,
    words: Sequence[WordTiming],
    *,
    max_words: int = 4,
    styles: Mapping[str, AssStyle] | None = None,
    play_res: tuple[int, int] = DEFAULT_PLAY_RES,
) -> Path:
    path.write_text(
        build_word_ass(words, max_words=max_words, styles=styles, play_res=play_res),
        encoding="utf-8",
    )
    return path


def words_to_dict(words: Sequence[WordTiming]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for word in words:
        item: dict[str, Any] = {"text": word.text, "start": word.start, "end": word.end}
        if word.speaker:
            item["speaker"] = word.speaker
        items.append(item)
    return items


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
            speaker = str(item.get("speaker") or "")
        else:
            text = str(getattr(item, "text", getattr(item, "word", ""))).strip()
            start = float(getattr(item, "start", 0.0))
            end = float(getattr(item, "end", start))
            speaker = str(getattr(item, "speaker", "") or "")
        if text:
            words.append(WordTiming(text, start, end, speaker))
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
