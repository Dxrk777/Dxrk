# SPDX-License-Identifier: MIT
"""Entity detector — extract_candidates, score_entity, classify_entity (simplified)."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import cast

PROSE_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".rst", ".csv"})
READABLE_EXTENSIONS: frozenset[str] = frozenset(
    {".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".csv", ".rst", ".toml", ".sh"}
)
SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".next",
        "coverage",
        ".dxrk",
        "target",
    }
)
SKIP_FILENAMES: frozenset[str] = frozenset({"license", "licence", "copying", "copyright"})

_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "this",
        "that",
        "these",
        "those",
        "when",
        "where",
        "what",
        "why",
        "who",
        "which",
        "how",
        "after",
        "before",
        "then",
        "now",
        "here",
        "there",
        "and",
        "but",
        "or",
        "yet",
        "so",
        "if",
        "else",
        "yes",
        "no",
        "maybe",
        "okay",
        "user",
        "assistant",
        "system",
        "tool",
    }
)

# Candidate patterns: capitalized words length >=2
_CANDIDATE_RE = re.compile(r"\b[A-Z][a-zA-Z]{1,}\b")
_MULTI_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b")

_DLG_RE = re.compile(r"^([A-Z][a-z]+):\s", re.MULTILINE)
_PERSON_VERBS = [r"\b{name}\s+(?:said|told|asked|replied|wrote|decided|built|fixed)\b"]
_PROJECT_VERBS = [r"\b{name}\s+(?:deployed|migrated|released|built|configured)\b"]
_PRONOUN_RE = re.compile(r"\b(?:he|she|they|him|her|them|his|hers|their)\b", re.IGNORECASE)


def extract_candidates(text: str, languages: tuple[str, ...] = ("en",)) -> dict[str, int]:
    """Extract capitalized candidates appearing 3+ times. Languages param kept for compat."""
    _ = languages
    counts: defaultdict[str, int] = defaultdict(int)
    for w in _CANDIDATE_RE.findall(text):
        if w.lower() in _STOPWORDS or len(w) < 2:
            continue
        counts[w] += 1
    for phrase in _MULTI_RE.findall(text):
        if any(p.lower() in _STOPWORDS for p in phrase.split()):
            continue
        counts[phrase] += 1
    return {k: v for k, v in counts.items() if v >= 3}


def score_entity(name: str, text: str, lines: list[str], languages: tuple[str, ...] = ("en",)) -> dict[str, object]:
    """Score candidate as person vs project."""
    _ = languages
    person_score = 0
    project_score = 0
    person_signals: list[str] = []
    project_signals: list[str] = []

    # dialogue: Name: pattern (require 2+ hits if bare colon)
    dlg_hits = len(re.compile(re.escape(name) + r":\s", re.IGNORECASE).findall(text))
    if dlg_hits >= 2:
        person_score += dlg_hits * 3
        person_signals.append(f"dialogue marker ({dlg_hits}x)")
    # also generic dialogue markers near name
    generic_dlg = len(_DLG_RE.findall(text))
    if generic_dlg >= 1 and name.lower() in text.lower():
        # light boost
        pass

    for pat in _PERSON_VERBS:
        rx = re.compile(pat.format(name=re.escape(name)), re.IGNORECASE)
        m = len(rx.findall(text))
        if m:
            person_score += m * 2
            person_signals.append(f"'{name} ...' action ({m}x)")

    # pronoun proximity
    name_lower = name.lower()
    idxs = [i for i, ln in enumerate(lines) if name_lower in ln.lower()]
    pronoun_hits = 0
    for idx in idxs:
        window = " ".join(lines[max(0, idx - 2) : idx + 3])
        if _PRONOUN_RE.search(window):
            pronoun_hits += 1
    if pronoun_hits:
        person_score += pronoun_hits * 2
        person_signals.append(f"pronoun nearby ({pronoun_hits}x)")

    for pat in _PROJECT_VERBS:
        rx = re.compile(pat.format(name=re.escape(name)), re.IGNORECASE)
        m = len(rx.findall(text))
        if m:
            project_score += m * 2
            project_signals.append(f"project verb ({m}x)")

    # versioned
    versioned = len(re.compile(rf"\b{re.escape(name)}[-_]v?\d+(?:\.\d+)*\b", re.IGNORECASE).findall(text))
    if versioned:
        project_score += versioned * 3
        project_signals.append(f"versioned/hyphenated ({versioned}x)")

    return {
        "person_score": person_score,
        "project_score": project_score,
        "person_signals": person_signals[:3],
        "project_signals": project_signals[:3],
    }


def classify_entity(name: str, frequency: int, scores: dict[str, object]) -> dict[str, object]:
    ps = int(cast(int, scores.get("person_score", 0)))  # type: ignore[call-overload]
    pr = int(cast(int, scores.get("project_score", 0)))  # type: ignore[call-overload]
    total = ps + pr
    if total == 0:
        confidence = min(0.4, frequency / 50)
        return {
            "name": name,
            "type": "uncertain",
            "confidence": round(confidence, 2),
            "frequency": frequency,
            "signals": [f"appears {frequency}x, no strong type signals"],
        }
    person_ratio = ps / total if total else 0
    # count signal categories
    cats: set[str] = set()
    for s in cast(list[str], scores.get("person_signals", []) or []):  # type: ignore[call-overload]
        s2 = str(s)
        if "dialogue" in s2:
            cats.add("dialogue")
        elif "action" in s2:
            cats.add("action")
        elif "pronoun" in s2:
            cats.add("pronoun")
    has_two = len(cats) >= 2
    pronoun_hits = 0
    for s in cast(list[str], scores.get("person_signals", []) or []):  # type: ignore[call-overload]
        m = re.search(r"pronoun nearby \((\d+)x\)", str(s))
        if m:
            pronoun_hits = int(m.group(1))
            break
    strong_pronoun = pronoun_hits >= 5 and frequency > 0 and pronoun_hits / frequency >= 0.2
    if person_ratio >= 0.7 and (has_two and ps >= 5 or strong_pronoun):
        conf = min(0.99, 0.5 + person_ratio * 0.5)
        signals = list(cast(list[str], scores.get("person_signals", []) or [f"appears {frequency}x"]))  # type: ignore[call-overload]
        return {
            "name": name,
            "type": "person",
            "confidence": round(conf, 2),
            "frequency": frequency,
            "signals": signals,
        }
    if person_ratio >= 0.7:
        return {
            "name": name,
            "type": "uncertain",
            "confidence": 0.4,
            "frequency": frequency,
            "signals": list(cast(list[str], scores.get("person_signals") or []))
            + [f"appears {frequency}x — weak person signal"],
        }
    if person_ratio <= 0.3:
        conf = min(0.99, 0.5 + (1 - person_ratio) * 0.5)
        signals = list(cast(list[str], scores.get("project_signals") or [f"appears {frequency}x"]))
        return {
            "name": name,
            "type": "project",
            "confidence": round(conf, 2),
            "frequency": frequency,
            "signals": signals,
        }
    return {
        "name": name,
        "type": "uncertain",
        "confidence": 0.5,
        "frequency": frequency,
        "signals": (
            list(cast(list[str], scores.get("person_signals") or []))
            + list(cast(list[str], scores.get("project_signals") or []))
        )[:3]
        + ["mixed signals — needs review"],
    }


def detect_entities(
    file_paths: list[Path],
    max_files: int = 10,
    languages: tuple[str, ...] = ("en",),
    corpus_origin: dict[str, object] | None = None,
) -> dict[str, list[dict[str, object]]]:
    all_text: list[str] = []
    all_lines: list[str] = []
    read = 0
    for fp in file_paths:
        if read >= max_files:
            break
        try:
            content = Path(fp).read_text(encoding="utf-8", errors="replace")[:5000]
        except OSError:
            continue
        all_text.append(content)
        all_lines.extend(content.splitlines())
        read += 1
    combined = "\n".join(all_text)
    cands = extract_candidates(combined, languages=languages)
    if not cands:
        return {"people": [], "projects": [], "topics": [], "uncertain": []}
    people: list[dict[str, object]] = []
    projects: list[dict[str, object]] = []
    uncertain: list[dict[str, object]] = []
    for name, freq in sorted(cands.items(), key=lambda x: x[1], reverse=True):
        sc = score_entity(name, combined, all_lines, languages=languages)
        ent = classify_entity(name, freq, sc)
        t = ent.get("type")
        if t == "person":
            people.append(ent)
        elif t == "project":
            projects.append(ent)
        else:
            uncertain.append(ent)
    people.sort(key=lambda x: float(cast(float, x.get("confidence", 0))), reverse=True)  # type: ignore[call-overload]
    projects.sort(key=lambda x: float(cast(float, x.get("confidence", 0))), reverse=True)  # type: ignore[call-overload]
    uncertain.sort(key=lambda x: int(cast(int, x.get("frequency", 0))), reverse=True)  # type: ignore[call-overload]
    detected: dict[str, list[dict[str, object]]] = {
        "people": people[:15],
        "projects": projects[:10],
        "topics": [],
        "uncertain": uncertain[:8],
    }
    # corpus_origin handling simplified: ignore unless provided
    _ = corpus_origin
    return detected


def scan_for_detection(project_dir: str | Path, max_files: int = 10) -> list[Path]:
    proj = Path(project_dir).expanduser().resolve()
    prose: list[Path] = []
    all_files: list[Path] = []
    for root, dirs, filenames in __import__("os").walk(proj):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in filenames:
            fp = Path(root) / fn
            if fp.stem.lower() in SKIP_FILENAMES:
                continue
            ext = fp.suffix.lower()
            if ext in PROSE_EXTENSIONS:
                prose.append(fp)
            elif ext in READABLE_EXTENSIONS:
                all_files.append(fp)
    files = prose if len(prose) >= 3 else prose + all_files
    return files[:max_files]
