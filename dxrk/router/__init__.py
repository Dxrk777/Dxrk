# SPDX-License-Identifier: MIT
"""Provider router with cost tracking and semantic caching."""

from __future__ import annotations

import hashlib
import heapq
import logging
import math
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional

from ..query import Message, Provider, Response, ToolSchema, Usage

_logger = logging.getLogger("dxrk.router")


class Capability(IntEnum):
    TOOL_CALL = 0
    VISION = 1
    STREAMING = 2


CapToolCall = Capability.TOOL_CALL
CapVision = Capability.VISION
CapStreaming = Capability.STREAMING


class Strategy(IntEnum):
    FIRST_AVAILABLE = 0
    LOWEST_COST = 1
    ROUND_ROBIN = 2


StrategyFirstAvailable = Strategy.FIRST_AVAILABLE
StrategyLowestCost = Strategy.LOWEST_COST
StrategyRoundRobin = Strategy.ROUND_ROBIN


@dataclass
class CostConfig:
    input_price_per_1k: float
    output_price_per_1k: float


DEFAULT_COSTS: dict[str, CostConfig] = {
    "claude-sonnet-4-20250514": CostConfig(0.003, 0.015),
    "claude-sonnet-4": CostConfig(0.003, 0.015),
    "claude-3-5-sonnet-20241022": CostConfig(0.003, 0.015),
    "claude-3-haiku-20240307": CostConfig(0.00025, 0.00125),
    "claude-opus-4-20250514": CostConfig(0.015, 0.075),
    "gpt-4o": CostConfig(0.0025, 0.01),
    "gpt-4o-mini": CostConfig(0.00015, 0.0006),
    "gpt-4-turbo": CostConfig(0.01, 0.03),
    "gemini-1.5-pro": CostConfig(0.00125, 0.005),
    "gemini-1.5-flash": CostConfig(0.000075, 0.0003),
    "gemini-2.0-flash": CostConfig(0.0001, 0.0004),
    "ollama/llama3.1:8b": CostConfig(0, 0),
    "ollama/mixtral:8x7b": CostConfig(0, 0),
    "bedrock/claude-sonnet-4": CostConfig(0.003, 0.015),
    "bedrock/claude-haiku-3": CostConfig(0.00025, 0.00125),
}


class CostTracker:
    """Tracks accumulated token costs per model."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._costs: dict[str, float] = {}
        self._total: float = 0.0

    def add(self, model: str, input_tokens: int, output_tokens: int) -> None:
        cfg = DEFAULT_COSTS.get(model)
        if cfg is None:
            return
        cost = (input_tokens / 1000.0) * cfg.input_price_per_1k + (
            output_tokens / 1000.0
        ) * cfg.output_price_per_1k
        with self._lock:
            self._costs[model] = self._costs.get(model, 0.0) + cost
            self._total += cost

    def total(self) -> float:
        with self._lock:
            return self._total

    def by_model(self) -> dict[str, float]:
        with self._lock:
            return dict(self._costs)

    def reset(self) -> None:
        with self._lock:
            self._costs = {}
            self._total = 0.0


@dataclass
class ProviderEntry:
    name: str
    model: str
    provider: Provider
    capabilities: list[Capability] = field(default_factory=list)


@dataclass
class Router:
    """Routes generate calls across providers."""

    providers: list[ProviderEntry]
    strategy: Strategy = Strategy.FIRST_AVAILABLE
    cost_tracker: CostTracker | None = None
    rr_index: int = 0
    logger: Callable[..., None] = field(default=lambda *args: None)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def generate(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> tuple[Response | None, str | None]:
        selected = self._select_providers()

        last_err: str | None = None
        for idx in selected:
            entry = self.providers[idx]

            resp, err = entry.provider.generate(messages, tools)
            if err is None and resp is not None:
                if self.cost_tracker is not None:
                    self.cost_tracker.add(
                        entry.model, resp.usage.input_tokens, resp.usage.output_tokens
                    )
                self.logger(
                    "[router] %s/%s succeeded (%d in + %d out tokens)",
                    entry.name,
                    entry.model,
                    resp.usage.input_tokens,
                    resp.usage.output_tokens,
                )
                return resp, None

            self.logger("[router] %s/%s failed: %s", entry.name, entry.model, err)
            last_err = err

        if last_err is None:
            last_err = "no providers"
        return None, f"all providers failed: {last_err}"

    def add_provider(self, entry: ProviderEntry) -> None:
        with self._lock:
            self.providers.append(entry)

    def _select_providers(self) -> list[int]:
        with self._lock:
            total = len(self.providers)
            if total == 0:
                return []

            if self.strategy == Strategy.ROUND_ROBIN:
                idx = self.rr_index % total
                self.rr_index = (idx + 1) % total
                return [idx]

            if self.strategy == Strategy.LOWEST_COST:
                return self._sort_by_cost_locked()

            return list(range(total))

    def _sort_by_cost_locked(self) -> list[int]:
        scored: list[tuple[float, int]] = []
        for i, p in enumerate(self.providers):
            cost = 0.0
            cfg = DEFAULT_COSTS.get(p.model)
            if cfg is not None:
                cost = cfg.input_price_per_1k
            scored.append((cost, i))

        for i in range(len(scored)):
            for j in range(i + 1, len(scored)):
                if scored[j][0] < scored[i][0]:
                    scored[i], scored[j] = scored[j], scored[i]

        return [idx for _, idx in scored]


def new_router(
    providers: list[ProviderEntry],
    *,
    strategy: Strategy = Strategy.FIRST_AVAILABLE,
    cost_tracker: CostTracker | None = None,
    logger: Callable[..., None] | None = None,
) -> Router:
    r = Router(
        providers=providers,
        strategy=strategy,
        cost_tracker=cost_tracker if cost_tracker is not None else CostTracker(),
        logger=logger if logger is not None else (lambda *args: None),
    )
    if len(providers) > 0:
        r.rr_index = random.randrange(len(providers))
    return r


@dataclass
class QueryResponse:
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class CacheEntry:
    response: QueryResponse
    created_at: float
    expires_at: float
    access_count: int = 0
    last_access: float = 0.0
    index: int = -1

    def __lt__(self, other: CacheEntry) -> bool:
        return self.last_access < other.last_access


@dataclass
class CacheStats:
    size: int
    max_size: int
    hits: int
    ttl: float


class SemanticCache:
    """LRU response cache with optional semantic matching.
"""

    def __init__(
        self,
        *,
        max_size: int = 1000,
        ttl: float = 300.0,
        semantic_enabled: bool = False,
        semantic_threshold: float = 0.95,
        key_fn: Callable[[str], str] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, CacheEntry] = {}
        self._lru: list[CacheEntry] = []
        self._max_size = max_size
        self._ttl = ttl
        self._semantic_enabled = semantic_enabled
        self._semantic_threshold = semantic_threshold
        self._embeddings: dict[str, list[float]] = {}
        self._key_fn = key_fn if key_fn is not None else default_key_fn

    def get(self, messages: str) -> tuple[QueryResponse, bool]:
        with self._lock:
            key = self._key_fn(messages)
            entry = self._entries.get(key)
            if entry is None:
                if not self._semantic_enabled:
                    return QueryResponse(), False
                return self._semantic_get(messages)

            now = time.time()
            if now > entry.expires_at:
                return QueryResponse(), False

            entry.access_count += 1
            entry.last_access = now
            return entry.response, True

    def set(self, messages: str, resp: QueryResponse) -> None:
        with self._lock:
            key = self._key_fn(messages)
            now = time.time()
            existing = self._entries.get(key)
            if existing is not None:
                existing.response = resp
                existing.expires_at = now + self._ttl
                existing.last_access = now
                return

            entry = CacheEntry(
                response=resp,
                created_at=now,
                expires_at=now + self._ttl,
                last_access=now,
            )

            if len(self._entries) >= self._max_size:
                self._evict_locked()

            self._entries[key] = entry
            entry.index = len(self._lru)
            heapq.heappush(self._lru, entry)

            if self._semantic_enabled:
                self._embeddings[key] = simple_embed(messages)

    def invalidate(self, messages: str) -> None:
        with self._lock:
            key = self._key_fn(messages)
            entry = self._entries.get(key)
            if entry is not None:
                self._heap_remove(entry)
                del self._entries[key]
                self._embeddings.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries = {}
            self._lru = []
            self._embeddings = {}

    def stats(self) -> CacheStats:
        with self._lock:
            hits = 0
            for e in self._entries.values():
                if e.access_count > 0:
                    hits += 1
            return CacheStats(
                size=len(self._entries),
                max_size=self._max_size,
                hits=hits,
                ttl=self._ttl,
            )

    def _evict_locked(self) -> None:
        while len(self._lru) > 0 and len(self._entries) >= self._max_size:
            entry = heapq.heappop(self._lru)
            entry.index = -1
            for key, e in self._entries.items():
                if e is entry:
                    del self._entries[key]
                    self._embeddings.pop(key, None)
                    break

    def _heap_remove(self, entry: CacheEntry) -> None:
        pos = entry.index
        if pos < 0 or pos >= len(self._lru):
            return
        last = self._lru[-1]
        self._lru[pos] = last
        last.index = pos
        self._lru.pop()
        entry.index = -1
        if pos < len(self._lru):
            heapq.heapify(self._lru)

    def _semantic_get(self, messages: str) -> tuple[QueryResponse, bool]:
        query_emb = simple_embed(messages)
        best_score = 0.0
        best_resp = QueryResponse()
        now = time.time()

        for key, entry in self._entries.items():
            if now > entry.expires_at:
                continue
            emb = self._embeddings.get(key)
            if emb is None:
                continue
            score = cosine_sim(query_emb, emb)
            if score > best_score:
                best_score = score
                best_resp = entry.response

        if best_score >= self._semantic_threshold:
            return best_resp, True
        return QueryResponse(), False


def default_key_fn(messages: str) -> str:
    h = hashlib.sha256(messages.encode("utf-8")).digest()
    return h[:16].hex()


def simple_embed(text: str) -> list[float]:
    words = text.split()
    if len(words) == 0:
        return [0.0] * 128

    vec = [0.0] * 128
    for w in words:
        h = hashlib.sha256(w.encode("utf-8")).digest()
        idx = h[0] % 128
        val = float(h[1] % 100) / 50.0
        if h[2] % 2 == 0:
            val = -val
        vec[idx] += val

    norm = 0.0
    for v in vec:
        norm += v * v
    if norm > 0:
        inv = 1.0 / math.sqrt(norm)
        vec = [v * inv for v in vec]
    return vec


def cosine_sim(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(len(a)):
        dot += a[i] * b[i]
        norm_a += a[i] * a[i]
        norm_b += b[i] * b[i]
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class CachingRouter:
    """Router wrapper that caches responses by joined prompt."""

    def __init__(self, router: Router, cache: SemanticCache) -> None:
        self.router = router
        self.cache = cache

    def cached_generate(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> tuple[Response | None, str | None]:
        prompt = join_messages(messages)

        cached, ok = self.cache.get(prompt)
        if ok:
            return (
                Response(
                    text=cached.text,
                    usage=Usage(
                        input_tokens=cached.input_tokens,
                        output_tokens=cached.output_tokens,
                    ),
                ),
                None,
            )

        resp, err = self.router.generate(messages, tools)
        if err is not None or resp is None:
            return resp, err

        self.cache.set(
            prompt,
            QueryResponse(
                text=resp.text,
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            ),
        )
        return resp, None


def join_messages(msgs: list[Message]) -> str:
    parts: list[str] = []
    for m in msgs:
        parts.append(f"{m.role}: {m.content}\n")
    return "".join(parts)
