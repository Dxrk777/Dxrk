# SPDX-License-Identifier: MIT
"""Tests for the standalone Dxrk Omni short-video pipeline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import types
from datetime import datetime
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

import scripts.omni as omni


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 32), (10, 200, 180)).save(buffer, "PNG")
    return buffer.getvalue()


def _fake_runner(commands: list[list[str]]):
    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        target = Path(cmd[-1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"artifact")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return run


# ---------------------------------------------------------------------------
# Config and script
# ---------------------------------------------------------------------------


def test_config_rejects_invalid_values(tmp_path: Path) -> None:
    with pytest.raises(omni.OmniError):
        omni.OmniConfig(topic="  ")
    with pytest.raises(omni.OmniError):
        omni.OmniConfig(topic="x", duration=4)
    with pytest.raises(omni.OmniError):
        omni.OmniConfig(topic="x", scene_count=1)
    with pytest.raises(omni.OmniError):
        omni.OmniConfig(topic="x", image_source="unknown")
    with pytest.raises(omni.OmniError):
        omni.OmniConfig(topic="x", image_source="local", images_dir=None)
    config = omni.OmniConfig(topic="  hola  ", images_dir=tmp_path)
    assert config.topic == "hola"


def test_fallback_script_shapes() -> None:
    for count in (2, 5, 8, 12):
        script = omni.fallback_script("IA en Tokio", count)
        assert len(script.scenes) == count
        assert script.title == "IA en Tokio"
        assert script.narration
        assert all(scene.visual_prompt for scene in script.scenes)
        assert [scene.index for scene in script.scenes] == list(range(1, count + 1))
    assert omni.fallback_script("  ", 2).topic == "el futuro"


def test_build_script_prompt_contains_constraints() -> None:
    prompt = omni.build_script_prompt("Tokio", 5, 30)
    assert "exactamente 5" in prompt
    assert "75 palabras" in prompt
    assert "SOLO JSON" in prompt


def test_parse_script_json_valid_and_fenced() -> None:
    raw = json.dumps(
        {
            "title": "Tokio",
            "scenes": [
                {"narration": "Uno.", "visual_prompt": "city"},
                {"narration": "Dos.", "visual_prompt": "light"},
            ],
        }
    )
    script = omni.parse_script_json(raw, "tema")
    assert script.title == "Tokio"
    assert len(script.scenes) == 2
    fenced = omni.parse_script_json(f"```json\n{raw}\n```", "tema")
    assert fenced.scenes[0].narration == "Uno."


@pytest.mark.parametrize(
    "raw",
    [
        "no json",
        "{}",
        '{"scenes": []}',
        '{"scenes": ["bad"]}',
        '{"scenes": [{"narration": "", "visual_prompt": "x"}, {"narration": "y", "visual_prompt": "z"}]}',
        '{"scenes": [{"narration": "x", "visual_prompt": ""}, {"narration": "y", "visual_prompt": "z"}]}',
    ],
)
def test_parse_script_json_rejects_bad_payloads(raw: str) -> None:
    with pytest.raises(omni.OmniError):
        omni.parse_script_json(raw, "tema")


def test_generate_script_uses_llm_and_falls_back() -> None:
    class GoodLlm:
        def complete(self, prompt: str) -> str:
            assert "tema" in prompt
            return json.dumps(
                {
                    "title": "Tema",
                    "scenes": [
                        {"narration": "A", "visual_prompt": "B"},
                        {"narration": "C", "visual_prompt": "D"},
                    ],
                }
            )

    class BadLlm:
        def complete(self, prompt: str) -> str:
            raise RuntimeError("offline")

    assert omni.generate_script("tema", 2, 30, GoodLlm()).title == "Tema"
    fallback = omni.generate_script("tema", 2, 30, BadLlm())
    assert len(fallback.scenes) == 2


def test_openai_compatible_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer key"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hola"}}]},
        )

    client = omni.OpenAICompatibleClient(
        base_url="http://llm.test/v1",
        model="model",
        api_key="key",
        transport=httpx.MockTransport(handler),
    )
    assert client.complete("prompt") == "hola"


# ---------------------------------------------------------------------------
# Paths and images
# ---------------------------------------------------------------------------


def test_slugify_and_unique_workdir(tmp_path: Path) -> None:
    assert omni.slugify("El futuro de la IA en Tokio!") == "el-futuro-de-la-ia-en-tokio"
    assert omni.slugify("!!!") == "short-video"
    now = datetime(2026, 1, 2, 3, 4, 5)
    first = omni.unique_workdir(tmp_path, "tema", now=now)
    second = omni.unique_workdir(tmp_path, "tema", now=now)
    assert first.name == "tema-20260102-030405"
    assert second.name == "tema-20260102-030405-01"


def test_build_pollinations_url() -> None:
    url = omni.build_pollinations_url("neon city", 7)
    assert "image.pollinations.ai" in url
    assert "neon%20city" in url
    assert "seed=7" in url


def test_placeholder_and_prepare_image(tmp_path: Path) -> None:
    placeholder = omni.placeholder_image("un tema de prueba", tmp_path / "placeholder.jpg", seed=1)
    with Image.open(placeholder) as image:
        assert image.size == (omni.VIDEO_WIDTH, omni.VIDEO_HEIGHT)

    source = tmp_path / "source.png"
    Image.new("RGB", (200, 100), (1, 2, 3)).save(source)
    prepared = omni.prepare_image(source, tmp_path / "prepared.jpg")
    with Image.open(prepared) as image:
        assert image.size == (omni.VIDEO_WIDTH, omni.VIDEO_HEIGHT)


def test_prepare_image_rejects_missing(tmp_path: Path) -> None:
    with pytest.raises(omni.OmniError):
        omni.prepare_image(tmp_path / "missing.png", tmp_path / "out.jpg")


def test_generate_image_placeholder(tmp_path: Path) -> None:
    result = omni.generate_image("prompt", tmp_path / "x.jpg", source="placeholder", seed=1)
    assert result.source == "placeholder"
    assert result.path.exists()


def test_generate_image_pollinations_success(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=_png_bytes()))
    with httpx.Client(transport=transport) as client:
        result = omni.generate_image("prompt", tmp_path / "x.jpg", source="pollinations", seed=1, client=client)
    assert result.source == "pollinations"
    assert result.path.exists()


def test_generate_image_pollinations_falls_back(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    with httpx.Client(transport=transport) as client:
        result = omni.generate_image("prompt", tmp_path / "x.jpg", source="pollinations", seed=1, client=client)
    assert result.source == "placeholder"
    assert result.error
    assert result.path.exists()


def test_generate_image_rejects_unknown_source(tmp_path: Path) -> None:
    with pytest.raises(omni.OmniError):
        omni.generate_image("prompt", tmp_path / "x.jpg", source="unknown", seed=1)


def test_list_local_images(tmp_path: Path) -> None:
    Image.new("RGB", (8, 8)).save(tmp_path / "b.png")
    Image.new("RGB", (8, 8)).save(tmp_path / "a.jpg")
    (tmp_path / "ignore.txt").write_text("x")
    assert [path.name for path in omni.list_local_images(tmp_path)] == ["a.jpg", "b.png"]
    with pytest.raises(omni.OmniError):
        omni.list_local_images(None)
    with pytest.raises(omni.OmniError):
        omni.list_local_images(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(omni.OmniError):
        omni.list_local_images(empty)


# ---------------------------------------------------------------------------
# Commands and media
# ---------------------------------------------------------------------------


def test_run_command_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def ok(cmd, check, capture_output, text):
        return subprocess.CompletedProcess(cmd, 0, "out", "")

    monkeypatch.setattr(omni.subprocess, "run", ok)
    assert omni.run_capture(["ffprobe"]) == "out"

    def fail(cmd, check, capture_output, text):
        raise subprocess.CalledProcessError(1, cmd, stderr="boom")

    monkeypatch.setattr(omni.subprocess, "run", fail)
    with pytest.raises(omni.OmniError, match="boom"):
        omni.run_command(["ffmpeg"])

    def missing(cmd, check, capture_output, text):
        raise FileNotFoundError

    monkeypatch.setattr(omni.subprocess, "run", missing)
    with pytest.raises(omni.OmniError, match="ffmpeg"):
        omni.run_command(["ffmpeg"])


def test_ensure_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(omni.shutil, "which", lambda name: None)
    with pytest.raises(omni.OmniError, match="ffmpeg"):
        omni.ensure_ffmpeg()
    monkeypatch.setattr(omni.shutil, "which", lambda name: f"/usr/bin/{name}")
    omni.ensure_ffmpeg()


def test_probe_duration() -> None:
    assert omni.probe_duration(Path("x"), runner=lambda cmd: "12.5\n") == 12.5
    with pytest.raises(omni.OmniError):
        omni.probe_duration(Path("x"), runner=lambda cmd: "nope")


def test_tts_narrate_with_injected_callable(tmp_path: Path) -> None:
    dest = tmp_path / "voice.mp3"
    omni.tts_narrate("hola", dest, "voz", tts=lambda text, path, voice: path.write_bytes(b"audio"))
    assert dest.read_bytes() == b"audio"
    with pytest.raises(omni.OmniError):
        omni.tts_narrate("hola", tmp_path / "empty.mp3", "voz", tts=lambda text, path, voice: path.write_bytes(b""))


def test_tts_narrate_with_edge_tts_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCommunicate:
        def __init__(self, text: str, voice: str) -> None:
            self.text = text
            self.voice = voice

        async def save(self, path: str) -> None:
            Path(path).write_bytes(b"edge-audio")

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=FakeCommunicate))
    dest = tmp_path / "edge.mp3"
    omni.tts_narrate("hola", dest, "voz")
    assert dest.read_bytes() == b"edge-audio"


def test_generate_and_prepare_music(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    runner = _fake_runner(commands)
    dest = omni.generate_music(tmp_path / "music.wav", 10, runner=runner)
    assert dest.exists()
    assert any("sine=frequency=110" in part for part in commands[0])
    source = tmp_path / "source.mp3"
    source.write_bytes(b"audio")
    prepared = omni.prepare_music(source, tmp_path / "prepared.wav", 10, runner=runner)
    assert prepared.exists()
    with pytest.raises(omni.OmniError):
        omni.prepare_music(tmp_path / "missing.mp3", tmp_path / "x.wav", 10, runner=runner)


def test_build_scene_clip_command(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    out = omni.build_scene_clip(
        tmp_path / "in.jpg",
        tmp_path / "out.mp4",
        3.0,
        runner=_fake_runner(commands),
    )
    assert out.exists()
    command = commands[0]
    assert "-pix_fmt" in command
    assert any("zoompan" in part for part in command)
    assert any("fade=t=in" in part for part in command)


def test_concat_clips_escapes_quotes(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    clip = tmp_path / "a'b.mp4"
    clip.write_bytes(b"x")
    out = omni.concat_clips([clip], tmp_path / "out.mp4", runner=_fake_runner(commands))
    assert out.exists()
    listing = (tmp_path / "out.txt").read_text()
    assert "'\\''" in listing
    with pytest.raises(omni.OmniError):
        omni.concat_clips([], tmp_path / "none.mp4", runner=_fake_runner(commands))


def test_mix_audio_with_and_without_music(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    runner = _fake_runner(commands)
    narration = tmp_path / "voice.mp3"
    narration.write_bytes(b"x")
    music = tmp_path / "music.wav"
    music.write_bytes(b"x")
    omni.mix_audio(narration, music, tmp_path / "mix.m4a", 10, 12.0, runner=runner)
    assert any("atempo=1.2000" in part for part in commands[0])
    assert "-filter_complex" in commands[0]
    omni.mix_audio(narration, None, tmp_path / "plain.m4a", 10, 8.0, runner=runner)
    assert "-af" in commands[1]
    with pytest.raises(omni.OmniError):
        omni.mix_audio(narration, None, tmp_path / "bad.m4a", 10, 0, runner=runner)


def test_mux_video_with_and_without_subtitles(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    runner = _fake_runner(commands)
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.m4a"
    video.write_bytes(b"x")
    audio.write_bytes(b"x")
    subs = tmp_path / "subs.ass"
    subs.write_text("x")
    omni.mux_video(video, audio, tmp_path / "with.mp4", subs, runner=runner)
    assert any("ass=" in part for part in commands[0])
    assert "-pix_fmt" in commands[0]
    omni.mux_video(video, audio, tmp_path / "without.mp4", None, runner=runner)
    assert "-c:v" in commands[1] and "copy" in commands[1]


# ---------------------------------------------------------------------------
# Subtitles
# ---------------------------------------------------------------------------


def test_caption_chunks_and_ass_time() -> None:
    chunks = omni.caption_chunks("Hola mundo. Esto es una prueba, con pausas.", max_words=3)
    assert chunks[0] == "Hola mundo."
    assert omni.ass_time(3661.23) == "1:01:01.23"
    assert omni.ass_time(-1) == "0:00:00.00"
    assert omni.caption_chunks("") == []


def test_escape_and_build_ass() -> None:
    assert omni.escape_ass("a{b}\\c") == r"a\{b\}\\c"
    text = omni.build_ass(["Hola", "mundo"], 10)
    assert "Dialogue: 0,0:00:00.00,0:00:04.44" in text
    assert "{\\fad(120,120)}Hola" in text
    assert "Dialogue: 0,0:00:04.44,0:00:10.00" in text
    with pytest.raises(omni.OmniError):
        omni.build_ass([], 10)


def test_write_ass(tmp_path: Path) -> None:
    path = omni.write_ass(tmp_path / "subs.ass", ["Hola"], 5)
    assert path.read_text().startswith("[Script Info]")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _patch_success_pipeline(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    monkeypatch.setattr(omni, "ensure_ffmpeg", lambda: calls.append("ffmpeg"))
    monkeypatch.setattr(omni, "generate_script", lambda *args, **kwargs: omni.fallback_script("tema", 2))
    monkeypatch.setattr(
        omni,
        "generate_image",
        lambda prompt, dest, **kwargs: (
            dest.write_bytes(b"image"),
            omni.ImageResult(dest, "placeholder"),
        )[1],
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
                (omni.WordTiming("Hola", 0.0, 0.5),),
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
        "write_ass",
        lambda path, chunks, duration: (path.write_text("subs"), path)[1],
    )
    monkeypatch.setattr(
        omni,
        "mux_video",
        lambda video, audio, out, subs, **kwargs: (out.write_bytes(b"final"), out)[1],
    )


def test_run_pipeline_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _patch_success_pipeline(monkeypatch, calls)
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
    assert result.video.exists()
    assert result.manifest.exists()
    manifest = json.loads(result.manifest.read_text())
    assert manifest["status"] == "ok"
    assert manifest["video"].endswith("final.mp4")
    assert manifest["script"]["title"] == "Tema"
    assert calls == ["ffmpeg"]


def test_run_pipeline_with_music_and_local_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _patch_success_pipeline(monkeypatch, calls)
    monkeypatch.setattr(
        omni,
        "prepare_image",
        lambda src, dest: (dest.write_bytes(b"local"), dest)[1],
    )
    monkeypatch.setattr(
        omni,
        "generate_music",
        lambda dest, duration, **kwargs: (dest.write_bytes(b"music"), dest)[1],
    )
    images = tmp_path / "images"
    images.mkdir()
    (images / "a.jpg").write_bytes(b"x")
    config = omni.OmniConfig(
        topic="tema",
        output_root=tmp_path / "out",
        duration=10,
        scene_count=2,
        image_source="local",
        images_dir=images,
        use_llm=False,
    )
    result = omni.run_pipeline(config)
    manifest = json.loads(result.manifest.read_text())
    assert manifest["status"] == "ok"
    assert manifest["music"].endswith("music.wav")
    assert [item["source"] for item in manifest["image_sources"]] == ["local", "local"]


def test_run_pipeline_failure_writes_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_success_pipeline(monkeypatch, [])

    def boom(*args, **kwargs):
        raise omni.OmniError("sin voz")

    monkeypatch.setattr(omni, "tts_narrate_with_timings", boom)
    config = omni.OmniConfig(
        topic="tema",
        output_root=tmp_path,
        duration=10,
        scene_count=2,
        image_source="placeholder",
        no_music=True,
        use_llm=False,
    )
    with pytest.raises(omni.OmniError, match="sin voz"):
        omni.run_pipeline(config)
    failed = list(tmp_path.glob("tema-*/manifest.json"))
    assert failed
    payload = json.loads(failed[0].read_text())
    assert payload["status"] == "failed"
    assert payload["stage"] == "narration"


def test_run_pipeline_wraps_unknown_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_success_pipeline(monkeypatch, [])
    monkeypatch.setattr(omni, "generate_script", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad")))
    config = omni.OmniConfig(
        topic="tema",
        output_root=tmp_path,
        duration=10,
        scene_count=2,
        image_source="placeholder",
        no_music=True,
        use_llm=False,
    )
    with pytest.raises(omni.OmniError, match="etapa script"):
        omni.run_pipeline(config)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_config_from_args(tmp_path: Path) -> None:
    args = argparse.Namespace(
        topic="tema",
        output_dir=str(tmp_path),
        duration=20,
        scenes=4,
        voice="voz",
        image_source="placeholder",
        images_dir=None,
        music=None,
        no_music=True,
        no_subtitles=True,
        seed=1,
        llm_base_url="http://llm",
        llm_model="model",
        llm_api_key="key",
        no_llm=True,
    )
    config = omni.config_from_args(args)
    assert config.topic == "tema"
    assert config.duration == 20
    assert config.scene_count == 4
    assert config.use_llm is False


def test_main_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = omni.PipelineResult(
        workdir=tmp_path,
        video=tmp_path / "final.mp4",
        script=omni.fallback_script("tema", 2),
        manifest=tmp_path / "manifest.json",
    )
    monkeypatch.setattr(omni, "run_pipeline", lambda config, **kwargs: result)
    assert omni.main(["tema", "--no-llm", "--image-source", "placeholder"]) == 0
    assert "video:" in capsys.readouterr().out

    def boom(config, **kwargs):
        raise omni.OmniError("falló")

    monkeypatch.setattr(omni, "run_pipeline", boom)
    assert omni.main(["tema", "--no-llm", "--image-source", "placeholder"]) == 1
    assert "error: falló" in capsys.readouterr().err
