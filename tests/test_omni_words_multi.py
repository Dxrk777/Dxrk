# SPDX-License-Identifier: MIT
"""Speaker-aware karaoke and ASS style tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.omni_media import words as word_utils


def test_word_timing_scaled_and_shifted_preserve_speaker() -> None:
    word = word_utils.WordTiming("hola", 1.0, 2.0, "quote")
    assert word.scaled(2.0) == word_utils.WordTiming("hola", 2.0, 4.0, "quote")
    assert word.shifted(0.5) == word_utils.WordTiming("hola", 1.5, 2.5, "quote")


def test_sanitize_style_name_and_scale() -> None:
    assert word_utils.sanitize_style_name("Narrator") == "Narrator"
    assert word_utils.sanitize_style_name("voz principal!") == "voz_principal_"
    assert word_utils.sanitize_style_name("   ") == "Speaker"
    assert word_utils.default_style() == word_utils.AssStyle()
    scaled = word_utils.default_style((2160, 3840))
    assert scaled.fontsize == 128
    assert scaled.outline_width == 8
    assert scaled.shadow == 2
    assert scaled.margin_l == 120
    assert scaled.margin_v == 360


def test_style_for_speaker_and_dxrk_branch() -> None:
    default = word_utils.style_for_speaker("Dxrk")
    assert default == word_utils.AssStyle()
    first = word_utils.style_for_speaker("narrator", 0)
    second = word_utils.style_for_speaker("quote", 1)
    assert first.name == "narrator"
    assert first.primary != second.primary
    assert first.secondary == second.primary
    wrapped = word_utils.style_for_speaker("other", len(word_utils._ASS_COLORS))
    assert wrapped.primary == word_utils._ASS_COLORS[0]
    scaled = word_utils.style_for_speaker("narrator", 0, (2160, 3840))
    assert scaled.fontsize == 128


def test_ass_header_includes_sanitized_speaker_styles() -> None:
    header = word_utils.ass_header(
        {
            "narrator": word_utils.style_for_speaker("narrator", 0),
            "voz principal": word_utils.style_for_speaker("voz principal", 1),
        },
        play_res=(2160, 3840),
    )
    assert "PlayResX: 2160" in header
    assert "PlayResY: 3840" in header
    assert "Style: Dxrk,DejaVu Sans,128" in header
    assert "Style: narrator," in header
    assert "Style: voz_principal," in header


def test_group_word_timings_splits_by_speaker_and_validates() -> None:
    words = (
        word_utils.WordTiming("Hola", 0.0, 0.2, "narrator"),
        word_utils.WordTiming("mundo", 0.2, 0.4, "narrator"),
        word_utils.WordTiming("Cita", 0.4, 0.6, "quote"),
        word_utils.WordTiming("final", 0.6, 0.8, "quote"),
    )
    groups = word_utils.group_word_timings(words, max_words=4)
    assert [[word.speaker for word in group] for group in groups] == [
        ["narrator", "narrator"],
        ["quote", "quote"],
    ]
    with pytest.raises(ValueError, match="max_words"):
        word_utils.group_word_timings(words, max_words=0)
    with pytest.raises(ValueError, match="max_gap"):
        word_utils.group_word_timings(words, max_gap=-1)


def test_build_word_ass_with_speaker_styles_and_4k() -> None:
    words = (
        word_utils.WordTiming("Hola", 0.0, 0.5, "narrator"),
        word_utils.WordTiming("mundo", 0.5, 1.0, "narrator"),
        word_utils.WordTiming("Cita", 1.0, 1.5, "quote"),
        word_utils.WordTiming("final", 1.5, 2.0, "quote"),
    )
    ass = word_utils.build_word_ass(
        words,
        styles={"narrator": word_utils.style_for_speaker("narrator", 0, (2160, 3840))},
        play_res=(2160, 3840),
    )
    assert "PlayResX: 2160" in ass
    assert "Style: narrator,DejaVu Sans,128" in ass
    assert "Style: quote,DejaVu Sans,128" in ass
    assert "Dialogue: 0,0:00:00.00,0:00:01.00,narrator" in ass
    assert "Dialogue: 0,0:00:01.00,0:00:02.00,quote" in ass
    assert r"{\kf50}Hola" in ass


def test_build_word_ass_default_style_and_zero_duration() -> None:
    ass = word_utils.build_word_ass(
        (word_utils.WordTiming("solo", 1.0, 1.0),),
        play_res=(1080, 1920),
    )
    assert "Dialogue: 0,0:00:01.00,0:00:01.01,Dxrk" in ass
    assert r"{\kf1}solo" in ass


def test_write_word_ass_and_words_to_dict(tmp_path: Path) -> None:
    out = tmp_path / "subs.ass"
    words = (
        word_utils.WordTiming("Hola", 0.0, 0.5, "narrator"),
        word_utils.WordTiming("Cita", 0.5, 1.0, "quote"),
    )
    result = word_utils.write_word_ass(out, words, play_res=(1080, 1920))
    assert result == out
    assert "narrator" in out.read_text(encoding="utf-8")
    assert word_utils.words_to_dict(words) == [
        {"text": "Hola", "start": 0.0, "end": 0.5, "speaker": "narrator"},
        {"text": "Cita", "start": 0.5, "end": 1.0, "speaker": "quote"},
    ]
    assert word_utils.words_to_dict((word_utils.WordTiming("x", 0.0, 1.0),)) == [
        {"text": "x", "start": 0.0, "end": 1.0}
    ]


def test_normalize_words_preserves_speaker_from_mappings_and_objects() -> None:
    normalized = word_utils._normalize_words(
        [
            {"text": "uno", "start": 0.0, "end": 0.5, "speaker": "narrator"},
            type("Word", (), {"word": "dos", "start": 0.5, "end": 1.0, "speaker": "quote"})(),
            word_utils.WordTiming("tres", 1.0, 1.5, "guest"),
            {"text": " "},
        ]
    )
    assert normalized == (
        word_utils.WordTiming("uno", 0.0, 0.5, "narrator"),
        word_utils.WordTiming("dos", 0.5, 1.0, "quote"),
        word_utils.WordTiming("tres", 1.0, 1.5, "guest"),
    )
