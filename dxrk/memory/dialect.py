# SPDX-License-Identifier: MIT
"""AAAK dialect — compress / count_tokens, stdlib only."""

from __future__ import annotations

import re
from pathlib import Path

EMOTION_CODES: dict[str, str] = {
    "vulnerability": "vul",
    "joy": "joy",
    "fear": "fear",
    "trust": "trust",
    "grief": "grief",
    "wonder": "wonder",
    "rage": "rage",
    "love": "love",
    "hope": "hope",
    "despair": "despair",
    "peace": "peace",
    "relief": "relief",
    "humor": "humor",
    "tenderness": "tender",
    "raw_honesty": "raw",
    "self_doubt": "doubt",
    "anxiety": "anx",
    "exhaustion": "exhaust",
    "conviction": "convict",
    "curiosity": "curious",
    "gratitude": "grat",
    "frustration": "frust",
}

_EMOTION_SIGNALS: dict[str, str] = {
    "decided": "determ",
    "worried": "anx",
    "excited": "excite",
    "frustrated": "frust",
    "love": "love",
    "hope": "hope",
    "fear": "fear",
    "trust": "trust",
    "happy": "joy",
    "sad": "grief",
    "grateful": "grat",
    "curious": "curious",
    "wonder": "wonder",
    "anxious": "anx",
    "relieved": "relief",
}

_FLAG_SIGNALS: dict[str, str] = {
    "decided": "DECISION",
    "chose": "DECISION",
    "switched": "DECISION",
    "migrated": "DECISION",
    "because": "DECISION",
    "founded": "ORIGIN",
    "created": "ORIGIN",
    "started": "ORIGIN",
    "born": "ORIGIN",
    "launched": "ORIGIN",
    "core": "CORE",
    "principle": "CORE",
    "turning point": "PIVOT",
    "realized": "PIVOT",
    "breakthrough": "PIVOT",
    "api": "TECHNICAL",
    "database": "TECHNICAL",
    "architecture": "TECHNICAL",
    "deploy": "TECHNICAL",
}

_STOP_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "about",
        "during",
        "before",
        "after",
        "and",
        "but",
        "or",
        "if",
        "while",
        "that",
        "this",
        "these",
        "those",
        "it",
        "i",
        "we",
        "you",
        "he",
        "she",
        "they",
        "my",
        "your",
        "his",
        "our",
        "their",
        "what",
        "which",
        "who",
        "also",
        "much",
        "many",
        "like",
        "because",
        "use",
        "used",
        "using",
        "make",
        "made",
        "thing",
        "things",
        "way",
        "well",
        "really",
        "want",
        "need",
    }
)

_ALPHA_RE = re.compile(r"[^a-zA-Z]")


class Dialect:
    """AAAK compressor — extract entities/topics/quotes/emotions/flags."""

    def __init__(self, entities: dict[str, str] | None = None, skip_names: list[str] | None = None) -> None:
        self.entity_codes: dict[str, str] = {}
        if entities:
            for k, v in entities.items():
                self.entity_codes[k] = v
                self.entity_codes[k.lower()] = v
        self.skip_names: list[str] = [n.lower() for n in (skip_names or [])]

    def encode_entity(self, name: str) -> str | None:
        if any(s in name.lower() for s in self.skip_names):
            return None
        if name in self.entity_codes:
            return self.entity_codes[name]
        if name.lower() in self.entity_codes:
            return self.entity_codes[name.lower()]
        for k, code in self.entity_codes.items():
            if k.lower() in name.lower():
                return code
        return name[:3].upper()

    def _detect_emotions(self, text: str) -> list[str]:
        low = text.lower()
        seen: set[str] = set()
        out: list[str] = []
        for kw, code in _EMOTION_SIGNALS.items():
            if kw in low and code not in seen:
                out.append(code)
                seen.add(code)
        return out[:3]

    def _detect_flags(self, text: str) -> list[str]:
        low = text.lower()
        seen: set[str] = set()
        out: list[str] = []
        for kw, flag in _FLAG_SIGNALS.items():
            if kw in low and flag not in seen:
                out.append(flag)
                seen.add(flag)
        return out[:3]

    def _extract_topics(self, text: str, max_topics: int = 3) -> list[str]:
        words = re.findall(r"[a-zA-Z][a-zA-Z_-]{2,}", text)
        freq: dict[str, int] = {}
        for w in words:
            low = w.lower()
            if low in _STOP_WORDS or len(low) < 3:
                continue
            freq[low] = freq.get(low, 0) + 1
        for w in words:
            low = w.lower()
            if low in _STOP_WORDS:
                continue
            if w[0].isupper() and low in freq:
                freq[low] += 2
            if "_" in w or "-" in w or any(c.isupper() for c in w[1:]):
                if low in freq:
                    freq[low] += 2
        ranked = sorted(freq.items(), key=lambda x: -x[1])
        return [w for w, _ in ranked[:max_topics]]

    def _extract_key_sentence(self, text: str) -> str:
        sentences = [s.strip() for s in re.split(r"[.!?\n]+", text) if len(s.strip()) > 10]
        if not sentences:
            return ""
        decision = {
            "decided",
            "because",
            "instead",
            "prefer",
            "switched",
            "chose",
            "realized",
            "important",
            "key",
            "critical",
            "discovered",
            "learned",
            "conclusion",
            "solution",
            "why",
            "breakthrough",
            "insight",
        }
        best = sentences[0]
        best_score = -1
        for s in sentences:
            score = 0
            low = s.lower()
            for w in decision:
                if w in low:
                    score += 2
            if len(s) < 80:
                score += 1
            if len(s) > 150:
                score -= 2
            if score > best_score:
                best_score = score
                best = s
        if len(best) > 55:
            best = best[:52] + "..."
        return best

    def _detect_entities_in_text(self, text: str) -> list[str]:
        found: list[str] = []
        for name, code in self.entity_codes.items():
            if not name.islower() and name.lower() in text.lower() and code not in found:
                found.append(code)
        if found:
            return found
        for i, w in enumerate(text.split()):
            clean = _ALPHA_RE.sub("", w)
            if (
                len(clean) >= 2
                and clean[0].isupper()
                and clean[1:].islower()
                and i > 0
                and clean.lower() not in _STOP_WORDS
            ):
                code = clean[:3].upper()
                if code not in found:
                    found.append(code)
                if len(found) >= 3:
                    break
        return found

    def compress(self, text: str, metadata: dict[str, object] | None = None) -> str:
        """Compress plain text into AAAK dialect line."""
        metadata = metadata or {}
        entities = self._detect_entities_in_text(text)
        entity_str = "+".join(entities[:3]) if entities else "???"
        topics = self._extract_topics(text)
        topic_str = "_".join(topics[:3]) if topics else "misc"
        quote = self._extract_key_sentence(text)
        quote_part = f'"{quote}"' if quote else ""
        emotions = self._detect_emotions(text)
        emotion_str = "+".join(emotions) if emotions else ""
        flags = self._detect_flags(text)
        flag_str = "+".join(flags) if flags else ""
        source = str(metadata.get("source_file", "")) if metadata.get("source_file") else ""
        wing = str(metadata.get("wing", "")) if metadata.get("wing") else ""
        room = str(metadata.get("room", "")) if metadata.get("room") else ""
        date_s = str(metadata.get("date", "")) if metadata.get("date") else ""
        lines: list[str] = []
        if source or wing:
            lines.append("|".join([wing or "?", room or "?", date_s or "?", Path(source).stem if source else "?"]))
        parts: list[str] = [f"0:{entity_str}", topic_str]
        if quote_part:
            parts.append(quote_part)
        if emotion_str:
            parts.append(emotion_str)
        if flag_str:
            parts.append(flag_str)
        lines.append("|".join(parts))
        return "\n".join(lines)

    def decode(self, dialect_text: str) -> dict[str, object]:
        lines = dialect_text.strip().split("\n")
        result: dict[str, object] = {"header": {}, "arc": "", "zettels": [], "tunnels": []}
        for line in lines:
            if line.startswith("ARC:"):
                result["arc"] = line[4:]
            elif line.startswith("T:"):
                (result["tunnels"] or []).append(line)  # type: ignore[attr-defined]
            elif "|" in line and ":" in line.split("|")[0]:
                (result["zettels"] or []).append(line)  # type: ignore[attr-defined]
            elif "|" in line:
                parts = line.split("|")
                result["header"] = {
                    "file": parts[0] if len(parts) > 0 else "",
                    "entities": parts[1] if len(parts) > 1 else "",
                    "date": parts[2] if len(parts) > 2 else "",
                    "title": parts[3] if len(parts) > 3 else "",
                }
        return result

    @staticmethod
    def count_tokens(text: str) -> int:
        """Estimate tokens as words * 1.3."""
        words = text.split()
        return max(1, int(len(words) * 1.3))

    def compression_stats(self, original: str, compressed: str) -> dict[str, object]:
        o = self.count_tokens(original)
        c = self.count_tokens(compressed)
        return {
            "original_tokens_est": o,
            "summary_tokens_est": c,
            "size_ratio": round(o / max(c, 1), 1),
            "original_chars": len(original),
            "summary_chars": len(compressed),
            "note": "AAAK is lossy summary",
        }
