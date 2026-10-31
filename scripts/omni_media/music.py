# SPDX-License-Identifier: MIT
"""Long-duration music backends for Dxrk Omni.

The default backend is still the dependency-free FFmpeg ambient synthesizer.
MusicGen and Stable Audio Open are optional local models: they are imported
lazily, generated in chunks, and joined with FFmpeg crossfades so a track can
be longer than a single model context window.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

DEFAULT_MUSICGEN_MODEL = "facebook/musicgen-small"
DEFAULT_STABLE_AUDIO_MODEL = "stabilityai/stable-audio-open-1.0"


class MusicBackendError(RuntimeError):
    """A music backend could not generate a track."""


class MusicGenerator(Protocol):
    def generate(self, dest: Path, duration: float, prompt: str) -> Path:
        """Generate ``duration`` seconds of music into ``dest``."""
        ...


def _run(cmd: Sequence[str], runner: Callable[[Sequence[str]], Any] | None = None) -> Any:
    if runner is not None:
        return runner(cmd)
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise MusicBackendError(f"no encontré {cmd[0]}; instalá ffmpeg") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise MusicBackendError(f"falló {cmd[0]}: {detail[-600:]}") from exc


def synthesize_ambient(
    dest: Path,
    duration: float,
    runner: Callable[[Sequence[str]], Any] | None = None,
) -> Path:
    """Synthesize an original ambient bed with FFmpeg sine filters."""
    fade_out = max(0.0, duration - 2)
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
    _run(cmd, runner)
    return dest


def prepare_track(
    src: Path,
    dest: Path,
    duration: float,
    runner: Callable[[Sequence[str]], Any] | None = None,
) -> Path:
    if not src.exists():
        raise MusicBackendError(f"no existe la música: {src}")
    fade_out = max(0.0, duration - 2)
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
    _run(cmd, runner)
    return dest


def concat_audio_chunks(
    chunks: Sequence[Path],
    out: Path,
    *,
    crossfade: float = 1.0,
    runner: Callable[[Sequence[str]], Any] | None = None,
) -> Path:
    if not chunks:
        raise MusicBackendError("no hay chunks de música para concatenar")
    if len(chunks) == 1:
        cmd = ["ffmpeg", "-y", "-i", str(chunks[0]), "-c:a", "pcm_s16le", str(out)]
        _run(cmd, runner)
        return out
    inputs: list[str] = []
    for chunk in chunks:
        inputs.extend(["-i", str(chunk)])
    filters: list[str] = []
    previous = "[0:a]"
    for index in range(1, len(chunks)):
        label = f"[a{index}]" if index < len(chunks) - 1 else "[a]"
        filters.append(f"{previous}[{index}:a]acrossfade=d={crossfade:.3f}{label}")
        previous = label
    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[a]",
        "-c:a",
        "pcm_s16le",
        str(out),
    ]
    _run(cmd, runner)
    return out


def concat_audio_tracks(
    tracks: Sequence[Path],
    out: Path,
    runner: Callable[[Sequence[str]], Any] | None = None,
) -> Path:
    """Join finished audio tracks without crossfading (preserves sync)."""
    if not tracks:
        raise MusicBackendError("no hay pistas de audio para concatenar")
    list_file = out.with_suffix(".txt")
    list_file.write_text(
        "".join(
            f"file '{track.as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for track in tracks
        ),
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out),
    ]
    _run(cmd, runner)
    return out


def trim_audio(
    src: Path,
    dest: Path,
    duration: float,
    runner: Callable[[Sequence[str]], Any] | None = None,
) -> Path:
    cmd = ["ffmpeg", "-y", "-i", str(src), "-t", f"{duration:.3f}", "-c:a", "pcm_s16le", str(dest)]
    _run(cmd, runner)
    return dest


@dataclass
class FfmpegSynthGenerator:
    runner: Callable[[Sequence[str]], Any] | None = None

    def generate(self, dest: Path, duration: float, prompt: str) -> Path:
        return synthesize_ambient(dest, duration, self.runner)


@dataclass
class MusicGenGenerator:
    model_name: str = DEFAULT_MUSICGEN_MODEL
    chunk_seconds: float = 30.0
    device: str = "auto"
    generator: Callable[[str, float, Path], None] | None = None
    runner: Callable[[Sequence[str]], Any] | None = None
    _model: Any = field(default=None, init=False, repr=False)
    _processor: Any = field(default=None, init=False, repr=False)

    def generate(self, dest: Path, duration: float, prompt: str) -> Path:
        chunks = self._generate_chunks(dest, duration, prompt)
        return concat_audio_chunks(
            chunks,
            dest,
            crossfade=min(1.0, max(0.1, self.chunk_seconds / 10)),
            runner=self.runner,
        )

    def _generate_chunks(self, dest: Path, duration: float, prompt: str) -> list[Path]:
        if duration <= 0:
            raise MusicBackendError("la duración de la música debe ser positiva")
        chunks: list[Path] = []
        remaining = duration
        index = 0
        while remaining > 1e-6:
            chunk_duration = min(self.chunk_seconds, remaining)
            chunk = dest.with_name(f"{dest.stem}_chunk_{index:03d}.wav")
            if self.generator is not None:
                self.generator(prompt, chunk_duration, chunk)
            else:
                self._generate_chunk(prompt, chunk_duration, chunk)
            if not chunk.exists() or chunk.stat().st_size == 0:
                raise MusicBackendError(f"MusicGen no generó el chunk {chunk.name}")
            chunks.append(chunk)
            remaining -= chunk_duration
            index += 1
        return chunks

    def _generate_chunk(self, prompt: str, duration: float, dest: Path) -> None:
        try:
            import scipy.io.wavfile as wavfile
            from transformers import AutoProcessor, MusicgenForConditionalGeneration
        except ImportError as exc:  # pragma: no cover - optional dependency guard
            raise MusicBackendError(
                "MusicGen requiere transformers, torch y scipy. Ejecutá: uv pip install transformers torch scipy"
            ) from exc
        if self._model is None or self._processor is None:
            self._processor = AutoProcessor.from_pretrained(self.model_name)
            self._model = MusicgenForConditionalGeneration.from_pretrained(self.model_name)
            if self.device != "auto":
                self._model = self._model.to(self.device)
        inputs = self._processor(text=[prompt], padding=True, return_tensors="pt")
        if self.device != "auto":
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
        max_new_tokens = max(1, int(round(duration * 50)))
        audio = self._model.generate(**inputs, max_new_tokens=max_new_tokens)
        sample_rate = int(self._model.config.audio_encoder.sampling_rate)
        wavfile.write(dest, sample_rate, audio[0, 0].detach().cpu().numpy())


@dataclass
class StableAudioGenerator:
    model_name: str = DEFAULT_STABLE_AUDIO_MODEL
    chunk_seconds: float = 30.0
    device: str = "cpu"
    generator: Callable[[str, float, Path], None] | None = None
    runner: Callable[[Sequence[str]], Any] | None = None
    _model: Any = field(default=None, init=False, repr=False)
    _config: Any = field(default=None, init=False, repr=False)

    def generate(self, dest: Path, duration: float, prompt: str) -> Path:
        chunks = self._generate_chunks(dest, duration, prompt)
        return concat_audio_chunks(
            chunks,
            dest,
            crossfade=min(1.0, max(0.1, self.chunk_seconds / 10)),
            runner=self.runner,
        )

    def _generate_chunks(self, dest: Path, duration: float, prompt: str) -> list[Path]:
        if duration <= 0:
            raise MusicBackendError("la duración de la música debe ser positiva")
        chunks: list[Path] = []
        remaining = duration
        index = 0
        while remaining > 1e-6:
            chunk_duration = min(self.chunk_seconds, remaining)
            chunk = dest.with_name(f"{dest.stem}_chunk_{index:03d}.wav")
            if self.generator is not None:
                self.generator(prompt, chunk_duration, chunk)
            else:
                self._generate_chunk(prompt, chunk_duration, chunk)
            if not chunk.exists() or chunk.stat().st_size == 0:
                raise MusicBackendError(f"Stable Audio no generó el chunk {chunk.name}")
            chunks.append(chunk)
            remaining -= chunk_duration
            index += 1
        return chunks

    def _generate_chunk(self, prompt: str, duration: float, dest: Path) -> None:
        try:
            import torchaudio
            from stable_audio_tools import get_pretrained_model
            from stable_audio_tools.inference.generation import generate_diffusion_cond
        except ImportError as exc:  # pragma: no cover - optional dependency guard
            raise MusicBackendError(
                "Stable Audio requiere stable-audio-tools, torch y torchaudio. "
                "Ejecutá: uv pip install stable-audio-tools"
            ) from exc
        if self._model is None or self._config is None:
            self._model, self._config = get_pretrained_model(self.model_name)
            self._model = self._model.to(self.device).eval()
        conditioning = [{"prompt": prompt, "seconds_start": 0, "seconds_total": duration}]
        output = generate_diffusion_cond(
            self._model,
            steps=100,
            cfg_scale=7,
            conditioning=conditioning,
            sample_size=self._config["sample_size"],
            sigma_min=0.3,
            sigma_max=500,
            sampler_type="dpmpp-3m-sde",
            device=self.device,
        )
        torchaudio.save(dest, output["audio"][0].cpu(), self._config["sample_rate"])


def build_music_generator(
    source: str,
    *,
    model: str = "",
    chunk_seconds: float = 30.0,
    generator: Callable[[str, float, Path], None] | None = None,
    runner: Callable[[Sequence[str]], Any] | None = None,
) -> MusicGenerator:
    if source == "synth":
        return FfmpegSynthGenerator(runner=runner)
    if source == "musicgen":
        return MusicGenGenerator(
            model_name=model or DEFAULT_MUSICGEN_MODEL,
            chunk_seconds=chunk_seconds,
            generator=generator,
            runner=runner,
        )
    if source == "stable-audio":
        return StableAudioGenerator(
            model_name=model or DEFAULT_STABLE_AUDIO_MODEL,
            chunk_seconds=chunk_seconds,
            generator=generator,
            runner=runner,
        )
    raise ValueError(f"music source desconocido: {source}")
