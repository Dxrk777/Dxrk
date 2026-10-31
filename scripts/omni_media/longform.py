# SPDX-License-Identifier: MIT
"""Long-form plan and timeline helpers for Dxrk Omni.

A long-form piece is a sequence of chapters, and each chapter is a sequence of
shots. The plan is intentionally data-only: rendering lives in ``omni.py`` so
the existing short-video pipeline and its dependency-injection points stay
intact.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("dxrk.omni.longform")


class LongformError(RuntimeError):
    """A long-form plan is invalid."""


@dataclass(frozen=True, slots=True)
class Shot:
    index: int
    narration: str
    visual_prompt: str


@dataclass(frozen=True, slots=True)
class Chapter:
    index: int
    title: str
    shots: tuple[Shot, ...]


@dataclass(frozen=True, slots=True)
class LongformPlan:
    topic: str
    title: str
    chapters: tuple[Chapter, ...]

    @property
    def shots(self) -> tuple[Shot, ...]:
        return tuple(shot for chapter in self.chapters for shot in chapter.shots)

    @property
    def total_shots(self) -> int:
        return sum(len(chapter.shots) for chapter in self.chapters)


_BEATS: tuple[tuple[str, str], ...] = (
    (
        "Esto es lo que nadie te cuenta sobre {topic}.",
        "cinematic close-up of a mysterious object representing {topic}, neon reflections, shallow depth of field",
    ),
    (
        "En los próximos minutos vas a entender por qué {topic} importa de verdad.",
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


def fallback_longform_plan(topic: str, chapters: int = 3, shots_per_chapter: int = 3) -> LongformPlan:
    """Build a deterministic long-form plan when no LLM is available."""
    clean = topic.strip().rstrip(".!?") or "el futuro"
    chapter_list: list[Chapter] = []
    shot_index = 0
    for chapter_index in range(chapters):
        shots: list[Shot] = []
        for _ in range(shots_per_chapter):
            narration, visual = _BEATS[shot_index % len(_BEATS)]
            shots.append(
                Shot(
                    index=shot_index + 1,
                    narration=narration.format(topic=clean),
                    visual_prompt=(
                        f"{visual.format(topic=clean)}. Topic: {clean}. "
                        "Vertical 9:16, cinematic, ultra detailed, no text."
                    ),
                )
            )
            shot_index += 1
        chapter_list.append(Chapter(index=chapter_index + 1, title=f"Capítulo {chapter_index + 1}", shots=tuple(shots)))
    title = f"{clean[0].upper()}{clean[1:]}" if clean else "Dxrk Omni"
    return LongformPlan(topic=clean, title=title, chapters=tuple(chapter_list))


def build_longform_prompt(topic: str, chapters: int, shots_per_chapter: int, chapter_duration: int) -> str:
    return (
        "Sos un director de cine. Devolvé SOLO JSON válido, sin markdown.\n"
        f"Tema: {topic}\n"
        f"Capítulos: exactamente {chapters}.\n"
        f"Planos por capítulo: exactamente {shots_per_chapter}.\n"
        f"Duración objetivo por capítulo: {chapter_duration} segundos.\n"
        "Cada capítulo debe tener 'title' y 'shots'. Cada shot debe tener "
        "'narration' (español rioplatense, natural) y 'visual_prompt' "
        "(inglés, cinematográfico, vertical 9:16, sin texto ni logos).\n"
        "La narración del capítulo es la suma de sus shots. No repitas frases.\n"
        'Formato: {"title": "...", "chapters": [{"title": "...", "shots": [{"narration": "...", "visual_prompt": "..."}]}]}'
    )


def parse_longform_json(raw: str, topic: str) -> LongformPlan:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise LongformError("el LLM no devolvió un objeto JSON")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LongformError(f"JSON inválido del LLM: {exc}") from exc
    if not isinstance(data, dict):
        raise LongformError("el JSON del LLM debe ser un objeto")
    raw_chapters = data.get("chapters")
    if not isinstance(raw_chapters, list) or not 1 <= len(raw_chapters) <= 24:
        raise LongformError("el JSON del LLM debe traer entre 1 y 24 capítulos")
    chapters: list[Chapter] = []
    shot_index = 0
    for chapter_index, chapter_item in enumerate(raw_chapters):
        if not isinstance(chapter_item, dict):
            raise LongformError(f"el capítulo {chapter_index + 1} no es un objeto")
        raw_shots = chapter_item.get("shots")
        if not isinstance(raw_shots, list) or not 1 <= len(raw_shots) <= 12:
            raise LongformError(f"el capítulo {chapter_index + 1} debe traer entre 1 y 12 shots")
        shots: list[Shot] = []
        for shot_item in raw_shots:
            if not isinstance(shot_item, dict):
                raise LongformError("cada shot debe ser un objeto")
            narration = str(shot_item.get("narration", "")).strip()
            visual_prompt = str(shot_item.get("visual_prompt", "")).strip()
            if not narration or not visual_prompt:
                raise LongformError("cada shot necesita narration y visual_prompt")
            shot_index += 1
            shots.append(Shot(index=shot_index, narration=narration, visual_prompt=visual_prompt))
        chapters.append(
            Chapter(
                index=chapter_index + 1,
                title=str(chapter_item.get("title") or f"Capítulo {chapter_index + 1}").strip(),
                shots=tuple(shots),
            )
        )
    title = str(data.get("title") or topic).strip() or topic
    return LongformPlan(topic=topic, title=title, chapters=tuple(chapters))


def generate_longform_plan(
    topic: str,
    chapters: int,
    shots_per_chapter: int,
    chapter_duration: int,
    llm: Any | None,
) -> LongformPlan:
    if llm is None:
        return fallback_longform_plan(topic, chapters, shots_per_chapter)
    try:
        raw = llm.complete(build_longform_prompt(topic, chapters, shots_per_chapter, chapter_duration))
        return parse_longform_json(raw, topic)
    except Exception as exc:
        logger.warning("LLM long-form plan failed (%s); using deterministic fallback", exc)
        return fallback_longform_plan(topic, chapters, shots_per_chapter)


def plan_to_dict(plan: LongformPlan) -> dict[str, Any]:
    return {
        "topic": plan.topic,
        "title": plan.title,
        "chapters": [
            {
                "index": chapter.index,
                "title": chapter.title,
                "shots": [
                    {
                        "index": shot.index,
                        "narration": shot.narration,
                        "visual_prompt": shot.visual_prompt,
                    }
                    for shot in chapter.shots
                ],
            }
            for chapter in plan.chapters
        ],
    }


def chapter_offsets(durations: Sequence[float]) -> tuple[float, ...]:
    offsets: list[float] = []
    elapsed = 0.0
    for duration in durations:
        offsets.append(elapsed)
        elapsed += duration
    return tuple(offsets)
