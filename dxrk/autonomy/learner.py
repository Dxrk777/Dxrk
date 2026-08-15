# SPDX-License-Identifier: MIT
"""Learner: pattern memory for autonomy"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class MemoryItem:
    id: str = ""
    timestamp: str = ""
    category: str = ""
    input: str = ""
    output: str = ""
    success: bool = False
    error: str | None = None
    fixed_by: str | None = None
    tags: list[str] = field(default_factory=list)
    tokens: int = 0
    latency_ms: float = 0.0
    metadata: dict[str, str] | None = None


@dataclass
class Pattern:
    trigger: str = ""
    action: str = ""
    success_rate: float = 0.0
    count: int = 0
    tags: list[str] = field(default_factory=list)


@dataclass
class ErrorEntry:
    error: str = ""
    count: int = 0


class Learner:
    """Records memory items, learns input/output patterns and tracks top errors."""

    def __init__(self, path: str, max_items: int) -> None:
        self.mu = threading.RLock()
        self.path = path
        self.max_items = max_items
        self.memories: list[MemoryItem] = []
        self.patterns: dict[str, Pattern] = {}
        self.error_patterns: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except OSError:
            return
        except json.JSONDecodeError as exc:
            logger.info("[learner] failed to unmarshal store: %s", exc)
            return
        self.memories = [MemoryItem(**m) for m in data.get("memories", [])]
        for p in data.get("patterns", []):
            self.patterns[p["trigger"]] = Pattern(**p)

    def _make_store(self) -> dict:
        return {
            "memories": [asdict(m) for m in self.memories],
            "patterns": [asdict(p) for p in self.patterns.values()],
        }

    def _save(self) -> None:
        with self.mu:
            store = self._make_store()
        try:
            data = json.dumps(store, indent=2)
        except TypeError as exc:
            logger.info("[learner] failed to marshal store: %s", exc)
            return
        directory = os.path.dirname(self.path)
        try:
            os.makedirs(directory, mode=0o750, exist_ok=True)
        except OSError as exc:
            logger.info("[learner] failed to create dir: %s", exc)
            return
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
        except OSError as exc:
            logger.info("[learner] failed to write file: %s", exc)

    def record(self, item: MemoryItem) -> None:
        with self.mu:
            if item.id == "":
                digest = hashlib.sha256(
                    (
                        item.input
                        + item.output
                        + datetime.now(UTC).isoformat()
                    ).encode()
                ).hexdigest()
                item.id = digest[:16]
            item.timestamp = datetime.now(UTC).isoformat()
            self.memories.append(item)
            if len(self.memories) > self.max_items:
                self.memories = self.memories[len(self.memories) - self.max_items :]
            self._learn_pattern(item)
            if not item.success and item.error:
                key = _error_key(item.error)
                self.error_patterns[key] = self.error_patterns.get(key, 0) + 1
        self._save()

    def _learn_pattern(self, item: MemoryItem) -> None:
        trigger = _extract_trigger(item)
        if trigger == "":
            return
        p = self.patterns.get(trigger)
        if p is None:
            p = Pattern(trigger=trigger, tags=item.tags)
            self.patterns[trigger] = p
        total = p.count * int(p.success_rate + 50) + 1
        if item.success:
            total += 1
        p.count += 1
        p.success_rate = (total - 50) / p.count
        if p.success_rate > 1:
            p.success_rate = 1
        if p.success_rate < 0:
            p.success_rate = 0
        p.action = item.output

    def suggest(self, input_: str) -> list[Pattern]:
        with self.mu:
            candidates = [
                p
                for p in self.patterns.values()
                if input_ in p.trigger or p.trigger in input_
            ]
        candidates.sort(key=lambda p: p.success_rate, reverse=True)
        return candidates[:5]

    def recent_memories(self, n: int) -> list[MemoryItem]:
        with self.mu:
            if n > len(self.memories):
                n = len(self.memories)
            return list(self.memories[len(self.memories) - n :])

    def top_errors(self, n: int) -> list[ErrorEntry]:
        with self.mu:
            entries = [
                ErrorEntry(error=e, count=c) for e, c in self.error_patterns.items()
            ]
        entries.sort(key=lambda e: e.count, reverse=True)
        return entries[:n]


def _extract_trigger(item: MemoryItem) -> str:
    if item.input == "":
        return ""
    words = item.input.split()
    if len(words) > 10:
        return " ".join(words[:10])
    return item.input


def _error_key(err: str) -> str:
    err = err.lower().replace(" ", "_")
    return err[:64]


def NewLearner(path: str, max_items: int) -> Learner:
    return Learner(path, max_items)
