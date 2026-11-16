# SPDX-License-Identifier: MIT
"""End-to-end tests for multi-voice, upscaling, and preview artifacts."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

import scripts.omni as omni
from scripts.omni_media import longform as longform_utils
from scripts.omni_media import voices as voice_utils
from scripts.omni_media.words import WordTiming


def _png_bytes(size: tuple[int, int] = (32, 32)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (10, 200, 180)).save(buffer, "PNG")
    return buffer.getvalue()


def _script(tmp_path: Path) -> Path:
    path = tmp_path / "script.json"
    path.write_text(
        json.dumps(
            {
                "title": "Voces",
                "scenes": [
                    {
                        "visual_prompt": "neon city",
                        "lines": [
                            {"speaker": "narrator", "text": "Hola"},
                            {"speaker": "guest", "text": "Mundo"},
                        ],
                    },
                    {
                        "visual_prompt": "rain",
                        "speaker": "narrator",
                        "narration": "Final",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _patch_short(monkeypatch: pytest.MonkeyPatch, voices: list[str], clips: list[dict]) -> None:
    monkeypatch.setattr(omni, "ensure_ffmpeg", lambda: None)
    monkeypatch.setattr(
        omni,
        "generate_image",
        lambda prompt, dest, **kwargs: (
            dest.write_bytes(_png_bytes()),
            omni.ImageResult(dest, "placeholder"),
        )[1],
    )
    monkeypatch.setattr(
        omni,
        "tts_narrate_with_timings",
        lambda text, dest, voice, **kwargs: (
            voices.append(voice),
            dest.write_bytes(b"voice"),
            omni.NarrationResult(
                dest,
                tuple(WordTiming(word, index * 0.5, (index + 1) * 0.5) for index, word in enumerate(text.split())),
                "edge-tts",
            ),
        )[2],
    )
    monkeypatch.setattr(
        omni,
        "probe_duration",
        lambda path: 15.0 if path.name == "narration.m4a" else 5.0,
    )
    monkeypatch.setattr(
        omni,
        "build_scene_clip",
        lambda image, out, duration, **kwargs: (
            clips.append(kwargs),
            out.write_bytes(b"clip"),
            out,
        )[2],
    )
    monkeypatch.setattr(
        omni,
        "concat_clips",
        lambda clips, out, **kwargs: (out.write_bytes(b"video"), out)[1],
    )
    monkeypatch.setattr(
        omni,
        "concat_audio_tracks",
        lambda tracks, out, **kwargs: (out.write_bytes(b"audio"), out)[1],
    )
    monkeypatch.setattr(
        omni,
        "mix_audio",
        lambda *args, **kwargs: (args[2].write_bytes(b"audio"), args[2])[1],
    )
    monkeypatch.setattr(
        omni,
        "mux_video",
        lambda video, audio, out, subs, **kwargs: (out.write_bytes(b"final"), out)[1],
    )


def test_multivoice_short_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    voices: list[str] = []
    clips: list[dict] = []
    _patch_short(monkeypatch, voices, clips)
    config = omni.OmniConfig(
        topic="voces",
        output_root=tmp_path,
        duration=10,
        scene_count=2,
        script_path=_script(tmp_path),
        voice="base-voice",
        voice_map=voice_utils.parse_voice_specs(["guest=es-AR-GuestNeural"]),
        resolution="4k",
        video_preset="slow",
        video_crf=18,
        image_source="placeholder",
        no_music=True,
        use_llm=False,
    )
    result = omni.run_pipeline(config)
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["status"] == "ok"
    assert manifest["multi_voice"] is True
    assert manifest["resolution"] == "4k"
    assert manifest["upscale"] == "none"
    assert manifest["narration_duration"] == 15.0
    assert manifest["narration_tempo"] == 1.5
    assert manifest["scene_durations"] == pytest.approx([10 / 1.5, 5 / 1.5])
    assert sum(manifest["scene_durations"]) == pytest.approx(10.0)
    assert voices == ["base-voice", "es-AR-GuestNeural", "base-voice"]
    assert [item["speaker"] for item in manifest["voice_segments"]] == [
        "narrator",
        "guest",
        "narrator",
    ]
    assert [item["start"] for item in manifest["voice_segments"]] == [0.0, 5.0, 10.0]
    assert {item["name"] for item in manifest["voices"]} == {"narrator", "guest"}
    assert [item["source"] for item in manifest["image_sources"]] == ["placeholder", "placeholder"]
    assert len(clips) == 2
    assert clips[0]["width"] == 2160
    assert clips[0]["height"] == 3840
    assert clips[0]["preset"] == "slow"
    assert clips[0]["crf"] == 18

    subtitles = Path(manifest["subtitles"])
    assert subtitles.exists()
    text = subtitles.read_text(encoding="utf-8")
    assert "PlayResX: 2160" in text
    assert "PlayResY: 3840" in text
    assert "Style: narrator" in text
    assert "Style: guest" in text
    assert (result.workdir / "assets" / "words.json").exists()
    assert (result.workdir / "script.json").exists()
    assert Path(manifest["contact_sheet"]).exists()
    assert Path(manifest["engine_log"]).read_text(encoding="utf-8").count("multi-voice") >= 1


def _plan() -> longform_utils.LongformPlan:
    return longform_utils.LongformPlan(
        topic="tema",
        title="Tema",
        chapters=(
            longform_utils.Chapter(
                index=1,
                title="Capitulo 1",
                speaker="narrator",
                shots=(
                    longform_utils.Shot(
                        index=1,
                        narration="Narración uno",
                        visual_prompt="city",
                        lines=(
                            voice_utils.VoiceLine("narrator", "Hola"),
                            voice_utils.VoiceLine("guest", "Mundo"),
                        ),
                    ),
                    longform_utils.Shot(
                        index=2,
                        narration="Narración dos",
                        visual_prompt="light",
                        speaker="narrator",
                    ),
                ),
            ),
            longform_utils.Chapter(
                index=2,
                title="Capitulo 2",
                speaker="guest",
                shots=(
                    longform_utils.Shot(
                        index=3,
                        narration="Narración tres",
                        visual_prompt="rain",
                        speaker="guest",
                    ),
                    longform_utils.Shot(
                        index=4,
                        narration="Narración cuatro",
                        visual_prompt="sun",
                        speaker="guest",
                    ),
                ),
            ),
        ),
    )


def test_multivoice_longform_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    voices: list[str] = []
    clips: list[dict] = []
    _patch_short(monkeypatch, voices, clips)
    monkeypatch.setattr(omni, "generate_longform_plan", lambda *args, **kwargs: _plan())
    monkeypatch.setattr(
        omni,
        "probe_duration",
        lambda path: (
            15.0
            if path.name == "narration.m4a" and "chapter_01" in path.as_posix()
            else 10.0
            if path.name == "narration.m4a" and "chapter_02" in path.as_posix()
            else 5.0
        ),
    )
    config = omni.OmniConfig(
        topic="tema",
        output_root=tmp_path,
        duration=30,
        longform=True,
        chapters=2,
        shots_per_chapter=2,
        chapter_duration=15,
        voice="base-voice",
        voice_map=voice_utils.parse_voice_specs(["guest=es-AR-GuestNeural"]),
        image_source="placeholder",
        no_music=True,
        use_llm=False,
    )
    result = omni.run_pipeline(config)
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["status"] == "ok"
    assert manifest["multi_voice"] is True
    assert manifest["chapter_durations"] == pytest.approx([15.5, 15.0])
    assert manifest["total_duration"] == pytest.approx(30.5)
    assert len(manifest["voice_segments"]) == 5
    assert [item["chapter"] for item in manifest["voice_segments"]] == [1, 1, 1, 2, 2]
    assert manifest["voice_segments"][3]["start"] == pytest.approx(15.5)
    assert {item["speaker"] for item in manifest["word_timings"]} == {"narrator", "guest"}
    assert manifest["word_timings"][0]["start"] == 0.0
    assert manifest["longform"]["chapters"][0]["shots"][0]["lines"] == [
        {"speaker": "narrator", "text": "Hola"},
        {"speaker": "guest", "text": "Mundo"},
    ]
    assert manifest["longform"]["chapters"][1]["speaker"] == "guest"
    assert len(clips) == 4
    assert voices.count("base-voice") == 2
    assert voices.count("es-AR-GuestNeural") == 3
    subtitles = Path(manifest["subtitles"]).read_text(encoding="utf-8")
    assert "Style: narrator" in subtitles
    assert "Style: guest" in subtitles
    assert Path(manifest["contact_sheet"]).exists()
    assert (result.workdir / "plan.json").exists()


def test_finalize_image_none_and_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        omni,
        "generate_image",
        lambda prompt, dest, **kwargs: (dest.write_bytes(_png_bytes()), omni.ImageResult(dest, "placeholder"))[1],
    )
    monkeypatch.setattr(
        omni,
        "prepare_image",
        lambda src, dest, width, height: (dest.write_bytes(_png_bytes()), dest)[1],
    )
    config = omni.OmniConfig(topic="tema", image_source="placeholder")
    generated = omni._finalize_image("prompt", tmp_path / "a.png", config, None, 1, None)
    assert generated.source == "placeholder"
    local = omni._finalize_image(
        "prompt",
        tmp_path / "b.png",
        config,
        None,
        1,
        None,
        local_source=tmp_path / "source.png",
    )
    assert local.source == "local"


def test_finalize_image_upscale_success_and_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generated: list[dict] = []

    def fake_generate(prompt, dest, **kwargs):
        generated.append(kwargs)
        dest.write_bytes(_png_bytes())
        return omni.ImageResult(dest, "placeholder")

    monkeypatch.setattr(omni, "generate_image", fake_generate)
    calls: list[dict] = []

    def upscale(src, dest, config, **kwargs):
        calls.append(kwargs)
        dest.write_bytes(_png_bytes())
        return dest

    monkeypatch.setattr(omni, "upscale_image", upscale)
    config = omni.OmniConfig(topic="tema", resolution="4k", upscale="ffmpeg")
    result = omni._finalize_image("prompt", tmp_path / "a.png", config, None, 1, None)
    assert result.source == "placeholder+upscale"
    assert result.path.name == "a_upscaled.png"
    assert calls[0]["target"].width == 2160
    assert calls[0]["target"].height == 3840
    assert generated[0]["width"] == 1080
    assert generated[0]["height"] == 1920

    def boom(src, dest, config, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(omni, "upscale_image", boom)
    auto = omni.OmniConfig(topic="tema", upscale="auto")
    assert omni._finalize_image("prompt", tmp_path / "b.png", auto, None, 1, None).source == "placeholder"
    explicit = omni.OmniConfig(topic="tema", upscale="ffmpeg")
    with pytest.raises(omni.OmniError, match="upscaling"):
        omni._finalize_image("prompt", tmp_path / "c.png", explicit, None, 1, None)


def test_base_resolution_size() -> None:
    default = omni.OmniConfig(topic="tema").base_resolution_size
    assert (default.width, default.height) == (1080, 1920)
    four_k = omni.OmniConfig(topic="tema", resolution="4k", upscale="ffmpeg")
    assert (four_k.base_resolution_size.width, four_k.base_resolution_size.height) == (1080, 1920)
    no_upscale = omni.OmniConfig(topic="tema", resolution="4k")
    assert (no_upscale.base_resolution_size.width, no_upscale.base_resolution_size.height) == (2160, 3840)
    horizontal = omni.OmniConfig(topic="tema", resolution="3840x2160", upscale="auto")
    assert (horizontal.base_resolution_size.width, horizontal.base_resolution_size.height) == (1080, 1920)


def test_is_multivoice_cases() -> None:
    plain = omni.VideoScript(
        topic="tema",
        title="Tema",
        scenes=(omni.Scene(1, "hola", "city"), omni.Scene(2, "chau", "rain")),
    )
    config = omni.OmniConfig(topic="tema")
    assert omni._is_multivoice(plain, config) is False
    assert omni._is_multivoice(plain, omni.OmniConfig(topic="tema", voices_path=Path("voices.json"))) is True
    assert (
        omni._is_multivoice(
            plain,
            omni.OmniConfig(
                topic="tema",
                voice_map=(voice_utils.VoiceSpec("guest", "voz"),),
            ),
        )
        is True
    )
    with_lines = omni.VideoScript(
        topic="tema",
        title="Tema",
        scenes=(
            omni.Scene(
                1,
                "hola",
                "city",
                lines=(voice_utils.VoiceLine("narrator", "hola"),),
            ),
        ),
    )
    assert omni._is_multivoice(with_lines, config) is True
    other_speaker = omni.VideoScript(
        topic="tema",
        title="Tema",
        scenes=(omni.Scene(1, "hola", "city", speaker="guest"),),
    )
    assert omni._is_multivoice(other_speaker, config) is True


def test_parse_script_and_longform_speakers() -> None:
    raw = json.dumps(
        {
            "scenes": [
                {
                    "visual_prompt": "city",
                    "lines": [
                        {"speaker": "narrator", "text": "Hola"},
                        {"text": "Mundo"},
                    ],
                },
                {"visual_prompt": "rain", "speaker": "guest", "narration": "Chau"},
            ]
        }
    )
    script = omni.parse_script_json(raw, "tema")
    assert script.scenes[0].narration == "Hola Mundo"
    assert script.scenes[0].lines[0].speaker == "narrator"
    assert script.scenes[1].speaker == "guest"

    for bad in (
        {"scenes": [{"visual_prompt": "x", "lines": "bad"}, {"visual_prompt": "y", "narration": "z"}]},
        {"scenes": [{"visual_prompt": "x", "lines": ["bad"]}, {"visual_prompt": "y", "narration": "z"}]},
        {
            "scenes": [
                {"visual_prompt": "x", "lines": [{"text": ""}]},
                {"visual_prompt": "y", "narration": "z"},
            ]
        },
    ):
        with pytest.raises(omni.OmniError):
            omni.parse_script_json(json.dumps(bad), "tema")

    plan = longform_utils.parse_longform_json(
        json.dumps(
            {
                "chapters": [
                    {
                        "speaker": "guest",
                        "shots": [
                            {"visual_prompt": "x", "lines": [{"text": "Hola"}]},
                            {"visual_prompt": "y", "narration": "Chau"},
                        ],
                    }
                ]
            }
        ),
        "tema",
    )
    assert plan.chapters[0].speaker == "guest"
    assert plan.chapters[0].shots[0].speaker == "guest"
    assert plan.chapters[0].shots[0].lines[0].speaker == "guest"
    assert plan.chapters[0].shots[1].speaker == "guest"

    inherited = longform_utils.parse_longform_json(
        json.dumps(
            {
                "chapters": [
                    {
                        "speaker": "narrator",
                        "shots": [
                            {
                                "speaker": "guest",
                                "visual_prompt": "x",
                                "lines": [{"text": "Hola"}],
                            }
                        ],
                    }
                ]
            }
        ),
        "tema",
    )
    assert inherited.chapters[0].shots[0].speaker == "guest"
    assert inherited.chapters[0].shots[0].lines[0].speaker == "guest"

    with pytest.raises(longform_utils.LongformError):
        longform_utils.parse_longform_json(
            json.dumps({"chapters": [{"shots": [{"visual_prompt": "x", "lines": "bad"}]}]}),
            "tema",
        )


def test_cli_v16_flags(tmp_path: Path) -> None:
    parser = omni.build_parser()
    args = parser.parse_args(
        [
            "--script",
            str(tmp_path / "script.json"),
            "--voice-map",
            "narrator=uno",
            "--voice-map",
            "guest=dos",
            "--default-speaker",
            "narrator",
            "--resolution",
            "4k",
            "--upscale",
            "auto",
            "--upscale-model",
            "model",
            "--upscale-sharpen",
            "0.5",
            "--crf",
            "18",
            "--preset",
            "slow",
            "--no-llm",
            "--image-source",
            "placeholder",
        ]
    )
    config = omni.config_from_args(args)
    assert config.script_path == tmp_path / "script.json"
    assert [spec.voice for spec in config.voice_map] == ["uno", "dos"]
    assert config.resolution == "4k"
    assert config.upscale == "auto"
    assert config.upscale_model == "model"
    assert config.upscale_sharpen == 0.5
    assert config.video_crf == 18
    assert config.video_preset == "slow"
