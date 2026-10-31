# SPDX-License-Identifier: MIT
"""Tests for the advanced Dxrk Omni media backends."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import types
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

import scripts.omni as omni
from scripts.omni_media import images as image_backends
from scripts.omni_media import longform as longform_utils
from scripts.omni_media import music as music_backends
from scripts.omni_media import words as word_utils


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 32), (10, 200, 180)).save(buffer, "PNG")
    return buffer.getvalue()


def _fake_runner(commands: list[list[str]]):
    def run(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        commands.append(list(cmd))
        target = Path(cmd[-1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"artifact")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return run


# ---------------------------------------------------------------------------
# Local image backends
# ---------------------------------------------------------------------------


def test_comfy_workflow_contains_prompt_and_dimensions() -> None:
    workflow = image_backends.build_comfy_workflow(
        prompt="neon city",
        negative_prompt="blurry",
        seed=7,
        width=832,
        height=1472,
        checkpoint="model.safetensors",
    )
    assert workflow["6"]["inputs"]["text"] == "neon city"
    assert workflow["7"]["inputs"]["text"] == "blurry"
    assert workflow["3"]["inputs"]["seed"] == 7
    assert workflow["5"]["inputs"]["width"] == 832
    assert workflow["5"]["inputs"]["height"] == 1472
    assert workflow["4"]["inputs"]["ckpt_name"] == "model.safetensors"


def test_comfy_workflow_template_replaces_typed_placeholders() -> None:
    template = {
        "1": {
            "class_type": "Test",
            "inputs": {
                "text": "{{PROMPT}}",
                "seed": "{{SEED}}",
                "size": ["{{WIDTH}}", "{{HEIGHT}}"],
            },
        }
    }
    rendered = image_backends.apply_workflow_template(
        template,
        {"PROMPT": "hola", "SEED": 9, "WIDTH": 1080, "HEIGHT": 1920},
    )
    assert rendered["1"]["inputs"]["seed"] == 9
    assert rendered["1"]["inputs"]["size"] == [1080, 1920]
    assert template["1"]["inputs"]["text"] == "{{PROMPT}}"


def test_comfy_client_polls_history_and_downloads(tmp_path: Path) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/prompt":
            payload = json.loads(request.content)
            assert payload["prompt"]["6"]["inputs"]["text"] == "neon"
            return httpx.Response(200, json={"prompt_id": "pid", "number": 1, "node_errors": {}})
        if request.url.path == "/history/pid":
            return httpx.Response(
                200,
                json={
                    "pid": {
                        "outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}},
                        "status": {"completed": True},
                    }
                },
            )
        if request.url.path == "/view":
            assert request.url.params["filename"] == "out.png"
            return httpx.Response(200, content=_png_bytes())
        raise AssertionError(f"unexpected request: {request.url}")

    client = image_backends.ComfyUIClient(
        base_url="http://comfy.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        use_websocket=False,
        sleep=lambda _: None,
    )
    result = client.generate("neon", tmp_path / "x.jpg", seed=1)
    assert result.source == "comfyui"
    assert result.path.exists()
    assert "/prompt" in requests
    assert "/history/pid" in requests
    assert "/view" in requests


def test_comfy_client_uses_websocket_messages(tmp_path: Path) -> None:
    messages = [
        json.dumps({"type": "executing", "data": {"node": 9, "prompt_id": "pid"}}),
        json.dumps(
            {
                "type": "executed",
                "data": {
                    "node": 9,
                    "prompt_id": "pid",
                    "output": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]},
                },
            }
        ),
        json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "pid"}}),
    ]

    class FakeWebSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            return iter(messages)

    def ws_connect(url: str, **kwargs):
        assert "clientId=" in url
        return FakeWebSocket()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "pid", "node_errors": {}})
        if request.url.path == "/view":
            return httpx.Response(200, content=_png_bytes())
        raise AssertionError(f"unexpected request: {request.url}")

    client = image_backends.ComfyUIClient(
        base_url="http://comfy.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        use_websocket=True,
        ws_connect=ws_connect,
    )
    result = client.generate("neon", tmp_path / "x.jpg", seed=1)
    assert result.source == "comfyui"
    assert result.path.exists()


def test_comfy_client_rejects_node_errors(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"prompt_id": "pid", "node_errors": {"3": "bad"}})

    client = image_backends.ComfyUIClient(
        base_url="http://comfy.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        use_websocket=False,
    )
    with pytest.raises(image_backends.ImageBackendError, match="node_errors"):
        client.generate("neon", tmp_path / "x.jpg", seed=1)


def test_sdwebui_client_decodes_base64_image(tmp_path: Path) -> None:
    encoded = base64.b64encode(_png_bytes()).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sdapi/v1/txt2img"
        payload = json.loads(request.content)
        assert payload["prompt"] == "neon"
        assert payload["negative_prompt"] == "blurry"
        assert payload["seed"] == 11
        assert payload["width"] == 512
        assert payload["height"] == 768
        return httpx.Response(200, json={"images": [encoded]})

    client = image_backends.SDWebUIClient(
        base_url="http://sd.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.generate(
        "neon",
        tmp_path / "x.jpg",
        seed=11,
        negative_prompt="blurry",
        width=512,
        height=768,
    )
    assert result.source == "sdwebui"
    assert result.path.exists()


def test_sdwebui_client_rejects_empty_images(tmp_path: Path) -> None:
    client = image_backends.SDWebUIClient(
        base_url="http://sd.test",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))),
    )
    with pytest.raises(image_backends.ImageBackendError, match="imagen"):
        client.generate("neon", tmp_path / "x.jpg", seed=1)


def test_generate_image_auto_prefers_local_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeComfy:
        def __init__(self, **kwargs) -> None:
            pass

        def generate(self, prompt: str, dest: Path, **kwargs) -> omni.ImageResult:
            dest.write_bytes(b"image")
            return omni.ImageResult(dest, "comfyui")

    monkeypatch.setattr(omni, "ComfyUIClient", FakeComfy)
    result = omni.generate_image("prompt", tmp_path / "x.jpg", source="auto", seed=1)
    assert result.source == "comfyui"
    assert result.path.exists()


def test_generate_image_auto_falls_back_to_placeholder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def __init__(self, **kwargs) -> None:
            pass

        def generate(self, prompt: str, dest: Path, **kwargs) -> omni.ImageResult:
            raise RuntimeError("offline")

    monkeypatch.setattr(omni, "ComfyUIClient", Broken)
    monkeypatch.setattr(omni, "SDWebUIClient", Broken)
    result = omni.generate_image("prompt", tmp_path / "x.jpg", source="auto", seed=1)
    assert result.source == "placeholder"
    assert "offline" in result.error
    assert result.path.exists()


# ---------------------------------------------------------------------------
# Word-level subtitles
# ---------------------------------------------------------------------------


def test_timings_from_edge_events() -> None:
    words = word_utils.timings_from_edge_events(
        [
            {"type": "WordBoundary", "text": "Hola", "offset": 0, "duration": 5_000_000},
            {"type": "WordBoundary", "text": "mundo", "offset": 6_000_000, "duration": 4_000_000},
        ]
    )
    assert words[0] == word_utils.WordTiming("Hola", 0.0, 0.5)
    assert words[1].start == 0.6
    assert words[1].end == 1.0


def test_proportional_timings_cover_the_audio() -> None:
    words = word_utils.proportional_timings("Hola mundo", 2.0)
    assert [word.text for word in words] == ["Hola", "mundo"]
    assert words[0].start == 0.0
    assert words[-1].end == pytest.approx(2.0)
    assert words[0].end <= words[1].start


def test_scale_and_offset_timings() -> None:
    words = (word_utils.WordTiming("Hola", 1.0, 2.0),)
    scaled = word_utils.scale_timings(words, 0.5)
    assert scaled[0].start == 0.5
    assert scaled[0].end == 1.0
    shifted = word_utils.offset_timings(scaled, 10.0)
    assert shifted[0].start == 10.5


def test_group_word_timings_respects_punctuation_and_length() -> None:
    words = (
        word_utils.WordTiming("Hola", 0.0, 0.2),
        word_utils.WordTiming("mundo.", 0.2, 0.4),
        word_utils.WordTiming("Esto", 0.5, 0.7),
        word_utils.WordTiming("es", 0.7, 0.8),
        word_utils.WordTiming("una", 0.8, 1.0),
        word_utils.WordTiming("prueba", 1.0, 1.4),
    )
    groups = word_utils.group_word_timings(words, max_words=3)
    assert [" ".join(word.text for word in group) for group in groups] == [
        "Hola mundo.",
        "Esto es una",
        "prueba",
    ]


def test_build_word_ass_emits_karaoke_timing() -> None:
    words = (
        word_utils.WordTiming("Hola", 0.0, 0.4),
        word_utils.WordTiming("mundo.", 0.5, 1.0),
    )
    ass = word_utils.build_word_ass(words, max_words=2)
    assert "Dialogue: 0,0:00:00.00,0:00:01.00" in ass
    assert r"{\kf50}Hola" in ass
    assert r"{\kf50}mundo." in ass
    assert "{\\fad(120,120)}" in ass


def test_build_word_ass_rejects_empty() -> None:
    with pytest.raises(ValueError):
        word_utils.build_word_ass([])


def test_transcribe_words_uses_injected_transcriber(tmp_path: Path) -> None:
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"audio")

    def transcriber(path: Path, **kwargs):
        assert path == audio
        assert kwargs["model_size"] == "tiny"
        return [word_utils.WordTiming("Hola", 0.0, 0.2)]

    words = word_utils.transcribe_words(audio, model_size="tiny", transcriber=transcriber)
    assert words == (word_utils.WordTiming("Hola", 0.0, 0.2),)


def test_tts_narrate_with_timings_from_edge_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCommunicate:
        def __init__(self, text: str, voice: str) -> None:
            self.text = text
            self.voice = voice

        async def stream(self):
            yield {"type": "audio", "data": b"edge-audio"}
            yield {"type": "WordBoundary", "text": "Hola", "offset": 0, "duration": 10_000_000}

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=FakeCommunicate))
    dest = tmp_path / "voice.mp3"
    result = omni.tts_narrate_with_timings("Hola", dest, "voz")
    assert dest.read_bytes() == b"edge-audio"
    assert result.source == "edge-tts"
    assert result.words == (word_utils.WordTiming("Hola", 0.0, 1.0),)


def test_tts_narrate_with_timings_falls_back_to_proportional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCommunicate:
        def __init__(self, text: str, voice: str) -> None:
            pass

        async def stream(self):
            yield {"type": "audio", "data": b"edge-audio"}

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=FakeCommunicate))
    monkeypatch.setattr(omni, "probe_duration", lambda path: 2.0)
    result = omni.tts_narrate_with_timings("Hola mundo", tmp_path / "voice.mp3", "voz")
    assert result.source == "proportional"
    assert len(result.words) == 2


def test_tts_narrate_with_timings_uses_whisper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCommunicate:
        def __init__(self, text: str, voice: str) -> None:
            pass

        async def stream(self):
            yield {"type": "audio", "data": b"edge-audio"}

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=FakeCommunicate))
    monkeypatch.setattr(
        omni,
        "transcribe_words",
        lambda audio, **kwargs: (word_utils.WordTiming("Hola", 0.0, 0.5),),
    )
    result = omni.tts_narrate_with_timings("Hola", tmp_path / "voice.mp3", "voz", whisper=True)
    assert result.source == "whisper"


def test_run_pipeline_persists_word_timings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_success_pipeline(monkeypatch)
    config = omni.OmniConfig(
        topic="tema",
        output_root=tmp_path,
        duration=10,
        scene_count=2,
        image_source="placeholder",
        no_music=True,
        use_llm=False,
    )
    result = omni.run_pipeline(config)
    manifest = json.loads(result.manifest.read_text())
    assert manifest["word_timings"][0]["text"] == "Hola"
    assert (result.workdir / "assets" / "words.json").exists()
    assert (result.workdir / "assets" / "subtitles.ass").read_text() == "subs"


# ---------------------------------------------------------------------------
# Long-form and long music
# ---------------------------------------------------------------------------


def test_fallback_longform_plan_shapes() -> None:
    plan = longform_utils.fallback_longform_plan("IA en Tokio", chapters=3, shots_per_chapter=2)
    assert len(plan.chapters) == 3
    assert all(len(chapter.shots) == 2 for chapter in plan.chapters)
    assert plan.total_shots == 6
    assert plan.title == "IA en Tokio"
    assert all(shot.visual_prompt for shot in plan.shots)


def test_parse_longform_json_valid_and_fenced() -> None:
    raw = json.dumps(
        {
            "title": "Pelicula",
            "chapters": [
                {
                    "title": "Capitulo 1",
                    "shots": [
                        {"narration": "Uno.", "visual_prompt": "city"},
                        {"narration": "Dos.", "visual_prompt": "light"},
                    ],
                }
            ],
        }
    )
    plan = longform_utils.parse_longform_json(raw, "tema")
    assert plan.title == "Pelicula"
    assert len(plan.chapters) == 1
    assert len(plan.chapters[0].shots) == 2
    assert longform_utils.parse_longform_json(f"```json\n{raw}\n```", "tema").title == "Pelicula"


@pytest.mark.parametrize(
    "raw",
    [
        "no json",
        "{}",
        '{"chapters": []}',
        '{"chapters": [{"shots": []}]}',
        '{"chapters": [{"shots": [{"narration": "", "visual_prompt": "x"}]}]}',
    ],
)
def test_parse_longform_json_rejects_bad_payloads(raw: str) -> None:
    with pytest.raises(longform_utils.LongformError):
        longform_utils.parse_longform_json(raw, "tema")


def test_generate_longform_plan_uses_llm_and_falls_back() -> None:
    class GoodLlm:
        def complete(self, prompt: str) -> str:
            return json.dumps(
                {
                    "title": "Tema",
                    "chapters": [
                        {
                            "title": "Uno",
                            "shots": [{"narration": "A", "visual_prompt": "B"}],
                        }
                    ],
                }
            )

    class BadLlm:
        def complete(self, prompt: str) -> str:
            raise RuntimeError("offline")

    assert longform_utils.generate_longform_plan("tema", 1, 1, 60, GoodLlm()).title == "Tema"
    fallback = longform_utils.generate_longform_plan("tema", 2, 2, 60, BadLlm())
    assert len(fallback.chapters) == 2


def test_musicgen_generator_chunks_and_concats(tmp_path: Path) -> None:
    generated: list[tuple[str, float, Path]] = []
    commands: list[list[str]] = []

    def generator(prompt: str, duration: float, path: Path) -> None:
        generated.append((prompt, duration, path))
        path.write_bytes(b"wav")

    backend = music_backends.MusicGenGenerator(
        chunk_seconds=30,
        generator=generator,
        runner=_fake_runner(commands),
    )
    out = backend.generate(tmp_path / "music.wav", 65, "cinematic")
    assert out.exists()
    assert [duration for _, duration, _ in generated] == [30, 30, 5]
    assert any("acrossfade" in part for part in commands[0])


def test_stable_audio_generator_chunks_and_concats(tmp_path: Path) -> None:
    generated: list[float] = []

    def generator(prompt: str, duration: float, path: Path) -> None:
        generated.append(duration)
        path.write_bytes(b"wav")

    backend = music_backends.StableAudioGenerator(
        chunk_seconds=20,
        generator=generator,
        runner=_fake_runner([]),
    )
    out = backend.generate(tmp_path / "music.wav", 45, "ambient")
    assert out.exists()
    assert generated == [20, 20, 5]


def test_build_music_generator_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="music source"):
        music_backends.build_music_generator("unknown")


def test_build_music_generator_returns_requested_backend() -> None:
    assert isinstance(music_backends.build_music_generator("musicgen"), music_backends.MusicGenGenerator)
    assert isinstance(
        music_backends.build_music_generator("stable-audio"),
        music_backends.StableAudioGenerator,
    )


def test_concat_audio_tracks_writes_absolute_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    first = Path("chapter_01.m4a")
    second = Path("chapter_02.m4a")
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    out = music_backends.concat_audio_tracks([first, second], tmp_path / "narration.m4a", runner=_fake_runner([]))
    listing = (tmp_path / "narration.txt").read_text()
    assert (tmp_path / "chapter_01.m4a").resolve().as_posix() in listing
    assert (tmp_path / "chapter_02.m4a").resolve().as_posix() in listing
    assert out.exists()


def test_run_longform_pipeline_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_longform_pipeline(monkeypatch)
    config = omni.OmniConfig(
        topic="tema",
        output_root=tmp_path,
        longform=True,
        chapters=2,
        shots_per_chapter=2,
        chapter_duration=15,
        image_source="placeholder",
        no_music=True,
        use_llm=False,
    )
    result = omni.run_pipeline(config)
    manifest = json.loads(result.manifest.read_text())
    assert manifest["status"] == "ok"
    assert manifest["longform"]["chapters"][0]["title"]
    assert manifest["chapter_durations"] == [15.0, 15.0]
    assert [word["start"] for word in manifest["word_timings"]] == [0.0, 15.0]
    assert (result.workdir / "plan.json").exists()


def test_config_from_args_longform_defaults(tmp_path: Path) -> None:
    args = argparse_namespace(
        longform=True,
        chapters=2,
        shots_per_chapter=2,
        chapter_duration=20,
        image_source="placeholder",
    )
    config = omni.config_from_args(args)
    assert config.longform is True
    assert config.chapters == 2
    assert config.shots_per_chapter == 2
    assert config.chapter_duration == 20


def test_config_rejects_bad_longform_values() -> None:
    with pytest.raises(omni.OmniError):
        omni.OmniConfig(topic="x", longform=True, chapters=1)
    with pytest.raises(omni.OmniError):
        omni.OmniConfig(topic="x", longform=True, chapter_duration=5)
    with pytest.raises(omni.OmniError):
        omni.OmniConfig(topic="x", longform=True, shots_per_chapter=0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def argparse_namespace(**overrides):
    import argparse

    values = {
        "topic": "tema",
        "output_dir": "outputs",
        "duration": 30,
        "scenes": 5,
        "voice": "voz",
        "image_source": "auto",
        "images_dir": None,
        "music": None,
        "no_music": False,
        "no_subtitles": False,
        "seed": 1,
        "llm_base_url": "http://llm",
        "llm_model": "model",
        "llm_api_key": "key",
        "no_llm": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _patch_success_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(omni, "ensure_ffmpeg", lambda: None)
    monkeypatch.setattr(omni, "generate_script", lambda *args, **kwargs: omni.fallback_script("tema", 2))
    monkeypatch.setattr(
        omni,
        "generate_image",
        lambda prompt, dest, **kwargs: (dest.write_bytes(b"image"), omni.ImageResult(dest, "placeholder"))[1],
    )
    monkeypatch.setattr(
        omni,
        "build_scene_clip",
        lambda image, out, duration, **kwargs: (out.write_bytes(b"clip"), out)[1],
    )
    monkeypatch.setattr(
        omni,
        "tts_narrate_with_timings",
        lambda text, dest, voice, **kwargs: (
            dest.write_bytes(b"voice"),
            omni.NarrationResult(
                dest,
                (word_utils.WordTiming("Hola", 0.0, 0.5),),
                "edge-tts",
            ),
        )[1],
    )
    monkeypatch.setattr(omni, "probe_duration", lambda path: 10.0)
    monkeypatch.setattr(
        omni,
        "mix_audio",
        lambda *args, **kwargs: (args[2].write_bytes(b"audio"), args[2])[1],
    )
    monkeypatch.setattr(
        omni,
        "concat_clips",
        lambda clips, out, **kwargs: (out.write_bytes(b"video"), out)[1],
    )
    monkeypatch.setattr(
        omni,
        "write_word_ass",
        lambda path, words, **kwargs: (path.write_text("subs"), path)[1],
    )
    monkeypatch.setattr(
        omni,
        "mux_video",
        lambda video, audio, out, subs, **kwargs: (out.write_bytes(b"final"), out)[1],
    )


def _patch_longform_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = longform_utils.fallback_longform_plan("tema", 2, 2)
    monkeypatch.setattr(omni, "ensure_ffmpeg", lambda: None)
    monkeypatch.setattr(omni, "generate_longform_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr(
        omni,
        "generate_image",
        lambda prompt, dest, **kwargs: (dest.write_bytes(b"image"), omni.ImageResult(dest, "placeholder"))[1],
    )
    monkeypatch.setattr(
        omni,
        "build_scene_clip",
        lambda image, out, duration, **kwargs: (out.write_bytes(b"clip"), out)[1],
    )
    monkeypatch.setattr(
        omni,
        "tts_narrate_with_timings",
        lambda text, dest, voice, **kwargs: (
            dest.write_bytes(b"voice"),
            omni.NarrationResult(dest, (word_utils.WordTiming("Hola", 0.0, 0.5),), "edge-tts"),
        )[1],
    )
    monkeypatch.setattr(omni, "probe_duration", lambda path: 10.0)
    monkeypatch.setattr(
        omni,
        "concat_clips",
        lambda clips, out, **kwargs: (out.write_bytes(b"video"), out)[1],
    )
    monkeypatch.setattr(
        omni,
        "mix_audio",
        lambda *args, **kwargs: (args[2].write_bytes(b"audio"), args[2])[1],
    )
    monkeypatch.setattr(
        omni,
        "concat_audio_tracks",
        lambda tracks, out, **kwargs: (out.write_bytes(b"audio"), out)[1],
    )
    monkeypatch.setattr(
        omni,
        "write_word_ass",
        lambda path, words, **kwargs: (path.write_text("subs"), path)[1],
    )
    monkeypatch.setattr(
        omni,
        "mux_video",
        lambda video, audio, out, subs, **kwargs: (out.write_bytes(b"final"), out)[1],
    )
