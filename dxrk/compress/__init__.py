from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
import json
import os
import threading
from typing import Callable


@dataclass
class Content:
    id: str
    role: str = ""
    text: str = ""
    created_at: datetime = datetime.min
    size: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "text": self.text,
            "created_at": self.created_at.isoformat(),
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Content":
        return cls(
            id=data.get("id", ""),
            role=data.get("role", ""),
            text=data.get("text", ""),
            created_at=datetime.fromisoformat(data.get("created_at", "")),
            size=data.get("size", 0),
        )


class Strategy(IntEnum):
    SNIP = 0
    TRIM_HEAD = 1
    SUMMARY = 2


class Compressor:
    def __init__(
        self,
        max_tokens: int = 128000,
        compression_pct: int = 50,
        strategy: Strategy = Strategy.SNIP,
    ):
        self._mu = threading.RLock()
        self.max_tokens = max_tokens
        self.compression_pct = compression_pct
        self.strategy = strategy

    def compress(self, contents: list[Content]) -> tuple[list[Content], bool]:
        with self._mu:
            total = total_bytes(contents)
            if total <= self.max_tokens:
                return contents, False
            target = total * (100 - self.compression_pct) // 100
            if self.strategy == Strategy.TRIM_HEAD:
                return self._trim_head(contents, target)
            if self.strategy == Strategy.SUMMARY:
                return self._summarize(contents, target)
            return self._snip(contents, target)

    def _snip(self, contents: list[Content], target: int) -> tuple[list[Content], bool]:
        kept: list[Content] = []
        accum = 0
        for chunk in reversed(contents):
            if accum + chunk.size <= target or not kept:
                kept.insert(0, chunk)
                accum += chunk.size
        return kept, True

    def _trim_head(
        self, contents: list[Content], target: int
    ) -> tuple[list[Content], bool]:
        result = list(contents)
        per_block = target // len(contents) if contents else 0
        for i, chunk in enumerate(contents):
            if chunk.size <= per_block:
                continue
            keep_bytes = chunk.size * (100 - self.compression_pct) // 100
            trimmed = chunk.text
            if len(trimmed) > keep_bytes:
                trimmed = trimmed[len(trimmed) - keep_bytes :]
            result[i] = Content(
                id=chunk.id,
                role=chunk.role,
                text=trimmed,
                created_at=chunk.created_at,
                size=len(trimmed),
            )
        return result, True

    def _summarize(
        self, contents: list[Content], target: int
    ) -> tuple[list[Content], bool]:
        per_block = target // max(len(contents), 1)
        result = list(contents)
        for i, chunk in enumerate(contents):
            summary = chunk.text
            if len(summary) > per_block:
                summary = summary[:per_block] + "..."
            result[i] = Content(
                id=chunk.id,
                role=chunk.role,
                text=summary,
                created_at=chunk.created_at,
                size=len(summary),
            )
        return result, True


def new(*opts: Callable[[Compressor], None]) -> Compressor:
    c = Compressor()
    for opt in opts:
        opt(c)
    return c


def with_max_tokens(n: int) -> Callable[[Compressor], None]:
    return lambda c: setattr(c, "max_tokens", n)


def with_compression_pct(pct: int) -> Callable[[Compressor], None]:
    return lambda c: setattr(c, "compression_pct", pct)


def with_strategy(s: Strategy) -> Callable[[Compressor], None]:
    return lambda c: setattr(c, "strategy", s)


def token_count(text: str) -> int:
    return len(text) // 4


def estimate_tokens(contents: list[Content]) -> int:
    return total_bytes(contents) // 4


def total_bytes(contents: list[Content]) -> int:
    return sum(c.size for c in contents)


class Budget:
    def __init__(self, limit: int):
        self._mu = threading.RLock()
        self.used = 0
        self.limit = limit
        self.threshold = 0.9
        self.diminishing_window = 500

    def add(self, tokens: int) -> None:
        with self._mu:
            self.used += tokens

    def reset(self) -> None:
        with self._mu:
            self.used = 0

    def remaining(self) -> int:
        with self._mu:
            return self.limit - self.used

    def needs_compression(self) -> bool:
        with self._mu:
            return float(self.used) >= float(self.limit) * self.threshold

    def is_near_limit(self) -> bool:
        return self.remaining() <= self.diminishing_window


def new_budget(limit: int) -> Budget:
    return Budget(limit)


@dataclass
class Snapshot:
    id: str
    created_at: datetime
    content: list[Content]
    token_estimate: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "content": [c.to_dict() for c in self.content],
            "token_estimate": self.token_estimate,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Snapshot":
        return cls(
            id=data.get("id", ""),
            created_at=datetime.fromisoformat(data.get("created_at", "")),
            content=[Content.from_dict(c) for c in data.get("content", [])],
            token_estimate=data.get("token_estimate", 0),
        )


class Snapshotter:
    def __init__(self, max_age: float, max_count: int):
        self._mu = threading.RLock()
        self.max_age = max_age
        self.max_count = max_count
        self.snaps: list[Snapshot] = []

    def record(self, id: str, contents: list[Content]) -> Snapshot:
        with self._mu:
            snap = Snapshot(
                id=id,
                created_at=datetime.now(),
                content=list(contents),
                token_estimate=estimate_tokens(contents),
            )
            expired = datetime.now().timestamp() - self.max_age
            active = [s for s in self.snaps if s.created_at.timestamp() > expired]
            if len(active) > self.max_count - 1:
                active = active[len(active) - self.max_count + 1 :]
            active.append(snap)
            self.snaps = active
            return snap

    def recent(self) -> list[Snapshot]:
        with self._mu:
            expired = datetime.now().timestamp() - self.max_age
            return [s for s in self.snaps if s.created_at.timestamp() > expired]

    def string(self) -> str:
        recent = self.recent()
        total = sum(s.token_estimate for s in recent)
        return f"snapshots: {len(recent)} recent, ~{total} tokens"

    def save_to_file(self, path: str) -> None:
        with self._mu:
            snaps = list(self.snaps)
        try:
            data = json.dumps({"snapshots": [s.to_dict() for s in snaps]}).encode()
        except (TypeError, ValueError) as e:
            raise RuntimeError(f"marshal snapshots: {e}") from e
        tmp = path + ".tmp"
        try:
            with open(tmp, "wb", 0o600) as f:
                f.write(data)
        except OSError as e:
            raise RuntimeError(f"write snapshot file: {e}") from e
        try:
            os.replace(tmp, path)
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise RuntimeError(f"rename snapshot file: {e}") from e

    def load_from_file(self, path: str) -> tuple[int, None]:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            return 0, None
        except OSError as e:
            raise RuntimeError(f"read snapshot file: {e}") from e
        try:
            sf = json.loads(data)
        except (json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(f"unmarshal snapshots: {e}") from e
        with self._mu:
            loaded_snaps = [Snapshot.from_dict(s) for s in sf.get("snapshots", [])]
            self.snaps.extend(loaded_snaps)
            if len(self.snaps) > self.max_count:
                self.snaps = self.snaps[len(self.snaps) - self.max_count :]
            loaded = len(loaded_snaps)
        return loaded, None


def new_snapshotter(max_age: float, max_count: int) -> Snapshotter:
    return Snapshotter(max_age, max_count)


@dataclass
class TrimmedResult:
    content: str
    original_bytes: int
    trimmed_bytes: int
    ratio: float
    strategy: str


def trim(text: str, max_bytes: int) -> TrimmedResult:
    if len(text) <= max_bytes:
        return TrimmedResult(
            content=text, original_bytes=0, trimmed_bytes=0, ratio=0.0, strategy="none"
        )
    cut = text[:max_bytes]
    return TrimmedResult(
        content=cut,
        original_bytes=len(text),
        trimmed_bytes=len(text) - max_bytes,
        ratio=float(max_bytes) / float(len(text)),
        strategy="trim",
    )


def trim_to_tokens(text: str, max_tokens: int) -> TrimmedResult:
    return trim(text, max_tokens * 4)


def combine_context(contents: list[Content], separator: str = "") -> str:
    if separator == "":
        separator = "\n\n"
    parts = []
    for c in contents:
        if c.text != "":
            label = c.role.upper()
            parts.append(f"<{label}>\n{c.text}\n</{label}>")
    return separator.join(parts)


def merge_snapshots(snapshots: list[Snapshot], max_tokens: int) -> list[Content]:
    seen = set()
    result: list[Content] = []
    for snap in reversed(snapshots):
        for c in snap.content:
            if c.id not in seen:
                seen.add(c.id)
                result.insert(0, c)
    return result
