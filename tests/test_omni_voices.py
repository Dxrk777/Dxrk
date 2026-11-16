# SPDX-License-Identifier: MIT
"""Tests for multi-voice narration and timeline math."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.omni_media import voices
from scripts.omni_media.voices import (
    DEFAULT_SPEAKER,
    MultiVoiceNarration,
    VoiceError,
    VoiceLine,
    VoiceRequest,
    VoiceSegment,
    VoiceSpec,
)
from scripts.omni_media.words import NarrationResult, WordTiming


def _segment(
    index: int,
    scene_index: int,
    duration: float,
    speaker: str = "narrator",
    words: tuple[WordTiming, ...] | None = None,
) -> VoiceSegment:
    return VoiceSegment(
        index=index,
        scene_index=scene_index,
        speaker=speaker,
        text=f"text {index}",
        audio=Path(f"segment_{index}.mp3"),
        words=words or (WordTiming(f"w{index}", 0.0, duration, speaker),),
        duration=duration,
        start=0.0,
        end=duration,
    )


class _Scene:
    def __init__(self, index: int, narration: str = "", speaker: str = "", lines=()) -> None:
        self.index = index
        self.narration = narration
        self.speaker = speaker
        self.lines = lines


def test_parse_voice_specs_and_errors() -> None:
    specs = voices.parse_voice_specs(
        ["narrator=voice-a", "quote=voice=b", "narrator=voice-c", "  ", ""],
        default_speaker="host",
    )
    assert [(spec.name, spec.voice) for spec in specs] == [("narrator", "voice-c"), ("quote", "voice=b")]
    assert voices.parse_voice_specs(["=voice"], default_speaker="host")[0].name == "host"
    with pytest.raises(VoiceError, match="speaker=voice"):
        voices.parse_voice_specs(["voice-only"])
    with pytest.raises(VoiceError, match="voz vacía"):
        voices.parse_voice_specs(["narrator="])


def test_load_voice_map_shapes_and_errors(tmp_path: Path) -> None:
    assert voices.load_voice_map(None) == {}
    direct = tmp_path / "direct.json"
    direct.write_text(json.dumps({"narrator": "v1"}), encoding="utf-8")
    assert voices.load_voice_map(direct)["narrator"].voice == "v1"
    nested = tmp_path / "nested.json"
    nested.write_text(
        json.dumps(
            {
                "voices": {
                    "narrator": {"voice": "v2", "rate": "+5%", "pitch": "+1Hz", "volume": "+2%"},
                    "quote": "v3",
                }
            }
        ),
        encoding="utf-8",
    )
    loaded = voices.load_voice_map(nested)
    assert loaded["narrator"].rate == "+5%"
    assert loaded["narrator"].pitch == "+1Hz"
    assert loaded["narrator"].volume == "+2%"
    assert loaded["quote"].voice == "v3"
    empty_name = tmp_path / "empty-name.json"
    empty_name.write_text(json.dumps({"": "v4"}), encoding="utf-8")
    assert DEFAULT_SPEAKER in voices.load_voice_map(empty_name)

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{", encoding="utf-8")
    with pytest.raises(VoiceError, match="inválido"):
        voices.load_voice_map(bad_json)
    not_object = tmp_path / "not-object.json"
    not_object.write_text("[]", encoding="utf-8")
    with pytest.raises(VoiceError, match="objeto JSON"):
        voices.load_voice_map(not_object)
    bad_voices = tmp_path / "bad-voices.json"
    bad_voices.write_text(json.dumps({"voices": []}), encoding="utf-8")
    with pytest.raises(VoiceError, match="'voices'"):
        voices.load_voice_map(bad_voices)
    bad_value = tmp_path / "bad-value.json"
    bad_value.write_text(json.dumps({"narrator": 3}), encoding="utf-8")
    with pytest.raises(VoiceError, match="string o un objeto"):
        voices.load_voice_map(bad_value)
    missing_voice = tmp_path / "missing-voice.json"
    missing_voice.write_text(json.dumps({"narrator": {"rate": "+1%"}}), encoding="utf-8")
    with pytest.raises(VoiceError, match="campo 'voice'"):
        voices.load_voice_map(missing_voice)
    empty_voice = tmp_path / "empty-voice.json"
    empty_voice.write_text(json.dumps({"narrator": ""}), encoding="utf-8")
    with pytest.raises(VoiceError, match="vacía"):
        voices.load_voice_map(empty_voice)
    with pytest.raises(VoiceError, match="no pude leer"):
        voices.load_voice_map(tmp_path / "missing.json")


def test_resolve_voices_order_and_errors() -> None:
    voice_map = {"narrator": VoiceSpec("narrator", "map"), "quote": VoiceSpec("quote", "map-q")}
    specs = (VoiceSpec("quote", "cli-q"),)
    resolved = voices.resolve_voices("default", specs, voice_map)
    assert resolved["narrator"].voice == "map"
    assert resolved["quote"].voice == "cli-q"
    custom = voices.resolve_voices("default", default_speaker="host")
    assert custom["host"].voice == "default"
    with pytest.raises(VoiceError, match="vacía"):
        voices.resolve_voices("  ")


def test_segment_scenes_variants_and_errors() -> None:
    scenes = [
        _Scene(1, narration="uno", speaker="narrator"),
        _Scene(
            2,
            lines=(
                VoiceLine("quote", "dos"),
                {"speaker": "guest", "text": "tres"},
                type("Line", (), {"speaker": "", "text": "cuatro"})(),
            ),
        ),
        _Scene(3, lines=({"narration": "cinco"},)),
    ]
    requests = voices.segment_scenes(scenes, default_speaker="host")
    assert [request.speaker for request in requests] == ["narrator", "quote", "guest", "host", "host"]
    assert [request.scene_index for request in requests] == [1, 2, 2, 2, 3]
    assert [request.index for request in requests] == [1, 2, 3, 4, 5]
    with pytest.raises(VoiceError, match="línea vacía"):
        voices.segment_scenes([_Scene(1, lines=(VoiceLine("x", " "),))])
    with pytest.raises(VoiceError, match="no tiene narración"):
        voices.segment_scenes([_Scene(1)])
    with pytest.raises(VoiceError, match="lista"):
        voices.segment_scenes([_Scene(1, lines="bad")])
    with pytest.raises(VoiceError, match="no es un objeto"):
        voices.segment_scenes([_Scene(1, lines=(3,))])
    assert voices.segment_scenes([_Scene(1, narration="uno")])[0].speaker == DEFAULT_SPEAKER


def _synth_factory(durations: dict[Path, float], words: bool = True, empty_words: bool = False):
    def synth(text: str, dest: Path, voice: str) -> NarrationResult:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"audio")
        durations[dest] = 1.5
        if empty_words:
            result_words: tuple[WordTiming, ...] = ()
        elif words:
            result_words = (WordTiming(text, 0.0, 0.9),)
        else:
            result_words = ()
        return NarrationResult(dest, result_words, "fake")

    return synth


def _concat_factory(durations: dict[Path, float]):
    def concat(tracks, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"concat")
        durations[dest] = sum(durations.get(track, 1.0) for track in tracks)
        return dest

    return concat


def test_synthesize_requests_with_probe_and_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    durations: dict[Path, float] = {}
    voices_used: list[str] = []
    synth = _synth_factory(durations)
    base_synth = synth

    def recording_synth(text: str, dest: Path, voice: str) -> NarrationResult:
        voices_used.append(voice)
        return base_synth(text, dest, voice)

    def fake_concat(tracks, dest: Path, runner=None) -> Path:
        dest.write_bytes(b"concat")
        durations[dest] = sum(durations.get(track, 1.0) for track in tracks)
        return dest

    monkeypatch.setattr(voices, "concat_audio_tracks", fake_concat)
    requests = (
        VoiceRequest(1, 1, "narrator", "uno"),
        VoiceRequest(2, 1, "missing", "dos"),
    )
    narration = voices.synthesize_requests(
        requests,
        tmp_path / "voice",
        voices.resolve_voices("v1", (VoiceSpec("quote", "v2"),)),
        synthesize=recording_synth,
        probe=lambda path: durations.get(path, 2.0),
    )
    assert isinstance(narration, MultiVoiceNarration)
    assert narration.audio.exists()
    assert narration.source == "fake"
    assert voices_used == ["v1", "v1"]
    assert [segment.speaker for segment in narration.segments] == ["narrator", "missing"]
    assert narration.segments[0].duration == 1.5
    assert narration.segments[1].start == 1.5
    assert narration.words[0].speaker == "narrator"
    assert narration.words[1].speaker == "missing"


def test_synthesize_requests_without_probe_uses_words(tmp_path: Path) -> None:
    durations: dict[Path, float] = {}
    narration = voices.synthesize_requests(
        (VoiceRequest(1, 1, "narrator", "uno"),),
        tmp_path,
        {"narrator": VoiceSpec("narrator", "v")},
        synthesize=_synth_factory(durations),
        concat=_concat_factory(durations),
    )
    assert narration.segments[0].duration == 0.9


def test_synthesize_requests_errors(tmp_path: Path) -> None:
    with pytest.raises(VoiceError, match="no hay requests"):
        voices.synthesize_requests([], tmp_path, {}, synthesize=_synth_factory({}))
    with pytest.raises(VoiceError, match="falta la voz por defecto"):
        voices.synthesize_requests(
            (VoiceRequest(1, 1, "narrator", "uno"),),
            tmp_path,
            {},
            synthesize=_synth_factory({}),
        )
    durations: dict[Path, float] = {}
    with pytest.raises(VoiceError, match="pasá un probe"):
        voices.synthesize_requests(
            (VoiceRequest(1, 1, "narrator", "uno"),),
            tmp_path,
            {"narrator": VoiceSpec("narrator", "v")},
            synthesize=_synth_factory(durations, empty_words=True),
            concat=_concat_factory(durations),
        )
    zero = _synth_factory(durations)
    with pytest.raises(VoiceError, match="duración válida"):
        voices.synthesize_requests(
            (VoiceRequest(1, 1, "narrator", "uno"),),
            tmp_path,
            {"narrator": VoiceSpec("narrator", "v")},
            synthesize=zero,
            probe=lambda path: 0.0,
            concat=_concat_factory(durations),
        )


def test_assign_scene_durations_and_errors() -> None:
    segments = (
        _segment(1, 1, 2.0),
        _segment(2, 1, 1.0),
        _segment(3, 2, 3.0),
    )
    assert voices.assign_scene_durations(segments, 10.0, 1.0) == (3.0, 7.0)
    assert voices.assign_scene_durations(segments, 3.0, 1.0) == (3.0, 3.0)
    assert voices.assign_scene_durations(segments, 6.0, 2.0) == (1.5, 4.5)
    with pytest.raises(VoiceError, match="objetivo"):
        voices.assign_scene_durations(segments, 0.0, 1.0)
    with pytest.raises(VoiceError, match="tempo"):
        voices.assign_scene_durations(segments, 10.0, 0.0)
    with pytest.raises(VoiceError, match="no hay segmentos"):
        voices.assign_scene_durations((), 10.0, 1.0)
    with pytest.raises(VoiceError, match="no tiene duración"):
        voices.assign_scene_durations((_segment(1, 1, 0.0),), 10.0, 1.0)


def test_timeline_words_and_errors() -> None:
    segments = (
        _segment(1, 1, 1.0, words=(WordTiming("a", 0.0, 0.5, "narrator"),)),
        _segment(2, 2, 2.0, speaker="quote", words=(WordTiming("b", 0.5, 1.5, "quote"),)),
    )
    words = voices.timeline_words(segments, (1.0, 2.0), 2.0)
    assert words[0] == WordTiming("a", 0.0, 0.25, "narrator")
    assert words[1] == WordTiming("b", 1.25, 1.75, "quote")
    with pytest.raises(VoiceError, match="tempo"):
        voices.timeline_words(segments, (1.0, 2.0), 0.0)
    with pytest.raises(VoiceError, match="no coincide"):
        voices.timeline_words(segments, (1.0,), 1.0)


def test_speaker_style_name() -> None:
    assert voices.speaker_style_name("Narrator") == "Narrator"
    assert voices.speaker_style_name("voz principal!") == "voz_principal_"
    assert voices.speaker_style_name("   ") == "Speaker"
